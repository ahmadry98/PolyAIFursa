import asyncio
import base64
import binascii
import io
import json
import logging
import os
import re
import sys
import time
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_core.tools import tool
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from PIL import Image
from pydantic import BaseModel

from s3_utils import upload_bytes_to_s3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logging.getLogger("langchain").setLevel(logging.DEBUG)
logging.getLogger("langchain_core").setLevel(logging.DEBUG)

YOLO_SERVICE_URL = os.environ.get("YOLO_SERVICE_URL", "http://localhost:8080")
IMG_PROC_MCP_SCRIPT = os.environ.get(
    "IMG_PROC_MCP_SCRIPT",
    str(Path(__file__).resolve().parents[1] / "img-proc-mcp" / "img_proc_app.py"),
)
MODEL = os.environ.get("MODEL")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Text-only models. The LLM never receives image bytes.
ALLOWED_MODELS = {
    "bedrock/openai.gpt-oss-20b-1:0",
    "bedrock/anthropic.claude-3-haiku-20240307-v1:0",
    "bedrock/amazon.nova-micro-v1:0",
    "bedrock/amazon.nova-lite-v1:0",
    "bedrock/meta.llama3-1-8b-instruct-v1:0",
    "bedrock/mistral.mistral-7b-instruct-v0:2",
}

SYSTEM_PROMPT = (
    "You are an AI vision assistant. "
    "You help users understand, analyze, and edit images. "
    "Use the available tools whenever needed. "
    "For requests that ask what is in an image, identify objects, count objects, "
    "or locate objects, use the object detection tool. "
    "Report object counts exactly as provided in label_counts. "
    "For requests that ask to rotate, flip, blur, resize, crop, add noise, "
    "or edit a detected object in an image, use the appropriate image-processing tool. "
    "When an image-processing tool returns an image, do not include the base64 string "
    "or markdown image syntax in your response. "
    "Reply with one short sentence describing what you did. "
    "The frontend will display the processed image automatically."
)

_current_image_b64: ContextVar[Optional[str]] = ContextVar(
    "current_image_b64",
    default=None,
)
_current_user_text: ContextVar[str] = ContextVar("current_user_text", default="")


def _decode_uploaded_image(image_b64: str) -> tuple[bytes, str, str]:
    try:
        image_bytes = base64.b64decode(image_b64, validate=True)
    except (binascii.Error, ValueError, TypeError) as error:
        raise ValueError("The uploaded image is not valid base64 data.") from error

    if image_bytes.startswith(b"\xff\xd8\xff"):
        return image_bytes, "image.jpg", "image/jpeg"

    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return image_bytes, "image.png", "image/png"

    raise ValueError("Only JPEG and PNG images are supported.")


def _detect_uploaded_image(image_b64: str) -> dict[str, Any]:
    image_bytes, image_name, content_type = _decode_uploaded_image(image_b64)

    chat_id = str(uuid.uuid4())
    prediction_id = str(uuid.uuid4())
    original_key = f"{chat_id}/{prediction_id}/original/{image_name}"

    upload_bytes_to_s3(
        data=image_bytes,
        key=original_key,
        content_type=content_type,
    )

    with httpx.Client(timeout=60.0) as client:
        response = client.post(
            f"{YOLO_SERVICE_URL}/predict",
            params={"image_s3_key": original_key},
        )
        response.raise_for_status()

    return response.json()


def _compact_detection_result(result: dict[str, Any]) -> dict[str, Any]:
    labels = result.get("labels", [])
    label_counts: dict[str, int] = {}
    for label in labels:
        label_counts[label] = label_counts.get(label, 0) + 1

    compact = {
        "uid": result.get("uid"),
        "detection_count": result.get("detection_count", len(labels)),
        "labels": labels,
        "label_counts": label_counts,
    }

    if "detection_objects" in result:
        compact["detection_objects"] = result["detection_objects"]

    return compact


@tool
def detect_objects() -> str:
    """Detect and identify objects in the image provided by the user using YOLO object detection."""
    image_b64 = _current_image_b64.get()
    if not image_b64:
        return json.dumps({"error": "No image was provided by the user."})

    try:
        result = _detect_uploaded_image(image_b64)
    except ValueError as error:
        return json.dumps({"error": str(error)})
    except Exception:
        logging.exception("Object detection request failed")
        return json.dumps(
            {"error": "The object detection service could not process the image."}
        )

    return json.dumps(_compact_detection_result(result))


