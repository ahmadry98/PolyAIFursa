import base64
import binascii
import json
import logging
import time
import os
import re
import uuid
from contextvars import ContextVar
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

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
from pydantic import BaseModel

YOLO_SERVICE_URL = os.environ.get("YOLO_SERVICE_URL", "http://localhost:8080")
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
SYSTEM_PROMPT = (
    "You are an AI vision assistant. You help users understand and analyze images. "
    "When the user uploads an image, call detect_objects before answering. "
    "Use the tool result to answer the user's question. "
    "Report object counts exactly as provided in label_counts. "
)

_current_image_b64: ContextVar[Optional[str]] = ContextVar(
    "current_image_b64",
    default=None,
)


@tool
def detect_objects() -> str:
    """Detect and identify objects in the image provided by the user using YOLO object detection."""
    image_b64 = _current_image_b64.get()
    if not image_b64:
        return json.dumps({"error": "No image was provided by the user."})

    try:
        image_bytes = base64.b64decode(image_b64, validate=True)
    except (binascii.Error, ValueError, TypeError):
        return json.dumps({"error": "The uploaded image is not valid base64 data."})

    if image_bytes.startswith(b"\xff\xd8\xff"):
        image_name = "image.jpg"
        content_type = "image/jpeg"
    elif image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        image_name = "image.png"
        content_type = "image/png"
    else:
        return json.dumps({"error": "Only JPEG and PNG images are supported."})

    chat_id = str(uuid.uuid4())
    prediction_id = str(uuid.uuid4())

    original_key = f"{chat_id}/{prediction_id}/original/{image_name}"

    try:
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
    except Exception:
        logging.exception("Object detection request failed")
        return json.dumps(
            {"error": "The object detection service could not process the image."}
        )

    result = response.json()
    labels = result.get("labels", [])
    label_counts = {}
    for label in labels:
        label_counts[label] = label_counts.get(label, 0) + 1

    return json.dumps(
        {
            "uid": result.get("uid"),
            "detection_count": result.get("detection_count", len(labels)),
            "labels": labels,
            "label_counts": label_counts,
        }
    )


# Registry: map tool name -> tool function
TOOLS = {
    detect_objects.name: detect_objects
}
rate_limiter = InMemoryRateLimiter(
    requests_per_second=5,
    check_every_n_seconds=0.1,
    max_bucket_size=10,
)
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
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
                content,
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
    role: str  # "user" or "assistant"
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

    for msg in request.messages:
        if msg.role == "user":
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
