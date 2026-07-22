"""AnkiConnect integration and FlashForge note-type definitions."""

from __future__ import annotations

from dataclasses import dataclass
import html
import re
from typing import Any, Callable, Iterable

import httpx

from flashforge.models import CardType, Flashcard


class AnkiConnectError(RuntimeError):
    """Raised when AnkiConnect is unavailable or rejects a request."""


@dataclass(frozen=True, slots=True)
class NoteDefinition:
    model_name: str
    fields: tuple[str, ...]
    templates: tuple[dict[str, str], ...]
    is_cloze: bool = False


@dataclass(frozen=True, slots=True)
class ImportResult:
    note_ids: tuple[int, ...]
    skipped_count: int

    @property
    def added_count(self) -> int:
        return len(self.note_ids)


BASE_CSS = """
.card { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 21px; text-align: left; color: #1f2937; background: #ffffff; line-height: 1.55; }
.remark { margin-top: 24px; color: #6b7280; font-size: 15px; }
.answer { margin-top: 18px; padding-top: 18px; border-top: 1px solid #d1d5db; }
.option-list { display: grid; gap: 10px; margin-top: 20px; }
.option-button, .answer-button { width: 100%; box-sizing: border-box; padding: 12px 14px; border: 1px solid #9ca3af; border-radius: 6px; background: transparent; color: inherit; font: inherit; text-align: left; cursor: pointer; }
.option-button:hover, .option-button.selected { border-color: #0f766e; background: #ccfbf1; }
.judge-buttons { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 20px; }
.judge-buttons .option-button { text-align: center; }
.answer-button { margin-top: 16px; text-align: center; background: #0f766e; border-color: #0f766e; color: #ffffff; }
pre { margin: 16px 0; padding: 14px; overflow-x: auto; border-radius: 6px; background: #f3f4f6; }
pre, code { font-family: 'Cascadia Code', Consolas, monospace; }
code { font-size: 0.88em; }
.hljs-comment, .hljs-quote { color: #6b7280; }.hljs-keyword, .hljs-selector-tag { color: #7c3aed; }.hljs-string, .hljs-attr { color: #047857; }.hljs-number, .hljs-literal { color: #b45309; }
@media (prefers-color-scheme: dark) { .card { color: #e5e7eb; background: #111827; } .answer { border-color: #4b5563; } .remark { color: #9ca3af; } .option-button { border-color: #6b7280; } .option-button:hover, .option-button.selected { background: #134e4a; border-color: #2dd4bf; } pre { background: #030712; } }
""".strip()

CARD_ENHANCEMENT_SCRIPT = """
<script>
(() => {
  const highlight = () => {
    if (window.hljs) document.querySelectorAll('pre code').forEach((block) => window.hljs.highlightElement(block));
    if (window.MathJax && window.MathJax.typesetPromise) window.MathJax.typesetPromise();
  };
  if (window.hljs) { highlight(); return; }
  const stylesheet = document.createElement('link');
  stylesheet.rel = 'stylesheet';
  stylesheet.href = 'https://cdn.jsdelivr.net/npm/highlight.js@11.11.1/styles/github.min.css';
  document.head.appendChild(stylesheet);
  const script = document.createElement('script');
  script.src = 'https://cdn.jsdelivr.net/npm/highlight.js@11.11.1/lib/common.min.js';
  script.onload = highlight;
  script.onerror = () => { if (window.MathJax && window.MathJax.typesetPromise) window.MathJax.typesetPromise(); };
  document.head.appendChild(script);
})();
</script>
""".strip()

AUTO_FLIP_OPTION_SCRIPT = """
<script>
(() => {
  const container = document.getElementById('flashforge-options');
  if (!container) return;
  const options = container.innerHTML.split(/<br\\s*\\/?\\s*>/i).filter(Boolean);
  container.innerHTML = '';
  options.forEach((option) => {
    const button = document.createElement('button');
    button.className = 'option-button';
    button.innerHTML = option;
    button.addEventListener('click', () => pycmd('ans'));
    container.appendChild(button);
  });
})();
</script>
""".strip()

MULTI_SELECT_OPTION_SCRIPT = """
<script>
(() => {
  const container = document.getElementById('flashforge-options');
  if (!container) return;
  const options = container.innerHTML.split(/<br\\s*\\/?\\s*>/i).filter(Boolean);
  container.innerHTML = '';
  options.forEach((option) => {
    const button = document.createElement('button');
    button.className = 'option-button';
    button.innerHTML = option;
    button.addEventListener('click', () => button.classList.toggle('selected'));
    container.appendChild(button);
  });
})();
</script>
""".strip()


