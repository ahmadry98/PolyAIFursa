
import importlib.util
import base64
import io
import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage
from PIL import Image

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
agent_runner = importlib.import_module("agent_runner")
config = importlib.import_module("config")
image_utils = importlib.import_module("image_utils")
tools = importlib.import_module("tools")


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

    monkeypatch.setattr(app, "run_agent", fake_run_agent)

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


def test_chat_multi_edit_uses_plan_executor_without_llm(monkeypatch):
    image = Image.new("RGB", (80, 40), "white")
    image_buffer = io.BytesIO()
    image.save(image_buffer, format="PNG")
    image_b64 = base64.b64encode(image_buffer.getvalue()).decode()
    stored = {}

    def fake_detect_uploaded_image(_image_b64):
        return {
            "detection_objects": [
                {"label": "person", "box": [5, 5, 25, 30]},
                {"label": "person", "box": [55, 5, 75, 30]},
            ]
        }

    def fake_run_img_proc_mcp(tool_name, arguments):
        crop = Image.open(
            io.BytesIO(base64.b64decode(arguments["image_b64"]))
        ).convert("RGB")
        color = "black" if arguments["amount"] == 0.5 else "gray"
        return image_utils._encode_image(Image.new("RGB", crop.size, color))

    def fake_store_processed_image(image_base64):
        stored["image_base64"] = image_base64
        return "/processed/final/image"

    def fail_if_llm_is_used():
        raise AssertionError("multi-edit requests should not need the LLM path")

    monkeypatch.setattr(tools, "_detect_uploaded_image", fake_detect_uploaded_image)
    monkeypatch.setattr(tools, "_run_img_proc_mcp", fake_run_img_proc_mcp)
    monkeypatch.setattr(
        agent_runner,
        "_store_processed_image",
        fake_store_processed_image,
    )
    monkeypatch.setattr(config, "get_llm_with_tools", fail_if_llm_is_used)

    response = client.post(
        "/chat",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "add 0.5 noise to the right person and 0.9 noise "
                        "to the left person"
                    ),
                    "image_base64": image_b64,
                }
            ]
        },
    )

    assert response.status_code == 200
    data = response.json()
    final_image = Image.open(
        io.BytesIO(base64.b64decode(stored["image_base64"]))
    ).convert("RGB")

    assert data["response"] == "I applied 2 edits to the image."
    assert data["annotated_image_url"] == "/processed/final/image"
    assert data["tools_called"] == ["apply_image_edit_plan"]
    assert final_image.getpixel((65, 10)) == (0, 0, 0)
    assert final_image.getpixel((10, 10)) == (128, 128, 128)


def test_chat_multiline_edit_uses_plan_executor_without_llm(monkeypatch):
    image = Image.new("RGB", (50, 30), "white")
    image_buffer = io.BytesIO()
    image.save(image_buffer, format="PNG")
    image_b64 = base64.b64encode(image_buffer.getvalue()).decode()
    stored = {}

    def fake_run_img_proc_mcp(tool_name, arguments):
        input_image = Image.open(
            io.BytesIO(base64.b64decode(arguments["image_b64"]))
        ).convert("RGB")

        if tool_name == "add_noise":
            return image_utils._encode_image(Image.new("RGB", input_image.size, "black"))

        assert tool_name == "rotate"
        rotated = input_image.rotate(arguments["angle"], expand=True)
        return image_utils._encode_image(rotated)

    def fake_store_processed_image(image_base64):
        stored["image_base64"] = image_base64
        return "/processed/multiline/image"

    def fail_if_llm_is_used():
        raise AssertionError("multiline edit requests should not need the LLM path")

    monkeypatch.setattr(tools, "_run_img_proc_mcp", fake_run_img_proc_mcp)
    monkeypatch.setattr(
        agent_runner,
        "_store_processed_image",
        fake_store_processed_image,
    )
    monkeypatch.setattr(config, "get_llm_with_tools", fail_if_llm_is_used)

    response = client.post(
        "/chat",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "- add noise to the whole image\n"
                        "- rotate the whole image"
                    ),
                    "image_base64": image_b64,
                }
            ]
        },
    )

    assert response.status_code == 200
    data = response.json()
    final_image = Image.open(
        io.BytesIO(base64.b64decode(stored["image_base64"]))
    ).convert("RGB")

    assert data["response"] == "I applied 2 edits to the image."
    assert data["annotated_image_url"] == "/processed/multiline/image"
    assert data["tools_called"] == ["apply_image_edit_plan"]
    assert final_image.size == (30, 50)


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
