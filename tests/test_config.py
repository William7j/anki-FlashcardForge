import yaml
import pytest

from flashforge.config import AppSettings


class FakeSecretStore:
    def __init__(self, value="") -> None:
        self.value = value

    def get_api_key(self) -> str:
        return self.value

    def set_api_key(self, value: str) -> None:
        self.value = value


def test_settings_save_and_load_round_trip(tmp_path) -> None:
    settings_path = tmp_path / "settings.yaml"
    expected = AppSettings(api_key="test-key", model="vision-model", deck_name="Biology")
    secrets = FakeSecretStore()

    expected.save(settings_path, secrets)

    assert AppSettings.load(settings_path, secrets) == expected
    assert "api_key" not in yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    assert secrets.value == "test-key"


def test_mapping_uses_defaults_for_omitted_values() -> None:
    settings = AppSettings.from_mapping({"api_key": " key "})

    assert settings.api_key == "key"
    assert settings.base_url == "https://api.openai.com/v1"


def test_ollama_settings_do_not_require_an_api_key() -> None:
    settings = AppSettings.from_mapping({"provider": "ollama", "model": "qwen3"})

    assert settings.provider == "ollama"
    assert settings.base_url == "http://127.0.0.1:11434/v1"
    assert settings.requires_api_key is False


def test_theme_is_persisted_in_settings_mapping() -> None:
    settings = AppSettings.from_mapping({"theme": "dark"})

    assert settings.theme == "dark"


def test_capture_autogeneration_is_persisted_in_settings_mapping() -> None:
    settings = AppSettings.from_mapping({"auto_generate_after_capture": "true"})

    assert settings.auto_generate_after_capture is True


def test_hotkey_and_auto_import_are_persisted_in_settings_mapping() -> None:
    settings = AppSettings.from_mapping(
        {
            "screenshot_hotkey": "Ctrl + Shift + S",
            "auto_import_after_generation": "true",
        }
    )

    assert settings.screenshot_hotkey == "ctrl+shift+s"
    assert settings.auto_import_after_generation is True


def test_legacy_yaml_api_key_is_read_until_next_save(tmp_path) -> None:
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text("api_key: legacy-key\nmodel: legacy-model\n", encoding="utf-8")
    secrets = FakeSecretStore()

    settings = AppSettings.load(settings_path, secrets)
    settings.save(settings_path, secrets)

    assert settings.api_key == "legacy-key"
    assert secrets.value == "legacy-key"
    assert "api_key" not in yaml.safe_load(settings_path.read_text(encoding="utf-8"))


def test_malformed_yaml_has_actionable_error(tmp_path) -> None:
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text("model: [broken", encoding="utf-8")

    with pytest.raises(ValueError, match="无法读取设置文件"):
        AppSettings.load(settings_path, FakeSecretStore())
