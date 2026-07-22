import pytest

from flashforge.config import AppSettings
from flashforge.pipeline import CardGenerationError, parse_cards
from flashforge.pipeline import CardPipeline


def test_parses_cards_wrapper_from_model_json_mode() -> None:
    cards = parse_cards(
        '{"cards": [{"type": "qa", "fields": {"question": "牛顿第二定律？", "answer": "F=ma"}, "tags": ["物理"]}]}'
    )

    assert len(cards) == 1
    assert cards[0].fields["answer"] == "F=ma"


def test_parses_array_embedded_in_extra_text() -> None:
    cards = parse_cards('结果如下： [{"type": "judge", "fields": {"question": "光速恒定？", "answer": "正确"}}]')

    assert cards[0].card_type.value == "judge"


def test_reports_invalid_card_with_position() -> None:
    with pytest.raises(CardGenerationError, match="第 1 张"):
        parse_cards('[{"type": "qa", "fields": {"question": "缺少答案"}}]')


class FakeLlmClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts = []

    def generate_text(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


class FakeOcrClient:
    def extract(self, image_path):
        return "OCR 结果"


def test_regenerate_card_returns_one_card_with_feedback() -> None:
    existing = parse_cards('[{"type":"qa","fields":{"question":"Q","answer":"旧答案"}}]')[0]
    llm = FakeLlmClient(
        '{"cards":[{"type":"qa","fields":{"question":"Q","answer":"新答案"}}]}'
    )
    pipeline = CardPipeline(AppSettings(api_key="test"), llm_client=llm)

    card = pipeline.regenerate_card(existing, "更精确", material="学习材料")

    assert card.fields["answer"] == "新答案"
    assert "修改反馈：更精确" in llm.prompts[0]


def test_regenerate_card_rejects_type_change() -> None:
    existing = parse_cards('[{"type":"qa","fields":{"question":"Q","answer":"A"}}]')[0]
    llm = FakeLlmClient(
        '{"cards":[{"type":"judge","fields":{"question":"Q","answer":"正确"}}]}'
    )
    pipeline = CardPipeline(AppSettings(api_key="test"), llm_client=llm)

    with pytest.raises(CardGenerationError, match="改变了题型"):
        pipeline.regenerate_card(existing, "", material="学习材料")


def test_image_pipeline_can_fall_back_to_local_ocr(tmp_path) -> None:
    llm = FakeLlmClient(
        '{"cards":[{"type":"qa","fields":{"question":"Q","answer":"A"}}]}'
    )
    settings = AppSettings(api_key="test", image_input_mode="ocr")
    pipeline = CardPipeline(settings, llm_client=llm, ocr_client=FakeOcrClient())

    cards = pipeline.generate_from_image(tmp_path / "source.png")

    assert cards[0].fields["answer"] == "A"
    assert "OCR 结果" in llm.prompts[0]


def test_regenerate_card_uses_ocr_text_path_for_image_source(tmp_path) -> None:
    existing = parse_cards(
        '[{"type":"qa","fields":{"question":"Q","answer":"旧答案"}}]'
    )[0]
    llm = FakeLlmClient(
        '{"cards":[{"type":"qa","fields":{"question":"Q","answer":"新答案"}}]}'
    )
    settings = AppSettings(api_key="test", image_input_mode="ocr")
    pipeline = CardPipeline(settings, llm_client=llm, ocr_client=FakeOcrClient())

    card = pipeline.regenerate_card(
        existing,
        "更准确",
        image_path=tmp_path / "source.png",
    )

    assert card.fields["answer"] == "新答案"
    assert "OCR 结果" in llm.prompts[0]


def test_document_generation_uses_document_extraction_prompt() -> None:
    llm = FakeLlmClient(
        '{"cards":[{"type":"qa","fields":{"question":"Q","answer":"A"}}]}'
    )
    pipeline = CardPipeline(AppSettings(api_key="test"), llm_client=llm)

    cards = pipeline.generate_from_text("清洗后的课堂对话", document_mode=True)

    assert cards[0].fields["answer"] == "A"
    assert "本地资料提炼规则" in llm.prompts[0]
