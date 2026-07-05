
import importlib.util
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage

AGENT_DIR = Path(__file__).resolve().parents[1]
if str(AGENT_DIR) in sys.path:
    sys.path.remove(str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR))

spec = importlib.util.spec_from_file_location("agent_app_test_app", AGENT_DIR / "app.py")
app = importlib.util.module_from_spec(spec)
assert spec.loader is not None
previous_s3_utils = sys.modules.pop("s3_utils", None)
try:
    spec.loader.exec_module(app)
finally:
    if previous_s3_utils is not None:
        sys.modules["s3_utils"] = previous_s3_utils
    else:
        sys.modules.pop("s3_utils", None)

client = TestClient(app.app)


def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_api_mocks_run_agent(monkeypatch):
    captured = {}

    def fake_run_agent(history, max_iterations=10):
        captured["history"] = history
        captured["image"] = app._current_image_b64.get()
        return {
            "response": "Mocked response",
            "prediction_id": "test-prediction-id",
            "annotated_image": None,
            "annotated_image_url": None,
            "agent_loop_time_s": 0.1,
            "iterations": 1,
            "tools_called": [],
            "context_limit_exceeded": False,
            "tokens_used": {
                "input": 10,
                "output": 5,
                "total": 15,
            },
        }

    monkeypatch.setattr(app, "run_agent", fake_run_agent)

    response = client.post(
        "/chat",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": "hello",
                    "image_base64": "aW1hZ2UtYnl0ZXM=",
                }
            ]
        },
    )

    assert response.status_code == 200

    data = response.json()
    assert data["response"] == "Mocked response"
    assert data["prediction_id"] == "test-prediction-id"
    assert data["iterations"] == 1
    assert data["tools_called"] == []
    assert data["tokens_used"]["total"] == 15
    assert captured["image"] == "aW1hZ2UtYnl0ZXM="
    assert isinstance(captured["history"][0], HumanMessage)
    assert "aW1hZ2UtYnl0ZXM=" not in captured["history"][0].content
    assert app._current_image_b64.get() is None


def test_chat_object_edit_goes_through_run_agent(monkeypatch):
    captured = {}

    def fake_run_agent(history, max_iterations=10):
        captured["history"] = history
        captured["image"] = app._current_image_b64.get()
        captured["text"] = app._current_user_text.get()
        return {
            "response": "I blurred only the selected person.",
            "prediction_id": None,
            "annotated_image": None,
            "annotated_image_url": "/processed/processed-image-id/image",
            "agent_loop_time_s": 0.1,
            "iterations": 2,
            "tools_called": ["edit_detected_object"],
            "context_limit_exceeded": False,
            "tokens_used": {
                "input": 10,
                "output": 5,
                "total": 15,
            },
        }

    class FakeEditTool:
        name = "edit_detected_object"

        def invoke(self, args):
            raise AssertionError("chat should not call edit_detected_object directly")

    monkeypatch.setattr(app, "run_agent", fake_run_agent)
    monkeypatch.setattr(app, "edit_detected_object", FakeEditTool())

    response = client.post(
        "/chat",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": "blur the second person from the right",
                    "image_base64": "aW1hZ2UtYnl0ZXM=",
                }
            ]
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["response"] == "I blurred only the selected person."
    assert data["annotated_image"] is None
    assert data["annotated_image_url"] == "/processed/processed-image-id/image"
    assert data["tools_called"] == ["edit_detected_object"]
    assert captured["image"] == "aW1hZ2UtYnl0ZXM="
    assert captured["text"] == "blur the second person from the right"
    assert isinstance(captured["history"][0], HumanMessage)


def test_processed_image_endpoint_returns_png(monkeypatch):
    captured = {}

    def fake_download_bytes_from_s3(key):
        captured["key"] = key
        return b"png bytes"

    monkeypatch.setattr(app, "download_bytes_from_s3", fake_download_bytes_from_s3)

    response = client.get("/processed/processed-image-id/image")

    assert response.status_code == 200
    assert response.content == b"png bytes"
    assert response.headers["content-type"] == "image/png"
    assert captured["key"] == "processed/processed-image-id/image.png"
