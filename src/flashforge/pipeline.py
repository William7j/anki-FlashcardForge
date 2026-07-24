"""The text/image-to-card orchestration layer."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Callable

from flashforge.anki import AnkiConnectClient, ImportResult
from flashforge.config import AppSettings
from flashforge.llm import LlmClient, LlmOutputTruncatedError
from flashforge.models import CardValidationError, Flashcard
from flashforge.ocr import LocalOcr
from flashforge.prompts import PromptManager


class CardGenerationError(ValueError):
    """Raised when an LLM response is not a valid card collection."""


DOCUMENT_CHUNK_CHARACTERS = 12_000
JSON_RETRY_INSTRUCTIONS = """

## JSON 格式重试
上一轮输出不是完整、合法的 JSON，可能是生成内容过长。请重新生成并遵守以下要求：
- 只输出一个包含 cards 数组的合法 JSON 对象，不要使用 Markdown 代码块或附加说明。
- 本次最多生成 16 张卡片，只保留最重要的知识点。
- 确保所有字符串、对象和数组均完整闭合。
- LaTeX 命令的反斜杠必须按 JSON 规则写成双反斜杠，例如 `\\\\frac`、`\\\\int` 和 `\\\\(`。
""".rstrip()

JSON_SIMPLE_ESCAPES = frozenset('"\\/bfnrt')
LATEX_COMMANDS = frozenset(
    {
        "alpha", "approx", "bar", "begin", "beta", "binom", "boxed",
        "cdot", "cdots", "cos", "delta", "displaystyle", "div", "dots",
        "end", "exp", "frac", "gamma", "ge", "geq", "hat", "infty",
        "int", "lambda", "ldots", "le", "left", "leq", "lim", "limits",
        "ln", "log", "mathbb", "mathbf", "mathcal", "mathit", "mathrm",
        "mathsf", "mathtt", "matrix", "mp", "mu", "nabla", "ne", "neq",
        "omega", "operatorname", "overbrace", "overline", "overset", "partial",
        "phi", "pi", "pm", "prod", "qquad", "quad", "right", "rho",
        "sigma", "sin", "sqrt", "substack", "sum", "tan", "text", "theta",
        "times", "underbrace", "underline", "underset", "vec",
    }
)


def parse_cards(raw_response: str) -> list[Flashcard]:
    """Extract a card array from a plain JSON response or a `cards` wrapper."""
    payload = _extract_json_payload(raw_response)

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


def _extract_json_payload(raw_response: str) -> Any:
    source = raw_response.strip().lstrip("\ufeff")
    if not source:
        raise CardGenerationError("模型返回了空内容。")
    source = _repair_json_latex_escapes(source)
    try:
        return json.loads(source)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for match in re.finditer(r"[\[{]", source):
        try:
            candidate, _ = decoder.raw_decode(source, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and ("cards" in candidate or "data" in candidate):
            return candidate
        if isinstance(candidate, list) and (
            not candidate or all(isinstance(item, dict) for item in candidate)
        ):
            return candidate

    if "[" not in source and "{" not in source:
        raise CardGenerationError("模型没有返回 JSON 卡片数组。")
    raise CardGenerationError("模型返回的卡片 JSON 不完整或无法解析。")


def _repair_json_latex_escapes(source: str) -> str:
    """Escape bare LaTeX backslashes inside JSON strings without changing JSON syntax."""

    repaired: list[str] = []
    in_string = False
    position = 0
    while position < len(source):
        char = source[position]
        if not in_string:
            repaired.append(char)
            if char == '"':
                in_string = True
            position += 1
            continue

        if char == '"':
            repaired.append(char)
            in_string = False
            position += 1
            continue

        if char != "\\" or position + 1 >= len(source):
            repaired.append(char)
            position += 1
            continue

        next_char = source[position + 1]
        if _is_bare_latex_escape(source, position):
            repaired.append("\\\\")
            position += 1
            continue

        repaired.extend((char, next_char))
        position += 2

    return "".join(repaired)


def _is_bare_latex_escape(source: str, position: int) -> bool:
    next_char = source[position + 1]
    if next_char in "()[]{} ,;:!%#&_":
        return True
    if next_char == "u":
        unicode_digits = source[position + 2 : position + 6]
        return len(unicode_digits) != 4 or any(
            digit not in "0123456789abcdefABCDEF" for digit in unicode_digits
        )
    command_match = re.match(r"[A-Za-z]+", source[position + 1 :])
    if command_match and command_match.group(0).lower() in LATEX_COMMANDS:
        return True
    return next_char not in JSON_SIMPLE_ESCAPES


def _split_document_material(material: str) -> list[str]:
    source = material.strip()
    if len(source) <= DOCUMENT_CHUNK_CHARACTERS:
        return [source]

    blocks = [block.strip() for block in re.split(r"\n\s*\n", source) if block.strip()]
    chunks: list[str] = []
    current = ""
    for block in blocks:
        if len(block) > DOCUMENT_CHUNK_CHARACTERS:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_split_large_block(block))
            continue
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= DOCUMENT_CHUNK_CHARACTERS:
            current = candidate
        else:
            chunks.append(current)
            current = block
    if current:
        chunks.append(current)
    return chunks


def _split_large_block(block: str) -> list[str]:
    chunks: list[str] = []
    remaining = block
    while len(remaining) > DOCUMENT_CHUNK_CHARACTERS:
        boundary = remaining.rfind("\n", 0, DOCUMENT_CHUNK_CHARACTERS + 1)
        if boundary < DOCUMENT_CHUNK_CHARACTERS // 2:
            boundary = DOCUMENT_CHUNK_CHARACTERS
        chunks.append(remaining[:boundary].strip())
        remaining = remaining[boundary:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


def _deduplicate_cards(cards: list[Flashcard]) -> list[Flashcard]:
    unique_cards: list[Flashcard] = []
    seen: set[tuple[Any, ...]] = set()
    for card in cards:
        identity = (
            card.card_type.value,
            tuple(sorted(card.fields.items())),
            tuple(sorted(card.tags)),
        )
        if identity in seen:
            continue
        seen.add(identity)
        unique_cards.append(card)
    return unique_cards


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

    def generate_from_text(
        self,
        material: str,
        *,
        document_mode: bool = False,
        socratopia_mode: bool = False,
    ) -> list[Flashcard]:
        chunks = (
            _split_document_material(material)
            if document_mode and not socratopia_mode
            else [material]
        )
        cards: list[Flashcard] = []
        for chunk in chunks:
            prompt = self.prompt_manager.render(
                chunk,
                self.settings.prompt_name,
                document_mode=document_mode,
                socratopia_mode=socratopia_mode,
            )
            cards.extend(self._generate_text_cards(prompt))
        return _deduplicate_cards(cards)

    def _generate_text_cards(self, prompt: str) -> list[Flashcard]:
        try:
            return parse_cards(self.llm_client.generate_text(prompt))
        except (CardGenerationError, LlmOutputTruncatedError):
            try:
                return parse_cards(
                    self.llm_client.generate_text(f"{prompt}{JSON_RETRY_INSTRUCTIONS}")
                )
            except (CardGenerationError, LlmOutputTruncatedError) as second_error:
                raise CardGenerationError(
                    "模型连续两次返回不完整或无效的卡片 JSON。"
                    "请缩短材料或降低生成数量后重试。\n"
                    f"最后一次错误：{second_error}"
                ) from second_error

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
        document_mode: bool = False,
        socratopia_mode: bool = False,
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
            document_mode=document_mode and request_image_path is None,
            socratopia_mode=socratopia_mode and request_image_path is None,
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
