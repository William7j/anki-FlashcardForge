import json
from pathlib import Path

import pytest

from flashforge.socratopia import (
    SocratopiaParseError,
    SocratopiaTextbookClient,
    discover_socratopia_accounts,
    discover_socratopia_courses,
    discover_socratopia_lessons,
    load_socratopia_material,
)


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _account(tmp_path: Path, *, with_lesson: bool = True) -> Path:
    account = tmp_path / "account"
    world = account / "profiles" / "student" / "worlds" / "SQ"
    textbook = world / "textbooks" / "tb1"
    textbook.mkdir(parents=True)
    _write_json(
        account / "profiles" / "profiles.json",
        {
            "activeProfileId": "student",
            "profiles": [{"id": "student", "name": "学习者"}],
        },
    )
    _write_json(
        account / "profiles" / "student" / "worlds" / "active.json",
        {"worldId": "SQ", "textbookId": "tb1"},
    )
    _write_json(
        world / "textbooks" / "textbook_index.json",
        {
            "textbooks": [
                {
                    "id": "tb1",
                    "title": "计算机组成原理",
                    "format": "qbook",
                    "numPages": 100,
                    "currentPage": 12,
                }
            ]
        },
    )
    _write_json(
        textbook / "pages.json",
        {
            "pages": [
                {"pageNum": 10, "title": "Chapter 2: 数据表示"},
                {"pageNum": 11, "title": "2.1 字节序"},
                {"pageNum": 12, "title": "2.2 边界对齐"},
                {"pageNum": 13, "title": "2.3 尚未学习"},
            ]
        },
    )
    if with_lesson:
        (textbook / "progress.md").write_text(
            "# 当前进度\n\n已经学过边界对齐；学习者曾误以为只为方便找地址，经提示后理解为减少内存读取次数。",
            encoding="utf-8",
        )
        _write_json(
            world / "chats" / "chat1.json",
            {
                "id": "chat1",
                "createdAt": "2026-07-23T12:00:00Z",
                "textbookId": "tb1",
                "title": "边界对齐与字节序 (07-23)",
                "studySeconds": 1800,
                "messages": [
                    {"role": "user", "content": "边界对齐是方便找地址。"},
                    {
                        "role": "assistant",
                        "content": "更准确地说，边界对齐让一个整数落在单个字内，减少内存读取次数。",
                    },
                ],
            },
        )
        summary = world / "lesson_summaries" / "chat1.md"
        summary.parent.mkdir(parents=True)
        summary.write_text(
            "学习者对边界对齐的原因表述不精确，经提示后完成纠正。",
            encoding="utf-8",
        )
        reading = world / "conversations" / "chat1" / "current_reading.md"
        reading.parent.mkdir(parents=True)
        reading.write_text(
            """<!-- startPage: 12 endPage: 20 -->

## 边界对齐
边界对齐让数据落在单个存储字内，从而减少内存读取次数。

--- 第 13 页 ---
## 尚未学习的量子纠错
量子纠错使用逻辑量子比特和稳定子码，这是未来章节。
""",
            encoding="utf-8",
        )
        _write_json(
            world / "flashcards" / "tb1.json",
            [
                {
                    "question": (
                        "傅里叶级数为什么需要周期延拓？"
                        r"计算式包含 \frac{a}{b}、\int 和 x^2。"
                    )
                },
                {"question": "边界对齐为什么能提高访问速度？"},
            ],
        )
    else:
        (textbook / "progress.md").write_text(
            "Progress: not yet started\nChapters studied: none",
            encoding="utf-8",
        )
    return account


def test_discovers_active_socratopia_course(tmp_path) -> None:
    courses = discover_socratopia_courses(_account(tmp_path))

    assert len(courses) == 1
    assert courses[0].title == "计算机组成原理"
    assert courses[0].is_active is True
    assert "[当前]" in courses[0].display_name


def test_automatically_discovers_accounts_and_lesson_records(tmp_path) -> None:
    account = _account(tmp_path)

    accounts = discover_socratopia_accounts(tmp_path)
    course = discover_socratopia_courses(accounts[0])[0]
    lessons = discover_socratopia_lessons(course)

    assert accounts == [account]
    assert len(lessons) == 1
    assert lessons[0].title == "边界对齐与字节序 (07-23)"
    assert lessons[0].duration_label == "30 分钟"
    assert lessons[0].message_count == 2
    assert "表述不精确" in lessons[0].record_preview


