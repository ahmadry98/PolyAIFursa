import base64
import io
import json
import logging
import time
import os
import uuid
from s3_utils import upload_bytes_to_s3
from contextvars import ContextVar
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logging.getLogger("langchain").setLevel(logging.DEBUG)
logging.getLogger("langchain_core").setLevel(logging.DEBUG)

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
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
if MODEL not in ALLOWED_MODELS:
    allowed_list = "\n  ".join(sorted(ALLOWED_MODELS))
    raise SystemExit(
        f"\n[ERROR] MODEL='{MODEL}' is not allowed.\n"
        f"Set MODEL in your .env to one of the supported text-only models:\n  {allowed_list}\n"
    )

SYSTEM_PROMPT = (
    "You are an AI vision assistant. You help users understand and analyze images. "
    "Use the available tools to extract information from images. "
)

_current_image_b64: ContextVar[Optional[str]] = ContextVar("current_image_b64", default=None)

@tool
def detect_objects() -> str:
    """Detect and identify objects in the image provided by the user using YOLO object detection."""
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


# Registry: map tool name -> tool function
TOOLS = {
    detect_objects.name: detect_objects
}
rate_limiter = InMemoryRateLimiter(
    requests_per_second=1,
    check_every_n_seconds=0.1,
    max_bucket_size=5,
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


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
