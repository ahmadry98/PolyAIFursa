
import importlib.util
import base64
import io
import json
import sys
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from PIL import Image

AGENT_DIR = Path(__file__).resolve().parents[1]
if str(AGENT_DIR) in sys.path:
    sys.path.remove(str(AGENT_DIR))
sys.path.insert(0, str(AGENT_DIR))

spec = importlib.util.spec_from_file_location(
    "agent_app_test_run_agent",
    AGENT_DIR / "app.py",
)
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


class FakeLLMWithTools:
    def __init__(self):
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1

        if self.calls == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "detect_objects",
                        "args": {},
                        "id": "call_1",
                    }
                ],
            )

        return AIMessage(
            content="I found 2 people in the image.",
            response_metadata={},
            usage_metadata={
                "input_tokens": 20,
                "output_tokens": 8,
                "total_tokens": 28,
            },
        )


class FakeTool:
    def invoke(self, tool_call):
        return type(
            "FakeToolMessage",
            (),
            {
                "content": (
                    '{"uid":"prediction-123",'
                    '"predicted_image":null,'
                    '"detection_count":2,'
                    '"labels":["person","person"]}'
                )
            },
        )()


def test_run_agent_calls_tool_and_returns_final_answer(monkeypatch):
    fake_llm = FakeLLMWithTools()

    monkeypatch.setattr(app, "llm_with_tools", fake_llm)
    monkeypatch.setattr(app, "TOOLS", {"detect_objects": FakeTool()})
    monkeypatch.setattr(app, "YOLO_SERVICE_URL", "http://localhost:8080")

    result = app.run_agent(
        [HumanMessage(content="What objects are in this image?")]
    )

    assert result["response"] == "I found 2 people in the image."
    assert result["prediction_id"] == "prediction-123"
    assert result["annotated_image_url"] == "/prediction/prediction-123/image"
    assert result["iterations"] == 2
    assert result["tools_called"] == ["detect_objects"]
    assert result["tokens_used"].total == 28
    assert result["context_limit_exceeded"] is False


def test_run_agent_uploads_processed_tool_image(monkeypatch):
    class ImageProcessingLLM:
        def __init__(self):
            self.calls = 0
            self.second_call_messages = None

        def invoke(self, messages):
            self.calls += 1

            if self.calls == 1:
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "rotate_image",
                            "args": {"angle": 90},
                            "id": "call_image",
                        }
                    ],
                )

            self.second_call_messages = messages
            return AIMessage(
                content="I rotated the image.",
                response_metadata={},
                usage_metadata={
                    "input_tokens": 30,
                    "output_tokens": 6,
                    "total_tokens": 36,
                },
            )

    class ImageProcessingTool:
        def invoke(self, tool_call):
            return type(
                "FakeToolMessage",
                (),
                {
                    "content": (
                        '{"operation":"rotate",'
                        '"scope":"whole_image",'
                        '"parameters":{"angle":90},'
                        '"image_base64":"cHJvY2Vzc2VkLWltYWdl"}'
                    )
                },
            )()

    captured = {}

    def fake_upload_bytes_to_s3(data, key, content_type):
        captured["upload"] = {
            "data": data,
            "key": key,
            "content_type": content_type,
        }
        return key

    fake_llm = ImageProcessingLLM()

    monkeypatch.setattr(app, "llm_with_tools", fake_llm)
    monkeypatch.setattr(app, "TOOLS", {"rotate_image": ImageProcessingTool()})
    monkeypatch.setattr(app.uuid, "uuid4", lambda: "processed-image-id")
    monkeypatch.setattr(app, "upload_bytes_to_s3", fake_upload_bytes_to_s3)

    result = app.run_agent([HumanMessage(content="Rotate this image")])

    assert result["response"] == "I rotated the image."
    assert result["annotated_image"] is None
    assert result["annotated_image_url"] == "/processed/processed-image-id/image"
    assert result["iterations"] == 2
    assert result["tokens_used"].total == 36
    assert captured["upload"] == {
        "data": b"processed-image",
        "key": "processed/processed-image-id/image.png",
        "content_type": "image/png",
    }
    tool_messages = [
        message
        for message in fake_llm.second_call_messages
        if isinstance(message, ToolMessage)
    ]
    assert len(tool_messages) == 1
    assert tool_messages[0].tool_call_id == "call_image"
    sanitized = json.loads(tool_messages[0].content)
    assert sanitized == {
        "operation": "rotate",
        "scope": "whole_image",
        "parameters": {
            "angle": 90,
        },
        "status": "success",
        "image_returned": True,
        "result": "The processed image was stored and will be displayed by the frontend.",
        "response_guidance": (
            "Use these details to explain the edit naturally. "
            "Do not mention storage, URLs, base64, or internal IDs."
        ),
    }
    assert "image_base64" not in tool_messages[0].content
    assert "cHJvY2Vzc2VkLWltYWdl" not in tool_messages[0].content


