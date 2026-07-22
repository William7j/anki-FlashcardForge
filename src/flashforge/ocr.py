"""Optional local OCR fallback for image-to-card generation."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any


class OcrError(RuntimeError):
    """Raised when the optional RapidOCR path cannot produce text."""


class LocalOcr:
    def __init__(self, engine: Any | None = None) -> None:
        if engine is not None:
            self._engine = engine
            return
        if sys.version_info >= (3, 13):
            raise OcrError("RapidOCR 当前仅支持 Python 3.12；请使用 Python 3.12 安装 OCR 组件。")
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise OcrError("未安装 OCR 组件。请执行 python -m pip install -e .[ocr]。") from exc
        self._engine = RapidOCR()

    def extract(self, image_path: Path) -> str:
        try:
            output = self._engine(str(image_path))
        except Exception as exc:
            raise OcrError("本地 OCR 执行失败。") from exc
        result = output[0] if isinstance(output, tuple) else output
        if not result:
            raise OcrError("未从截图中识别到文字。")
        lines: list[str] = []
        for item in result:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            text = str(item[1]).strip()
            if text:
                lines.append(text)
        if not lines:
            raise OcrError("未从截图中识别到文字。")
        return "\n".join(lines)
