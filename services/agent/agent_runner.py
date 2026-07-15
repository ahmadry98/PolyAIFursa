import json
import logging
import re
import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

import config
from image_utils import _remove_none_values, _store_processed_image
from schemas import TokenUsage
from tools import TOOLS, _current_chat_id, run_multi_edit_request


def _store_tool_image_result(data: dict) -> tuple[str | None, dict]:
    processed_image_b64 = data.get("image_base64")
    if not processed_image_b64:
        return None, data

    chat_id = data.get("chat_id") or _current_chat_id.get()
    if chat_id:
        annotated_image_url = f"/processed/{chat_id}/image"
    else:
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


def _describe_edit_target(operation: dict) -> str:
    if operation.get("target") == "whole image":
        return "the whole image"

    object_label = operation.get("object_label")
    if object_label:
        selection_text = operation.get("selection_text", "").lower()
        if "right" in selection_text:
            return f"the {object_label} on the right"
        if "left" in selection_text:
            return f"the {object_label} on the left"

        occurrence = operation.get("occurrence", 1)
        if occurrence == 1:
            return f"the selected {object_label}"
        return f"the selected {object_label} #{occurrence}"

    return "the image"


def _describe_edit_operation(operation: dict) -> str:
    tool_name = operation.get("tool", "edit")
    target = _describe_edit_target(operation)

    if tool_name == "add_noise":
        amount = operation.get("amount", 0.05)
        return f"added {amount} noise to {target}"
    if tool_name == "blur":
        radius = operation.get("radius", 2.0)
        return f"blurred {target} with radius {radius}"
    if tool_name == "rotate":
        angle = operation.get("angle", 90)
        return f"rotated {target} by {angle} degrees"
    if tool_name == "flip":
        direction = operation.get("direction", "horizontal")
        return f"flipped {target} {direction}ly"
    if tool_name == "draw_box":
        color = operation.get("color", "yellow")
        return f"drew a {color} box around {target}"
    if tool_name == "crop":
        return f"cropped {target}"

    return f"edited {target}"


def _format_multi_edit_response(operations: list[dict]) -> str:
    if not operations:
        return "I applied the requested edits to the image."

    descriptions = [
        _describe_edit_operation(operation)
        for operation in operations
    ]

    if len(descriptions) == 1:
        return f"I {descriptions[0]}."

    return (
        f"I applied {len(descriptions)} edits: "
        + "; ".join(descriptions)
        + "."
    )


def _content_to_text(content) -> str:
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )

    return str(content)


def _clean_model_text(content) -> str:
    text = _content_to_text(content)
    return re.sub(
        r"<thinking>.*?</thinking>\s*",
        "",
        text,
        flags=re.DOTALL,
    ).strip()


def _generate_edit_response_with_llm(
    messages: list,
    sanitized_data: dict,
    fallback_response: str,
) -> str:
    prompt = HumanMessage(
        content=(
            "The image edits have already been completed successfully. "
            "Write a friendly, informative 2-3 sentence response for the user. "
            "Mention what changed, which objects or image areas were targeted, "
            "and any important parameters like angle, blur radius, or noise amount. "
            "Do not call tools. Do not mention base64, S3, storage keys, URLs, "
            "JSON, internal IDs, or backend implementation details.\n\n"
            f"Completed edit summary:\n{json.dumps(sanitized_data)}"
        )
    )

    try:
        response: AIMessage = config.get_llm_with_tools().invoke(messages + [prompt])
    except Exception:
        logging.exception("Failed to generate edit response with LLM")
        return fallback_response

    if response.tool_calls:
        return fallback_response

    content = _clean_model_text(response.content)
    return content or fallback_response


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
            annotated_image_url, sanitized_data = _store_tool_image_result(
                multi_edit_result
            )
            operations = multi_edit_result.get("operations", [])
            response = _generate_edit_response_with_llm(
                messages,
                sanitized_data,
                _format_multi_edit_response(operations),
            )

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
            content = _clean_model_text(response.content)

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
