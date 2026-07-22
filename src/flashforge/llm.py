"""OpenAI-compatible chat client with text and multimodal entry points."""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage

from flashforge.config import AppSettings, OLLAMA_BASE_URL


class LlmError(RuntimeError):
    """Raised when a provider cannot return usable card JSON."""


class LlmClient:
    MAX_IMAGE_EDGE = 2048
    MAX_IMAGE_BYTES = 6 * 1024 * 1024

    def __init__(self, settings: AppSettings, client: Any | None = None) -> None:
        self.settings = settings
        self._client = client

    def _client_or_create(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.settings.api_key and self.settings.provider != "ollama":
            raise LlmError("请先在设置页填写 API 密钥。")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise LlmError("缺少 openai 依赖，请重新安装 FlashForge。") from exc
        api_key = self.settings.api_key or "ollama"
        base_url = self.settings.base_url
        if self.settings.provider == "ollama" and base_url == "https://api.openai.com/v1":
            base_url = OLLAMA_BASE_URL
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=self.settings.request_timeout_seconds,
        )
        return self._client

    def generate_text(self, prompt: str) -> str:
        response = self._create_completion([{"role": "user", "content": prompt}])
        return self._content_from_response(response)

    def generate_image(self, prompt: str, image_path: Path) -> str:
        image_data_uri = self._image_data_uri(image_path)
        response = self._create_completion(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": image_data_uri},
                        },
                    ],
                }
            ]
        )
        return self._content_from_response(response)

    @classmethod
    def _image_data_uri(cls, image_path: Path) -> str:
        source = image_path.read_bytes()
        image = QImage(str(image_path))
        if image.isNull():
            raise LlmError("截图文件无法读取。")
        should_compress = (
            image.width() > cls.MAX_IMAGE_EDGE
            or image.height() > cls.MAX_IMAGE_EDGE
            or len(source) > cls.MAX_IMAGE_BYTES
        )
        if should_compress:
            scaled = image.scaled(
                cls.MAX_IMAGE_EDGE,
                cls.MAX_IMAGE_EDGE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            if not scaled.save(buffer, "JPEG", 88):  # type: ignore[call-overload]
                raise LlmError("无法压缩截图。")
            source = bytes(buffer.data().data())
            media_type = "image/jpeg"
        else:
            media_type = mimetypes.guess_type(image_path.name)[0] or "image/png"
        image_data = base64.b64encode(source).decode("ascii")
        return f"data:{media_type};base64,{image_data}"

    def _create_completion(self, messages: list[dict[str, Any]]) -> Any:
        create = self._client_or_create().chat.completions.create
        kwargs: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
        }
        if self.settings.provider != "ollama":
            kwargs["response_format"] = {"type": "json_object"}
        return create(**kwargs)

    @staticmethod
    def _content_from_response(response: Any) -> str:
        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as exc:
            raise LlmError("模型响应中没有可用内容。") from exc
        if not isinstance(content, str) or not content.strip():
            raise LlmError("模型返回了空内容。")
        return content.strip()
