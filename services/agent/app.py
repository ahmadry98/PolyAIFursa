from dotenv import load_dotenv
load_dotenv()
import base64
import binascii
import json
import logging
import time
import os
import re
import uuid
import asyncio
from pathlib import Path
from typing import Any
from s3_utils import upload_bytes_to_s3
from contextvars import ContextVar
from typing import Optional



from s3_utils import upload_bytes_to_s3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logging.getLogger("langchain").setLevel(logging.DEBUG)
logging.getLogger("langchain_core").setLevel(logging.DEBUG)

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_core.rate_limiters import InMemoryRateLimiter
from PIL import Image
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import BaseModel

YOLO_SERVICE_URL = os.environ.get("YOLO_SERVICE_URL", "http://localhost:8080")
IMG_PROC_MCP_SCRIPT = os.environ.get(
    "IMG_PROC_MCP_SCRIPT",
    str(Path(__file__).resolve().parents[1] / "img-proc-mcp" / "img_proc_app.py"),

)
MODEL = os.environ.get("MODEL")

# Text-only models
ALLOWED_MODELS = {
    "bedrock/openai.gpt-oss-20b-1:0",
    "bedrock/anthropic.claude-3-haiku-20240307-v1:0",
    "bedrock/amazon.nova-micro-v1:0",
    "bedrock/amazon.nova-lite-v1:0",
    "bedrock/meta.llama3-1-8b-instruct-v1:0",
    "bedrock/mistral.mistral-7b-instruct-v0:2",
}
if MODEL not in ALLOWED_MODELS:
    allowed_list = "\n  ".join(sorted(ALLOWED_MODELS))
    raise SystemExit(
        f"\n[ERROR] MODEL='{MODEL}' is not allowed.\n"
        f"Set MODEL in your .env to one of the supported text-only models:\n  {allowed_list}\n"
    )

SYSTEM_PROMPT = (
    "You are an AI vision assistant. "
    "You help users understand, analyze, and edit images. "
    "Use the available tools whenever needed. "
    "For requests that ask what is in an image, identify objects, count objects, "
    "or locate objects, use the object detection tool. "
    "For requests that ask to rotate, flip, blur, resize, crop, or add noise to an image, "
    "use the appropriate image-processing tool. "
    "When an image-processing tool returns an image, do not include the base64 string "
    "or markdown image syntax in your response. "
    "Reply with one short sentence describing what you did. "
    "The frontend will display the processed image automatically."
)

_current_image_b64: ContextVar[Optional[str]] = ContextVar("current_image_b64", default=None)

@tool
def detect_objects() -> str:
    """Detect and identify objects in the image provided by the user using YOLO object detection."""
    print(">>> detect_objects called")
    image_b64 = _current_image_b64.get()
    if not image_b64:
        return json.dumps({"error": "No image was provided by the user."})

    image_bytes = base64.b64decode(image_b64)

    chat_id = str(uuid.uuid4())
    prediction_id = str(uuid.uuid4())
    image_name = "image.jpg"

    original_key = f"{chat_id}/{prediction_id}/original/{image_name}"

    upload_bytes_to_s3(
        data=image_bytes,
        key=original_key,
        content_type="image/jpeg",
    )

    with httpx.Client(timeout=60.0) as client:
        response = client.post(
            f"{YOLO_SERVICE_URL}/predict",
            json={
                "image_s3_key": original_key,
                "chat_id": chat_id,
                "prediction_id": prediction_id,
                "image_name": image_name,
            },
        )
        response.raise_for_status()

    return json.dumps(response.json())
