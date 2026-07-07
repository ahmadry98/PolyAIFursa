
import importlib.util
import base64
import io
import importlib
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

agent_runner = importlib.import_module("agent_runner")
config = importlib.import_module("config")
image_utils = importlib.import_module("image_utils")
tools = importlib.import_module("tools")


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

    monkeypatch.setattr(config, "llm_with_tools", fake_llm)
    monkeypatch.setattr(agent_runner, "TOOLS", {"detect_objects": FakeTool()})

    result = agent_runner.run_agent(
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

    monkeypatch.setattr(config, "llm_with_tools", fake_llm)
    monkeypatch.setattr(agent_runner, "TOOLS", {"rotate_image": ImageProcessingTool()})
    monkeypatch.setattr(image_utils.uuid, "uuid4", lambda: "processed-image-id")
    monkeypatch.setattr(image_utils, "upload_bytes_to_s3", fake_upload_bytes_to_s3)

    result = agent_runner.run_agent([HumanMessage(content="Rotate this image")])

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

    monkeypatch.setattr(config, "llm_with_tools", AlwaysToolCallingLLM())
    monkeypatch.setattr(agent_runner, "TOOLS", {"detect_objects": FakeTool()})

    result = agent_runner.run_agent(
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

    sorted_detections = image_utils._sort_detections_horizontally(
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

    sorted_detections = image_utils._sort_detections_horizontally(
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

    monkeypatch.setattr(tools, "_run_img_proc_mcp", fake_run_img_proc_mcp)
    token = tools._current_image_b64.set("image-base64")

    try:
        result = tools.rotate_image.invoke({"angle": 90})
    finally:
        tools._current_image_b64.reset(token)

    assert captured["tool_name"] == "rotate"
    assert captured["arguments"]["angle"] == 90
    assert '"operation": "rotate"' in result


def test_crop_image_rounds_float_coordinates(monkeypatch):
    captured = {}

    def fake_run_img_proc_mcp(tool_name, arguments):
        captured["tool_name"] = tool_name
        captured["arguments"] = arguments
        return "processed-image"

    monkeypatch.setattr(tools, "_run_img_proc_mcp", fake_run_img_proc_mcp)
    token = tools._current_image_b64.set("image-base64")

    try:
        result = json.loads(
            tools.crop_image.invoke(
                {
                    "left": 191.1942138671875,
                    "top": 339.7136535644531,
                    "right": 310.1331481933594,
                    "bottom": 571.4204711914062,
                }
            )
        )
    finally:
        tools._current_image_b64.reset(token)

    assert captured["tool_name"] == "crop"
    assert captured["arguments"] == {
        "image_b64": "image-base64",
        "left": 191,
        "top": 340,
        "right": 310,
        "bottom": 571,
    }
    assert result["parameters"] == {
        "left": 191,
        "top": 340,
        "right": 310,
        "bottom": 571,
    }
    assert result["operation"] == "crop"


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

    monkeypatch.setattr(tools, "_detect_uploaded_image", fake_detect_uploaded_image)
    monkeypatch.setattr(tools, "_run_img_proc_mcp", fake_run_img_proc_mcp)
    token = tools._current_image_b64.set(image_b64)
    text_token = tools._current_user_text.set("rotate the second person from the right")

    try:
        result = json.loads(
            tools.edit_detected_object.invoke(
                {
                    "object_label": "person",
                    "occurrence": 2,
                    "operation": "rotate",
                    "angle": 90,
                }
            )
        )
    finally:
        tools._current_image_b64.reset(token)
        tools._current_user_text.reset(text_token)

    cropped = Image.open(
        io.BytesIO(base64.b64decode(captured["arguments"]["image_b64"]))
    )

    assert captured["tool_name"] == "rotate"
    assert captured["arguments"]["angle"] == 90
    assert cropped.size == (15, 90)
    assert result["operation"] == "rotate_object"


def test_edit_detected_object_can_crop_selected_object(monkeypatch):
    image = Image.new("RGB", (120, 120), "white")
    image_buffer = io.BytesIO()
    image.save(image_buffer, format="PNG")
    image_b64 = base64.b64encode(image_buffer.getvalue()).decode()

    def fake_detect_uploaded_image(_image_b64):
        return {
            "detection_objects": [
                {"label": "person", "box": [10, 10, 20, 100]},
                {"label": "person", "box": [90, 10, 110, 100]},
                {"label": "person", "box": [50, 10, 65, 100]},
            ]
        }

    monkeypatch.setattr(tools, "_detect_uploaded_image", fake_detect_uploaded_image)
    token = tools._current_image_b64.set(image_b64)
    text_token = tools._current_user_text.set("crop the second person from the right")

    try:
        result = json.loads(
            tools.edit_detected_object.invoke(
                {
                    "object_label": "person",
                    "occurrence": 2,
                    "operation": "crop",
                }
            )
        )
    finally:
        tools._current_image_b64.reset(token)
        tools._current_user_text.reset(text_token)

    cropped = Image.open(io.BytesIO(base64.b64decode(result["image_base64"])))

    assert result["operation"] == "crop_object"
    assert result["scope"] == "selected_object"
    assert result["parameters"]["box"] == [50, 10, 65, 100]
    assert cropped.size == (15, 90)


def test_plan_image_edits_extracts_multiple_noise_operations():
    plan = tools.plan_image_edits(
        "add 0.5 noise to the right person and 0.9 noise to the left person"
    )

    assert plan == [
        {
            "tool": "add_noise",
            "target": "add 0.5 noise to the right person",
            "selection_text": "add 0.5 noise to the right person",
            "object_label": "person",
            "occurrence": 1,
            "amount": 0.5,
        },
        {
            "tool": "add_noise",
            "target": "0.9 noise to the left person",
            "selection_text": "0.9 noise to the left person",
            "object_label": "person",
            "occurrence": 1,
            "amount": 0.9,
        },
    ]


def test_run_agent_applies_multiple_independent_object_edits(monkeypatch):
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
        assert tool_name == "add_noise"
        crop = Image.open(
            io.BytesIO(base64.b64decode(arguments["image_b64"]))
        ).convert("RGB")
        color = "black" if arguments["amount"] == 0.5 else "gray"
        return image_utils._encode_image(Image.new("RGB", crop.size, color))

    def fake_store_processed_image(image_base64):
        stored["image_base64"] = image_base64
        return "/processed/final/image"

    monkeypatch.setattr(tools, "_detect_uploaded_image", fake_detect_uploaded_image)
    monkeypatch.setattr(tools, "_run_img_proc_mcp", fake_run_img_proc_mcp)
    monkeypatch.setattr(
        agent_runner,
        "_store_processed_image",
        fake_store_processed_image,
    )

    image_token = tools._current_image_b64.set(image_b64)
    working_token = tools._working_image_b64.set(image_b64)
    text_token = tools._current_user_text.set(
        "add 0.5 noise to the right person and 0.9 noise to the left person"
    )
    try:
        result = agent_runner.run_agent(
            [
                HumanMessage(
                    content=(
                        "add 0.5 noise to the right person and 0.9 noise "
                        "to the left person"
                    )
                )
            ]
        )
    finally:
        tools._current_image_b64.reset(image_token)
        tools._working_image_b64.reset(working_token)
        tools._current_user_text.reset(text_token)

    final_image = Image.open(
        io.BytesIO(base64.b64decode(stored["image_base64"]))
    ).convert("RGB")

    assert result["annotated_image_url"] == "/processed/final/image"
    assert result["tools_called"] == ["apply_image_edit_plan"]
    assert final_image.getpixel((65, 10)) == (0, 0, 0)
    assert final_image.getpixel((10, 10)) == (128, 128, 128)
    assert final_image.getpixel((40, 10)) == (255, 255, 255)


def test_run_agent_can_mix_blur_and_draw_box_object_edits(monkeypatch):
    image = Image.new("RGB", (90, 50), "white")
    image_buffer = io.BytesIO()
    image.save(image_buffer, format="PNG")
    image_b64 = base64.b64encode(image_buffer.getvalue()).decode()
    stored = {}

    def fake_detect_uploaded_image(_image_b64):
        return {
            "detection_objects": [
                {"label": "person", "box": [5, 5, 25, 35]},
                {"label": "car", "box": [50, 10, 80, 35]},
            ]
        }

    def fake_run_img_proc_mcp(tool_name, arguments):
        assert tool_name == "blur"
        crop = Image.open(
            io.BytesIO(base64.b64decode(arguments["image_b64"]))
        ).convert("RGB")
        return image_utils._encode_image(Image.new("RGB", crop.size, "black"))

    def fake_store_processed_image(image_base64):
        stored["image_base64"] = image_base64
        return "/processed/box/image"

    monkeypatch.setattr(tools, "_detect_uploaded_image", fake_detect_uploaded_image)
    monkeypatch.setattr(tools, "_run_img_proc_mcp", fake_run_img_proc_mcp)
    monkeypatch.setattr(
        agent_runner,
        "_store_processed_image",
        fake_store_processed_image,
    )

    image_token = tools._current_image_b64.set(image_b64)
    working_token = tools._working_image_b64.set(image_b64)
    text_token = tools._current_user_text.set(
        "blur the left person and draw a red box around the car"
    )
    try:
        result = agent_runner.run_agent(
            [
                HumanMessage(
                    content="blur the left person and draw a red box around the car"
                )
            ]
        )
    finally:
        tools._current_image_b64.reset(image_token)
        tools._working_image_b64.reset(working_token)
        tools._current_user_text.reset(text_token)

    final_image = Image.open(
        io.BytesIO(base64.b64decode(stored["image_base64"]))
    ).convert("RGB")

    assert result["annotated_image_url"] == "/processed/box/image"
    assert final_image.getpixel((10, 10)) == (0, 0, 0)
    assert final_image.getpixel((50, 10)) == (255, 0, 0)


def test_run_agent_applies_sequential_object_then_whole_image_edit(monkeypatch):
    image = Image.new("RGB", (60, 40), "white")
    image_buffer = io.BytesIO()
    image.save(image_buffer, format="PNG")
    image_b64 = base64.b64encode(image_buffer.getvalue()).decode()
    stored = {}
    rotate_input = {}

    def fake_detect_uploaded_image(_image_b64):
        return {
            "detection_objects": [
                {"label": "dog", "box": [5, 5, 25, 25]},
            ]
        }

    def fake_run_img_proc_mcp(tool_name, arguments):
        input_image = Image.open(
            io.BytesIO(base64.b64decode(arguments["image_b64"]))
        ).convert("RGB")

        if tool_name == "add_noise":
            noisy_image = Image.new("RGB", input_image.size, "black")
            return image_utils._encode_image(noisy_image)

        assert tool_name == "rotate"
        rotate_input["pixel_after_first_edit"] = input_image.getpixel((10, 10))
        rotated = input_image.rotate(arguments["angle"], expand=True)
        return image_utils._encode_image(rotated)

    def fake_store_processed_image(image_base64):
        stored["image_base64"] = image_base64
        return "/processed/sequential/image"

    monkeypatch.setattr(tools, "_detect_uploaded_image", fake_detect_uploaded_image)
    monkeypatch.setattr(tools, "_run_img_proc_mcp", fake_run_img_proc_mcp)
    monkeypatch.setattr(
        agent_runner,
        "_store_processed_image",
        fake_store_processed_image,
    )

    image_token = tools._current_image_b64.set(image_b64)
    working_token = tools._working_image_b64.set(image_b64)
    text_token = tools._current_user_text.set(
        "add noise to the dog, then rotate the whole image"
    )
    try:
        result = agent_runner.run_agent(
            [HumanMessage(content="add noise to the dog, then rotate the whole image")]
        )
    finally:
        tools._current_image_b64.reset(image_token)
        tools._working_image_b64.reset(working_token)
        tools._current_user_text.reset(text_token)

    final_image = Image.open(
        io.BytesIO(base64.b64decode(stored["image_base64"]))
    ).convert("RGB")

    assert result["annotated_image_url"] == "/processed/sequential/image"
    assert rotate_input["pixel_after_first_edit"] == (0, 0, 0)
    assert final_image.size == (40, 60)
