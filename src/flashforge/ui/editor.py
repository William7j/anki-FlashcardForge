"""Card editor dialog for modifying generated cards before Anki import."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from flashforge.models import CardType, Flashcard


class CardEditorDialog(QDialog):
    """Edit one card while reusing the same validation applied to LLM output."""

    FIELD_LABELS = {
        "question": "问题",
        "content": "填空内容",
        "answer": "答案",
        "options": "选项（每行一项）",
        "remark": "备注",
    }

    def __init__(self, card: Flashcard, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.card: Flashcard | None = None
        self.setWindowTitle("编辑卡片")
        self.setMinimumSize(620, 520)
        layout = QVBoxLayout(self)
        self.form = QFormLayout()
        self.card_type_input = QComboBox()
        for card_type in CardType:
            self.card_type_input.addItem(card_type.value, card_type)
        self.card_type_input.setCurrentIndex(list(CardType).index(card.card_type))
        self.card_type_input.currentIndexChanged.connect(self._sync_visible_fields)
        self.form.addRow("题型", self.card_type_input)
        self.field_inputs: dict[str, QPlainTextEdit] = {}
        for field_name in self.FIELD_LABELS:
            input_widget = QPlainTextEdit(card.fields.get(field_name, ""))
            input_widget.setMinimumHeight(68)
            self.field_inputs[field_name] = input_widget
            self.form.addRow(self.FIELD_LABELS[field_name], input_widget)
        self.tags_input = QLineEdit(", ".join(card.tags))
        self.tags_input.setPlaceholderText("用逗号分隔标签")
        self.form.addRow("标签", self.tags_input)
        layout.addLayout(self.form)
        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: #b91c1c;")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._active_fields: set[str] = set()
        self._sync_visible_fields()

    def _selected_type(self) -> CardType:
        return CardType(str(self.card_type_input.currentData()))

    def _sync_visible_fields(self) -> None:
        card_type = self._selected_type()
        visible = {"remark"}
        if card_type is CardType.CLOZE:
            visible.add("content")
        else:
            visible.update({"question", "answer"})
        if card_type in {CardType.CHOICE, CardType.MULTICHOICE}:
            visible.add("options")
        self._active_fields = visible
        for field_name, input_widget in self.field_inputs.items():
            input_widget.setVisible(field_name in visible)
            label = self.form.labelForField(input_widget)
            if label:
                label.setVisible(field_name in visible)

    def _save(self) -> None:
        fields = {
            field_name: input_widget.toPlainText().strip()
            for field_name, input_widget in self.field_inputs.items()
            if field_name in self._active_fields
        }
        tags = [tag.strip() for tag in self.tags_input.text().replace("，", ",").split(",") if tag.strip()]
        try:
            self.card = Flashcard.from_payload(
                {"type": self._selected_type().value, "fields": fields, "tags": tags}
            )
        except Exception as exc:
            self.error_label.setText(str(exc))
            return
        self.accept()
