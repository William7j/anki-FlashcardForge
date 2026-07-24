import pytest

from flashforge.config import AppSettings
from flashforge.pipeline import DOCUMENT_CHUNK_CHARACTERS, CardGenerationError, parse_cards
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


def test_parses_json_object_inside_markdown_fence() -> None:
    cards = parse_cards(
        '```json\n{"cards":[{"type":"qa","fields":{"question":"Q","answer":"A"}}]}\n```'
    )

    assert cards[0].fields["answer"] == "A"


def test_repairs_unescaped_latex_backslashes_in_model_json() -> None:
    cards = parse_cards(
        r'{"cards":[{"type":"cloze","fields":{"content":"积分为{{c1::\(\frac{x^{2}}{2}+C\)}}"}}]}'
    )

    assert cards[0].fields["content"] == r"积分为{{c1::\(\frac{x^{2} }{2}+C\)}}"


def test_keeps_valid_json_newlines_while_repairing_latex() -> None:
    cards = parse_cards(
        r'{"cards":[{"type":"choice","fields":{"question":"计算 \int x dx",'
        r'"options":"A\nB\nC\nD","answer":"A"}}]}'
    )

    assert cards[0].fields["question"] == r"计算 \int x dx"
    assert cards[0].fields["options"].splitlines() == ["A", "B", "C", "D"]


def test_reports_truncated_json_as_incomplete() -> None:
    with pytest.raises(CardGenerationError, match="不完整"):
        parse_cards('{"cards":[{"type":"qa","fields":{"question":"Q","answer":"A"}}')


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


class SequenceLlmClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = iter(responses)
        self.prompts = []

    def generate_text(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return next(self.responses)


def test_generation_retries_once_after_invalid_json() -> None:
    llm = SequenceLlmClient(
        [
            '{"cards":[{"type":"qa","fields":{"question":"Q","answer":"A"}}',
            '{"cards":[{"type":"qa","fields":{"question":"Q","answer":"A"}}]}',
        ]
    )
    pipeline = CardPipeline(AppSettings(api_key="test"), llm_client=llm)

    cards = pipeline.generate_from_text("学习材料")

    assert cards[0].fields["answer"] == "A"
    assert len(llm.prompts) == 2
    assert "JSON 格式重试" in llm.prompts[1]


def test_generation_reports_the_last_retry_error() -> None:
    llm = SequenceLlmClient(
        [
            '{"cards":[{"type":"qa"',
            '{"cards":[{"type":"qa","fields":',
        ]
    )
    pipeline = CardPipeline(AppSettings(api_key="test"), llm_client=llm)

    with pytest.raises(CardGenerationError, match="最后一次错误.*不完整或无法解析"):
        pipeline.generate_from_text("学习材料")


def test_document_generation_splits_long_material_and_deduplicates_cards() -> None:
    response = '{"cards":[{"type":"qa","fields":{"question":"Q","answer":"A"}}]}'
    llm = FakeLlmClient(response)
    pipeline = CardPipeline(AppSettings(api_key="test"), llm_client=llm)
    first_block = "甲" * (DOCUMENT_CHUNK_CHARACTERS // 2 + 500)
    second_block = "乙" * (DOCUMENT_CHUNK_CHARACTERS // 2 + 500)

    cards = pipeline.generate_from_text(f"{first_block}\n\n{second_block}", document_mode=True)

    assert len(llm.prompts) == 2
    assert first_block in llm.prompts[0]
    assert second_block in llm.prompts[1]
    assert len(cards) == 1


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


def test_socratopia_generation_keeps_evidence_and_textbook_in_one_prompt() -> None:
    llm = FakeLlmClient(
        '{"cards":[{"type":"qa","fields":{"question":"Q","answer":"A"}}]}'
    )
    pipeline = CardPipeline(AppSettings(api_key="test"), llm_client=llm)
    material = "课堂证据\n\n" + "教材原文" * DOCUMENT_CHUNK_CHARACTERS

    cards = pipeline.generate_from_text(
        material,
        document_mode=True,
        socratopia_mode=True,
    )

    assert cards[0].fields["answer"] == "A"
    assert len(llm.prompts) == 1
    assert "Socratopia 自适应制卡规则" in llm.prompts[0]
    assert material in llm.prompts[0]
