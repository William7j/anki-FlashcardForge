"""Application entry point."""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path
import tempfile

from PySide6.QtCore import QLockFile
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from flashforge.config import AppSettings
from flashforge.resources import app_icon_path
from flashforge.theme import apply_theme
from flashforge.ui import MainWindow


def acquire_instance_lock(lock_path: Path | None = None) -> QLockFile | None:
    path = lock_path or Path(tempfile.gettempdir()) / "FlashForge-instance.lock"
    lock = QLockFile(str(path))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        return None
    return lock


def main() -> int:
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FlashForge.Desktop")
        except AttributeError:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("FlashForge")
    app.setWindowIcon(QIcon(str(app_icon_path())))
    app.setQuitOnLastWindowClosed(True)
    instance_lock = acquire_instance_lock()
    if instance_lock is None:
        QMessageBox.information(None, "FlashForge 已在运行", "FlashForge 已经启动，请使用现有窗口。")
        return 0
    try:
        settings = AppSettings.load()
    except ValueError as exc:
        settings = AppSettings()
        QMessageBox.warning(None, "设置文件无效", f"将使用默认设置启动。\n\n{exc}")
    apply_theme(app, settings.theme)
    window = MainWindow(settings)
    app.aboutToQuit.connect(window.prepare_for_exit)
    window.show()
    try:
        return app.exec()
    finally:
        window.prepare_for_exit()
        instance_lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())
