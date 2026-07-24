import time
from datetime import datetime

from PySide6.QtCore import QThread, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox

from flashforge.config import AppSettings
from flashforge.models import Flashcard
from flashforge.prompts import PromptManager
from flashforge.screenshot import GlobalScreenshotHotkey, RegionSelector, capture_virtual_desktop
from flashforge.socratopia import SocratopiaCourse, SocratopiaLesson
from flashforge.ui import MainWindow
from flashforge.ui import main_window as ui_main_window
from flashforge.ui.socratopia_dialog import SocratopiaLessonDialog


TEST_APP = QApplication.instance() or QApplication([])


def _window(monkeypatch, tmp_path, settings=None):
    prompt_manager = PromptManager(user_prompt_dir=tmp_path / "prompts")
    monkeypatch.setattr(ui_main_window, "PromptManager", lambda: prompt_manager)
    monkeypatch.setattr(GlobalScreenshotHotkey, "register", lambda self: False)
    monkeypatch.setattr(MainWindow, "_refresh_decks", lambda self, *args, **kwargs: None)
    window = MainWindow(settings or AppSettings())
    monkeypatch.setattr(window, "_quit_application", lambda: None)
    return TEST_APP, window, prompt_manager


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
    assert unregistrations == ["alt+s"]
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
    assert window._screenshot_hotkey.shortcut == "alt+s"
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


def test_generation_failure_dialog_runs_after_thread_cleanup_on_main_thread(
    monkeypatch, tmp_path
) -> None:
    app, window, _ = _window(
        monkeypatch,
        tmp_path,
        AppSettings(api_key="test"),
    )
    main_thread = QThread.currentThread()
    warnings = []

    def fail_generation(worker) -> None:
        worker.failed.emit("模拟生成失败")
        worker.finished.emit()

    def record_warning(*args):
        warnings.append(
            {
                "args": args,
                "on_main_thread": QThread.currentThread() == main_thread,
                "thread_cleaned": window._generation_thread is None,
                "button_enabled": window.generate_button.isEnabled(),
            }
        )
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(window, "_save_settings", lambda: True)
    monkeypatch.setattr(ui_main_window.GenerationWorker, "run", fail_generation)
    monkeypatch.setattr(QMessageBox, "warning", record_warning)
    window.material_input.setPlainText("测试材料")

    window._start_generation()
    deadline = time.monotonic() + 3
    while window._generation_thread is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)

    assert len(warnings) == 1
    assert warnings[0]["args"][1:] == ("生成失败", "模拟生成失败")
    assert warnings[0]["on_main_thread"] is True
    assert warnings[0]["thread_cleaned"] is True
    assert warnings[0]["button_enabled"] is True
    assert window._generation_thread is None
    window.close()


def test_saving_settings_preserves_selected_import_deck(monkeypatch, tmp_path) -> None:
    _, window, _ = _window(monkeypatch, tmp_path)
    monkeypatch.setattr(AppSettings, "save", lambda self: None)
    window.deck_input.setCurrentText("本次导入牌组")
    window.default_deck_input.setText("新的默认牌组")

    assert window._save_settings() is True

    assert window.settings.deck_name == "新的默认牌组"
    assert window.deck_input.currentText() == "本次导入牌组"
    window.close()


