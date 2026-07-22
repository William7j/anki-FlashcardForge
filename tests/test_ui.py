from PySide6.QtCore import QThread, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QMessageBox

from flashforge.config import AppSettings
from flashforge.models import Flashcard
from flashforge.prompts import PromptManager
from flashforge.screenshot import GlobalScreenshotHotkey, RegionSelector, capture_virtual_desktop
from flashforge.ui import MainWindow
from flashforge.ui import main_window as ui_main_window


def _window(monkeypatch, tmp_path, settings=None):
    app = QApplication.instance() or QApplication([])
    prompt_manager = PromptManager(user_prompt_dir=tmp_path / "prompts")
    monkeypatch.setattr(ui_main_window, "PromptManager", lambda: prompt_manager)
    monkeypatch.setattr(GlobalScreenshotHotkey, "register", lambda self: False)
    monkeypatch.setattr(MainWindow, "_refresh_decks", lambda self, *args, **kwargs: None)
    return app, MainWindow(settings or AppSettings()), prompt_manager


def test_switching_prompt_flushes_pending_autosave(monkeypatch, tmp_path) -> None:
    _, window, manager = _window(monkeypatch, tmp_path)
    updated = window.prompt_editor.toPlainText().replace(
        "# Anki 高质量闪卡生成器", "# 未等待定时器的修改"
    )
    window.prompt_editor.setPlainText(updated)

    window.prompt_selector.setCurrentText("cloze_focused")

    assert manager.load("default_adaptive").startswith("# 未等待定时器的修改")
    window.close()


def test_ollama_generation_is_not_blocked_by_missing_api_key(monkeypatch, tmp_path) -> None:
    _, window, _ = _window(
        monkeypatch,
        tmp_path,
        AppSettings(provider="ollama", api_key=""),
    )
    missing_key_messages = []
    monkeypatch.setattr(window, "_save_settings", lambda: True)
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *args: missing_key_messages.append(args),
    )
    monkeypatch.setattr(QThread, "start", lambda self: None)
    window.material_input.setPlainText("测试材料")

    window._start_generation()

    assert missing_key_messages == []
    assert window._generation_worker is not None
    window._generation_worker.deleteLater()
    window._generation_thread.deleteLater()
    window._generation_worker = None
    window._generation_thread = None
    window.close()


def test_settings_save_captures_auto_generate_after_screenshot(monkeypatch, tmp_path) -> None:
    _, window, _ = _window(monkeypatch, tmp_path)
    monkeypatch.setattr(AppSettings, "save", lambda self: None)

    window.auto_generate_capture_input.setChecked(True)

    assert window._save_settings() is True
    assert window.settings.auto_generate_after_capture is True
    window.close()


def test_settings_save_reregisters_hotkey_and_auto_import(monkeypatch, tmp_path) -> None:
    _, window, _ = _window(monkeypatch, tmp_path)
    registrations = []
    unregistrations = []
    monkeypatch.setattr(AppSettings, "save", lambda self: None)
    monkeypatch.setattr(
        GlobalScreenshotHotkey,
        "register",
        lambda hotkey: registrations.append(hotkey.shortcut) or True,
    )
    monkeypatch.setattr(
        GlobalScreenshotHotkey,
        "unregister",
        lambda hotkey: unregistrations.append(hotkey.shortcut),
    )
    window.screenshot_hotkey_input.setKeySequence(
        QKeySequence.fromString("Ctrl+Shift+S", QKeySequence.SequenceFormat.PortableText)
    )
    window.auto_import_after_generation_input.setChecked(True)

    assert window._save_settings() is True
    assert registrations == ["ctrl+shift+s"]
    assert unregistrations == ["ctrl+alt+a"]
    assert window.settings.screenshot_hotkey == "ctrl+shift+s"
    assert window.settings.auto_import_after_generation is True
    assert "Ctrl+Shift+S" in window.capture_button.text()
    window.close()


def test_settings_save_keeps_existing_hotkey_when_new_hotkey_cannot_register(monkeypatch, tmp_path) -> None:
    _, window, _ = _window(monkeypatch, tmp_path)
    warnings = []
    monkeypatch.setattr(GlobalScreenshotHotkey, "register", lambda hotkey: False)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    window.screenshot_hotkey_input.setKeySequence(
        QKeySequence.fromString("Ctrl+Shift+S", QKeySequence.SequenceFormat.PortableText)
    )

    assert window._save_settings() is False
    assert window._screenshot_hotkey.shortcut == "ctrl+alt+a"
    assert warnings
    window.close()


def test_generation_completion_starts_automatic_anki_import(monkeypatch, tmp_path) -> None:
    _, window, _ = _window(
        monkeypatch,
        tmp_path,
        AppSettings(auto_import_after_generation=True),
    )
    card = Flashcard.from_payload(
        {"type": "qa", "fields": {"question": "Q", "answer": "A"}}
    )
    imported = []
    monkeypatch.setattr(window, "_import_cards", lambda: imported.append(True))

    window._show_cards([card])
    window._generation_finished()

    assert imported == [True]
    assert window._auto_import_pending is False
    window.close()


def test_deck_selector_is_editable_and_preserves_manual_deck(monkeypatch, tmp_path) -> None:
    _, window, _ = _window(monkeypatch, tmp_path)

    window.deck_input.setCurrentText("手动牌组")
    window._set_available_decks(["Alpha", "Biology"])

    assert window.deck_input.isEditable() is True
    assert [window.deck_input.itemText(index) for index in range(window.deck_input.count())] == [
        "Alpha",
        "Biology",
    ]
    assert window.deck_input.currentText() == "手动牌组"
    window.close()


def test_screenshot_auto_starts_generation_when_enabled(monkeypatch, tmp_path) -> None:
    _, window, _ = _window(
        monkeypatch,
        tmp_path,
        AppSettings(auto_generate_after_capture=True),
    )
    full_screen = tmp_path / "full-screen.png"
    selected = tmp_path / "selected.png"
    selected.write_bytes(b"image")
    generated = []

    class FakeSelector:
        def __init__(self, image_path):
            assert image_path == full_screen
            self.selected_path = selected

        def exec(self):
            return True

    monkeypatch.setattr(ui_main_window, "capture_virtual_desktop", lambda: full_screen)
    monkeypatch.setattr(ui_main_window, "RegionSelector", FakeSelector)
    monkeypatch.setattr(QTimer, "singleShot", lambda _delay, callback: callback())
    monkeypatch.setattr(window, "_start_generation", lambda: generated.append(True))

    window._capture_screenshot()

    assert generated == [True]
    assert window._image_path == selected
    assert "selected.png" in window.image_status.text()
    selected.unlink()
    window._image_path = None
    window.close()
