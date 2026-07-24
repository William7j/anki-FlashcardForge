"""AnkiConnect integration and FlashForge note-type definitions."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import html
import re
from typing import Any, Callable, Iterable, Iterator

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
    failed_count: int = 0

    @property
    def added_count(self) -> int:
        return len(self.note_ids)


IMPORT_BATCH_SIZE = 100


BASE_CSS = """
.card {
  margin: 0;
  padding: 32px 20px;
  color: #20262d;
  background: #edf1f4;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Microsoft YaHei', sans-serif;
  font-size: 20px;
  line-height: 1.62;
  text-align: left;
}
.ff-shell {
  --accent: #087f8c;
  max-width: 760px;
  box-sizing: border-box;
  margin: 0 auto;
  padding: 26px 30px 30px;
  border: 1px solid #d3d9df;
  border-left: 6px solid var(--accent);
  border-radius: 4px;
  background: #fcfcfd;
  box-shadow: 0 12px 28px rgba(32, 38, 45, .08);
}
.ff-qa { --accent: #087f8c; }
.ff-cloze { --accent: #3157a4; }
.ff-judge { --accent: #b45f06; }
.ff-choice { --accent: #b4234d; }
.ff-multichoice { --accent: #5d6b2f; }
.ff-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 24px;
  padding-bottom: 13px;
  border-bottom: 1px solid #e1e5e9;
}
.ff-kind, .ff-series, .ff-answer-label, .ff-remark-label {
  letter-spacing: 0;
  text-transform: uppercase;
}
.ff-kind { color: var(--accent); font-size: 12px; font-weight: 800; }
.ff-series { color: #7a838d; font-size: 10px; font-weight: 700; }
.ff-prompt, .ff-content { font-size: 1.06em; font-weight: 650; }
.ff-answer {
  margin-top: 26px;
  padding: 20px 22px;
  border: 1px solid #d9dee3;
  border-left: 3px solid var(--accent);
  background: #f6f8f9;
}
.ff-answer-label, .ff-remark-label {
  display: block;
  margin-bottom: 9px;
  color: var(--accent);
  font-size: 11px;
  font-weight: 800;
}
.ff-remark {
  margin-top: 18px;
  padding: 14px 17px;
  border: 1px dashed #c8cfd6;
  background: #ffffff;
  color: #59636e;
  font-size: 15px;
}
.option-list { display: grid; gap: 10px; margin-top: 22px; }
.option-button, .answer-button {
  width: 100%;
  box-sizing: border-box;
  min-height: 48px;
  padding: 11px 14px;
  border: 1px solid #bbc3cb;
  border-radius: 4px;
  background: #ffffff;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.option-button:hover, .option-button.selected {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 9%, #ffffff);
}
.judge-buttons { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 22px; }
.judge-buttons .option-button { text-align: center; font-weight: 700; }
.answer-button {
  margin-top: 12px;
  border-color: #20262d;
  background: #20262d;
  color: #ffffff;
  font-weight: 700;
  text-align: center;
}
.ff-option-review { margin-top: 18px; color: #59636e; font-size: .92em; }
pre { margin: 16px 0; padding: 14px; overflow-x: auto; border: 1px solid #d9dee3; border-radius: 4px; background: #f0f3f5; }
pre, code { font-family: 'Cascadia Code', Consolas, monospace; }
code { font-size: .88em; }
img { max-width: 100%; height: auto; }
.hljs-comment, .hljs-quote { color: #6b7280; }
.hljs-keyword, .hljs-selector-tag { color: #7c3aed; }
.hljs-string, .hljs-attr { color: #047857; }
.hljs-number, .hljs-literal { color: #b45309; }
@media (max-width: 520px) {
  .card { padding: 12px; font-size: 18px; }
  .ff-shell { padding: 20px 20px 24px; }
  .ff-head { align-items: flex-start; flex-direction: column; gap: 3px; }
  .judge-buttons { grid-template-columns: 1fr; }
}
@media (prefers-color-scheme: dark) {
  .card { color: #e8ebee; background: #171a1e; }
  .ff-shell { border-color: #424950; background: #22272d; box-shadow: none; }
  .ff-head { border-color: #414850; }
  .ff-series { color: #9ba3ac; }
  .ff-answer { border-color: #48515a; background: #292f36; }
  .ff-remark { border-color: #555e68; background: #1c2025; color: #b4bbc2; }
  .option-button { border-color: #59636d; background: #22272d; }
  .option-button:hover, .option-button.selected { background: #303840; }
  .answer-button { border-color: #e8ebee; background: #e8ebee; color: #20262d; }
  .ff-option-review { color: #b4bbc2; }
  pre { border-color: #424950; background: #14171a; }
}
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


def _card_shell(kind: str, label: str, content: str) -> str:
    return (
        f'<article class="ff-shell ff-{kind}">'
        '<header class="ff-head">'
        f'<span class="ff-kind">{label}</span>'
        '<span class="ff-series">FLASHFORGE / REVIEW</span>'
        '</header>'
        f'{content}'
        '</article>'
        + CARD_ENHANCEMENT_SCRIPT
    )


def _remark_block() -> str:
    return (
        '{{#Remark}}<aside class="ff-remark">'
        '<span class="ff-remark-label">记忆提示</span>{{Remark}}'
        '</aside>{{/Remark}}'
    )


def _answer_block(answer: str) -> str:
    return (
        '<section class="ff-answer">'
        '<span class="ff-answer-label">答案</span>'
        f'{answer}'
        '</section>'
    )


NOTE_DEFINITIONS: dict[CardType, NoteDefinition] = {
    CardType.QA: NoteDefinition(
        "FlashForge::QA",
        ("Question", "Answer", "Remark"),
        (
            {
                "Name": "Card 1",
                "Front": _card_shell("qa", "问答", '<div class="ff-prompt">{{Question}}</div>'),
                "Back": _card_shell(
                    "qa",
                    "问答 / 答案",
                    '<div class="ff-prompt">{{Question}}</div>'
                    + _answer_block("{{Answer}}")
                    + _remark_block(),
                ),
            },
        ),
    ),
    CardType.CLOZE: NoteDefinition(
        "FlashForge::Cloze",
        ("Text", "Remark"),
        (
            {
                "Name": "Cloze",
                "Front": _card_shell(
                    "cloze", "填空", '<div class="ff-content">{{cloze:Text}}</div>'
                ),
                "Back": _card_shell(
                    "cloze",
                    "填空 / 答案",
                    '<div class="ff-content">{{cloze:Text}}</div>' + _remark_block(),
                ),
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
                "Front": _card_shell(
                    "judge",
                    "判断",
                    '<div class="ff-prompt">{{Question}}</div>'
                    '<div class="judge-buttons">'
                    '<button type="button" class="option-button" onclick="pycmd(\'ans\')">正确</button>'
                    '<button type="button" class="option-button" onclick="pycmd(\'ans\')">错误</button>'
                    '</div>',
                ),
                "Back": _card_shell(
                    "judge",
                    "判断 / 结论",
                    '<div class="ff-prompt">{{Question}}</div>'
                    + _answer_block("{{Answer}}")
                    + _remark_block(),
                ),
            },
        ),
    ),
    CardType.CHOICE: NoteDefinition(
        "FlashForge::SingleChoice",
        ("Question", "Options", "Answer", "Remark"),
        (
            {
                "Name": "Card 1",
                "Front": _card_shell(
                    "choice",
                    "单项选择",
                    '<div class="ff-prompt">{{Question}}</div>'
                    '<div class="option-list" id="flashforge-options">{{Options}}</div>'
                    + AUTO_FLIP_OPTION_SCRIPT,
                ),
                "Back": _card_shell(
                    "choice",
                    "单项选择 / 答案",
                    '<div class="ff-prompt">{{Question}}</div>'
                    '<div class="ff-option-review">{{Options}}</div>'
                    + _answer_block("{{Answer}}")
                    + _remark_block(),
                ),
            },
        ),
    ),
    CardType.MULTICHOICE: NoteDefinition(
        "FlashForge::MultipleChoice",
        ("Question", "Options", "Answer", "Remark"),
        (
            {
                "Name": "Card 1",
                "Front": _card_shell(
                    "multichoice",
                    "多项选择",
                    '<div class="ff-prompt">{{Question}}</div>'
                    '<div class="option-list" id="flashforge-options">{{Options}}</div>'
                    + MULTI_SELECT_OPTION_SCRIPT
                    + '<button type="button" class="answer-button" '
                    'onclick="pycmd(\'ans\')">核对答案</button>',
                ),
                "Back": _card_shell(
                    "multichoice",
                    "多项选择 / 答案",
                    '<div class="ff-prompt">{{Question}}</div>'
                    '<div class="ff-option-review">{{Options}}</div>'
                    + _answer_block("{{Answer}}")
                    + _remark_block(),
                ),
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
        self._http_client: httpx.Client | None = None

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
        if self._http_client is not None:
            response = self._http_client.post(self.endpoint, json=payload)
        else:
            response = httpx.post(self.endpoint, json=payload, timeout=self.timeout_seconds)
        response.raise_for_status()
        return response.json()

    @contextmanager
    def _import_request_scope(self) -> Iterator[None]:
        if self._request is not None:
            yield
            return
        with httpx.Client(timeout=self.timeout_seconds) as client:
            self._http_client = client
            try:
                yield
            finally:
                self._http_client = None

    def deck_names(self) -> list[str]:
        result = self.invoke("deckNames")
        if not isinstance(result, list) or not all(isinstance(name, str) for name in result):
            raise AnkiConnectError("Anki 未返回有效的牌组列表。")
        return sorted(result, key=str.casefold)

    def ensure_note_types(self, card_types: Iterable[CardType] | None = None) -> None:
        existing = set(self.invoke("modelNames") or [])
        requested_types = set(card_types) if card_types is not None else None
        definitions = (
            definition
            for card_type, definition in NOTE_DEFINITIONS.items()
            if requested_types is None or card_type in requested_types
        )
        for definition in definitions:
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

    def upgrade_note_types(self, card_types: Iterable[CardType] | None = None) -> int:
        """Update FlashForge-owned models without touching unrelated Anki models."""
        existing = set(self.invoke("modelNames") or [])
        requested_types = set(card_types) if card_types is not None else None
        updated_count = 0
        definitions = (
            definition
            for card_type, definition in NOTE_DEFINITIONS.items()
            if requested_types is None or card_type in requested_types
        )
        for definition in definitions:
            if definition.model_name not in existing:
                continue
            self._update_note_type(definition)
            updated_count += 1
        return updated_count

    def sync_note_types(self, card_types: Iterable[CardType] | None = None) -> int:
        """Create missing models and refresh existing models in one Anki round trip."""
        existing = set(self.invoke("modelNames") or [])
        requested_types = set(card_types) if card_types is not None else None
        updated_count = 0
        for card_type, definition in NOTE_DEFINITIONS.items():
            if requested_types is not None and card_type not in requested_types:
                continue
            if definition.model_name not in existing:
                self.invoke(
                    "createModel",
                    modelName=definition.model_name,
                    inOrderFields=list(definition.fields),
                    css=BASE_CSS,
                    isCloze=definition.is_cloze,
                    cardTemplates=list(definition.templates),
                )
                continue
            self._update_note_type(definition)
            updated_count += 1
        return updated_count

    def _update_note_type(self, definition: NoteDefinition) -> None:
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
        if not card_list:
            return ImportResult((), 0)

        note_ids: list[int] = []
        skipped_count = 0
        failed_count = 0
        total = len(card_list)
        notes = [self.note_for_card(card, target_deck) for card in card_list]
        with self._import_request_scope():
            self.sync_note_types(card.card_type for card in card_list)
            self.invoke("createDeck", deck=target_deck)
            for start in range(0, total, IMPORT_BATCH_SIZE):
                chunk = notes[start : start + IMPORT_BATCH_SIZE]
                can_add = self.invoke("canAddNotes", notes=chunk)
                if (
                    not isinstance(can_add, list)
                    or len(can_add) != len(chunk)
                    or not all(isinstance(value, bool) for value in can_add)
                ):
                    raise AnkiConnectError("Anki 未返回卡片可导入状态。")
                addable_notes = [note for note, allowed in zip(chunk, can_add, strict=True) if allowed]
                skipped_count += len(chunk) - len(addable_notes)
                if addable_notes:
                    added = self.invoke("addNotes", notes=addable_notes)
                    if not isinstance(added, list) or len(added) != len(addable_notes):
                        raise AnkiConnectError("Anki 未返回有效的批量导入结果。")
                    for note_id in added:
                        if isinstance(note_id, int):
                            note_ids.append(note_id)
                        else:
                            failed_count += 1
                if on_progress:
                    on_progress(min(start + len(chunk), total), total)
        return ImportResult(tuple(note_ids), skipped_count, failed_count)

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
