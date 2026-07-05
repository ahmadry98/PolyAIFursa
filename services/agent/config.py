import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.rate_limiters import InMemoryRateLimiter

load_dotenv()

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
    "For whole-image requests that ask to rotate, flip, blur, resize, crop, "
    "or add noise, use the matching whole-image processing tool. "
    "For object-specific edit requests, use edit_detected_object. "
    "If the user says 'person on the left' or 'person on the right', call "
    'edit_detected_object with object_label="person", occurrence=1, and the '
    "operation that matches the requested edit. "
    "Do not refuse blur, rotate, flip, or add_noise requests on detected objects. "
    "After an image-processing tool succeeds, write a helpful 2-3 sentence "
    "explanation using the sanitized tool result details. Mention the edit, "
    "target or scope, and important parameters such as angle, blur radius, "
    "noise amount, resize dimensions, or crop region when available. "
    "If the operation was applied to a detected object, mention that only the "
    "selected object was changed and identify the selected object in natural language. "
    "If operation is rotate_object, mention that rotating a cropped object may "
    "change its dimensions, so it was resized back into the original bounding box. "
    "Never include base64, markdown image syntax, or internal IDs in the final answer. "
    "The frontend will display the processed image automatically."
)

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

    from tools import TOOLS

    llm_with_tools = llm.bind_tools(list(TOOLS.values()))
    return llm_with_tools