async def _call_img_proc_mcp(tool_name: str, arguments: dict[str, Any]) -> str:
    server_params = StdioServerParameters(
        command="python",
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


def _crop_region(image_b64: str, box: list[float]) -> tuple[Image.Image, tuple[int, int, int, int]]:
    img = _decode_image(image_b64)

    left, top, right, bottom = [int(v) for v in box]
    left = max(0, left)
    top = max(0, top)
    right = min(img.width, right)
    bottom = min(img.height, bottom)

    cropped = img.crop((left, top, right, bottom))
    return cropped, (left, top, right, bottom)


def _paste_region(original_b64: str, region_b64: str, box: tuple[int, int, int, int]) -> str:
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

    return json.dumps({
        "operation": "rotate",
        "image_base64": processed,
    })
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

    return json.dumps({
        "operation": "flip",
        "image_base64": processed,
    })


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

    return json.dumps({
        "operation": "blur",
        "image_base64": processed,
    })
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

    return json.dumps({
        "operation": "resize",
        "image_base64": processed,
    })
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

    return json.dumps({
        "operation": "crop",
        "image_base64": processed,
    })
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

    return json.dumps({
        "operation": "add_noise",
        "image_base64": processed,
    })
@tool
def edit_detected_object(
    object_label: str,
    occurrence: int,
    operation: str,
    angle: float = 90,
    radius: float = 2,
) -> str:
    """Edit a detected object in the uploaded image. Returns JSON with image_base64."""
    print(">>> edit_detected_object called")
    image_b64 = _current_image_b64.get()
    if not image_b64:
        return json.dumps({"error": "No image was provided by the user."})

    image_bytes = base64.b64decode(image_b64)

    chat_id = str(uuid.uuid4())
    prediction_id = str(uuid.uuid4())
    image_name = "image.jpg"

    original_key = f"{chat_id}/{prediction_id}/original/{image_name}"
    import boto3

    sts = boto3.client("sts")

    print(sts.get_caller_identity())
    upload_bytes_to_s3(
        data=image_bytes,
        key=original_key,
        content_type="image/jpeg",
    )

    with httpx.Client(timeout=60.0) as client:
        response = client.post(
            f"{YOLO_SERVICE_URL}/predict",
            json={
                "image_s3_key": original_key,
                "chat_id": chat_id,
                "prediction_id": prediction_id,
                "image_name": image_name,
            },
        )
        response.raise_for_status()

    prediction = response.json()
    detections = [
    d
    for d in prediction["detection_objects"]
    if d["label"] == object_label
    ]

    if len(detections) < occurrence:
        return json.dumps({
            "error": f"Could not find {occurrence} '{object_label}' objects."
    })

    target = detections[occurrence - 1]
    box = target["box"]

    cropped_img, safe_box = _crop_region(image_b64, box)
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
        return json.dumps({
            "error": f"Unsupported object operation: {operation}"
        })

    final_image_b64 = _paste_region(image_b64, processed_crop_b64, safe_box)

    return json.dumps({
        "operation": f"{operation}_object",
        "image_base64": final_image_b64,
    })
# Registry: map tool name -> tool function
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
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
llm = init_chat_model(

    MODEL.replace("bedrock/", ""),

    model_provider="bedrock_converse",

    temperature=0,

    rate_limiter=rate_limiter,

    region_name=AWS_REGION,

)
MODEL_PROFILE = llm.profile or {}

if not MODEL_PROFILE.get("tool_calling"):
    raise SystemExit(
        f"[ERROR] MODEL='{MODEL}' does not support tool calling."
    )

if not MODEL_PROFILE.get("structured_output"):
    raise SystemExit(
        f"[ERROR] MODEL='{MODEL}' does not support structured output."
    )

MAX_INPUT_TOKENS = MODEL_PROFILE.get("max_input_tokens")

if MAX_INPUT_TOKENS is None:
    logging.warning(
        "Model profile does not expose max_input_tokens; context limit checks will be skipped."
    )
else:
    logging.info(f"Model max_input_tokens: {MAX_INPUT_TOKENS}")
llm_with_tools = llm.bind_tools(list(TOOLS.values()))
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

class TokenUsage(BaseModel):
    input: int = 0
    output: int = 0
    total: int = 0

def run_agent(history: list, max_iterations: int = 10):
    """
    Simple ReAct loop with max_iterations guard.
    Returns:
      - final assistant text
      - annotated image URL, if YOLO was used
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
    for iteration in range(max_iterations):
        iterations = iteration + 1
        response: AIMessage = llm_with_tools.invoke(messages)
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
                predicted_image_path = data.get("predicted_image")

                if uid:
                    prediction_id = uid
                    annotated_image_url = (
                        f"{YOLO_SERVICE_URL}/prediction/{uid}/image"
                    )

                if predicted_image_path:
                    annotated_image_url = predicted_image_path
                processed_image_b64 = data.get("image_base64")
                if processed_image_b64:
                    annotated_image = processed_image_b64

                    operation = data.get("operation", "processed")
                    return {
                        "response": operation_messages.get(operation, "Processed the image."),
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
                logging.exception(
                    "Failed to process YOLO response or annotated image"
                )


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
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatMessage(BaseModel):
    role: str                           # "user" or "assistant"
    content: str
    image_base64: Optional[str] = None  # only on user messages that carry an image


class ChatRequest(BaseModel):
    messages: list[ChatMessage]         # full conversation thread, oldest first





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

    for msg in request.messages:
        if msg.role == "user":
            if msg.image_base64:
                latest_image = msg.image_base64          # saved for detect_objects tool
                content = msg.content + "\n[An image was uploaded. Use existing tools to analyze it according to user instructions.]"
            else:
                content = msg.content
            lc_messages.append(HumanMessage(content=content))
        else:
            lc_messages.append(AIMessage(content=msg.content))

    token = _current_image_b64.set(latest_image)
    try:
        result = run_agent(lc_messages)
        return ChatResponse(**result)
    finally:
        _current_image_b64.reset(token)


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