def test_builds_material_from_progress_effectiveness_textbook_and_existing_cards(
    tmp_path,
) -> None:
    course = discover_socratopia_courses(_account(tmp_path))[0]

    source = load_socratopia_material(course)

    assert "已完成课程进度（权威范围）" in source.material
    assert "表述不精确" in source.material
    assert "减少内存读取次数" in source.material
    assert "边界对齐为什么能提高访问速度" in source.material
    assert "傅里叶级数为什么需要周期延拓" not in source.material
    assert "量子纠错使用逻辑量子比特" not in source.material
    assert source.lesson_evidence_count == 2
    assert source.textbook_section_count == 1
    assert source.existing_card_count == 1


def test_existing_cards_are_relevance_ranked_and_limited_to_24(tmp_path) -> None:
    account = _account(tmp_path)
    world = account / "profiles" / "student" / "worlds" / "SQ"
    cards = [
        {"question": f"边界对齐相关旧卡 {index}：为什么可以减少内存读取次数？"}
        for index in range(32)
    ]
    cards.extend(
        {"question": f"傅里叶级数无关旧卡 {index}"} for index in range(8)
    )
    _write_json(world / "flashcards" / "tb1.json", cards)
    course = discover_socratopia_courses(account)[0]

    source = load_socratopia_material(course)

    assert source.existing_card_count == 24
    assert source.material.count("边界对齐相关旧卡") == 24
    assert "傅里叶级数无关旧卡" not in source.material


def test_rejects_textbook_that_has_not_started(tmp_path) -> None:
    course = discover_socratopia_courses(_account(tmp_path, with_lesson=False))[0]

    with pytest.raises(SocratopiaParseError, match="没有找到实际上课记录"):
        load_socratopia_material(course)


def test_original_qbook_covers_lightly_taught_sections_within_taught_chapter(
    tmp_path,
) -> None:
    course = discover_socratopia_courses(_account(tmp_path))[0]

    class FakeTextbookClient(SocratopiaTextbookClient):
        def __init__(self) -> None:
            self.requested = []

        def read_section(self, course, section: int) -> str:
            self.requested.append(section)
            return {
                10: "第二章介绍数据表示。",
                11: "大端把高位字节放在低地址。这个知识课堂只是一笔带过。",
                12: "边界对齐可以减少内存读取次数。",
            }[section]

    client = FakeTextbookClient()
    source = load_socratopia_material(course, textbook_client=client)

    assert sorted(client.requested) == [10, 11, 12]
    assert source.used_original_textbook is True
    assert source.textbook_range == (10, 12)
    assert "qbook 原始教材已讲范围" in source.material
    assert "大端把高位字节放在低地址" in source.material
    assert "第 13" not in source.material


def test_selected_lesson_scopes_classroom_evidence_and_material(tmp_path) -> None:
    course = discover_socratopia_courses(_account(tmp_path))[0]
    lesson = discover_socratopia_lessons(course)[0]

    source = load_socratopia_material(course, lesson=lesson)

    assert source.lesson == lesson
    assert "## 所选课堂" in source.material
    assert "边界对齐与字节序 (07-23)" in source.material
    assert "## 所选课堂总结" in source.material
    assert "## 所选课堂对话尾部" in source.material
    assert "已完成课程进度（权威范围）" not in source.material


def test_latest_selected_lesson_uses_current_page_when_reading_cache_is_missing(
    tmp_path,
) -> None:
    account = _account(tmp_path)
    reading = (
        account
        / "profiles"
        / "student"
        / "worlds"
        / "SQ"
        / "conversations"
        / "chat1"
        / "current_reading.md"
    )
    reading.unlink()
    course = discover_socratopia_courses(account)[0]
    lesson = discover_socratopia_lessons(course)[0]

    class FakeTextbookClient(SocratopiaTextbookClient):
        def __init__(self) -> None:
            self.requested = []

        def read_section(self, course, section: int) -> str:
            self.requested.append(section)
            return f"第 {section} 节教材正文"

    client = FakeTextbookClient()
    source = load_socratopia_material(course, textbook_client=client, lesson=lesson)

    assert sorted(client.requested) == [10, 11, 12]
    assert source.textbook_range == (10, 12)
    assert source.used_original_textbook is True
