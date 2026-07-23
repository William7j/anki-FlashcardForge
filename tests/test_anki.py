from flashforge.anki import IMPORT_BATCH_SIZE, AnkiConnectClient, NOTE_DEFINITIONS, anki_fields_for
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


def test_import_registers_needed_models_creates_deck_and_adds_notes() -> None:
    calls = []
    progress = []

    def request(payload):
        calls.append(payload)
        if payload["action"] == "modelNames":
            return {"result": []}
        if payload["action"] == "canAddNotes":
            return {"result": [True]}
        if payload["action"] == "addNotes":
            return {"result": [123]}
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
    assert result.failed_count == 0
    assert calls[0]["action"] == "modelNames"
    create_calls = [call for call in calls if call["action"] == "createModel"]
    assert [call["params"]["modelName"] for call in create_calls] == ["FlashForge::QA"]
    add_call = next(call for call in calls if call["action"] == "addNotes")
    assert add_call["params"]["notes"][0]["modelName"] == "FlashForge::QA"
    assert not any(call["action"] == "addNote" for call in calls)
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
    assert result.failed_count == 0
    assert progress == [(1, 1)]
    assert not any(call["action"] == "addNotes" for call in calls)


def test_import_batches_notes_tracks_duplicates_and_partial_failures() -> None:
    calls = []
    progress = []
    next_note_id = 1000
    total_cards = IMPORT_BATCH_SIZE * 2 + 5
    duplicates = {"Q 4", f"Q {IMPORT_BATCH_SIZE + 4}", f"Q {IMPORT_BATCH_SIZE * 2 + 4}"}

    def request(payload):
        nonlocal next_note_id
        calls.append(payload)
        if payload["action"] == "modelNames":
            return {"result": ["FlashForge::QA"]}
        if payload["action"] == "canAddNotes":
            return {
                "result": [
                    note["fields"]["Question"] not in duplicates
                    for note in payload["params"]["notes"]
                ]
            }
        if payload["action"] == "addNotes":
            note_ids = []
            for note in payload["params"]["notes"]:
                if note["fields"]["Question"] == "Q 6":
                    note_ids.append(None)
                else:
                    note_ids.append(next_note_id)
                    next_note_id += 1
            return {"result": note_ids}
        return {"result": None}

    cards = [
        Flashcard.from_payload({"type": "qa", "fields": {"question": f"Q {index}", "answer": "A"}})
        for index in range(total_cards)
    ]
    result = AnkiConnectClient(request=request).import_cards(
        cards, "FlashForge", lambda completed, total: progress.append((completed, total))
    )

    can_add_calls = [call for call in calls if call["action"] == "canAddNotes"]
    add_calls = [call for call in calls if call["action"] == "addNotes"]
    assert [len(call["params"]["notes"]) for call in can_add_calls] == [IMPORT_BATCH_SIZE, IMPORT_BATCH_SIZE, 5]
    assert [len(call["params"]["notes"]) for call in add_calls] == [IMPORT_BATCH_SIZE - 1, IMPORT_BATCH_SIZE - 1, 4]
    assert len(can_add_calls) == len(add_calls) == 3
    assert result.added_count == total_cards - len(duplicates) - 1
    assert result.skipped_count == 3
    assert result.failed_count == 1
    assert progress == [
        (IMPORT_BATCH_SIZE, total_cards),
        (IMPORT_BATCH_SIZE * 2, total_cards),
        (total_cards, total_cards),
    ]
    assert not any(call["action"] == "addNote" for call in calls)


def test_import_reuses_one_http_client(monkeypatch) -> None:
    created_clients = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self) -> None:
            pass

        def json(self):
            action = self.payload["action"]
            if action == "modelNames":
                return {"result": ["FlashForge::QA"]}
            if action == "canAddNotes":
                return {"result": [True, True]}
            if action == "addNotes":
                return {"result": [10, 11]}
            return {"result": None}

    class Client:
        def __init__(self, timeout):
            self.timeout = timeout
            self.calls = []
            created_clients.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def post(self, endpoint, *, json):
            self.calls.append((endpoint, json))
            return Response(json)

    monkeypatch.setattr("flashforge.anki.httpx.Client", Client)
    cards = [
        Flashcard.from_payload({"type": "qa", "fields": {"question": "Q1", "answer": "A1"}}),
        Flashcard.from_payload({"type": "qa", "fields": {"question": "Q2", "answer": "A2"}}),
    ]

    result = AnkiConnectClient(timeout_seconds=17).import_cards(cards, "FlashForge")

    assert result.note_ids == (10, 11)
    assert len(created_clients) == 1
    assert created_clients[0].timeout == 17
    assert [payload["action"] for _, payload in created_clients[0].calls] == [
        "modelNames",
        "createDeck",
        "canAddNotes",
        "addNotes",
    ]


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
