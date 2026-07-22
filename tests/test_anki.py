from flashforge.anki import AnkiConnectClient, NOTE_DEFINITIONS, anki_fields_for
from flashforge.models import Flashcard


def test_choice_fields_convert_line_breaks_for_anki() -> None:
    card = Flashcard.from_payload(
        {
            "type": "choice",
            "fields": {
                "question": "哪项正确？",
                "options": "A. 一\nB. 二\nC. 三\nD. 四",
                "answer": "A. 一",
            },
        }
    )

    assert anki_fields_for(card)["Options"] == "A. 一<br>B. 二<br>C. 三<br>D. 四"


def test_fields_escape_html_and_render_fenced_code() -> None:
    card = Flashcard.from_payload(
        {
            "type": "qa",
            "fields": {"question": "<script>", "answer": "```python\nprint('ok')\n```"},
        }
    )

    fields = anki_fields_for(card)

    assert fields["Question"] == "&lt;script&gt;"
    assert "<pre><code class=language-python>" in fields["Answer"]
    assert "print(&#x27;ok&#x27;)" in fields["Answer"]


def test_all_templates_include_enhancement_script() -> None:
    for definition in NOTE_DEFINITIONS.values():
        assert "MathJax" in definition.templates[0]["Front"]


def test_import_registers_models_creates_deck_and_adds_note() -> None:
    calls = []
    progress = []

    def request(payload):
        calls.append(payload)
        if payload["action"] == "modelNames":
            return {"result": []}
        if payload["action"] == "canAddNotes":
            return {"result": [True]}
        if payload["action"] == "addNote":
            return {"result": 123}
        return {"result": None}

    client = AnkiConnectClient(request=request)
    card = Flashcard.from_payload(
        {"type": "qa", "fields": {"question": "Q", "answer": "A"}, "tags": ["test"]}
    )

    result = client.import_cards(
        [card], "FlashForge", lambda completed, total: progress.append((completed, total))
    )
    assert result.note_ids == (123,)
    assert result.skipped_count == 0
    assert calls[0]["action"] == "modelNames"
    assert any(call["action"] == "createModel" for call in calls)
    add_call = next(call for call in calls if call["action"] == "addNote")
    assert add_call["params"]["note"]["modelName"] == "FlashForge::QA"
    assert progress == [(1, 1)]


def test_import_skips_existing_cards_and_keeps_progress() -> None:
    calls = []

    def request(payload):
        calls.append(payload)
        if payload["action"] == "modelNames":
            return {"result": ["FlashForge::QA"]}
        if payload["action"] == "canAddNotes":
            return {"result": [False]}
        return {"result": None}

    client = AnkiConnectClient(request=request)
    card = Flashcard.from_payload({"type": "qa", "fields": {"question": "Q", "answer": "A"}})
    progress = []

    result = client.import_cards([card], "FlashForge", lambda done, total: progress.append((done, total)))

    assert result.note_ids == ()
    assert result.skipped_count == 1
    assert progress == [(1, 1)]
    assert not any(call["action"] == "addNote" for call in calls)


def test_upgrade_updates_only_existing_flashforge_models() -> None:
    calls = []

    def request(payload):
        calls.append(payload)
        if payload["action"] == "modelNames":
            return {"result": ["FlashForge::QA", "Unrelated"]}
        return {"result": None}

    client = AnkiConnectClient(request=request)

    assert client.upgrade_note_types() == 1
    styling = next(call for call in calls if call["action"] == "updateModelStyling")
    templates = next(call for call in calls if call["action"] == "updateModelTemplates")
    assert styling["params"]["model"]["name"] == "FlashForge::QA"
    assert "Card 1" in templates["params"]["model"]["templates"]


def test_deck_names_are_sorted_from_ankiconnect() -> None:
    client = AnkiConnectClient(
        request=lambda payload: {"result": ["Zeta", "Alpha", "学习"]}
    )

    assert client.deck_names() == ["Alpha", "Zeta", "学习"]