NOTE_DEFINITIONS: dict[CardType, NoteDefinition] = {
    CardType.QA: NoteDefinition(
        "FlashForge::QA",
        ("Question", "Answer", "Remark"),
        (
            {
                "Name": "Card 1",
                "Front": "{{Question}}" + CARD_ENHANCEMENT_SCRIPT,
                "Back": "{{FrontSide}}<div class=answer>{{Answer}}</div>{{#Remark}}<div class=remark>{{Remark}}</div>{{/Remark}}" + CARD_ENHANCEMENT_SCRIPT,
            },
        ),
    ),
    CardType.CLOZE: NoteDefinition(
        "FlashForge::Cloze",
        ("Text", "Remark"),
        (
            {
                "Name": "Cloze",
                "Front": "{{cloze:Text}}" + CARD_ENHANCEMENT_SCRIPT,
                "Back": "{{cloze:Text}}{{#Remark}}<div class=remark>{{Remark}}</div>{{/Remark}}" + CARD_ENHANCEMENT_SCRIPT,
            },
        ),
        is_cloze=True,
    ),
    CardType.JUDGE: NoteDefinition(
        "FlashForge::Judge",
        ("Question", "Answer", "Remark"),
        (
            {
                "Name": "Card 1",
                "Front": "判断：{{Question}}<div class=judge-buttons><button class=option-button onclick=\"pycmd('ans')\">正确</button><button class=option-button onclick=\"pycmd('ans')\">错误</button></div>" + CARD_ENHANCEMENT_SCRIPT,
                "Back": "{{FrontSide}}<div class=answer>{{Answer}}</div>{{#Remark}}<div class=remark>{{Remark}}</div>{{/Remark}}" + CARD_ENHANCEMENT_SCRIPT,
            },
        ),
    ),
    CardType.CHOICE: NoteDefinition(
        "FlashForge::SingleChoice",
        ("Question", "Options", "Answer", "Remark"),
        (
            {
                "Name": "Card 1",
                "Front": "{{Question}}<div class=option-list id=flashforge-options>{{Options}}</div>" + AUTO_FLIP_OPTION_SCRIPT + CARD_ENHANCEMENT_SCRIPT,
                "Back": "{{FrontSide}}<div class=answer>{{Answer}}</div>{{#Remark}}<div class=remark>{{Remark}}</div>{{/Remark}}" + CARD_ENHANCEMENT_SCRIPT,
            },
        ),
    ),
    CardType.MULTICHOICE: NoteDefinition(
        "FlashForge::MultipleChoice",
        ("Question", "Options", "Answer", "Remark"),
        (
            {
                "Name": "Card 1",
                "Front": "多选：{{Question}}<div class=option-list id=flashforge-options>{{Options}}</div>" + MULTI_SELECT_OPTION_SCRIPT + "<button class=answer-button onclick=\"pycmd('ans')\">显示答案</button>" + CARD_ENHANCEMENT_SCRIPT,
                "Back": "{{FrontSide}}<div class=answer>{{Answer}}</div>{{#Remark}}<div class=remark>{{Remark}}</div>{{/Remark}}" + CARD_ENHANCEMENT_SCRIPT,
            },
        ),
    ),
}


