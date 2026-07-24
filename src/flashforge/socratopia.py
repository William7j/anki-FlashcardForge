"""Read-only Socratopia course discovery and adaptive material assembly."""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Iterable

import httpx


MAX_SOURCE_CHARACTERS = 55_000
MAX_TEXTBOOK_CHARACTERS = 24_000
MAX_CHAT_MESSAGES = 24
MAX_RELEVANT_EXISTING_CARDS = 24
PAGE_MARKER_PATTERN = re.compile(r"^---\s*第\s*(\d+)\s*页\s*---\s*$", re.MULTILINE)
STAGE_DIRECTION_PATTERN = re.compile(r"(?<!\*)\*[^*\n]+\*(?!\*)")
PAGE_REFERENCE_PATTERN = re.compile(
    r"第\s*(\d+)\s*(?:[—–~-]|至|到)\s*(\d+)\s*页|第\s*(\d+)\s*页|[〔\[]§(\d+)[｜|]"
)
MATH_SPAN_PATTERN = re.compile(
    r"\$\$.+?\$\$|\\\(.+?\\\)|\\\[.+?\\\]|\$(?!\$).+?(?<!\\)\$",
    re.DOTALL,
)


class SocratopiaParseError(ValueError):
    """Raised when a Socratopia account cannot provide usable course evidence."""


class SocratopiaTextbookError(ValueError):
    """Raised when Socratopia cannot provide a decrypted textbook section."""


@dataclass(frozen=True, slots=True)
class SocratopiaCourse:
    account_path: Path
    profile_id: str
    profile_name: str
    world_id: str
    textbook_id: str
    title: str
    format: str
    current_page: int | None
    total_pages: int | None
    is_active: bool

    @property
    def key(self) -> str:
        return f"{self.account_path.name}/{self.profile_id}/{self.world_id}/{self.textbook_id}"

    @property
    def display_name(self) -> str:
        active = " [当前]" if self.is_active else ""
        progress = ""
        if self.current_page is not None and self.total_pages:
            progress = f" ({self.current_page}/{self.total_pages})"
        return f"{self.profile_name} / {self.title}{progress}{active}"


@dataclass(frozen=True, slots=True)
class SocratopiaLesson:
    course_key: str
    conversation_id: str
    title: str
    started_at: datetime
    message_count: int
    study_seconds: int | None
    summary: str = ""
    teaching_effect: str = ""

    @property
    def date_label(self) -> str:
        return self.started_at.strftime("%Y-%m-%d %H:%M")

    @property
    def duration_label(self) -> str:
        if not self.study_seconds:
            return "未记录"
        minutes = max(1, round(self.study_seconds / 60))
        return f"{minutes} 分钟"

    @property
    def record_preview(self) -> str:
        parts = []
        if self.summary:
            parts.append(f"课堂总结：{self.summary}")
        if self.teaching_effect:
            parts.append(f"课后效果：{self.teaching_effect}")
        if not parts:
            return "暂无课堂总结，制卡时仍会使用课堂对话。"
        text = "\n\n".join(parts)
        compact = re.sub(r"\s+", " ", text).strip()
        return compact if len(compact) <= 360 else compact[:357].rstrip() + "..."


@dataclass(frozen=True, slots=True)
class SocratopiaMaterial:
    course: SocratopiaCourse
    material: str
    lesson_evidence_count: int
    textbook_section_count: int
    existing_card_count: int
    used_original_textbook: bool = False
    textbook_range: tuple[int, int] | None = None
    textbook_warning: str = ""
    lesson: SocratopiaLesson | None = None


