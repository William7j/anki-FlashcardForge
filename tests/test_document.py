from pathlib import Path

import pytest

from flashforge.document import DocumentParseError, load_markdown_document


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_socratopia_markdown_is_parsed_and_stage_directions_are_removed(tmp_path) -> None:
    source = _write(
        tmp_path / "lesson.md",
        r"""---
title: 课堂聊天记录
textbook: 微积分
companion: 老师
learner: 学生
date: 2026-07-05
---

# 课堂聊天记录

**学生** · 09:39

我认为周期和振幅有关。

**老师** · 09:40

*她拿起笔，在纸上画了一条线。*

先纠正：简谐振动的周期与振幅无关。*她把公式圈了起来。*

\[
T = 2\pi\sqrt{\frac{m}{k}}
\]
""",
    )

    document = load_markdown_document(source)

    assert document.title == "课堂聊天记录"
    assert document.metadata["textbook"] == "微积分"
    assert document.message_count == 2
    assert document.messages[1].speaker == "老师"
    assert "她拿起笔" not in document.cleaned_material
    assert "她把公式圈了起来" not in document.cleaned_material
    assert "周期与振幅无关" in document.cleaned_material
    assert r"\frac{m}{k}" in document.cleaned_material
    assert "消息 2 | 老师 | 09:40" in document.cleaned_material


def test_generic_markdown_keeps_regular_content_and_removes_front_matter(tmp_path) -> None:
    source = _write(
        tmp_path / "chapter.md",
        """---
title: 导数
subject: 数学
---

# 第一章

*斜体也是正文。*

导数描述函数的局部变化率。
""",
    )

    document = load_markdown_document(source)

    assert document.message_count == 0
    assert document.title == "导数"
    assert "title:" not in document.cleaned_material
    assert "*斜体也是正文。*" in document.cleaned_material


def test_markdown_rejects_unsupported_or_empty_files(tmp_path) -> None:
    text_file = _write(tmp_path / "notes.txt", "notes")
    empty_file = _write(tmp_path / "empty.md", "   ")

    with pytest.raises(DocumentParseError, match="仅支持 Markdown"):
        load_markdown_document(text_file)
    with pytest.raises(DocumentParseError, match="为空"):
        load_markdown_document(empty_file)
