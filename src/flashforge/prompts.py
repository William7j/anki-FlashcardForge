"""Prompt loading and safe material insertion."""

from __future__ import annotations

import os
from pathlib import Path
import re


DEFAULT_PROMPT_NAME = "default_adaptive"
MATERIAL_TOKEN = "{{学习材料}}"
IMAGE_INSTRUCTIONS = """## 输入格式说明
用户提供的是学习材料截图。请结合文字、表格、公式、图表和版面结构提取知识点。

"""
TEMPLATE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def default_user_prompt_dir() -> Path:
    app_data = Path(os.environ.get("APPDATA", Path.home()))
    return app_data / "FlashForge" / "prompts"


class PromptManager:
    def __init__(self, user_prompt_dir: Path | None = None) -> None:
        self._user_prompt_dir = user_prompt_dir or default_user_prompt_dir()
        self._built_in_dir = Path(__file__).parent / "prompts"

    def available_names(self) -> list[str]:
        names = {path.stem for path in self._built_in_dir.glob("*.md")}
        if self._user_prompt_dir.exists():
            names.update(path.stem for path in self._user_prompt_dir.glob("*.md"))
        return sorted(names)

    def load(self, name: str = DEFAULT_PROMPT_NAME) -> str:
        filename = f"{name}.md"
        user_path = self._user_prompt_dir / filename
        path = user_path if user_path.exists() else self._built_in_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"找不到提示词模板：{name}")
        template = path.read_text(encoding="utf-8")
        if MATERIAL_TOKEN not in template:
            raise ValueError(f"提示词模板必须包含占位符 {MATERIAL_TOKEN}。")
        return template

    def save_override(self, name: str, template: str) -> Path:
        self._validate_name(name)
        if MATERIAL_TOKEN not in template:
            raise ValueError(f"提示词模板必须包含占位符 {MATERIAL_TOKEN}。")
        if not template.strip():
            raise ValueError("提示词模板不能为空。")
        self._user_prompt_dir.mkdir(parents=True, exist_ok=True)
        path = self._user_prompt_dir / f"{name}.md"
        path.write_text(template, encoding="utf-8")
        return path

    def remove_override(self, name: str) -> bool:
        self._validate_name(name)
        path = self._user_prompt_dir / f"{name}.md"
        if not path.exists():
            return False
        path.unlink()
        return True

    def has_override(self, name: str) -> bool:
        return (self._user_prompt_dir / f"{name}.md").exists()

    def is_built_in(self, name: str) -> bool:
        return (self._built_in_dir / f"{name}.md").exists()

    @staticmethod
    def _validate_name(name: str) -> None:
        if not TEMPLATE_NAME_PATTERN.fullmatch(name):
            raise ValueError("模板名称只能使用小写字母、数字和下划线，且必须以字母开头。")

    def render(self, material: str, name: str = DEFAULT_PROMPT_NAME, *, image_mode: bool = False) -> str:
        cleaned = material.strip()
        if not cleaned:
            raise ValueError("学习材料不能为空。")
        template = self.load(name)
        if image_mode:
            template = template.replace("## 角色\n", f"## 角色\n{IMAGE_INSTRUCTIONS}", 1)
        return template.replace(MATERIAL_TOKEN, cleaned)
