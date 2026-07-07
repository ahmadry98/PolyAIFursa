import json
import logging
import re
import time

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

import config
from image_utils import _remove_none_values, _store_processed_image
from schemas import TokenUsage
from tools import TOOLS, run_multi_edit_request


def _store_tool_image_result(data: dict) -> tuple[str | None, dict]:
    processed_image_b64 = data.get("image_base64")
    if not processed_image_b64:
        return None, data

    annotated_image_url = _store_processed_image(processed_image_b64)
    operation = data.get("operation", "processed")
    sanitized_data = {
        key: value
        for key, value in data.items()
        if key != "image_base64"
    }
    sanitized_data.update(
        {
            "operation": operation,
            "status": "success",
            "image_returned": True,
            "result": (
                "The processed image was stored and will be displayed by the frontend."
            ),
            "response_guidance": (
                "Use these details to explain the edit naturally. "
                "Do not mention storage, URLs, base64, or internal IDs."
            ),
        }
    )
    return annotated_image_url, _remove_none_values(sanitized_data)


def run_agent(history: list, max_iterations: int = 10):
    """
    Simple ReAct loop with max_iterations guard.
    Returns final assistant text and image metadata when a tool produces one.
    """
    messages = [SystemMessage(content=config.SYSTEM_PROMPT)] + history
    start_time = time.time()

    annotated_image_url = None
    annotated_image = None
    prediction_id = None
    tools_called = []
    iterations = 0
    tokens_used = TokenUsage()
    context_limit_exceeded = False

    multi_edit_result = run_multi_edit_request()
    if multi_edit_result is not None:
        if multi_edit_result.get("error"):
            response = multi_edit_result["error"]
            annotated_image_url = None
        else:
            annotated_image_url, _ = _store_tool_image_result(multi_edit_result)
            operations = multi_edit_result.get("operations", [])
            response = f"I applied {len(operations)} edits to the image."

            errors = multi_edit_result.get("errors", [])
            if errors:
                response += " Some requested edits could not be completed: "
                response += "; ".join(errors)

        return {
            "response": response,
            "prediction_id": prediction_id,
            "annotated_image": annotated_image,
            "annotated_image_url": annotated_image_url,
            "agent_loop_time_s": round(time.time() - start_time, 2),
            "iterations": iterations,
            "tools_called": ["apply_image_edit_plan"],
            "context_limit_exceeded": context_limit_exceeded,
            "tokens_used": tokens_used,
        }

    model = config.get_llm_with_tools()

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
            config.MAX_INPUT_TOKENS is not None
            and tokens_used.input > config.MAX_INPUT_TOKENS * 0.9
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

            try:
                data = json.loads(tool_result.content)
            except Exception:
                logging.exception("Failed to process tool response")
                messages.append(tool_result)
                continue

            uid = data.get("uid") or data.get("prediction_uid")
            if uid:
                prediction_id = uid
                annotated_image_url = f"/prediction/{uid}/image"

            processed_image_b64 = data.get("image_base64")
            if processed_image_b64:
                annotated_image = None
                annotated_image_url, sanitized_data = _store_tool_image_result(data)
                messages.append(
                    ToolMessage(
                        content=json.dumps(sanitized_data),
                        tool_call_id=tool_call["id"],
                    )
                )
                continue

            messages.append(tool_result)

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
