"""Screen capture and region selection used by the multimodal card flow."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QGuiApplication, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QDialog


class ScreenshotError(RuntimeError):
    """Raised when a screen image cannot be captured or selected."""


def capture_virtual_desktop() -> Path:
    """Capture every attached display into a temporary PNG and return its path."""
    try:
        import mss
        import mss.tools
    except ImportError as exc:
        raise ScreenshotError("缺少 mss 依赖，请重新安装 FlashForge。") from exc

    output_path = Path(tempfile.gettempdir()) / f"flashforge-{uuid4().hex}.png"
    try:
        with mss.mss() as capturer:
            # Index zero is MSS's virtual monitor, spanning all connected displays.
            monitor = capturer.monitors[0]
            image = capturer.grab(monitor)
            mss.tools.to_png(image.rgb, image.size, output=str(output_path))
    except Exception as exc:
        raise ScreenshotError("无法读取屏幕内容。") from exc
    return output_path


class GlobalScreenshotHotkey:
    """Best-effort global shortcut registration with deterministic cleanup."""

    def __init__(
        self,
        shortcut: str,
        callback: Callable[[], None],
        keyboard_module: Any | None = None,
    ) -> None:
        self.shortcut = shortcut
        self.callback = callback
        self._keyboard_module = keyboard_module
        self._hotkey_id: Any | None = None

    def register(self) -> bool:
        if self._hotkey_id is not None:
            return True
        try:
            keyboard = self._keyboard_module
            if keyboard is None:
                import keyboard as keyboard_module

                keyboard = keyboard_module
            self._keyboard_module = keyboard
            self._hotkey_id = keyboard.add_hotkey(self.shortcut, self.callback)
        except Exception:
            self._hotkey_id = None
            return False
        return True

    def unregister(self) -> None:
        if self._hotkey_id is None or self._keyboard_module is None:
            return
        try:
            self._keyboard_module.remove_hotkey(self._hotkey_id)
        except Exception:
            pass
        finally:
            self._hotkey_id = None


class RegionSelector(QDialog):
    """A temporary full-screen overlay that saves the drag-selected image region."""

    def __init__(self, screenshot_path: Path) -> None:
        super().__init__()
        self._source_path = screenshot_path
        self._pixmap = QPixmap(str(screenshot_path))
        if self._pixmap.isNull():
            raise ScreenshotError("截图文件无法读取。")
        self._start: QPoint | None = None
        self._selection = QRect()
        self.selected_path: Path | None = None
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setCursor(Qt.CursorShape.CrossCursor)
        primary_screen = QGuiApplication.primaryScreen()
        if primary_screen is None:
            raise ScreenshotError("无法获取显示器信息。")
        self.setGeometry(primary_screen.virtualGeometry())
        self.show()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = event.position().toPoint()
            self._selection = QRect(self._start, self._start)
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._start is not None:
            self._selection = QRect(self._start, event.position().toPoint()).normalized()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._start is None:
            return
        self._selection = QRect(self._start, event.position().toPoint()).normalized()
        self._start = None
        if self._selection.width() < 8 or self._selection.height() < 8:
            self.reject()
            return
        cropped = self._displayed_pixmap().copy(self._selection)
        output_path = self._source_path.with_name(f"flashforge-selection-{uuid4().hex}.png")
        if not cropped.save(str(output_path), "PNG"):
            raise ScreenshotError("无法保存截图选区。")
        self.selected_path = output_path
        self.accept()

    def keyPressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        pixmap = self._displayed_pixmap()
        painter.drawPixmap(0, 0, pixmap)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 105))
        if not self._selection.isNull():
            painter.drawPixmap(self._selection, pixmap, self._selection)
            painter.setPen(QPen(QColor("#2dd4bf"), 2))
            painter.drawRect(self._selection)

    def _displayed_pixmap(self) -> QPixmap:
        return self._pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
