import pytest

from flashforge.models import CardType, CardValidationError, Flashcard


def test_accepts_native_cloze_card() -> None:
    card = Flashcard.from_payload(
        {"type": "cloze", "fields": {"content": "水的沸点是{{c1::100°C}}。"}, "tags": ["化学"]}
    )

    assert card.card_type is CardType.CLOZE
    assert card.tags == ("化学",)


def test_rejects_cloze_without_anki_syntax() -> None:
    with pytest.raises(CardValidationError, match="原生"):
        Flashcard.from_payload({"type": "cloze", "fields": {"content": "水的沸点是 100°C。"}})


def test_rejects_missing_required_fields() -> None:
    with pytest.raises(CardValidationError, match="answer"):
        Flashcard.from_payload({"type": "qa", "fields": {"question": "什么是熵？"}})


def test_rejects_choice_with_wrong_option_count() -> None:
    with pytest.raises(CardValidationError, match="4 个选项"):
        Flashcard.from_payload(
            {
                "type": "choice",
                "fields": {"question": "Q", "options": "A\nB", "answer": "A"},
            }
        )


def test_rejects_judge_with_ambiguous_answer() -> None:
    with pytest.raises(CardValidationError, match="正确"):
        Flashcard.from_payload(
            {"type": "judge", "fields": {"question": "Q", "answer": "可能正确"}}
        )