class SocratopiaTextbookClient:
    """Read qbook sections through Socratopia's local read-only HTTP API."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:13713",
        timeout_seconds: float = 5.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def is_available(self) -> bool:
        try:
            httpx.get(self.base_url, timeout=min(self.timeout_seconds, 1.0))
        except httpx.HTTPError:
            return False
        return True

    def read_section(self, course: SocratopiaCourse, section: int) -> str:
        try:
            response = httpx.get(
                f"{self.base_url}/api/textbook-section",
                headers={"X-Account-Id": course.account_path.name},
                params={
                    "profileId": course.profile_id,
                    "worldId": course.world_id,
                    "textbookId": course.textbook_id,
                    "section": section,
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SocratopiaTextbookError(
                "无法通过 Socratopia 本地接口读取 qbook；请先启动 Socratopia。"
            ) from exc
        content = payload.get("content") if isinstance(payload, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise SocratopiaTextbookError(f"qbook 第 {section} 节没有可用正文。")
        return content.strip()

    def read_sections(
        self, course: SocratopiaCourse, sections: Iterable[int]
    ) -> list[tuple[int, str]]:
        section_numbers = list(sections)
        if not section_numbers:
            return []
        with ThreadPoolExecutor(max_workers=min(8, len(section_numbers))) as executor:
            futures = [
                (section, executor.submit(self.read_section, course, section))
                for section in section_numbers
            ]
            return [(section, future.result()) for section, future in futures]


def default_socratopia_accounts_path() -> Path:
    return Path.home() / "AppData" / "Roaming" / "socratopia" / "project-data" / "accounts"


def discover_socratopia_accounts(accounts_path: Path | None = None) -> list[Path]:
    root = Path(accounts_path) if accounts_path is not None else default_socratopia_accounts_path()
    if not root.exists():
        raise SocratopiaParseError(
            "没有找到 Socratopia 本地数据，请确认 Socratopia 已安装并至少登录过一次。"
        )
    accounts = [
        path
        for path in root.iterdir()
        if path.is_dir() and (path / "profiles" / "profiles.json").is_file()
    ]
    if not accounts:
        raise SocratopiaParseError("没有找到可用的 Socratopia 账户。")
    return sorted(accounts, key=lambda path: path.stat().st_mtime, reverse=True)


def discover_socratopia_courses(account_path: Path) -> list[SocratopiaCourse]:
    account = Path(account_path)
    profiles_root = account / "profiles"
    profiles_payload = _read_json(profiles_root / "profiles.json", "档案索引")
    if not isinstance(profiles_payload, dict):
        raise SocratopiaParseError("Socratopia profiles.json 格式不正确。")
    profile_names = {
        str(item.get("id")): str(item.get("name") or item.get("id"))
        for item in profiles_payload.get("profiles", [])
        if isinstance(item, dict) and item.get("id")
    }
    if not profile_names:
        raise SocratopiaParseError("没有找到 Socratopia 学习档案。")

    active_profile_id = str(profiles_payload.get("activeProfileId") or "")
    courses: list[SocratopiaCourse] = []
    for profile_id, profile_name in profile_names.items():
        worlds_root = profiles_root / profile_id / "worlds"
        active_world = _read_optional_json(worlds_root / "active.json")
        active_world_id = str(active_world.get("worldId") or "")
        active_textbook_id = str(active_world.get("textbookId") or "")
        if not worlds_root.exists():
            continue
        for world_path in worlds_root.iterdir():
            if not world_path.is_dir():
                continue
            index = _read_optional_json(world_path / "textbooks" / "textbook_index.json")
            textbooks = index.get("textbooks", [])
            if not isinstance(textbooks, list):
                continue
            for textbook in textbooks:
                if not isinstance(textbook, dict) or not textbook.get("id"):
                    continue
                textbook_id = str(textbook["id"])
                courses.append(
                    SocratopiaCourse(
                        account_path=account,
                        profile_id=profile_id,
                        profile_name=profile_name,
                        world_id=world_path.name,
                        textbook_id=textbook_id,
                        title=str(textbook.get("title") or textbook.get("fileName") or textbook_id),
                        format=str(textbook.get("format") or ""),
                        current_page=_optional_int(textbook.get("currentPage")),
                        total_pages=_optional_int(textbook.get("numPages")),
                        is_active=(
                            profile_id == active_profile_id
                            and world_path.name == active_world_id
                            and textbook_id == active_textbook_id
                        ),
                    )
                )
    if not courses:
        raise SocratopiaParseError("没有找到 Socratopia 教材。")
    return sorted(
        courses,
        key=lambda item: (
            not item.is_active,
            item.profile_name.casefold(),
            item.title.casefold(),
        ),
    )


def discover_socratopia_lessons(course: SocratopiaCourse) -> list[SocratopiaLesson]:
    world_path = (
        course.account_path
        / "profiles"
        / course.profile_id
        / "worlds"
        / course.world_id
    )
    lessons: list[SocratopiaLesson] = []
    for chat in _load_course_chats(world_path / "chats", course.textbook_id):
        conversation_id = str(chat.get("id") or "")
        if not conversation_id:
            continue
        summary = _read_optional_text(world_path / "lesson_summaries" / f"{conversation_id}.md")
        postclass = _read_optional_json(world_path / "postclass" / f"{conversation_id}.json")
        written = postclass.get("written")
        effect = written.get("progressMd") if isinstance(written, dict) else ""
        if not isinstance(effect, str):
            effect = ""
        messages = chat.get("messages")
        message_count = len(messages) if isinstance(messages, list) else 0
        started_at = _parse_sort_time(chat.get("createdAt"), Path(str(chat.get("_path") or ".")))
        fallback_title = f"{course.title} ({started_at:%m-%d})"
        lessons.append(
            SocratopiaLesson(
                course_key=course.key,
                conversation_id=conversation_id,
                title=str(chat.get("title") or fallback_title),
                started_at=started_at,
                message_count=message_count,
                study_seconds=_optional_int(chat.get("studySeconds")),
                summary=summary,
                teaching_effect=effect.strip(),
            )
        )
    return lessons


def load_socratopia_material(
    course: SocratopiaCourse,
    textbook_client: SocratopiaTextbookClient | None = None,
    lesson: SocratopiaLesson | None = None,
) -> SocratopiaMaterial:
    world_path = (
        course.account_path
        / "profiles"
        / course.profile_id
        / "worlds"
        / course.world_id
    )
    textbook_path = world_path / "textbooks" / course.textbook_id
    all_chats = _load_course_chats(world_path / "chats", course.textbook_id)
    chats = all_chats
    selected_is_latest = False
    if lesson is not None:
        if lesson.course_key != course.key:
            raise SocratopiaParseError("所选课堂不属于当前课程。")
        chats = [chat for chat in chats if chat.get("id") == lesson.conversation_id]
        if not chats:
            raise SocratopiaParseError("所选课堂记录已不存在，请重新连接 Socratopia。")
        selected_is_latest = bool(all_chats and all_chats[0].get("id") == lesson.conversation_id)
    chat_by_id = {chat["id"]: chat for chat in chats}

    progress = "" if lesson is not None else _read_optional_text(textbook_path / "progress.md")
    lesson_summaries = _load_lesson_summaries(world_path, chat_by_id)
    postclass_entries = _load_postclass_entries(world_path, chat_by_id)
    latest_chat = chats[0] if chats else None
    chat_tail = _render_chat_tail(latest_chat) if latest_chat else ""

    evidence_parts = [progress]
    evidence_parts.extend(text for _, text in lesson_summaries)
    evidence_parts.extend(text for _, text in postclass_entries)
    if chat_tail:
        evidence_parts.append(chat_tail)
    evidence = "\n\n".join(part for part in evidence_parts if part.strip())
    if not evidence.strip() or _only_not_started(progress, lesson_summaries, postclass_entries, chats):
        raise SocratopiaParseError(
            f"教材《{course.title}》没有找到实际上课记录，暂不应按进度制卡。"
        )

    reading_sections = _load_reading_sections(world_path, chats)
    current_evidence = "\n\n".join(
        part
        for part in [chat_tail, *(text for _, text in lesson_summaries[:2])]
        if part.strip()
    )
    selected_sections = _select_relevant_sections(
        reading_sections,
        current_evidence=current_evidence,
        all_evidence=evidence,
    )
    page_index = _load_page_index(textbook_path / "pages.json")
    referenced_pages = _extract_textbook_page_references(_visible_chat_text(chats))
    textbook_range = _infer_taught_chapter_range(
        course,
        page_index,
        selected_sections,
        reference_pages=referenced_pages,
        fallback_page=(
            course.current_page if lesson is None or selected_is_latest else None
        ),
    )
    used_original_textbook = False
    textbook_warning = ""
    if textbook_client is not None and course.format.casefold() == "qbook":
        try:
            selected_sections = _load_original_textbook_sections(
                textbook_client,
                course,
                textbook_range,
            )
            used_original_textbook = bool(selected_sections)
        except SocratopiaTextbookError as exc:
            textbook_warning = str(exc)
    existing_card_candidates = _load_existing_cards(
        world_path / "flashcards" / f"{course.textbook_id}.json"
    )
    textbook_evidence = "\n\n".join(
        text for _, text in selected_sections if not _is_overview_section(text)
    )
    existing_cards = _select_relevant_existing_cards(
        existing_card_candidates,
        current_evidence=current_evidence,
        textbook_evidence=textbook_evidence,
    )

    sections = [
        "# Socratopia 自适应制卡材料",
        _course_overview(course),
    ]
    if lesson is not None:
        sections.append(
            "## 所选课堂\n\n"
            f"- 课堂：{lesson.title}\n"
            f"- 时间：{lesson.date_label}\n"
            f"- 学习时长：{lesson.duration_label}\n"
            f"- 课堂消息：{lesson.message_count} 条"
        )
    if progress:
        sections.append(f"## 已完成课程进度（权威范围）\n\n{progress}")
    if lesson_summaries:
        rendered = "\n\n".join(
            f"### {label}\n\n{text}" for label, text in lesson_summaries[:6]
        )
        heading = "所选课堂总结" if lesson is not None else "课堂滚动总结（含进行中的课程）"
        sections.append(f"## {heading}\n\n{rendered}")
    if postclass_entries:
        rendered = "\n\n".join(
            f"### {label}\n\n{text}" for label, text in postclass_entries[:6]
        )
        heading = "所选课堂教学效果" if lesson is not None else "课后教学效果记录"
        sections.append(f"## {heading}\n\n{rendered}")
    if chat_tail:
        heading = (
            "所选课堂对话尾部（用于识别掌握与卡点）"
            if lesson is not None
            else "最近课堂尾部（用于识别最新掌握与卡点）"
        )
        sections.append(f"## {heading}\n\n{chat_tail}")
    if selected_sections:
        rendered = "\n\n".join(text for _, text in selected_sections)
        heading = (
            "## qbook 原始教材已讲范围（覆盖性来源）"
            if used_original_textbook
            else "## 与已学证据匹配的教材缓存"
        )
        sections.append(f"{heading}\n\n{rendered}")
    if existing_cards:
        rendered = "\n".join(f"- {card}" for card in existing_cards)
        sections.append(f"## 已有卡片问题（排除同义重复）\n\n{rendered}")

    material = _fit_sections(sections, MAX_SOURCE_CHARACTERS)
    return SocratopiaMaterial(
        course=course,
        material=material,
        lesson_evidence_count=(
            len(lesson_summaries) + len(postclass_entries) + (1 if chat_tail else 0)
        ),
        textbook_section_count=len(selected_sections),
        existing_card_count=len(existing_cards),
        used_original_textbook=used_original_textbook,
        textbook_range=textbook_range,
        textbook_warning=textbook_warning,
        lesson=lesson,
    )


def _course_overview(course: SocratopiaCourse) -> str:
    page = str(course.current_page) if course.current_page is not None else "未知"
    total = str(course.total_pages) if course.total_pages is not None else "未知"
    return (
        "## 课程标识\n\n"
        f"- 学习者：{course.profile_name}\n"
        f"- 世界：{course.world_id}\n"
        f"- 教材：{course.title}\n"
        f"- 教材 ID：{course.textbook_id}\n"
        f"- 阅读器位置：{page}/{total}（仅作辅助，实际范围以课程记录为准）"
    )


def _load_course_chats(chats_path: Path, textbook_id: str) -> list[dict[str, Any]]:
    chats: list[dict[str, Any]] = []
    if not chats_path.exists():
        return chats
    for path in chats_path.glob("*.json"):
        payload = _read_optional_json(path)
        if str(payload.get("textbookId") or "") != textbook_id:
            continue
        payload = dict(payload)
        payload["id"] = str(payload.get("id") or path.stem)
        payload["_sort_time"] = _parse_sort_time(payload.get("createdAt"), path)
        payload["_path"] = str(path)
        chats.append(payload)
    return sorted(chats, key=lambda item: item["_sort_time"], reverse=True)


def _load_lesson_summaries(
    world_path: Path, chat_by_id: dict[str, dict[str, Any]]
) -> list[tuple[str, str]]:
    results: list[tuple[datetime, str, str]] = []
    root = world_path / "lesson_summaries"
    if not root.exists():
        return []
    for path in root.glob("*.md"):
        chat = chat_by_id.get(path.stem)
        if chat is None:
            continue
        text = _read_optional_text(path)
        if text:
            results.append(
                (
                    _parse_sort_time(chat.get("createdAt"), path),
                    f"课堂 {path.stem}",
                    text,
                )
            )
    results.sort(key=lambda item: item[0], reverse=True)
    return [(label, text) for _, label, text in results]


def _load_postclass_entries(
    world_path: Path, chat_by_id: dict[str, dict[str, Any]]
) -> list[tuple[str, str]]:
    results: list[tuple[datetime, str, str]] = []
    root = world_path / "postclass"
    if not root.exists():
        return []
    for path in root.glob("*.json"):
        payload = _read_optional_json(path)
        conversation_id = str(payload.get("conversationId") or path.stem)
        if conversation_id not in chat_by_id:
            continue
        written = payload.get("written")
        progress = written.get("progressMd") if isinstance(written, dict) else None
        if not isinstance(progress, str) or not progress.strip():
            continue
        when = _parse_sort_time(payload.get("completedAt"), path)
        date_label = str(payload.get("date") or conversation_id)
        results.append((when, f"{date_label} / {conversation_id}", progress.strip()))
    results.sort(key=lambda item: item[0], reverse=True)
    return [(label, text) for _, label, text in results]


def _render_chat_tail(chat: dict[str, Any]) -> str:
    messages = chat.get("messages")
    if not isinstance(messages, list):
        return ""
    rendered: list[str] = []
    for message in messages[-MAX_CHAT_MESSAGES:]:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        cleaned = STAGE_DIRECTION_PATTERN.sub("", content)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        if not cleaned:
            continue
        role = "学习者" if message.get("role") == "user" else "教师"
        rendered.append(f"### {role}\n\n{cleaned}")
    return "\n\n".join(rendered)


def _visible_chat_text(chats: Iterable[dict[str, Any]]) -> str:
    visible: list[str] = []
    for chat in chats:
        messages = chat.get("messages")
        if not isinstance(messages, list):
            continue
        for message in messages:
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, str):
                visible.append(content)
    return "\n".join(visible)


def _extract_textbook_page_references(text: str) -> list[int]:
    pages: set[int] = set()
    for match in PAGE_REFERENCE_PATTERN.finditer(text):
        range_start, range_end, single_page, section_page = match.groups()
        if range_start and range_end:
            start, end = int(range_start), int(range_end)
            if 0 < start <= end and end - start <= 30:
                pages.update(range(start, end + 1))
        else:
            value = single_page or section_page
            if value and int(value) > 0:
                pages.add(int(value))
    return sorted(pages)


def _load_reading_sections(
    world_path: Path, chats: Iterable[dict[str, Any]]
) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    seen: set[str] = set()
    for chat in chats:
        conversation_id = str(chat.get("id") or "")
        if not conversation_id:
            continue
        path = world_path / "conversations" / conversation_id / "current_reading.md"
        text = _read_optional_text(path)
        for label, section in _split_reading_pages(text):
            identity = re.sub(r"\s+", "", section)
            if not identity or identity in seen:
                continue
            seen.add(identity)
            results.append((label, section))
    return results


def _load_page_index(path: Path) -> list[tuple[int, str]]:
    payload = _read_optional_json(path)
    pages = payload.get("pages", [])
    if not isinstance(pages, list):
        return []
    results: list[tuple[int, str]] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        number = _optional_int(page.get("pageNum"))
        title = page.get("title")
        if number is not None and isinstance(title, str):
            results.append((number, title.strip()))
    return sorted(results)


def _infer_taught_chapter_range(
    course: SocratopiaCourse,
    page_index: list[tuple[int, str]],
    selected_sections: list[tuple[str, str]],
    *,
    reference_pages: Iterable[int] = (),
    fallback_page: int | None = None,
) -> tuple[int, int] | None:
    matched_pages = [
        page
        for label, _ in selected_sections
        if (page := _page_number(label)) is not None
    ]
    matched_pages.extend(page for page in reference_pages if page > 0)
    if fallback_page is not None:
        matched_pages.append(fallback_page)
    end_page = max(matched_pages) if matched_pages else None
    if end_page is None or end_page < 1:
        return None
    start_anchor = min(matched_pages)
    chapter_starts = [
        page
        for page, title in page_index
        if page <= start_anchor and re.match(r"^Chapter\s+\d+\b", title, re.IGNORECASE)
    ]
    start_page = max(chapter_starts) if chapter_starts else start_anchor
    return start_page, end_page


def _load_original_textbook_sections(
    client: SocratopiaTextbookClient,
    course: SocratopiaCourse,
    textbook_range: tuple[int, int] | None,
) -> list[tuple[str, str]]:
    if textbook_range is None:
        return []
    start_page, end_page = textbook_range
    sections: list[tuple[str, str]] = []
    for section, content in client.read_sections(
        course, range(start_page, end_page + 1)
    ):
        sections.append(
            (
                f"qbook 第 {section} 节",
                f"### qbook 第 {section} 节\n\n{content}",
            )
        )
    return sections


def _split_reading_pages(text: str) -> list[tuple[str, str]]:
    if not text.strip():
        return []
    matches = list(PAGE_MARKER_PATTERN.finditer(text))
    if not matches:
        return [("教材片段", text.strip())]
    sections: list[tuple[str, str]] = []
    prefix = text[: matches[0].start()].strip()
    if prefix:
        sections.append(("教材片段（起始页）", prefix))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        page = match.group(1)
        body = text[match.end() : end].strip()
        if body:
            sections.append((f"教材第 {page} 页", f"### 教材第 {page} 页\n\n{body}"))
    return sections


def _select_relevant_sections(
    sections: list[tuple[str, str]], *, current_evidence: str, all_evidence: str
) -> list[tuple[str, str]]:
    if not sections:
        return []
    current_grams = Counter(_character_ngrams(current_evidence, size=6))
    all_grams = Counter(_character_ngrams(all_evidence, size=6))
    scored: list[tuple[int, int, int, str, str]] = []
    for index, (label, text) in enumerate(sections):
        grams = set(_character_ngrams(text, size=6))
        current_score = sum(current_grams[gram] for gram in grams)
        history_score = sum(all_grams[gram] for gram in grams)
        if current_score > 0 or history_score > 0:
            scored.append((current_score, history_score, index, label, text))

    strongest_current = max((item[0] for item in scored), default=0)
    minimum_current = max(3, round(strongest_current * 0.2))
    candidates = [
        item
        for item in scored
        if item[0] >= minimum_current and not _is_exercise_section(item[4])
    ]
    if not candidates:
        candidates = sorted(
            (item for item in scored if not _is_exercise_section(item[4])),
            key=lambda item: (-(item[0] * 4 + item[1]), item[2]),
        )[:3]

    selected_indexes = {item[2] for item in candidates}
    for _, _, index, label, _ in candidates:
        page = _page_number(label)
        if page is None or index == 0:
            continue
        if _page_number(sections[index - 1][0]) == page - 1:
            selected_indexes.add(index - 1)

    selected: list[tuple[int, str, str]] = []
    characters = 0
    score_by_index = {item[2]: item for item in scored}
    ranked = sorted(
        (
            score_by_index.get(index, (0, 0, index, sections[index][0], sections[index][1]))
            for index in selected_indexes
        ),
        key=lambda item: (-(item[0] * 4 + item[1]), item[2]),
    )
    for _, _, index, label, text in ranked:
        if characters + len(text) > MAX_TEXTBOOK_CHARACTERS:
            continue
        selected.append((index, label, text))
        characters += len(text)
        if characters >= MAX_TEXTBOOK_CHARACTERS:
            break
    selected.sort(key=lambda item: item[0])
    return [(label, text) for _, label, text in selected]


def _page_number(label: str) -> int | None:
    match = re.fullmatch(r"教材第 (\d+) 页", label)
    return int(match.group(1)) if match else None


def _is_exercise_section(text: str) -> bool:
    heading = "\n".join(text.splitlines()[:5]).casefold()
    return "exercises" in heading or "习题" in heading


def _character_ngrams(text: str, size: int = 4) -> list[str]:
    normalized = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", text).casefold()
    if len(normalized) < size:
        return []
    return [normalized[index : index + size] for index in range(len(normalized) - size + 1)]


def _load_existing_cards(path: Path) -> list[str]:
    payload = _read_optional_json(path)
    cards = payload if isinstance(payload, list) else payload.get("cards", [])
    if not isinstance(cards, list):
        return []
    rendered: list[str] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        question = card.get("question")
        if not question and isinstance(card.get("fields"), dict):
            fields = card["fields"]
            question = fields.get("question") or fields.get("content")
        if isinstance(question, str) and question.strip():
            rendered.append(question.strip())
    return rendered


def _select_relevant_existing_cards(
    cards: list[str], *, current_evidence: str, textbook_evidence: str
) -> list[str]:
    if not cards:
        return []
    current_grams = Counter(_semantic_ngrams(current_evidence, size=4))
    textbook_grams = Counter(_semantic_ngrams(textbook_evidence, size=4))
    scored: list[tuple[int, int, int, float, int, str]] = []
    for index, card in enumerate(cards):
        grams = set(_semantic_ngrams(card, size=4))
        if not grams:
            continue
        current_score = sum(current_grams[gram] for gram in grams)
        textbook_score = sum(textbook_grams[gram] for gram in grams)
        current_density = current_score / len(grams)
        textbook_density = textbook_score / len(grams)
        current_relevant = current_score >= 2 and current_density >= 0.15
        textbook_relevant = textbook_score >= 3 and textbook_density > 0.30
        if not current_relevant and not textbook_relevant:
            continue
        weighted_score = current_score * 4 + textbook_score
        density = weighted_score / len(grams)
        scored.append(
            (
                weighted_score,
                current_score,
                textbook_score,
                density,
                index,
                card,
            )
        )

    scored.sort(
        key=lambda item: (-item[0], -item[1], -item[2], -item[3], -item[4])
    )
    return [item[5] for item in scored[:MAX_RELEVANT_EXISTING_CARDS]]


def _semantic_ngrams(text: str, size: int) -> list[str]:
    without_math = MATH_SPAN_PATTERN.sub(" ", text)
    without_commands = re.sub(r"\\[A-Za-z]+|\\.", " ", without_math)
    return _character_ngrams(without_commands, size=size)


def _is_overview_section(text: str) -> bool:
    heading = "\n".join(text.splitlines()[:8]).casefold()
    return any(
        marker in heading
        for marker in (
            "反过来走一遍",
            "全书导读",
            "全书概览",
            "课程概览",
            "本书概览",
            "前言",
            "目录",
        )
    )


def _fit_sections(sections: list[str], limit: int) -> str:
    retained: list[str] = []
    characters = 0
    for section in sections:
        cleaned = section.strip()
        if not cleaned:
            continue
        separator = 2 if retained else 0
        remaining = limit - characters - separator
        if remaining <= 0:
            break
        if len(cleaned) > remaining:
            cleaned = cleaned[:remaining].rstrip() + "\n\n[内容因长度限制截断]"
        retained.append(cleaned)
        characters += len(cleaned) + separator
    return "\n\n".join(retained)


def _only_not_started(
    progress: str,
    lesson_summaries: list[tuple[str, str]],
    postclass_entries: list[tuple[str, str]],
    chats: list[dict[str, Any]],
) -> bool:
    if lesson_summaries or postclass_entries or chats:
        return False
    lowered = progress.casefold()
    return "not yet started" in lowered or "尚未开始" in progress or not progress.strip()


def _read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise SocratopiaParseError(f"所选目录缺少 {label}：{path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SocratopiaParseError(f"无法读取 {label}：{path}") from exc


def _read_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {"cards": payload}


def _read_optional_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8-sig").strip()
    except (OSError, UnicodeError):
        return ""


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse_sort_time(value: Any, path: Path) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return datetime.min
