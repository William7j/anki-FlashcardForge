"""Main application window — the primary UI entry point."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from flashforge.anki import AnkiConnectClient, AnkiConnectError, ImportResult
from flashforge.config import AppSettings, OLLAMA_BASE_URL
from flashforge.document import DocumentParseError, load_markdown_document
from flashforge.models import CardType, Flashcard
from flashforge.pipeline import CardPipeline
from flashforge.prompts import DEFAULT_PROMPT_NAME, PromptManager
from flashforge.resources import app_icon_path
from flashforge.screenshot import (
    GlobalScreenshotHotkey,
    RegionSelector,
    ScreenshotError,
    capture_virtual_desktop,
)
from flashforge.secrets import SecretStorageError
from flashforge.theme import apply_theme

from flashforge.ui.editor import CardEditorDialog
from flashforge.ui.highlight import PromptHighlighter
from flashforge.ui.workers import (
    DeckLoadWorker,
    GenerationWorker,
    ImportWorker,
    RegenerationWorker,
    TemplateSyncWorker,
)


class MainWindow(QMainWindow):
    screenshot_requested = Signal()

    def __init__(self, settings: AppSettings) -> None:
        super().__init__()
        self.settings = settings
        self.cards: list[Flashcard] = []
        self._image_path: Path | None = None
        self._document_path: Path | None = None
        self._document_mode = False
        self._generation_thread: QThread | None = None
        self._generation_worker: GenerationWorker | None = None
        self._import_thread: QThread | None = None
        self._import_worker: ImportWorker | None = None
        self._regeneration_thread: QThread | None = None
        self._regeneration_worker: RegenerationWorker | None = None
        self._regeneration_row: int | None = None
        self._template_sync_thread: QThread | None = None
        self._template_sync_worker: TemplateSyncWorker | None = None
        self._deck_load_thread: QThread | None = None
        self._deck_load_worker: DeckLoadWorker | None = None
        self._capture_in_progress = False
        self._auto_import_pending = False
        self._last_material = ""
        self._last_image_path: Path | None = None
        self._last_document_mode = False
        self._prompt_manager = PromptManager()
        self._prompt_save_timer = QTimer(self)
        self._prompt_save_timer.setSingleShot(True)
        self._prompt_save_timer.setInterval(800)
        self._prompt_save_timer.timeout.connect(self._autosave_prompt)
        self._loading_prompt = False
        self._prompt_dirty = False
        self._loaded_prompt_name = ""
        self._screenshot_hotkey = GlobalScreenshotHotkey(
            self.settings.screenshot_hotkey, self.screenshot_requested.emit
        )
        self.setWindowTitle("FlashForge")
        self.setWindowIcon(QIcon(str(app_icon_path())))
        self.setMinimumSize(920, 680)
        self._build_ui()
        self.screenshot_requested.connect(self._capture_screenshot)
        if self._screenshot_hotkey.register():
            self.statusBar().showMessage(
                f"已启用全局截图热键 {self._hotkey_display(self.settings.screenshot_hotkey)}。",
                5000,
            )
        QTimer.singleShot(0, lambda: self._refresh_decks(show_error=False))

    def _build_ui(self) -> None:
        self.setStatusBar(QStatusBar(self))
        tabs = QTabWidget(self)
        tabs.addTab(self._build_cards_tab(), "制卡")
        tabs.addTab(self._build_settings_tab(), "设置")
        tabs.addTab(self._build_prompt_tab(), "提示词")
        self.setCentralWidget(tabs)

        about_action = QAction("关于 FlashForge", self)
        about_action.triggered.connect(
            lambda: QMessageBox.information(self, "FlashForge", "FlashForge MVP\n开源 AI Anki 制卡工具")
        )
        self.menuBar().addMenu("帮助").addAction(about_action)

    def _build_cards_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        layout.addWidget(QLabel("学习材料"))
        self.material_input = QPlainTextEdit()
        self.material_input.setPlaceholderText("粘贴需要记忆的文字、笔记或章节内容...")
        self.material_input.setMinimumHeight(180)
        layout.addWidget(self.material_input)

        self.image_status = QLabel("未选择截图")
        layout.addWidget(self.image_status)

        document_controls = QHBoxLayout()
        self.load_markdown_button = QPushButton("导入 Markdown")
        self.load_markdown_button.clicked.connect(self._load_markdown_file)
        document_controls.addWidget(self.load_markdown_button)
        self.clear_document_button = QPushButton("清除本地资料")
        self.clear_document_button.setEnabled(False)
        self.clear_document_button.clicked.connect(lambda: self._clear_document_source())
        document_controls.addWidget(self.clear_document_button)
        self.document_status = QLabel("未导入本地资料")
        document_controls.addWidget(self.document_status, stretch=1)
        layout.addLayout(document_controls)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("导入牌组"))
        self.deck_input = QComboBox()
        self.deck_input.setEditable(True)
        self.deck_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.deck_input.setCurrentText(self.settings.deck_name)
        self.deck_input.setMinimumWidth(240)
        controls.addWidget(self.deck_input)
        self.refresh_decks_button = QPushButton("刷新牌组")
        self.refresh_decks_button.clicked.connect(self._refresh_decks)
        controls.addWidget(self.refresh_decks_button)
        self.capture_button = QPushButton()
        self._update_capture_button_label()
        self.capture_button.clicked.connect(self._capture_screenshot)
        controls.addWidget(self.capture_button)
        self.clear_capture_button = QPushButton("清除截图")
        self.clear_capture_button.setEnabled(False)
        self.clear_capture_button.clicked.connect(self._clear_screenshot)
        controls.addWidget(self.clear_capture_button)
        controls.addStretch()
        self.generate_button = QPushButton("生成卡片")
        self.generate_button.clicked.connect(self._start_generation)
        controls.addWidget(self.generate_button)
        self.import_button = QPushButton("导入 Anki")
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self._import_cards)
        controls.addWidget(self.import_button)
        layout.addLayout(controls)

        layout.addWidget(QLabel("生成预览"))
        self.card_table = QTableWidget(0, 3)
        self.card_table.setHorizontalHeaderLabels(["题型", "问题 / 内容", "答案"])
        self.card_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.card_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.card_table.horizontalHeader().setStretchLastSection(True)
        self.card_table.setColumnWidth(0, 110)
        self.card_table.setColumnWidth(1, 440)
        layout.addWidget(self.card_table, stretch=1)
        card_actions = QHBoxLayout()
        self.edit_card_button = QPushButton("编辑选中卡片")
        self.edit_card_button.setEnabled(False)
        self.edit_card_button.clicked.connect(self._edit_selected_card)
        card_actions.addWidget(self.edit_card_button)
        self.regenerate_card_button = QPushButton("重新生成选中卡片")
        self.regenerate_card_button.setEnabled(False)
        self.regenerate_card_button.clicked.connect(self._regenerate_selected_card)
        card_actions.addWidget(self.regenerate_card_button)
        self.delete_card_button = QPushButton("删除选中卡片")
        self.delete_card_button.setEnabled(False)
        self.delete_card_button.clicked.connect(self._delete_selected_card)
        card_actions.addWidget(self.delete_card_button)
        card_actions.addStretch()
        layout.addLayout(card_actions)
        self.card_table.itemSelectionChanged.connect(self._update_card_action_state)
        return page

    def _load_markdown_file(self, checked: bool = False) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "选择 Markdown 学习资料",
            str(self._document_path.parent if self._document_path else Path.home()),
            "Markdown 文件 (*.md *.markdown)",
        )
        if not filename:
            return
        try:
            document = load_markdown_document(Path(filename))
        except DocumentParseError as exc:
            QMessageBox.warning(self, "无法导入 Markdown", str(exc))
            return
        if self._image_path is not None:
            self._clear_screenshot()
        self._document_path = document.path
        self._document_mode = True
        self.material_input.setPlainText(document.cleaned_material)
        message_summary = (
            f"，{document.message_count} 条课堂消息" if document.message_count else ""
        )
        self.document_status.setText(f"已导入：{document.path.name}{message_summary}")
        self.document_status.setToolTip(str(document.path))
        self.clear_document_button.setEnabled(True)
        self.statusBar().showMessage(
            f"已清洗 Markdown：{document.title}{message_summary}。请检查内容后生成卡片。",
            8000,
        )

    def _clear_document_source(self, *, clear_material: bool = True) -> None:
        self._document_path = None
        self._document_mode = False
        self.document_status.setText("未导入本地资料")
        self.document_status.setToolTip("")
        self.clear_document_button.setEnabled(False)
        if clear_material:
            self.material_input.clear()

    def _build_settings_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.provider_input = QComboBox()
        self.provider_input.addItem("OpenAI 兼容 API", "openai_compatible")
        self.provider_input.addItem("Ollama（本地）", "ollama")
        self.provider_input.setCurrentIndex(
            max(0, self.provider_input.findData(self.settings.provider))
        )
        self.provider_input.currentIndexChanged.connect(self._provider_changed)
        form.addRow("模型提供方", self.provider_input)
        self.api_key_input = QLineEdit(self.settings.api_key)
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("sk-...")
        form.addRow("API 密钥", self.api_key_input)
        self.base_url_input = QLineEdit(self.settings.base_url)
        form.addRow("API 地址", self.base_url_input)
        self.model_input = QLineEdit(self.settings.model)
        form.addRow("模型", self.model_input)
        self.image_mode_input = QComboBox()
        self.image_mode_input.addItem("多模态直传", "multimodal")
        self.image_mode_input.addItem("本地 OCR（图片文字）", "ocr")
        self.image_mode_input.setCurrentIndex(
            max(0, self.image_mode_input.findData(self.settings.image_input_mode))
        )
        form.addRow("图片制卡模式", self.image_mode_input)
        self.screenshot_hotkey_input = QKeySequenceEdit()
        self.screenshot_hotkey_input.setKeySequence(
            QKeySequence.fromString(
                self.settings.screenshot_hotkey,
                QKeySequence.SequenceFormat.PortableText,
            )
        )
        form.addRow("截图快捷键", self.screenshot_hotkey_input)
        self.auto_generate_capture_input = QCheckBox("截图选区完成后立即生成卡片")
        self.auto_generate_capture_input.setChecked(self.settings.auto_generate_after_capture)
        form.addRow("截图行为", self.auto_generate_capture_input)
        self.auto_import_after_generation_input = QCheckBox("生成卡片后自动导入 Anki")
        self.auto_import_after_generation_input.setChecked(
            self.settings.auto_import_after_generation
        )
        form.addRow("Anki 行为", self.auto_import_after_generation_input)
        self.theme_input = QComboBox()
        self.theme_input.addItem("跟随系统", "system")
        self.theme_input.addItem("浅色", "light")
        self.theme_input.addItem("深色", "dark")
        self.theme_input.setCurrentIndex(max(0, self.theme_input.findData(self.settings.theme)))
        form.addRow("应用主题", self.theme_input)
        self.default_deck_input = QLineEdit(self.settings.deck_name)
        form.addRow("默认牌组", self.default_deck_input)
        layout.addLayout(form)
        layout.addStretch()
        save_button = QPushButton("保存设置")
        save_button.clicked.connect(self._save_settings)
        layout.addWidget(save_button)
        self.sync_templates_button = QPushButton("更新 Anki 模板")
        self.sync_templates_button.clicked.connect(self._sync_anki_templates)
        layout.addWidget(self.sync_templates_button)
        self._sync_provider_fields()
        return page

    def _build_prompt_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("当前模板"))
        self.prompt_selector = QComboBox()
        self.prompt_selector.addItems(self._prompt_manager.available_names())
        selected_name = self.settings.prompt_name or DEFAULT_PROMPT_NAME
        selected_index = self.prompt_selector.findText(selected_name)
        self.prompt_selector.setCurrentIndex(max(0, selected_index))
        self.prompt_selector.currentTextChanged.connect(self._prompt_selection_changed)
        controls.addWidget(self.prompt_selector, stretch=1)
        new_button = QPushButton("新建模板")
        new_button.clicked.connect(self._create_prompt)
        controls.addWidget(new_button)
        reset_button = QPushButton("恢复 / 删除模板")
        reset_button.clicked.connect(self._remove_prompt_override)
        controls.addWidget(reset_button)
        layout.addLayout(controls)
        self.prompt_editor = QPlainTextEdit()
        self.prompt_editor.setPlaceholderText("提示词模板必须包含 {{学习材料}}")
        self.prompt_editor.textChanged.connect(self._prompt_changed)
        self._prompt_highlighter = PromptHighlighter(self.prompt_editor.document())
        layout.addWidget(self.prompt_editor, stretch=1)
        self.prompt_status = QLabel()
        layout.addWidget(self.prompt_status)
        self._load_selected_prompt()
        return page

    def _save_settings(self) -> bool:
        previous_default_deck = self.settings.deck_name
        current_target_deck = self.deck_input.currentText().strip()
        try:
            screenshot_hotkey = self.screenshot_hotkey_input.keySequence().toString(
                QKeySequence.SequenceFormat.PortableText
            )
            new_settings = AppSettings.from_mapping(
                {
                    "provider": self.provider_input.currentData(),
                    "api_key": self.api_key_input.text(),
                    "base_url": self.base_url_input.text(),
                    "model": self.model_input.text(),
                    "deck_name": self.default_deck_input.text(),
                    "prompt_name": self.prompt_selector.currentText(),
                    "image_input_mode": self.image_mode_input.currentData(),
                    "screenshot_hotkey": screenshot_hotkey,
                    "auto_generate_after_capture": self.auto_generate_capture_input.isChecked(),
                    "auto_import_after_generation": self.auto_import_after_generation_input.isChecked(),
                    "theme": self.theme_input.currentData(),
                    "request_timeout_seconds": self.settings.request_timeout_seconds,
                }
            )
        except ValueError as exc:
            QMessageBox.warning(self, "无法保存设置", str(exc))
            return False
        previous_hotkey = self._screenshot_hotkey.shortcut
        hotkey_changed = new_settings.screenshot_hotkey != previous_hotkey
        if hotkey_changed and not self._set_screenshot_hotkey(new_settings.screenshot_hotkey):
            return False
        try:
            new_settings.save()
        except (SecretStorageError, OSError) as exc:
            if hotkey_changed:
                self._set_screenshot_hotkey(previous_hotkey, show_error=False)
            QMessageBox.warning(self, "无法保存设置", str(exc))
            return False
        self.settings = new_settings
        if not current_target_deck or current_target_deck == previous_default_deck:
            self.deck_input.setCurrentText(self.settings.deck_name)
        else:
            self.deck_input.setCurrentText(current_target_deck)
        self._update_capture_button_label()
        apply_theme(QApplication.instance(), self.settings.theme)
        self.statusBar().showMessage("设置已保存。", 5000)
        return True

    @staticmethod
    def _hotkey_display(shortcut: str) -> str:
        sequence = QKeySequence.fromString(shortcut, QKeySequence.SequenceFormat.PortableText)
        return sequence.toString(QKeySequence.SequenceFormat.NativeText) or shortcut

    def _update_capture_button_label(self) -> None:
        self.capture_button.setText(
            f"截取屏幕 ({self._hotkey_display(self.settings.screenshot_hotkey)})"
        )

    def _set_screenshot_hotkey(self, shortcut: str, *, show_error: bool = True) -> bool:
        if shortcut == self._screenshot_hotkey.shortcut:
            return True
        replacement = GlobalScreenshotHotkey(shortcut, self.screenshot_requested.emit)
        if not replacement.register():
            if show_error:
                QMessageBox.warning(
                    self,
                    "无法启用截图快捷键",
                    f"无法注册全局快捷键 {self._hotkey_display(shortcut)}。请换用其他组合键。",
                )
            return False
        self._screenshot_hotkey.unregister()
        self._screenshot_hotkey = replacement
        return True

    def _provider_changed(self) -> None:
        self._sync_provider_fields()

    def _sync_provider_fields(self) -> None:
        is_ollama = self.provider_input.currentData() == "ollama"
        self.api_key_input.setEnabled(not is_ollama)
        if is_ollama and (
            not self.base_url_input.text().strip()
            or self.base_url_input.text().strip() == "https://api.openai.com/v1"
        ):
            self.base_url_input.setText(OLLAMA_BASE_URL)

    def _refresh_decks(self, checked: bool = False, *, show_error: bool = True) -> None:
        if self._deck_load_thread is not None:
            return
        self.refresh_decks_button.setEnabled(False)
        self.statusBar().showMessage("正在读取 Anki 牌组...")
        self._deck_load_thread = QThread(self)
        self._deck_load_worker = DeckLoadWorker()
        self._deck_load_worker.moveToThread(self._deck_load_thread)
        self._deck_load_thread.started.connect(self._deck_load_worker.run)
        self._deck_load_worker.loaded.connect(self._set_available_decks)
        self._deck_load_worker.failed.connect(
            lambda message: self._deck_load_failed(message, show_error)
        )
        self._deck_load_worker.finished.connect(self._deck_load_thread.quit)
        self._deck_load_worker.finished.connect(self._deck_load_worker.deleteLater)
        self._deck_load_thread.finished.connect(self._deck_load_finished)
        self._deck_load_thread.finished.connect(self._deck_load_thread.deleteLater)
        self._deck_load_thread.start()

    def _set_available_decks(self, deck_names: Sequence[str]) -> None:
        current = self.deck_input.currentText().strip()
        self.deck_input.blockSignals(True)
        self.deck_input.clear()
        self.deck_input.addItems(deck_names)
        self.deck_input.setCurrentText(current or self.settings.deck_name)
        self.deck_input.blockSignals(False)
        self.statusBar().showMessage(f"已读取 {len(deck_names)} 个 Anki 牌组。", 5000)

    def _deck_load_failed(self, message: str, show_error: bool) -> None:
        if show_error:
            QMessageBox.warning(self, "无法读取 Anki 牌组", message)
        else:
            self.statusBar().showMessage("Anki 未启动，仍可手动输入牌组名称。", 5000)

    def _deck_load_finished(self) -> None:
        self.refresh_decks_button.setEnabled(True)
        self._deck_load_worker = None
        self._deck_load_thread = None

    def _sync_anki_templates(self) -> None:
        if self._template_sync_thread is not None:
            return
        decision = QMessageBox.question(
            self,
            "更新 Anki 模板",
            "这会覆盖现有 FlashForge 笔记类型的卡片模板和 CSS，自定义的 FlashForge 模板将被替换。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if decision != QMessageBox.StandardButton.Yes:
            return
        self.sync_templates_button.setEnabled(False)
        self.statusBar().showMessage("正在更新 FlashForge Anki 模板...")
        self._template_sync_thread = QThread(self)
        self._template_sync_worker = TemplateSyncWorker()
        self._template_sync_worker.moveToThread(self._template_sync_thread)
        self._template_sync_thread.started.connect(self._template_sync_worker.run)
        self._template_sync_worker.updated.connect(
            lambda count: self.statusBar().showMessage(f"已更新 {count} 个 Anki 笔记类型。", 8000)
        )
        self._template_sync_worker.failed.connect(
            lambda message: QMessageBox.warning(self, "无法更新 Anki 模板", message)
        )
        self._template_sync_worker.finished.connect(self._template_sync_thread.quit)
        self._template_sync_worker.finished.connect(self._template_sync_worker.deleteLater)
        self._template_sync_thread.finished.connect(self._template_sync_finished)
        self._template_sync_thread.finished.connect(self._template_sync_thread.deleteLater)
        self._template_sync_thread.start()

    def _template_sync_finished(self) -> None:
        self.sync_templates_button.setEnabled(True)
        self._template_sync_worker = None
        self._template_sync_thread = None

    def _prompt_selection_changed(self, name: str) -> None:
        if not name:
            return
        self._prompt_save_timer.stop()
        if not self._save_dirty_prompt():
            self.prompt_selector.blockSignals(True)
            self.prompt_selector.setCurrentText(self._loaded_prompt_name)
            self.prompt_selector.blockSignals(False)
            return
        self._load_selected_prompt()
        self.settings.prompt_name = name
        try:
            self.settings.save()
        except (SecretStorageError, OSError) as exc:
            self.prompt_status.setText(f"无法保存当前模板选择：{exc}")

    def _load_selected_prompt(self) -> None:
        name = self.prompt_selector.currentText()
        if not name:
            return
        try:
            template = self._prompt_manager.load(name)
        except (OSError, ValueError) as exc:
            self.prompt_status.setText(str(exc))
            return
        self._loading_prompt = True
        self.prompt_editor.blockSignals(True)
        self.prompt_editor.setPlainText(template)
        self.prompt_editor.blockSignals(False)
        self._loading_prompt = False
        self._prompt_dirty = False
        self._loaded_prompt_name = name
        origin = "用户覆盖版本" if self._prompt_manager.has_override(name) else "内置版本"
        self.prompt_status.setText(f"{origin}，修改后将自动保存。")

    def _prompt_changed(self) -> None:
        if self._loading_prompt:
            return
        self._prompt_dirty = True
        self.prompt_status.setText("正在等待保存...")
        self._prompt_save_timer.start()

    def _autosave_prompt(self) -> None:
        self._save_dirty_prompt()

    def _save_dirty_prompt(self) -> bool:
        if not self._prompt_dirty:
            return True
        name = self._loaded_prompt_name or self.prompt_selector.currentText()
        try:
            self._prompt_manager.save_override(name, self.prompt_editor.toPlainText())
        except (OSError, ValueError) as exc:
            self.prompt_status.setText(f"无法保存：{exc}")
            return False
        self._prompt_dirty = False
        self.prompt_status.setText("已自动保存为用户覆盖版本。")
        return True

    def _create_prompt(self) -> None:
        name, accepted = QInputDialog.getText(self, "新建提示词", "模板名称（小写字母、数字、下划线）：")
        if not accepted:
            return
        try:
            template = self._prompt_manager.load(DEFAULT_PROMPT_NAME)
            self._prompt_manager.save_override(name.strip(), template)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "无法新建模板", str(exc))
            return
        if self.prompt_selector.findText(name.strip()) < 0:
            self.prompt_selector.addItem(name.strip())
        self.prompt_selector.setCurrentText(name.strip())

    def _remove_prompt_override(self) -> None:
        name = self.prompt_selector.currentText()
        self._prompt_save_timer.stop()
        self._prompt_dirty = False
        try:
            removed = self._prompt_manager.remove_override(name)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "无法恢复模板", str(exc))
            return
        if removed:
            if self._prompt_manager.is_built_in(name):
                self._load_selected_prompt()
                self.statusBar().showMessage("已恢复内置提示词版本。", 5000)
            else:
                self.prompt_selector.removeItem(self.prompt_selector.currentIndex())
                self.prompt_selector.setCurrentText(DEFAULT_PROMPT_NAME)
                self.statusBar().showMessage("已删除自定义提示词模板。", 5000)
        else:
            self.prompt_status.setText("当前没有可删除的用户覆盖版本。")

    def _start_generation(self) -> None:
        material = self.material_input.toPlainText().strip()
        if not material and self._image_path is None:
            QMessageBox.information(self, "缺少材料", "请输入学习材料或截取屏幕内容。")
            return
        if not self._save_settings():
            return
        if self.settings.requires_api_key and not self.settings.api_key:
            QMessageBox.information(self, "缺少 API 密钥", "请先在设置页填写 API 密钥。")
            return
        self.generate_button.setEnabled(False)
        self.capture_button.setEnabled(False)
        self.clear_capture_button.setEnabled(False)
        self._set_document_controls_enabled(False)
        self.import_button.setEnabled(False)
        self._update_card_action_state()
        self.statusBar().showMessage("正在生成卡片...")
        self._auto_import_pending = False
        self._last_material = material
        self._last_image_path = self._image_path
        self._last_document_mode = self._document_mode and self._image_path is None
        self._generation_thread = QThread(self)
        self._generation_worker = GenerationWorker(
            self.settings,
            material,
            self._image_path,
            self._last_document_mode,
        )
        self._generation_worker.moveToThread(self._generation_thread)
        self._generation_thread.started.connect(self._generation_worker.run)
        self._generation_worker.generated.connect(self._show_cards)
        self._generation_worker.failed.connect(
            lambda message: QMessageBox.warning(self, "生成失败", message)
        )
        self._generation_worker.finished.connect(self._generation_thread.quit)
        self._generation_worker.finished.connect(self._generation_worker.deleteLater)
        self._generation_thread.finished.connect(self._generation_finished)
        self._generation_thread.finished.connect(self._generation_thread.deleteLater)
        self._generation_thread.start()

    def _generation_finished(self) -> None:
        auto_import = self._auto_import_pending and bool(self.cards)
        self._auto_import_pending = False
        self._generation_worker = None
        self._generation_thread = None
        if auto_import:
            self._import_cards()
            return
        self.generate_button.setEnabled(True)
        self.capture_button.setEnabled(True)
        self.clear_capture_button.setEnabled(self._image_path is not None)
        self._set_document_controls_enabled(True)
        self.refresh_decks_button.setEnabled(self._deck_load_thread is None)

    def _capture_screenshot(self) -> None:
        if (
            self._capture_in_progress
            or self._template_sync_thread is not None
            or self._generation_thread is not None
            or self._import_thread is not None
            or self._regeneration_thread is not None
        ):
            return
        self._capture_in_progress = True
        full_screen_path: Path | None = None
        try:
            self.hide()
            QApplication.processEvents()
            full_screen_path = capture_virtual_desktop()
            self.show()
            selector = RegionSelector(full_screen_path)
            selected = selector.exec() and selector.selected_path
            if selected:
                self._clear_document_source(clear_material=False)
                self._remove_selected_screenshot()
                self._image_path = selector.selected_path
                self.image_status.setText(f"已选择截图：{selector.selected_path.name}")
                self.clear_capture_button.setEnabled(True)
                if self.settings.auto_generate_after_capture:
                    self.statusBar().showMessage("截图已选择，正在自动生成卡片...")
                    QTimer.singleShot(0, self._start_generation)
                else:
                    self.statusBar().showMessage("截图已选择，生成时将使用当前图片制卡模式。", 5000)
        except ScreenshotError as exc:
            self.show()
            QMessageBox.warning(self, "无法截图", str(exc))
        finally:
            self.show()
            if full_screen_path is not None:
                try:
                    full_screen_path.unlink(missing_ok=True)
                except OSError:
                    pass
            self._capture_in_progress = False

    def _clear_screenshot(self) -> None:
        self._remove_selected_screenshot()
        self._image_path = None
        self.image_status.setText("未选择截图")
        self.clear_capture_button.setEnabled(False)

    def _remove_selected_screenshot(self) -> None:
        if self._image_path is None:
            return
        try:
            self._image_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _show_cards(
        self,
        cards: Sequence[Flashcard],
        *,
        schedule_auto_import: bool = True,
    ) -> None:
        self.cards = list(cards)
        self.card_table.setRowCount(len(self.cards))
        for row, card in enumerate(self.cards):
            self.card_table.setItem(row, 0, QTableWidgetItem(card.card_type.value))
            self.card_table.setItem(row, 1, QTableWidgetItem(card.preview_question))
            self.card_table.setItem(row, 2, QTableWidgetItem(card.preview_answer))
        self._auto_import_pending = (
            schedule_auto_import
            and self.settings.auto_import_after_generation
            and bool(self.cards)
        )
        self.import_button.setEnabled(bool(self.cards) and not self._auto_import_pending)
        self._update_card_action_state()
        if self._auto_import_pending:
            self.statusBar().showMessage(f"已生成 {len(self.cards)} 张卡片，准备自动导入 Anki...")
        else:
            self.statusBar().showMessage(f"已生成 {len(self.cards)} 张卡片。")

    def _selected_card_row(self) -> int | None:
        row = self.card_table.currentRow()
        return row if 0 <= row < len(self.cards) else None

    def _update_card_action_state(self) -> None:
        selected = self._selected_card_row() is not None
        is_busy = (
            self._generation_thread is not None
            or self._regeneration_thread is not None
            or self._import_thread is not None
        )
        self.edit_card_button.setEnabled(selected and not is_busy)
        self.delete_card_button.setEnabled(selected and not is_busy)
        self.regenerate_card_button.setEnabled(selected and not is_busy)

    def _edit_selected_card(self) -> None:
        row = self._selected_card_row()
        if row is None:
            return
        dialog = CardEditorDialog(self.cards[row], self)
        if dialog.exec() and dialog.card is not None:
            self.cards[row] = dialog.card
            self._show_cards(self.cards, schedule_auto_import=False)
            self.card_table.selectRow(row)
            self.statusBar().showMessage("卡片已更新。", 5000)

    def _delete_selected_card(self) -> None:
        row = self._selected_card_row()
        if row is None:
            return
        self.cards.pop(row)
        self._show_cards(self.cards, schedule_auto_import=False)
        if self.cards:
            self.card_table.selectRow(min(row, len(self.cards) - 1))
        self.statusBar().showMessage("已删除选中卡片。", 5000)

    def _regenerate_selected_card(self) -> None:
        row = self._selected_card_row()
        if row is None:
            return
        image_path = self._last_image_path
        if image_path is not None and not image_path.exists():
            image_path = None
        if image_path is None and not self._last_material.strip():
            QMessageBox.information(self, "缺少原始材料", "请先重新生成整组卡片，再对单张卡片重新生成。")
            return
        feedback, accepted = QInputDialog.getMultiLineText(
            self,
            "重新生成卡片",
            "修改要求（可留空）：",
        )
        if not accepted:
            return
        self._set_card_workflow_enabled(False)
        self.statusBar().showMessage("正在重新生成选中卡片...")
        self._regeneration_row = row
        self._regeneration_thread = QThread(self)
        self._regeneration_worker = RegenerationWorker(
            self.settings,
            self.cards[row],
            feedback,
            self._last_material,
            image_path,
            self._last_document_mode and image_path is None,
        )
        self._regeneration_worker.moveToThread(self._regeneration_thread)
        self._regeneration_thread.started.connect(self._regeneration_worker.run)
        self._regeneration_worker.regenerated.connect(self._replace_regenerated_card)
        self._regeneration_worker.failed.connect(
            lambda message: QMessageBox.warning(self, "重新生成失败", message)
        )
        self._regeneration_worker.finished.connect(self._regeneration_thread.quit)
        self._regeneration_worker.finished.connect(self._regeneration_worker.deleteLater)
        self._regeneration_thread.finished.connect(self._regeneration_finished)
        self._regeneration_thread.finished.connect(self._regeneration_thread.deleteLater)
        self._regeneration_thread.start()

    def _replace_regenerated_card(self, card: Flashcard) -> None:
        if self._regeneration_row is None:
            return
        self.cards[self._regeneration_row] = card
        self._show_cards(self.cards, schedule_auto_import=False)
        self.card_table.selectRow(self._regeneration_row)
        self.statusBar().showMessage("选中卡片已重新生成。", 5000)

    def _regeneration_finished(self) -> None:
        self._regeneration_worker = None
        self._regeneration_thread = None
        self._regeneration_row = None
        self._set_card_workflow_enabled(True)

    def _set_card_workflow_enabled(self, enabled: bool) -> None:
        self.generate_button.setEnabled(enabled)
        self.capture_button.setEnabled(enabled)
        self.clear_capture_button.setEnabled(enabled and self._image_path is not None)
        self._set_document_controls_enabled(enabled)
        self.deck_input.setEnabled(enabled)
        self.refresh_decks_button.setEnabled(enabled and self._deck_load_thread is None)
        self.import_button.setEnabled(enabled and bool(self.cards))
        self._update_card_action_state()

    def _set_document_controls_enabled(self, enabled: bool) -> None:
        self.load_markdown_button.setEnabled(enabled)
        self.clear_document_button.setEnabled(enabled and self._document_path is not None)

    def _import_cards(self) -> None:
        if not self.cards:
            return
        deck_name = self.deck_input.currentText().strip()
        settings = AppSettings.from_mapping(
            {
                "api_key": self.settings.api_key,
                "base_url": self.settings.base_url,
                "model": self.settings.model,
                "deck_name": deck_name,
                "prompt_name": self.settings.prompt_name,
                "request_timeout_seconds": self.settings.request_timeout_seconds,
            }
        )
        self.import_button.setEnabled(False)
        self.generate_button.setEnabled(False)
        self.capture_button.setEnabled(False)
        self.clear_capture_button.setEnabled(False)
        self._set_document_controls_enabled(False)
        self.deck_input.setEnabled(False)
        self.refresh_decks_button.setEnabled(False)
        self.statusBar().showMessage(f"正在导入 0 / {len(self.cards)} 张卡片...")
        self._import_thread = QThread(self)
        self._import_worker = ImportWorker(settings, self.cards)
        self._import_worker.moveToThread(self._import_thread)
        self._import_thread.started.connect(self._import_worker.run)
        self._import_worker.progressed.connect(self._show_import_progress)
        self._import_worker.imported.connect(self._import_succeeded)
        self._import_worker.failed.connect(self._import_failed)
        self._import_worker.finished.connect(self._import_thread.quit)
        self._import_worker.finished.connect(self._import_worker.deleteLater)
        self._import_thread.finished.connect(self._import_finished)
        self._import_thread.finished.connect(self._import_thread.deleteLater)
        self._import_thread.start()

    def _show_import_progress(self, completed: int, total: int) -> None:
        self.statusBar().showMessage(f"正在导入 {completed} / {total} 张卡片...")

    def _import_succeeded(self, result: ImportResult) -> None:
        deck_name = self.deck_input.currentText().strip()
        message = f"已导入 {result.added_count} 张卡片到 {deck_name}。"
        if result.skipped_count:
            message += f" 跳过 {result.skipped_count} 张已存在或无效的卡片。"
        self.statusBar().showMessage(message, 8000)

    def _import_failed(self, message: str) -> None:
        QMessageBox.warning(self, "无法导入 Anki", message)

    def _import_finished(self) -> None:
        self.import_button.setEnabled(bool(self.cards))
        self.generate_button.setEnabled(True)
        self.capture_button.setEnabled(True)
        self.clear_capture_button.setEnabled(self._image_path is not None)
        self._set_document_controls_enabled(True)
        self.deck_input.setEnabled(True)
        self.refresh_decks_button.setEnabled(self._deck_load_thread is None)
        self._import_worker = None
        self._import_thread = None
        self._update_card_action_state()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._prompt_save_timer.stop()
        if not self._save_dirty_prompt():
            QMessageBox.warning(self, "提示词未保存", "提示词保存失败，窗口将保持打开。")
            event.ignore()
            return
        active_threads = (
            self._generation_thread,
            self._import_thread,
            self._regeneration_thread,
            self._template_sync_thread,
            self._deck_load_thread,
        )
        if any(thread is not None and thread.isRunning() for thread in active_threads):
            QMessageBox.information(
                self,
                "任务仍在运行",
                "当前任务尚未结束。请等待任务完成后再关闭 FlashForge。",
            )
            event.ignore()
            return
        self._screenshot_hotkey.unregister()
        super().closeEvent(event)
