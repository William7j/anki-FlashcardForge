"""Local document parsing and cleaning for document-based card generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import yaml


MAX_MARKDOWN_BYTES = 5 * 1024 * 1024
MAX_CLEANED_CHARACTERS = 60_000
MESSAGE_HEADER_PATTERN = re.compile(
    r"^\*\*(?P<speaker>[^*\n]+)\*\*\s*·\s*(?P<timestamp>\d{1,2}:\d{2})\s*$",
    re.MULTILINE,
)
STAGE_DIRECTION_PATTERN = re.compile(r"^\s*\*[^*\n].*\*\s*$")
INLINE_STAGE_DIRECTION_PATTERN = re.compile(r"(?<!\*)\*[^*\n]+\*(?!\*)")


class DocumentParseError(ValueError):
    """Raised when a local document cannot be converted into learning material."""


@dataclass(frozen=True, slots=True)
class DocumentMessage:
    index: int
    speaker: str
    timestamp: str
    content: str


@dataclass(frozen=True, slots=True)
class MarkdownDocument:
    path: Path
    title: str
    metadata: dict[str, str]
    messages: tuple[DocumentMessage, ...]
    cleaned_material: str

    @property
    def message_count(self) -> int:
        return len(self.messages)


def load_markdown_document(path: Path) -> MarkdownDocument:
    source_path = Path(path)
    if source_path.suffix.lower() not in {".md", ".markdown"}:
        raise DocumentParseError("第一阶段仅支持 Markdown 文件（.md 或 .markdown）。")
    try:
        file_size = source_path.stat().st_size
    except OSError as exc:
        raise DocumentParseError(f"无法读取文件：{source_path}") from exc
    if file_size > MAX_MARKDOWN_BYTES:
        raise DocumentParseError("Markdown 文件超过 5 MB，请拆分后再导入。")
    try:
        raw_text = source_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise DocumentParseError("无法以 UTF-8 读取 Markdown 文件。") from exc
    if not raw_text.strip():
        raise DocumentParseError("Markdown 文件为空。")

    metadata, body = _split_front_matter(raw_text)
    title = metadata.get("title") or _first_heading(body) or source_path.stem
    messages = _parse_messages(body)
    cleaned_material = (
        _render_classroom_material(title, metadata, messages)
        if messages
        else body.strip()
    )
    if not cleaned_material:
        raise DocumentParseError("Markdown 文件中没有可用于制卡的正文。")
    if len(cleaned_material) > MAX_CLEANED_CHARACTERS:
        raise DocumentParseError("清洗后的 Markdown 超过 60000 字符，请拆分章节后再导入。")
    return MarkdownDocument(
        path=source_path,
        title=title,
        metadata=metadata,
        messages=messages,
        cleaned_material=cleaned_material,
    )


def _split_front_matter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    try:
        closing_index = next(
            index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"
        )
    except StopIteration:
        return {}, text
    try:
        raw_metadata: Any = yaml.safe_load("\n".join(lines[1:closing_index])) or {}
    except yaml.YAMLError as exc:
        raise DocumentParseError("Markdown front matter 不是有效的 YAML。") from exc
    if not isinstance(raw_metadata, dict):
        raise DocumentParseError("Markdown front matter 必须是 YAML 对象。")
    metadata = {
        str(key).strip(): str(value).strip()
        for key, value in raw_metadata.items()
        if value is not None and str(value).strip()
    }
    return metadata, "\n".join(lines[closing_index + 1 :]).strip()


def _first_heading(body: str) -> str:
    match = re.search(r"^#\s+(.+?)\s*$", body, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def _parse_messages(body: str) -> tuple[DocumentMessage, ...]:
    matches = list(MESSAGE_HEADER_PATTERN.finditer(body))
    messages: list[DocumentMessage] = []
    for index, match in enumerate(matches, start=1):
        content_end = matches[index].start() if index < len(matches) else len(body)
        content = _clean_message_content(body[match.end() : content_end])
        if not content:
            continue
        messages.append(
            DocumentMessage(
                index=index,
                speaker=match.group("speaker").strip(),
                timestamp=match.group("timestamp"),
                content=content,
            )
        )
    return tuple(messages)


def _clean_message_content(content: str) -> str:
    retained_lines: list[str] = []
    for line in content.strip().splitlines():
        if STAGE_DIRECTION_PATTERN.fullmatch(line.strip()):
            continue
        retained_lines.append(INLINE_STAGE_DIRECTION_PATTERN.sub("", line).rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(retained_lines)).strip()


def _render_classroom_material(
    title: str,
    metadata: dict[str, str],
    messages: tuple[DocumentMessage, ...],
) -> str:
    header = [f"# {title}"]
    for key in ("textbook", "date", "source", "companion", "learner"):
        if value := metadata.get(key):
            header.append(f"- {key}: {value}")
    sections = ["\n".join(header), "## 清洗后的课堂对话"]
    sections.extend(
        f"### 消息 {message.index} | {message.speaker} | {message.timestamp}\n\n{message.content}"
        for message in messages
    )
    return "\n\n".join(sections)
