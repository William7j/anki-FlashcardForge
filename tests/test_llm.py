from types import SimpleNamespace
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import sys
import threading

from PySide6.QtGui import QColor, QImage

from flashforge.config import AppSettings
from flashforge.llm import LlmClient


def test_generate_text_uses_json_mode_and_returns_content() -> None:
    completions = SimpleNamespace()
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"cards": []}'))])

    completions.create = create
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    result = LlmClient(AppSettings(api_key="test-key", model="test-model"), client=client).generate_text("生成卡片")

    assert result == '{"cards": []}'
    assert calls[0]["model"] == "test-model"
    assert calls[0]["response_format"] == {"type": "json_object"}


def test_ollama_uses_prompt_json_contract_without_response_format() -> None:
    completions = SimpleNamespace()
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"cards": []}'))])

    completions.create = create
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    LlmClient(AppSettings(provider="ollama", model="qwen3"), client=client).generate_text("生成卡片")

    assert "response_format" not in calls[0]


def test_large_image_is_scaled_and_reencoded_before_upload(tmp_path) -> None:
    image_path = tmp_path / "large.png"
    image = QImage(2050, 12, QImage.Format.Format_RGB32)
    image.fill(QColor("#ffffff"))
    assert image.save(str(image_path), "PNG")

    data_uri = LlmClient._image_data_uri(image_path)

    assert data_uri.startswith("data:image/jpeg;base64,")


def test_ollama_provider_uses_openai_compatible_local_endpoint() -> None:
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            requests.append(json.loads(self.rfile.read(length)))
            body = json.dumps(
                {"choices": [{"message": {"content": '{"cards": []}'}}]}
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings = AppSettings(
            provider="ollama",
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            model="local-test",
        )
        response = LlmClient(settings).generate_text("生成卡片")
    finally:
        server.shutdown()
        thread.join()

    assert response == '{"cards": []}'
    assert requests[0]["model"] == "local-test"
    assert "response_format" not in requests[0]


def test_client_passes_configured_request_timeout_to_sdk(monkeypatch) -> None:
    captured = {}

    def openai_constructor(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=openai_constructor))
    settings = AppSettings(api_key="test-key", request_timeout_seconds=12.5)

    LlmClient(settings)._client_or_create()

    assert captured["timeout"] == 12.5