async def _call_img_proc_mcp(tool_name: str, arguments: dict[str, Any]) -> str:
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[IMG_PROC_MCP_SCRIPT],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)

    if not result.content:
        return ""

    first_content = result.content[0]
    return getattr(first_content, "text", str(first_content))


def _run_img_proc_mcp(tool_name: str, arguments: dict[str, Any]) -> str:
    return asyncio.run(_call_img_proc_mcp(tool_name, arguments))


def _decode_image(image_b64: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(image_b64))).convert("RGB")


def _encode_image(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _crop_region(
    image_b64: str,
    box: list[float],
) -> tuple[Image.Image, tuple[int, int, int, int]]:
    img = _decode_image(image_b64)

    left, top, right, bottom = [int(v) for v in box]
    left = max(0, left)
    top = max(0, top)
    right = min(img.width, right)
    bottom = min(img.height, bottom)

    cropped = img.crop((left, top, right, bottom))
    return cropped, (left, top, right, bottom)


def _box_center_x(detection: dict[str, Any]) -> float:
    left, _, right, _ = detection["box"]
    return (float(left) + float(right)) / 2


def _box_area(detection: dict[str, Any]) -> float:
    left, top, right, bottom = detection["box"]
    return max(0.0, float(right) - float(left)) * max(0.0, float(bottom) - float(top))


def _prominent_detections(detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not detections:
        return detections

    largest_area = max(_box_area(detection) for detection in detections)
    if largest_area <= 0:
        return detections

    prominent = [
        detection
        for detection in detections
        if _box_area(detection) >= largest_area * 0.35
    ]
    return prominent or detections


def _sort_detections_horizontally(
    detections: list[dict[str, Any]],
    user_text: str,
) -> list[dict[str, Any]]:
    normalized_text = user_text.lower()
    if "right" not in normalized_text and "left" not in normalized_text:
        return detections

    visible_detections = _prominent_detections(detections)
    left_to_right = sorted(visible_detections, key=_box_center_x)
    if "right" in normalized_text:
        return list(reversed(left_to_right))
    return left_to_right


def _paste_region(
    original_b64: str,
    region_b64: str,
    box: tuple[int, int, int, int],
) -> str:
    original = _decode_image(original_b64)
    region = _decode_image(region_b64)

    left, top, right, bottom = box
    region = region.resize((right - left, bottom - top))

    original.paste(region, (left, top))
    return _encode_image(original)


@tool
def rotate_image(angle: float) -> str:
    """Rotate the uploaded image by angle degrees. Returns JSON with image_base64."""
    image_b64 = _current_image_b64.get()
    if not image_b64:
        return json.dumps({"error": "No image was provided by the user."})

    processed = _run_img_proc_mcp(
        "rotate",
        {
            "image_b64": image_b64,
            "angle": angle,
        },
    )

    return json.dumps(
        {
            "operation": "rotate",
            "image_base64": processed,
        }
    )


@tool
def flip_image(direction: str) -> str:
    """Flip the uploaded image. direction must be horizontal or vertical. Returns JSON with image_base64."""
    image_b64 = _current_image_b64.get()
    if not image_b64:
        return json.dumps({"error": "No image was provided by the user."})

    processed = _run_img_proc_mcp(
        "flip",
        {
            "image_b64": image_b64,
            "direction": direction,
        },
    )

    return json.dumps(
        {
            "operation": "flip",
            "image_base64": processed,
        }
    )


@tool
def blur_image(radius: float = 2.0) -> str:
    """Blur the uploaded image. Returns JSON with image_base64."""
    image_b64 = _current_image_b64.get()
    if not image_b64:
        return json.dumps({"error": "No image was provided by the user."})

    processed = _run_img_proc_mcp(
        "blur",
        {
            "image_b64": image_b64,
            "radius": radius,
        },
    )

    return json.dumps(
        {
            "operation": "blur",
            "image_base64": processed,
        }
    )


@tool
def resize_image(width: int, height: int) -> str:
    """Resize the uploaded image to width x height. Returns JSON with image_base64."""
    image_b64 = _current_image_b64.get()
    if not image_b64:
        return json.dumps({"error": "No image was provided by the user."})

    processed = _run_img_proc_mcp(
        "resize",
        {
            "image_b64": image_b64,
            "width": width,
            "height": height,
        },
    )

    return json.dumps(
        {
            "operation": "resize",
            "image_base64": processed,
        }
    )


@tool
def crop_image(left: int, top: int, right: int, bottom: int) -> str:
    """Crop the uploaded image using bounding box coordinates. Returns JSON with image_base64."""
    image_b64 = _current_image_b64.get()
    if not image_b64:
        return json.dumps({"error": "No image was provided by the user."})

    processed = _run_img_proc_mcp(
        "crop",
        {
            "image_b64": image_b64,
            "left": left,
            "top": top,
            "right": right,
            "bottom": bottom,
        },
    )

    return json.dumps(
        {
            "operation": "crop",
            "image_base64": processed,
        }
    )


@tool
def add_noise_image(amount: float = 0.05) -> str:
    """Add salt-and-pepper noise to the uploaded image. Amount should be between 0 and 1."""
    image_b64 = _current_image_b64.get()
    if not image_b64:
        return json.dumps({"error": "No image was provided by the user."})

    processed = _run_img_proc_mcp(
        "add_noise",
        {
            "image_b64": image_b64,
            "amount": amount,
        },
    )

    return json.dumps(
        {
            "operation": "add_noise",
            "image_base64": processed,
        }
    )


@tool
def edit_detected_object(
    object_label: str,
    occurrence: int,
    operation: str,
    angle: float = 90,
    radius: float = 2,
) -> str:
    """Edit a detected object in the uploaded image.

    If the user said left or right, occurrence is counted visually from that side.
    Returns JSON with image_base64.
    """
    image_b64 = _current_image_b64.get()
    if not image_b64:
        return json.dumps({"error": "No image was provided by the user."})

    try:
        prediction = _detect_uploaded_image(image_b64)
    except ValueError as error:
        return json.dumps({"error": str(error)})
    except Exception:
        logging.exception("Object detection request failed")
        return json.dumps(
            {"error": "The object detection service could not process the image."}
        )

    detections = [
        detection
        for detection in prediction.get("detection_objects", [])
        if detection.get("label") == object_label
    ]

    sorted_detections = _sort_detections_horizontally(
        detections,
        _current_user_text.get(),
    )

    if len(sorted_detections) < occurrence:
        return json.dumps(
            {
                "error": f"Could not find {occurrence} '{object_label}' objects."
            }
        )

    target = sorted_detections[occurrence - 1]
    cropped_img, safe_box = _crop_region(image_b64, target["box"])
    cropped_b64 = _encode_image(cropped_img)

    if operation == "blur":
        processed_crop_b64 = _run_img_proc_mcp(
            "blur",
            {
                "image_b64": cropped_b64,
                "radius": radius,
            },
        )
    elif operation == "rotate":
        processed_crop_b64 = _run_img_proc_mcp(
            "rotate",
            {
                "image_b64": cropped_b64,
                "angle": angle,
            },
        )
    elif operation == "flip":
        processed_crop_b64 = _run_img_proc_mcp(
            "flip",
            {
                "image_b64": cropped_b64,
                "direction": "horizontal",
            },
        )
    elif operation == "add_noise":
        processed_crop_b64 = _run_img_proc_mcp(
            "add_noise",
            {
                "image_b64": cropped_b64,
                "amount": 0.1,
            },
        )
    else:
        return json.dumps(
            {
                "error": f"Unsupported object operation: {operation}"
            }
        )

    final_image_b64 = _paste_region(image_b64, processed_crop_b64, safe_box)

    return json.dumps(
        {
            "operation": f"{operation}_object",
            "image_base64": final_image_b64,
        }
    )


# Registry: map tool name -> tool function.
TOOLS = {
    detect_objects.name: detect_objects,
    rotate_image.name: rotate_image,
    flip_image.name: flip_image,
    blur_image.name: blur_image,
    resize_image.name: resize_image,
    crop_image.name: crop_image,
    add_noise_image.name: add_noise_image,
    edit_detected_object.name: edit_detected_object,
}

rate_limiter = InMemoryRateLimiter(
    requests_per_second=5,
    check_every_n_seconds=0.1,
    max_bucket_size=10,
)
llm_with_tools = None
MAX_INPUT_TOKENS = None


def get_llm_with_tools():
    """Create the Bedrock model on first use so imports and tests stay offline."""
    global llm_with_tools, MAX_INPUT_TOKENS

    if llm_with_tools is not None:
        return llm_with_tools

    if MODEL not in ALLOWED_MODELS:
        allowed_list = "\n  ".join(sorted(ALLOWED_MODELS))
        raise RuntimeError(
            f"MODEL='{MODEL}' is not allowed. Set MODEL to one of:\n  {allowed_list}"
        )

    model_options = {}
    if MODEL.startswith("bedrock/openai."):
        model_options["additional_model_request_fields"] = {
            "reasoning_effort": "low"
        }

    llm = init_chat_model(
        MODEL.replace("bedrock/", ""),
        model_provider="bedrock_converse",
        temperature=0,
        max_tokens=1024,
        timeout=60,
        max_retries=1,
        rate_limiter=rate_limiter,
        region_name=AWS_REGION,
        **model_options,
    )
    model_profile = llm.profile or {}

    if not model_profile.get("tool_calling"):
        raise RuntimeError(f"MODEL='{MODEL}' does not support tool calling.")

    MAX_INPUT_TOKENS = model_profile.get("max_input_tokens")
    if MAX_INPUT_TOKENS is None:
        logging.warning(
            "Model profile does not expose max_input_tokens; "
            "context limit checks will be skipped."
        )
    else:
        logging.info("Model max_input_tokens: %s", MAX_INPUT_TOKENS)

    llm_with_tools = llm.bind_tools(list(TOOLS.values()))
    return llm_with_tools


operation_messages = {
    "rotate": "Rotated the image.",
    "flip": "Flipped the image.",
    "blur": "Blurred the image.",
    "resize": "Resized the image.",
    "crop": "Cropped the image.",
    "add_noise": "Added noise to the image.",
    "blur_object": "Blurred the selected object.",
    "rotate_object": "Rotated the selected object.",
    "flip_object": "Flipped the selected object.",
    "add_noise_object": "Added noise to the selected object.",
}


ORDINAL_WORDS = {
    "first": 1,
    "1st": 1,
    "second": 2,
    "2nd": 2,
    "third": 3,
    "3rd": 3,
    "fourth": 4,
    "4th": 4,
    "fifth": 5,
    "5th": 5,
}


def _extract_occurrence(text: str) -> int:
    normalized = text.lower()
    for word, value in ORDINAL_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", normalized):
            return value
    return 1


def _extract_object_label(text: str) -> Optional[str]:
    normalized = text.lower()
    known_labels = ["person", "car", "bus", "truck", "dog", "cat", "bicycle"]
    for label in known_labels:
        if re.search(rf"\b{label}s?\b", normalized):
            return label
    return None


def _extract_direct_edit(text: str) -> Optional[dict[str, Any]]:
    normalized = text.lower()

    if "blur" in normalized:
        operation = "blur"
    elif "rotate" in normalized:
        operation = "rotate"
    elif "flip" in normalized:
        operation = "flip"
    elif "noise" in normalized:
        operation = "add_noise"
    else:
        return None

    object_label = _extract_object_label(normalized)
    if object_label is None:
        return None

    edit_args: dict[str, Any] = {
        "object_label": object_label,
        "occurrence": _extract_occurrence(normalized),
        "operation": operation,
    }

    if operation == "rotate":
        angle_match = re.search(r"\b(\d+(?:\.\d+)?)\b", normalized)
        if angle_match:
            edit_args["angle"] = float(angle_match.group(1))

    if operation == "blur":
        radius_match = re.search(r"\b(?:radius|blur)\s+(\d+(?:\.\d+)?)\b", normalized)
        if radius_match:
            edit_args["radius"] = float(radius_match.group(1))

    return edit_args


class TokenUsage(BaseModel):
    input: int = 0
    output: int = 0
    total: int = 0


def run_agent(history: list, max_iterations: int = 10):
    """
    Simple ReAct loop with max_iterations guard.
    Returns final assistant text and image metadata when a tool produces one.
    """
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + history
    start_time = time.time()

    annotated_image_url = None
    annotated_image = None
    prediction_id = None
    tools_called = []
    iterations = 0
    tokens_used = TokenUsage()
    context_limit_exceeded = False
    model = get_llm_with_tools()

    for iteration in range(max_iterations):
        iterations = iteration + 1
        response: AIMessage = model.invoke(messages)
        messages.append(response)
        usage = response.usage_metadata or {}

        tokens_used = TokenUsage(
            input=usage.get("input_tokens", 0),
            output=usage.get("output_tokens", 0),
            total=usage.get("total_tokens", 0),
        )
        context_limit_exceeded = (
            MAX_INPUT_TOKENS is not None
            and tokens_used.input > MAX_INPUT_TOKENS * 0.9
        )

        if not response.tool_calls:
            content = response.content

            if isinstance(content, list):
                content = "\n".join(
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )

            content = re.sub(
                r"<thinking>.*?</thinking>\s*",
                "",
                str(content),
                flags=re.DOTALL,
            )

            return {
                "response": content,
                "prediction_id": prediction_id,
                "annotated_image": annotated_image,
                "annotated_image_url": annotated_image_url,
                "agent_loop_time_s": round(time.time() - start_time, 2),
                "iterations": iterations,
                "tools_called": tools_called,
                "context_limit_exceeded": context_limit_exceeded,
                "tokens_used": tokens_used,
            }

        for tool_call in response.tool_calls:
            tools_called.append(tool_call["name"])

            tool_fn = TOOLS[tool_call["name"]]
            tool_result = tool_fn.invoke(tool_call)
            messages.append(tool_result)

            try:
                data = json.loads(tool_result.content)

                uid = data.get("uid") or data.get("prediction_uid")
                if uid:
                    prediction_id = uid
                    annotated_image_url = f"/prediction/{uid}/image"

                processed_image_b64 = data.get("image_base64")
                if processed_image_b64:
                    annotated_image = processed_image_b64
                    operation = data.get("operation", "processed")
                    return {
                        "response": operation_messages.get(
                            operation,
                            "Processed the image.",
                        ),
                        "prediction_id": prediction_id,
                        "annotated_image": annotated_image,
                        "annotated_image_url": annotated_image_url,
                        "agent_loop_time_s": round(time.time() - start_time, 2),
                        "iterations": iterations,
                        "tools_called": tools_called,
                        "context_limit_exceeded": context_limit_exceeded,
                        "tokens_used": tokens_used,
                    }

            except Exception:
                logging.exception("Failed to process tool response")

    return {
        "response": "The agent stopped because it reached the maximum number of iterations.",
        "prediction_id": prediction_id,
        "annotated_image": annotated_image,
        "annotated_image_url": annotated_image_url,
        "agent_loop_time_s": round(time.time() - start_time, 2),
        "iterations": iterations,
        "tools_called": tools_called,
        "context_limit_exceeded": True,
        "tokens_used": tokens_used,
    }


app = FastAPI(title="Vision Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://32.197.155.17:3000",
        "http://dev.ahmad.fursa.click:3000",
        "http://67.202.49.42:3000",
        "http://prod.ahmad.fursa.click:3000",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatMessage(BaseModel):
    role: str
    content: str
    image_base64: Optional[str] = None


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


class ChatResponse(BaseModel):
    response: str
    prediction_id: Optional[str] = None
    annotated_image: Optional[str] = None
    annotated_image_url: Optional[str] = None
    agent_loop_time_s: float
    iterations: int
    tools_called: list[str]
    context_limit_exceeded: bool = False
    tokens_used: TokenUsage


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    lc_messages = []
    latest_image = None
    latest_user_text = ""

    for msg in request.messages:
        if msg.role == "user":
            latest_user_text = msg.content
            if msg.image_base64:
                latest_image = msg.image_base64
                content = (
                    msg.content
                    + "\n[An image was uploaded. Use existing tools to analyze "
                    "it according to user instructions.]"
                )
            else:
                content = msg.content
            lc_messages.append(HumanMessage(content=content))
        else:
            lc_messages.append(AIMessage(content=msg.content))

    token = _current_image_b64.set(latest_image)
    text_token = _current_user_text.set(latest_user_text)
    try:
        direct_edit_args = _extract_direct_edit(latest_user_text)
        if latest_image and direct_edit_args is not None:
            tool_result = edit_detected_object.invoke(direct_edit_args)
            data = json.loads(tool_result)
            operation = data.get("operation", "processed")
            return ChatResponse(
                response=operation_messages.get(operation, "Processed the image."),
                annotated_image=data.get("image_base64"),
                agent_loop_time_s=0.0,
                iterations=1,
                tools_called=[edit_detected_object.name],
                context_limit_exceeded=False,
                tokens_used=TokenUsage(),
            )

        result = run_agent(lc_messages)
        return ChatResponse(**result)
    finally:
        _current_image_b64.reset(token)
        _current_user_text.reset(text_token)


@app.get("/prediction/{uid}/image")
def get_prediction_image(uid: str):
    """Proxy the annotated image from the internal YOLO service."""
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(f"{YOLO_SERVICE_URL}/prediction/{uid}/image")
    except httpx.RequestError as error:
        raise HTTPException(
            status_code=502,
            detail="The object detection service is unavailable.",
        ) from error

    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="Image not found")
    if response.is_error:
        raise HTTPException(
            status_code=502,
            detail="The object detection service could not return the image.",
        )

    content_type = response.headers.get("content-type", "image/jpeg")
    return Response(content=response.content, media_type=content_type)


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
