"""Application palette management."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def apply_theme(app: QApplication, theme: str) -> None:
    app.setStyle("Fusion")
    if theme != "dark":
        app.setPalette(app.style().standardPalette())
        return

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#111827"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e5e7eb"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#1f2937"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#111827"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#e5e7eb"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#111827"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#f9fafb"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#374151"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#f9fafb"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#0f766e"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)
