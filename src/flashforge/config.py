"""Persistent application settings stored outside the project directory."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
from typing import Any

import yaml

from flashforge.secrets import SecretStorageError, SecretStore


OLLAMA_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_SCREENSHOT_HOTKEY = "ctrl+alt+a"
PROVIDERS = {"openai_compatible", "ollama"}
IMAGE_INPUT_MODES = {"multimodal", "ocr"}
THEMES = {"system", "light", "dark"}


def default_settings_path() -> Path:
    app_data = Path(os.environ.get("APPDATA", Path.home()))
    return app_data / "FlashForge" / "settings.yaml"


@dataclass(slots=True)
class AppSettings:
    provider: str = "openai_compatible"
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4.1-mini"
    deck_name: str = "FlashForge"
    prompt_name: str = "default_adaptive"
    image_input_mode: str = "multimodal"
    screenshot_hotkey: str = DEFAULT_SCREENSHOT_HOTKEY
    auto_generate_after_capture: bool = False
    auto_import_after_generation: bool = False
    theme: str = "system"
    request_timeout_seconds: float = 90.0

    @property
    def requires_api_key(self) -> bool:
        return self.provider != "ollama"

    @classmethod
    def load(
        cls, path: Path | None = None, secret_store: SecretStore | None = None
    ) -> "AppSettings":
        settings_path = path or default_settings_path()
        secrets = secret_store or SecretStore()
        if not settings_path.exists():
            return cls(api_key=cls._load_api_key(secrets))

        try:
            raw = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise ValueError("无法读取设置文件，请修复或移除 settings.yaml 后重试。") from exc
        if not isinstance(raw, dict):
            raise ValueError("设置文件必须是 YAML 对象。")

        legacy_api_key = str(raw.pop("api_key", "") or "")
        stored_api_key = cls._load_api_key(secrets)
        raw["api_key"] = stored_api_key or legacy_api_key
        return cls.from_mapping(raw)

    def save(self, path: Path | None = None, secret_store: SecretStore | None = None) -> None:
        settings_path = path or default_settings_path()
        secrets = secret_store or SecretStore()
        secrets.set_api_key(self.api_key)
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        persisted = asdict(self)
        persisted.pop("api_key")
        settings_path.write_text(
            yaml.safe_dump(persisted, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    @staticmethod
    def _load_api_key(secrets: SecretStore) -> str:
        try:
            return secrets.get_api_key()
        except SecretStorageError:
            # A legacy YAML key remains available for one migration cycle even when
            # a locked-down environment cannot access the credential manager.
            return ""

    @classmethod
    def from_mapping(cls, values: dict[str, Any]) -> "AppSettings":
        defaults = cls()
        provider = str(values.get("provider", defaults.provider)).strip().lower()
        image_input_mode = str(
            values.get("image_input_mode", defaults.image_input_mode)
        ).strip().lower()
        screenshot_hotkey = _as_hotkey(
            values.get("screenshot_hotkey", defaults.screenshot_hotkey)
        )
        auto_generate_after_capture = _as_bool(
            values.get("auto_generate_after_capture", defaults.auto_generate_after_capture),
            "截图后自动生成",
        )
        auto_import_after_generation = _as_bool(
            values.get("auto_import_after_generation", defaults.auto_import_after_generation),
            "生成后自动导入 Anki",
        )
        theme = str(values.get("theme", defaults.theme)).strip().lower()
        if provider not in PROVIDERS:
            raise ValueError(f"不支持的模型提供方：{provider}")
        if image_input_mode not in IMAGE_INPUT_MODES:
            raise ValueError(f"不支持的图片输入模式：{image_input_mode}")
        if theme not in THEMES:
            raise ValueError(f"不支持的主题：{theme}")
        default_base_url = OLLAMA_BASE_URL if provider == "ollama" else defaults.base_url
        return cls(
            provider=provider,
            api_key=str(values.get("api_key", "")).strip(),
            base_url=str(values.get("base_url", default_base_url)).strip().rstrip("/"),
            model=str(values.get("model", defaults.model)).strip(),
            deck_name=str(values.get("deck_name", defaults.deck_name)).strip(),
            prompt_name=str(values.get("prompt_name", defaults.prompt_name)).strip(),
            image_input_mode=image_input_mode,
            screenshot_hotkey=screenshot_hotkey,
            auto_generate_after_capture=auto_generate_after_capture,
            auto_import_after_generation=auto_import_after_generation,
            theme=theme,
            request_timeout_seconds=float(
                values.get("request_timeout_seconds", defaults.request_timeout_seconds)
            ),
        )


def _as_hotkey(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("截图快捷键必须是文本。")
    hotkey = value.replace(" ", "").lower()
    if not hotkey:
        raise ValueError("截图快捷键不能为空。")
    return hotkey


def _as_bool(value: Any, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off", ""}:
            return False
    raise ValueError(f"{field_name}必须是布尔值。")
