"""Operating-system-backed storage for API credentials."""

from __future__ import annotations

from typing import Any


class SecretStorageError(RuntimeError):
    """Raised when the system credential store cannot be used."""


class SecretStore:
    SERVICE_NAME = "FlashForge"
    API_KEY_NAME = "api_key"

    def __init__(self, backend: Any | None = None) -> None:
        self._backend = backend

    def get_api_key(self) -> str:
        try:
            value = self._keyring().get_password(self.SERVICE_NAME, self.API_KEY_NAME)
        except Exception as exc:
            raise SecretStorageError("无法读取系统凭据库。") from exc
        return value or ""

    def set_api_key(self, api_key: str) -> None:
        try:
            if api_key:
                self._keyring().set_password(self.SERVICE_NAME, self.API_KEY_NAME, api_key)
            else:
                try:
                    self._keyring().delete_password(self.SERVICE_NAME, self.API_KEY_NAME)
                except Exception:
                    pass
        except Exception as exc:
            raise SecretStorageError("无法写入系统凭据库。") from exc

    def _keyring(self) -> Any:
        if self._backend is not None:
            return self._backend
        try:
            import keyring
        except ImportError as exc:
            raise SecretStorageError("缺少 keyring 依赖，请重新安装 FlashForge。") from exc
        self._backend = keyring
        return keyring
