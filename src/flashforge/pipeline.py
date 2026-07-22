"""The text/image-to-card orchestration layer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from flashforge.anki import AnkiConnectClient, ImportResult
from flashforge.config import AppSettings
from flashforge.llm import LlmClient
from flashforge.models import CardValidationError, Flashcard
from flashforge.ocr import LocalOcr
from flashforge.prompts import PromptManager


class CardGenerationError(ValueError):
    """Raised when an LLM response is not a valid card collection."""


def parse_cards(raw_response: str) -> list[Flashcard]:
    """Extract a card array from a plain JSON response or a `cards` wrapper."""
    try:
        payload: Any = json.loads(raw_response)
    except json.JSONDecodeError:
        start, end = raw_response.find("["), raw_response.rfind("]")
        if start < 0 or end < start:
            raise CardGenerationError("模型没有返回 JSON 卡片数组。") from None
        try:
            payload = json.loads(raw_response[start : end + 1])
        except json.JSONDecodeError as exc:
            raise CardGenerationError("模型返回的卡片 JSON 无法解析。") from exc

    if isinstance(payload, dict):
        payload = payload.get("cards", payload.get("data"))
    if not isinstance(payload, list):
        raise CardGenerationError("模型响应必须是卡片数组，或包含 cards 数组。")
    if not payload:
        raise CardGenerationError("模型没有生成任何卡片。")

    cards: list[Flashcard] = []
    errors: list[str] = []
    for index, item in enumerate(payload, start=1):
        try:
            cards.append(Flashcard.from_payload(item))
        except CardValidationError as exc:
            errors.append(f"第 {index} 张：{exc}")
    if errors:
        raise CardGenerationError("\n".join(errors))
    return cards


class CardPipeline:
    def __init__(
        self,
        settings: AppSettings,
        llm_client: LlmClient | None = None,
        prompt_manager: PromptManager | None = None,
        ocr_client: LocalOcr | None = None,
    ) -> None:
        self.settings = settings
        self.llm_client = llm_client or LlmClient(settings)
        self.prompt_manager = prompt_manager or PromptManager()
        self.ocr_client = ocr_client

    def generate_from_text(self, material: str) -> list[Flashcard]:
        prompt = self.prompt_manager.render(material, self.settings.prompt_name)
        return parse_cards(self.llm_client.generate_text(prompt))

    def generate_from_image(self, image_path: Path) -> list[Flashcard]:
        if self.settings.image_input_mode == "ocr":
            ocr = self.ocr_client or LocalOcr()
            return self.generate_from_text(ocr.extract(image_path))
        prompt = self.prompt_manager.render("请以截图内容为准制卡。", self.settings.prompt_name, image_mode=True)
        return parse_cards(self.llm_client.generate_image(prompt, image_path))

    def regenerate_card(
        self,
        card: Flashcard,
        feedback: str,
        *,
        material: str = "",
        image_path: Path | None = None,
    ) -> Flashcard:
        request_image_path = image_path
        if image_path is not None and self.settings.image_input_mode == "ocr":
            ocr = self.ocr_client or LocalOcr()
            material = ocr.extract(image_path)
            request_image_path = None
        if request_image_path is None and not material.strip():
            raise CardGenerationError("没有可用于重新生成的原始材料。")
        source_material = (
            material if request_image_path is None else "请以截图内容为准制卡。"
        )
        prompt = self.prompt_manager.render(
            source_material,
            self.settings.prompt_name,
            image_mode=request_image_path is not None,
        )
        existing = {
            "type": card.card_type.value,
            "fields": card.fields,
            "tags": list(card.tags),
        }
        prompt += (
            "\n\n## 单卡重新生成\n"
            "只输出一个 cards 元素。保持原题型不变，并根据反馈重写该卡片；"
            "仍须严格遵守前述所有格式约束。\n"
            f"当前卡片：{json.dumps(existing, ensure_ascii=False)}\n"
            f"修改反馈：{feedback.strip() or '无额外反馈，请提高准确性和简洁性。'}"
        )
        raw_response = (
            self.llm_client.generate_image(prompt, request_image_path)
            if request_image_path is not None
            else self.llm_client.generate_text(prompt)
        )
        cards = parse_cards(raw_response)
        if len(cards) != 1:
            raise CardGenerationError(f"重新生成必须返回 1 张卡片，实际返回 {len(cards)} 张。")
        if cards[0].card_type is not card.card_type:
            raise CardGenerationError("重新生成改变了题型，请修改反馈后重试。")
        return cards[0]

    def import_to_anki(
        self,
        cards: list[Flashcard],
        on_progress: Callable[[int, int], None] | None = None,
    ) -> ImportResult:
        client = AnkiConnectClient(timeout_seconds=self.settings.request_timeout_seconds)
        return client.import_cards(cards, self.settings.deck_name, on_progress)
