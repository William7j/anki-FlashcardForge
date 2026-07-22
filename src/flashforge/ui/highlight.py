"""Syntax highlighter for the prompt editor."""

from __future__ import annotations

from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat

from flashforge.prompts import MATERIAL_TOKEN


class PromptHighlighter(QSyntaxHighlighter):
    def __init__(self, document) -> None:  # type: ignore[no-untyped-def]
        super().__init__(document)
        self.heading_format = QTextCharFormat()
        self.heading_format.setForeground(QColor("#0f766e"))
        self.json_format = QTextCharFormat()
        self.json_format.setForeground(QColor("#1d4ed8"))
        self.token_format = QTextCharFormat()
        self.token_format.setForeground(QColor("#b45309"))

    def highlightBlock(self, text: str) -> None:
        if text.lstrip().startswith("#"):
            self.setFormat(0, len(text), self.heading_format)
        if text.strip().startswith(("{", "[", '"')):
            self.setFormat(0, len(text), self.json_format)
        start = text.find(MATERIAL_TOKEN)
        if start >= 0:
            self.setFormat(start, len(MATERIAL_TOKEN), self.token_format)
