from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

from flashforge.theme import apply_theme


def test_dark_theme_applies_dark_window_palette(monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])

    apply_theme(app, "dark")

    assert app.palette().color(QPalette.ColorRole.Window).name() == "#111827"
