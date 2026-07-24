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
DOCUMENT_INSTRUCTIONS = """## 本地资料提炼规则
输入来自本地 Markdown 资料，可能包含课堂对话、学生错误、教师纠正和重复总结。
- 只提取适合长期记忆的定义、公式、适用条件、方法选择、因果解释和常见误区。
- 学生回答和教师的中间尝试都不能直接视为事实；有纠正过程时，以后续明确确认且与上下文一致的结论为准。
- 忽略寒暄、鼓励、角色动作、课程安排和没有知识含量的过渡语。
- 保留必要的数学条件和变量含义，公式使用原有 MathJax/LaTeX 形式。
- 不为同一个结论生成措辞不同但实质重复的卡片。
- 当前输入可能只是完整文档的一个片段；每个片段最多生成 24 张卡片，优先保留高价值知识。

"""
SOCRATOPIA_INSTRUCTIONS = """## Socratopia 自适应制卡规则
输入同时包含教材原文、实际上课记录、教学效果和已有卡片问题。必须按以下证据层级制卡：
- “qbook 原始教材已讲范围”已经由所选课堂记录限定到本章起点至该堂课的实际授课终点，其中每个高价值小节都可以制卡，即使课堂只是一笔带过。
- 若只有“与已学证据匹配的教材缓存”，教材只负责确认知识事实，不能单独扩张已学范围。
- 教材缓存可能预加载未来章节；不得从当前输入以外推测或补充后续章节。
- 先逐节扫描已讲范围，列出核心定义、机制、公式、条件和典型误区，确保浅讲内容不会因课堂记录较少而遗漏；再综合教学效果筛选最终卡片。
- 优先制作学习者答错、提示后纠正、表述不精确、主动追问或仍在展开中的知识；独立稳定掌握的内容仅保留高价值核心卡。
- 学习者的错误答案只能作为误区来源，卡片答案必须采用教师确认且与教材一致的最终结论。
- “已有卡片问题”是排除清单，不得生成同义或仅换措辞的重复卡片。
- 卡片应加入 `socratopia`、教材 ID 和主题标签；薄弱点可额外加入 `薄弱点` 标签。
- 本次最多生成 20 张卡片。宁可少做，也不要越过实际教学进度或生成低价值重复卡。

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

    def render(
        self,
        material: str,
        name: str = DEFAULT_PROMPT_NAME,
        *,
        image_mode: bool = False,
        document_mode: bool = False,
        socratopia_mode: bool = False,
    ) -> str:
        cleaned = material.strip()
        if not cleaned:
            raise ValueError("学习材料不能为空。")
        template = self.load(name)
        instructions = ""
        if image_mode:
            instructions += IMAGE_INSTRUCTIONS
        if document_mode:
            instructions += DOCUMENT_INSTRUCTIONS
        if socratopia_mode:
            instructions += SOCRATOPIA_INSTRUCTIONS
        if instructions:
            marker = "## 角色\n"
            template = (
                template.replace(marker, f"{marker}{instructions}", 1)
                if marker in template
                else f"{instructions}\n{template}"
            )
        return template.replace(MATERIAL_TOKEN, cleaned)
