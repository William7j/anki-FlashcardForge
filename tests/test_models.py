import pytest

from flashforge.models import CardType, CardValidationError, Flashcard


def test_accepts_native_cloze_card() -> None:
    card = Flashcard.from_payload(
        {"type": "cloze", "fields": {"content": "水的沸点是{{c1::100°C}}。"}, "tags": ["化学"]}
    )

    assert card.card_type is CardType.CLOZE
    assert card.tags == ("化学",)


def test_accepts_latex_braces_inside_native_cloze() -> None:
    card = Flashcard.from_payload(
        {
            "type": "cloze",
            "fields": {"content": r"积分结果是{{c1::\(\frac{x^{2}}{2}+C\)}}。"},
        }
    )

    assert card.fields["content"] == r"积分结果是{{c1::\(\frac{x^{2} }{2}+C\)}}。"


def test_protects_formula_ending_brace_from_cloze_delimiter() -> None:
    card = Flashcard.from_payload(
        {
            "type": "cloze",
            "fields": {"content": r"比值为{{c1::\frac{a}{b}}}。"},
        }
    )

    assert card.fields["content"] == r"比值为{{c1::\frac{a}{b} }}。"


def test_protects_latex_braces_in_multiple_clozes() -> None:
    card = Flashcard.from_payload(
        {
            "type": "cloze",
            "fields": {
                "content": (
                    r"原函数为{{c1::x^a}}，积分为"
                    r"{{c2::\(\frac{x^{a+1}}{a+1}+C\)}}。"
                )
            },
        }
    )

    assert card.fields["content"] == (
        r"原函数为{{c1::x^a}}，积分为"
        r"{{c2::\(\frac{x^{a+1} }{a+1}+C\)}}。"
    )


def test_normalizes_full_width_cloze_delimiters() -> None:
    card = Flashcard.from_payload(
        {"type": "cloze", "fields": {"content": "水的沸点是｛｛ｃ１：：100°C｝｝。"}}
    )

    assert card.fields["content"] == "水的沸点是{{c1::100°C}}。"


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
