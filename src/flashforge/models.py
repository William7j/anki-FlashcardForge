"""Domain models and validation for cards returned by an LLM."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any


class CardValidationError(ValueError):
    """Raised when an LLM payload cannot become an Anki card."""


class CardType(str, Enum):
    QA = "qa"
    CLOZE = "cloze"
    CHOICE = "choice"
    MULTICHOICE = "multichoice"
    JUDGE = "judge"


REQUIRED_FIELDS: dict[CardType, tuple[str, ...]] = {
    CardType.QA: ("question", "answer"),
    CardType.CLOZE: ("content",),
    CardType.CHOICE: ("question", "options", "answer"),
    CardType.MULTICHOICE: ("question", "options", "answer"),
    CardType.JUDGE: ("question", "answer"),
}

EXPECTED_OPTION_COUNTS = {
    CardType.CHOICE: 4,
    CardType.MULTICHOICE: 5,
}
NATIVE_CLOZE_PATTERN = re.compile(r"\{\{c[1-9]\d*::[^{}]+\}\}")


@dataclass(frozen=True, slots=True)
class Flashcard:
    card_type: CardType
    fields: dict[str, str]
    tags: tuple[str, ...] = ()

    @classmethod
    def from_payload(cls, payload: Any) -> "Flashcard":
        if not isinstance(payload, dict):
            raise CardValidationError("每张卡片必须是对象。")

        try:
            card_type = CardType(str(payload.get("type", "")).lower())
        except ValueError as exc:
            supported = ", ".join(item.value for item in CardType)
            raise CardValidationError(f"未知题型，支持：{supported}。") from exc

        raw_fields = payload.get("fields")
        if not isinstance(raw_fields, dict):
            raise CardValidationError("卡片 fields 必须是对象。")
        fields = {
            str(key): str(value).strip()
            for key, value in raw_fields.items()
            if value is not None
        }

        missing = [key for key in REQUIRED_FIELDS[card_type] if not fields.get(key)]
        if missing:
            raise CardValidationError(f"{card_type.value} 卡片缺少字段：{', '.join(missing)}。")
        if card_type is CardType.CLOZE and not NATIVE_CLOZE_PATTERN.search(fields["content"]):
            raise CardValidationError("填空卡 content 必须使用 Anki 原生 {{c1::答案}} 语法。")
        if card_type in EXPECTED_OPTION_COUNTS:
            option_count = len([line for line in fields["options"].splitlines() if line.strip()])
            expected_count = EXPECTED_OPTION_COUNTS[card_type]
            if option_count != expected_count:
                raise CardValidationError(
                    f"{card_type.value} 卡片必须包含 {expected_count} 个选项，目前有 {option_count} 个。"
                )
        if card_type is CardType.JUDGE and fields["answer"] not in {"正确", "错误", "对", "错"}:
            raise CardValidationError("判断卡 answer 必须为“正确”或“错误”。")

        raw_tags = payload.get("tags", [])
        if raw_tags is None:
            raw_tags = []
        if not isinstance(raw_tags, list) or not all(isinstance(tag, str) for tag in raw_tags):
            raise CardValidationError("tags 必须是字符串数组。")
        tags = tuple(tag.strip() for tag in raw_tags if tag.strip())
        return cls(card_type=card_type, fields=fields, tags=tags)

    @property
    def preview_question(self) -> str:
        return self.fields.get("question") or self.fields.get("content", "")

    @property
    def preview_answer(self) -> str:
        return self.fields.get("answer", "填空卡")