class AnkiConnectClient:
    def __init__(
        self,
        endpoint: str = "http://127.0.0.1:8765",
        timeout_seconds: float = 10.0,
        request: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self._request = request

    def invoke(self, action: str, **params: Any) -> Any:
        payload = {"action": action, "version": 6, "params": params}
        try:
            response = self._request(payload) if self._request else self._post(payload)
        except httpx.HTTPError as exc:
            raise AnkiConnectError("无法连接 AnkiConnect。请确认 Anki 已打开且插件正在运行。") from exc
        if not isinstance(response, dict):
            raise AnkiConnectError("AnkiConnect 返回格式无效。")
        if response.get("error"):
            raise AnkiConnectError(str(response["error"]))
        return response.get("result")

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = httpx.post(self.endpoint, json=payload, timeout=self.timeout_seconds)
        response.raise_for_status()
        return response.json()

    def deck_names(self) -> list[str]:
        result = self.invoke("deckNames")
        if not isinstance(result, list) or not all(isinstance(name, str) for name in result):
            raise AnkiConnectError("Anki 未返回有效的牌组列表。")
        return sorted(result, key=str.casefold)

    def ensure_note_types(self) -> None:
        existing = set(self.invoke("modelNames") or [])
        for definition in NOTE_DEFINITIONS.values():
            if definition.model_name in existing:
                continue
            self.invoke(
                "createModel",
                modelName=definition.model_name,
                inOrderFields=list(definition.fields),
                css=BASE_CSS,
                isCloze=definition.is_cloze,
                cardTemplates=list(definition.templates),
            )

    def upgrade_note_types(self) -> int:
        """Update FlashForge-owned models without touching unrelated Anki models."""
        existing = set(self.invoke("modelNames") or [])
        updated_count = 0
        for definition in NOTE_DEFINITIONS.values():
            if definition.model_name not in existing:
                continue
            templates = {
                template["Name"]: {"Front": template["Front"], "Back": template["Back"]}
                for template in definition.templates
            }
            self.invoke(
                "updateModelStyling",
                model={"name": definition.model_name, "css": BASE_CSS},
            )
            self.invoke(
                "updateModelTemplates",
                model={"name": definition.model_name, "templates": templates},
            )
            updated_count += 1
        return updated_count

    def ensure_and_upgrade_note_types(self) -> int:
        self.ensure_note_types()
        return self.upgrade_note_types()

    def import_cards(
        self,
        cards: Iterable[Flashcard],
        deck_name: str,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> ImportResult:
        target_deck = deck_name.strip()
        if not target_deck:
            raise AnkiConnectError("牌组名称不能为空。")
        card_list = list(cards)
        self.ensure_note_types()
        self.invoke("createDeck", deck=target_deck)
        notes = [self.note_for_card(card, target_deck) for card in card_list]
        can_add = self.invoke("canAddNotes", notes=notes)
        if not isinstance(can_add, list) or len(can_add) != len(card_list):
            raise AnkiConnectError("Anki 未返回卡片可导入状态。")
        note_ids: list[int] = []
        skipped_count = 0
        total = len(card_list)
        for index, (card, can_add_card) in enumerate(zip(card_list, can_add, strict=True), start=1):
            if not can_add_card:
                skipped_count += 1
            else:
                note_ids.append(self.add_card(card, target_deck))
            if on_progress:
                on_progress(index, total)
        return ImportResult(tuple(note_ids), skipped_count)

    def add_card(self, card: Flashcard, deck_name: str) -> int:
        result = self.invoke("addNote", note=self.note_for_card(card, deck_name))
        if not isinstance(result, int):
            raise AnkiConnectError("Anki 未返回新笔记的编号。")
        return result

    def note_for_card(self, card: Flashcard, deck_name: str) -> dict[str, Any]:
        definition = NOTE_DEFINITIONS[card.card_type]
        return {
            "deckName": deck_name,
            "modelName": definition.model_name,
            "fields": anki_fields_for(card),
            "tags": list(card.tags),
            "options": {"allowDuplicate": False},
        }


def anki_fields_for(card: Flashcard) -> dict[str, str]:
    fields = card.fields
    if card.card_type is CardType.CLOZE:
        return {"Text": _anki_html(fields["content"]), "Remark": _anki_html(fields.get("remark", ""))}
    if card.card_type in {CardType.CHOICE, CardType.MULTICHOICE}:
        return {
            "Question": _anki_html(fields["question"]),
            "Options": _anki_html(fields["options"]),
            "Answer": _anki_html(fields["answer"]),
            "Remark": _anki_html(fields.get("remark", "")),
        }
    return {
        "Question": _anki_html(fields["question"]),
        "Answer": _anki_html(fields["answer"]),
        "Remark": _anki_html(fields.get("remark", "")),
    }


def _anki_html(value: str) -> str:
    chunks: list[str] = []
    cursor = 0
    for match in re.finditer(r"```([a-zA-Z0-9_+-]*)\n(.*?)```", value, flags=re.DOTALL):
        chunks.append(html.escape(value[cursor : match.start()]).replace("\n", "<br>"))
        language = match.group(1).lower()
        language_class = f" class=language-{language}" if language else ""
        chunks.append(f"<pre><code{language_class}>{html.escape(match.group(2))}</code></pre>")
        cursor = match.end()
    chunks.append(html.escape(value[cursor:]).replace("\n", "<br>"))
    return "".join(chunks)