def test_run_agent_stops_at_max_iterations(monkeypatch):
    class AlwaysToolCallingLLM:
        def invoke(self, messages):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "detect_objects",
                        "args": {},
                        "id": "call_loop",
                    }
                ],
            )

    monkeypatch.setattr(app, "llm_with_tools", AlwaysToolCallingLLM())
    monkeypatch.setattr(app, "TOOLS", {"detect_objects": FakeTool()})

    result = app.run_agent(
        [HumanMessage(content="Keep detecting objects")],
        max_iterations=1,
    )

    assert result["context_limit_exceeded"] is True
    assert result["iterations"] == 1
    assert result["tools_called"] == ["detect_objects"]


def test_sort_detections_from_right():
    detections = [
        {"label": "person", "box": [10, 0, 20, 100]},
        {"label": "person", "box": [90, 0, 100, 100]},
        {"label": "person", "box": [50, 0, 60, 100]},
    ]

    sorted_detections = app._sort_detections_horizontally(
        detections,
        user_text="rotate the second person from the right",
    )

    assert sorted_detections[0]["box"] == [90, 0, 100, 100]
    assert sorted_detections[1]["box"] == [50, 0, 60, 100]
    assert sorted_detections[2]["box"] == [10, 0, 20, 100]


def test_sort_detections_from_right_ignores_tiny_background_detection():
    detections = [
        {"label": "person", "box": [10, 10, 30, 110]},
        {"label": "person", "box": [45, 10, 65, 110]},
        {"label": "person", "box": [75, 10, 95, 110]},
        {"label": "person", "box": [105, 10, 125, 110]},
        {"label": "person", "box": [115, 5, 119, 20]},
    ]

    sorted_detections = app._sort_detections_horizontally(
        detections,
        user_text="blur the second person from the right",
    )

    assert sorted_detections[0]["box"] == [105, 10, 125, 110]
    assert sorted_detections[1]["box"] == [75, 10, 95, 110]
    assert [115, 5, 119, 20] not in [
        detection["box"] for detection in sorted_detections
    ]


def test_rotate_image_passes_angle_to_image_tool(monkeypatch):
    captured = {}

    def fake_run_img_proc_mcp(tool_name, arguments):
        captured["tool_name"] = tool_name
        captured["arguments"] = arguments
        return "processed-image"

    monkeypatch.setattr(app, "_run_img_proc_mcp", fake_run_img_proc_mcp)
    token = app._current_image_b64.set("image-base64")

    try:
        result = app.rotate_image.invoke({"angle": 90})
    finally:
        app._current_image_b64.reset(token)

    assert captured["tool_name"] == "rotate"
    assert captured["arguments"]["angle"] == 90
    assert '"operation": "rotate"' in result


def test_edit_detected_object_uses_occurrence_from_right(monkeypatch):
    image = Image.new("RGB", (120, 120), "white")
    image_buffer = io.BytesIO()
    image.save(image_buffer, format="PNG")
    image_b64 = base64.b64encode(image_buffer.getvalue()).decode()

    captured = {}

    def fake_detect_uploaded_image(_image_b64):
        return {
            "detection_objects": [
                {"label": "person", "box": [10, 10, 20, 100]},
                {"label": "person", "box": [90, 10, 110, 100]},
                {"label": "person", "box": [50, 10, 65, 100]},
            ]
        }

    def fake_run_img_proc_mcp(tool_name, arguments):
        captured["tool_name"] = tool_name
        captured["arguments"] = arguments
        return arguments["image_b64"]

    monkeypatch.setattr(app, "_detect_uploaded_image", fake_detect_uploaded_image)
    monkeypatch.setattr(app, "_run_img_proc_mcp", fake_run_img_proc_mcp)
    token = app._current_image_b64.set(image_b64)
    text_token = app._current_user_text.set("rotate the second person from the right")

    try:
        result = json.loads(
            app.edit_detected_object.invoke(
                {
                    "object_label": "person",
                    "occurrence": 2,
                    "operation": "rotate",
                    "angle": 90,
                }
            )
        )
    finally:
        app._current_image_b64.reset(token)
        app._current_user_text.reset(text_token)

    cropped = Image.open(
        io.BytesIO(base64.b64decode(captured["arguments"]["image_b64"]))
    )

    assert captured["tool_name"] == "rotate"
    assert captured["arguments"]["angle"] == 90
    assert cropped.size == (15, 90)
    assert result["operation"] == "rotate_object"