def test_importing_markdown_enters_document_mode(monkeypatch, tmp_path) -> None:
    _, window, _ = _window(monkeypatch, tmp_path)
    source = tmp_path / "lesson.md"
    source.write_text(
        """---
title: 微积分课堂
---

**学生** · 09:00

周期与振幅有关吗？

**老师** · 09:01

*她点了点公式。*

简谐振动的周期与振幅无关。
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        ui_main_window.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(source), "Markdown 文件 (*.md *.markdown)"),
    )

    window._load_markdown_file()

    assert window._document_mode is True
    assert window._document_path == source
    assert "她点了点公式" not in window.material_input.toPlainText()
    assert "周期与振幅无关" in window.material_input.toPlainText()
    assert "2 条课堂消息" in window.document_status.text()
    assert window.clear_document_button.isEnabled()
    window.close()


def test_importing_socratopia_enters_adaptive_course_mode(monkeypatch, tmp_path) -> None:
    _, window, _ = _window(monkeypatch, tmp_path)
    account = tmp_path / "account"
    account.mkdir()

    class FakeCourse:
        account_path = account
        profile_name = "学习者"
        title = "计算机组成原理"
        display_name = "学习者 / 计算机组成原理 [当前]"
        key = "account/student/SQ/tb1"
        is_active = True

    class FakeLesson:
        title = "边界对齐与字节序 (07-23)"

    class FakeSource:
        course = FakeCourse()
        lesson = FakeLesson()
        material = "# Socratopia 自适应制卡材料\n\n已学内容"
        lesson_evidence_count = 2
        textbook_section_count = 1
        existing_card_count = 3

    class FakeClient:
        def is_available(self):
            return True

    class FakeDialog:
        def __init__(self, courses, lessons_by_course, **kwargs):
            self.selected_course = courses[0]
            self.selected_lesson = lessons_by_course[courses[0].key][0]

        def exec(self):
            return True

    monkeypatch.setattr(
        ui_main_window,
        "discover_socratopia_accounts",
        lambda: [account],
    )
    monkeypatch.setattr(
        ui_main_window,
        "discover_socratopia_courses",
        lambda path: [FakeCourse()],
    )
    monkeypatch.setattr(
        ui_main_window,
        "discover_socratopia_lessons",
        lambda course: [FakeLesson()],
    )
    monkeypatch.setattr(ui_main_window, "SocratopiaTextbookClient", FakeClient)
    monkeypatch.setattr(ui_main_window, "SocratopiaLessonDialog", FakeDialog)
    monkeypatch.setattr(
        ui_main_window,
        "load_socratopia_material",
        lambda course, **kwargs: FakeSource(),
    )

    window._load_socratopia_course()

    assert window._document_mode is True
    assert window._socratopia_mode is True
    assert window._document_path == account
    assert "已学内容" in window.material_input.toPlainText()
    assert "3 张已有卡" in window.document_status.text()
    assert "边界对齐与字节序" in window.document_status.text()
    assert window.load_socratopia_button.text() == "导入自 Socratopia"
    window.close()
    window.deleteLater()
    TEST_APP.processEvents()


def test_socratopia_dialog_displays_course_and_lesson_records(tmp_path) -> None:
    course = SocratopiaCourse(
        account_path=tmp_path / "account",
        profile_id="student",
        profile_name="学习者",
        world_id="SQ",
        textbook_id="tb1",
        title="计算机组成原理",
        format="qbook",
        current_page=12,
        total_pages=100,
        is_active=True,
    )
    lesson = SocratopiaLesson(
        course_key=course.key,
        conversation_id="chat1",
        title="边界对齐与字节序 (07-23)",
        started_at=datetime(2026, 7, 23, 12, 0),
        message_count=52,
        study_seconds=1800,
        summary="课堂中纠正了边界对齐的常见误解。",
        teaching_effect="已经理解减少内存读取次数。",
    )

    dialog = SocratopiaLessonDialog(
        [course], {course.key: [lesson]}, connected=True
    )
    TEST_APP.processEvents()

    assert "计算机组成原理" in dialog.course_input.currentText()
    assert dialog.lesson_table.rowCount() == 1
    assert dialog.lesson_table.item(0, 1).text() == lesson.title
    assert dialog.lesson_table.item(0, 3).text() == "52"
    assert "常见误解" in dialog.lesson_preview.toPlainText()
    assert (
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Cancel).text()
        == "取消"
    )
    dialog._accept_selection()
    assert dialog.selected_course == course
    assert dialog.selected_lesson == lesson
    dialog.close()
    dialog.deleteLater()
    TEST_APP.processEvents()


def test_editing_cards_does_not_schedule_another_auto_import(monkeypatch, tmp_path) -> None:
    _, window, _ = _window(
        monkeypatch,
        tmp_path,
        AppSettings(auto_import_after_generation=True),
    )
    card = Flashcard.from_payload(
        {"type": "qa", "fields": {"question": "Q", "answer": "A"}}
    )

    window._show_cards([card], schedule_auto_import=False)

    assert window._auto_import_pending is False
    assert window.import_button.isEnabled()
    window.close()


def test_deleting_all_preview_cards_requires_confirmation(monkeypatch, tmp_path) -> None:
    _, window, _ = _window(monkeypatch, tmp_path)
    cards = [
        Flashcard.from_payload(
            {"type": "qa", "fields": {"question": f"Q{index}", "answer": "A"}}
        )
        for index in range(2)
    ]
    answers = iter(
        [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes]
    )
    prompts = []

    def answer_question(*args):
        prompts.append(args)
        return next(answers)

    monkeypatch.setattr(QMessageBox, "question", answer_question)
    window.material_input.setPlainText("保留的原始材料")
    window._show_cards(cards, schedule_auto_import=False)

    assert window.delete_all_cards_button.isEnabled()
    window._delete_all_cards()
    assert len(window.cards) == 2

    window._delete_all_cards()

    assert window.cards == []
    assert window.card_table.rowCount() == 0
    assert not window.import_button.isEnabled()
    assert not window.delete_all_cards_button.isEnabled()
    assert window.material_input.toPlainText() == "保留的原始材料"
    assert "2 张卡片" in prompts[0][2]
    assert "不会删除已经导入 Anki" in prompts[0][2]
    assert "已删除全部 2 张预览卡片" in window.statusBar().currentMessage()
    window.close()


def test_closing_main_window_explicitly_quits_application(monkeypatch, tmp_path) -> None:
    _, window, _ = _window(monkeypatch, tmp_path)
    quits = []
    cleanups = []
    monkeypatch.setattr(window, "_quit_application", lambda: quits.append(True))
    monkeypatch.setattr(
        window._screenshot_hotkey,
        "unregister",
        lambda: cleanups.append(True),
    )

    assert window.close() is True

    assert quits == [True]
    assert cleanups == [True]


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
