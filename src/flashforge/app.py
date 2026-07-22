"""Application entry point."""

from __future__ import annotations

import ctypes
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from flashforge.config import AppSettings
from flashforge.resources import app_icon_path
from flashforge.theme import apply_theme
from flashforge.ui import MainWindow


def main() -> int:
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FlashForge.Desktop")
        except AttributeError:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("FlashForge")
    app.setWindowIcon(QIcon(str(app_icon_path())))
    try:
        settings = AppSettings.load()
    except ValueError as exc:
        settings = AppSettings()
        QMessageBox.warning(None, "设置文件无效", f"将使用默认设置启动。\n\n{exc}")
    apply_theme(app, settings.theme)
    window = MainWindow(settings)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
