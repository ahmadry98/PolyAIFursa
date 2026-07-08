import asyncio
import json
import logging
import re
from contextvars import ContextVar
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse

from langchain_core.tools import tool
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from PIL import ImageDraw

from config import IMG_PROC_MCP_URL
from image_utils import (
    _compact_detection_result,
    _crop_region,
    _detect_uploaded_image,
    _decode_image,
    _encode_image,
    _load_image_b64_from_s3,
    _paste_region,
    _sort_detections_horizontally,
    _store_working_image,
)

_current_image_b64: ContextVar[Optional[str]] = ContextVar(
    "current_image_b64",
    default=None,
)
_working_image_b64: ContextVar[Optional[str]] = ContextVar(
    "working_image_b64",
    default=None,
)
_current_chat_id: ContextVar[Optional[str]] = ContextVar(
    "current_chat_id",
    default=None,
)

_working_s3_key: ContextVar[Optional[str]] = ContextVar(
    "working_s3_key",
    default=None,
)
_edit_step: ContextVar[int] = ContextVar("edit_step", default=0)
_current_user_text: ContextVar[str] = ContextVar("current_user_text", default="")

OBJECT_LABELS = [
    "person",
    "car",
    "dog",
    "cat",
    "bicycle",
    "bus",
    "truck",
    "bird",
    "horse",
    "sheep",
    "cow",
    "chair",
    "table",
    "bottle",
    "cup",
]

ORDINAL_WORDS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
}


def _get_image_b64() -> Optional[str]:
    working_s3_key = _working_s3_key.get()
    if working_s3_key:
        try:
            return _load_image_b64_from_s3(working_s3_key)
        except Exception:
            chat_id = _current_chat_id.get()
            if chat_id:
                return _load_image_b64_from_s3(f"processed/{chat_id}/image.png")
            raise

    return _working_image_b64.get() or _current_image_b64.get()


def _set_working_image_b64(image_b64: str) -> None:
    chat_id = _current_chat_id.get()
    working_s3_key = _working_s3_key.get()
    if chat_id and working_s3_key:
        step_number = _edit_step.get() + 1
        _edit_step.set(step_number)
        _store_working_image(
            image_b64,
            chat_id,
            working_s3_key,
            step_id=f"{step_number:03d}",
        )
        return

    _working_image_b64.set(image_b64)


def _img_proc_mcp_endpoint() -> str:
    parsed = urlparse(IMG_PROC_MCP_URL)
    if parsed.path and parsed.path != "/":
        return IMG_PROC_MCP_URL

    return urlunparse(
        parsed._replace(
            path="/mcp",
        )
    )


async def _call_img_proc_mcp(tool_name: str, arguments: dict[str, Any]) -> str:
    async with streamable_http_client(_img_proc_mcp_endpoint()) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)

    if not result.content:
        return ""

    first_content = result.content[0]
    return getattr(first_content, "text", str(first_content))


def _run_img_proc_mcp(tool_name: str, arguments: dict[str, Any]) -> str:
    return asyncio.run(_call_img_proc_mcp(tool_name, arguments))


@tool
def detect_objects() -> str:
    """Detect and identify objects in the image provided by the user using YOLO object detection."""
    image_b64 = _get_image_b64()
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


@tool
def rotate_image(angle: float) -> str:
    """Rotate the uploaded image by angle degrees. Returns JSON with image_base64."""
    image_b64 = _get_image_b64()
    if not image_b64:
        return json.dumps({"error": "No image was provided by the user."})

    processed = _run_img_proc_mcp(
        "rotate",
        {
            "image_b64": image_b64,
            "angle": angle,
        },
    )
    _set_working_image_b64(processed)

    return json.dumps(
        {
            "operation": "rotate",
            "scope": "whole_image",
            "parameters": {
                "angle": angle,
            },
            "image_base64": processed,
        }
    )


@tool
def flip_image(direction: str) -> str:
    """Flip the uploaded image. direction must be horizontal or vertical. Returns JSON with image_base64."""
    image_b64 = _get_image_b64()
    if not image_b64:
        return json.dumps({"error": "No image was provided by the user."})

    processed = _run_img_proc_mcp(
        "flip",
        {
            "image_b64": image_b64,
            "direction": direction,
        },
    )
    _set_working_image_b64(processed)

    return json.dumps(
        {
            "operation": "flip",
            "scope": "whole_image",
            "parameters": {
                "direction": direction,
            },
            "image_base64": processed,
        }
    )


@tool
def blur_image(radius: float = 2.0) -> str:
    """Blur the uploaded image. Returns JSON with image_base64."""
    image_b64 = _get_image_b64()
    if not image_b64:
        return json.dumps({"error": "No image was provided by the user."})

    processed = _run_img_proc_mcp(
        "blur",
        {
            "image_b64": image_b64,
            "radius": radius,
        },
    )
    _set_working_image_b64(processed)

    return json.dumps(
        {
            "operation": "blur",
            "scope": "whole_image",
            "parameters": {
                "radius": radius,
            },
            "image_base64": processed,
        }
    )


@tool
def resize_image(width: int, height: int) -> str:
    """Resize the uploaded image to width x height. Returns JSON with image_base64."""
    image_b64 = _get_image_b64()
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
    _set_working_image_b64(processed)

    return json.dumps(
        {
            "operation": "resize",
            "scope": "whole_image",
            "parameters": {
                "width": width,
                "height": height,
            },
            "image_base64": processed,
        }
    )


@tool
def crop_image(left: float, top: float, right: float, bottom: float) -> str:
    """Crop the uploaded image using bounding box coordinates. Returns JSON with image_base64."""
    image_b64 = _get_image_b64()
    if not image_b64:
        return json.dumps({"error": "No image was provided by the user."})

    crop_box = {
        "left": int(round(left)),
        "top": int(round(top)),
        "right": int(round(right)),
        "bottom": int(round(bottom)),
    }

    processed = _run_img_proc_mcp(
        "crop",
        {
            "image_b64": image_b64,
            **crop_box,
        },
    )
    _set_working_image_b64(processed)

    return json.dumps(
        {
            "operation": "crop",
            "scope": "whole_image",
            "parameters": crop_box,
            "image_base64": processed,
        }
    )


@tool
def add_noise_image(amount: float = 0.05) -> str:
    """Add salt-and-pepper noise to the uploaded image. Amount should be between 0 and 1."""
    image_b64 = _get_image_b64()
    if not image_b64:
        return json.dumps({"error": "No image was provided by the user."})

    processed = _run_img_proc_mcp(
        "add_noise",
        {
            "image_b64": image_b64,
            "amount": amount,
        },
    )
    _set_working_image_b64(processed)

    return json.dumps(
        {
            "operation": "add_noise",
            "scope": "whole_image",
            "parameters": {
                "amount": amount,
            },
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
    amount: float = 0.1,
) -> str:
    """Edit one detected object inside the uploaded image.

    Use this when the user asks to blur, rotate, flip, crop, or add noise to a specific detected object,
    such as "the first person", "the car on the right", or "the second dog from the left".

    The tool detects objects with YOLO, selects the requested object, crops that object,
    applies the requested image-processing operation only to that crop, pastes the edited crop
    back into the original image, and returns the full edited image. If the requested operation
    is crop, the tool returns only the selected object's cropped image.

    If operation is rotate, the rotated crop may change dimensions, so the edited crop is resized
    back into the original object's bounding box before being pasted into the full image.

    Arguments:
    - object_label: YOLO label such as person, car, dog, cat, bicycle.
    - occurrence: 1 for first/leftmost/rightmost depending on user wording, 2 for second, etc.
    - operation: one of blur, rotate, flip, crop, add_noise.
    - angle: degrees for rotate.
    - radius: blur radius for blur.
    - amount: noise amount for add_noise.

    Returns JSON with:
    - operation: one of blur_object, rotate_object, flip_object, crop_object, add_noise_object
    - image_base64: full edited image or selected object crop as base64 PNG
    """
    image_b64 = _get_image_b64()
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

    if operation == "crop":
        final_image_b64 = cropped_b64
    elif operation == "blur":
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
                "amount": amount,
            },
        )
    else:
        return json.dumps(
            {
                "error": f"Unsupported object operation: {operation}"
            }
        )

    if operation != "crop":
        final_image_b64 = _paste_region(image_b64, processed_crop_b64, safe_box)

    _set_working_image_b64(final_image_b64)

    return json.dumps(
        {
            "operation": f"{operation}_object",
            "scope": "selected_object",
            "target": {
                "object_label": object_label,
                "occurrence": occurrence,
                "selection_text": _current_user_text.get(),
                "matching_objects_found": len(sorted_detections),
            },
            "parameters": {
                "angle": angle if operation == "rotate" else None,
                "radius": radius if operation == "blur" else None,
                "amount": amount if operation == "add_noise" else None,
                "direction": "horizontal" if operation == "flip" else None,
                "box": safe_box if operation == "crop" else None,
            },
            "processing_note": (
                "For crop_object, only the selected object's cropped region is returned. "
                "For other object operations, the edited crop was pasted back into the original image. "
                "For rotate_object and flip_object, the edited crop was fitted "
                "back into the selected object's original location."
            ),
            "image_base64": final_image_b64,
        }
    )


def _clean_edit_part(part: str) -> str:
    cleaned = part.strip(" ,.")
    cleaned = re.sub(r"^\s*(?:[-*]|\d+[.)])\s+", "", cleaned)
    return cleaned.strip(" ,.")


def _split_edit_request(user_text: str) -> list[str]:
    parts = re.split(
        r"(?:\r?\n+|;|\b(?:and|then)\b)",
        user_text,
        flags=re.IGNORECASE,
    )
    cleaned_parts = [_clean_edit_part(part) for part in parts]
    return [part for part in cleaned_parts if part]


def _parse_occurrence(text: str) -> int:
    normalized = text.lower()
    for word, value in ORDINAL_WORDS.items():
        if word in normalized:
            return value

    match = re.search(r"\b(\d+)(?:st|nd|rd|th)\b", normalized)
    if match:
        return int(match.group(1))

    return 1


def _parse_object_label(text: str) -> Optional[str]:
    normalized = text.lower()
    for label in OBJECT_LABELS:
        if re.search(rf"\b{re.escape(label)}s?\b", normalized):
            return label
    return None


def _parse_number(text: str) -> Optional[float]:
    match = re.search(r"\b\d+(?:\.\d+)?\b", text)
    if not match:
        return None
    return float(match.group(0))


def _parse_edit_part(
    part: str,
    previous_tool: Optional[str],
) -> Optional[dict[str, Any]]:
    normalized = part.lower()
    tool_name = None

    if "noise" in normalized:
        tool_name = "add_noise"
    elif "blur" in normalized:
        tool_name = "blur"
    elif "rotate" in normalized:
        tool_name = "rotate"
    elif "flip" in normalized:
        tool_name = "flip"
    elif "crop" in normalized:
        tool_name = "crop"
    elif "box" in normalized or "rectangle" in normalized:
        tool_name = "draw_box"
    elif previous_tool and _parse_number(normalized) is not None:
        tool_name = previous_tool

    if tool_name is None:
        return None

    number = _parse_number(normalized)
    object_label = _parse_object_label(normalized)
    targets_whole_image = (
        object_label is None
        and ("whole image" in normalized or "entire image" in normalized)
    )

    operation: dict[str, Any] = {
        "tool": tool_name,
        "target": "whole image" if targets_whole_image else part,
        "selection_text": part,
    }

    if object_label is not None:
        operation["object_label"] = object_label
        operation["occurrence"] = _parse_occurrence(normalized)

    if tool_name == "add_noise":
        operation["amount"] = number if number is not None else 0.05
    elif tool_name == "blur":
        operation["radius"] = number if number is not None else 2.0
    elif tool_name == "rotate":
        operation["angle"] = number if number is not None else 90
    elif tool_name == "flip":
        if "vertical" in normalized:
            operation["direction"] = "vertical"
        else:
            operation["direction"] = "horizontal"
    elif tool_name == "draw_box":
        operation["color"] = "red" if "red" in normalized else "yellow"

    return operation


def plan_image_edits(user_text: str) -> list[dict[str, Any]]:
    """Build a small ordered edit plan from a natural-language request."""
    operations = []
    previous_tool = None

    for part in _split_edit_request(user_text):
        operation = _parse_edit_part(part, previous_tool)
        if operation is None:
            continue
        operations.append(operation)
        previous_tool = operation["tool"]

    return operations


def _select_detection(
    detections: list[dict[str, Any]],
    object_label: str,
    occurrence: int,
    selection_text: str,
) -> Optional[dict[str, Any]]:
    matches = [
        detection
        for detection in detections
        if detection.get("label") == object_label
    ]
    sorted_matches = _sort_detections_horizontally(matches, selection_text)
    if len(sorted_matches) < occurrence:
        return None
    return sorted_matches[occurrence - 1]


def _draw_box(image_b64: str, box: list[float], color: str) -> str:
    img = _decode_image(image_b64)
    left, top, right, bottom = [int(value) for value in box]
    draw = ImageDraw.Draw(img)
    for offset in range(3):
        draw.rectangle(
            [left - offset, top - offset, right + offset, bottom + offset],
            outline=color,
        )
    return _encode_image(img)


def _execute_whole_image_edit(image_b64: str, operation: dict[str, Any]) -> str:
    tool_name = operation["tool"]

    if tool_name == "add_noise":
        return _run_img_proc_mcp(
            "add_noise",
            {"image_b64": image_b64, "amount": operation.get("amount", 0.05)},
        )
    if tool_name == "blur":
        return _run_img_proc_mcp(
            "blur",
            {"image_b64": image_b64, "radius": operation.get("radius", 2.0)},
        )
    if tool_name == "rotate":
        return _run_img_proc_mcp(
            "rotate",
            {"image_b64": image_b64, "angle": operation.get("angle", 90)},
        )
    if tool_name == "flip":
        return _run_img_proc_mcp(
            "flip",
            {
                "image_b64": image_b64,
                "direction": operation.get("direction", "horizontal"),
            },
        )

    return image_b64


def _execute_object_edit(
    image_b64: str,
    operation: dict[str, Any],
    detections: list[dict[str, Any]],
) -> tuple[str, Optional[str]]:
    target = _select_detection(
        detections,
        operation["object_label"],
        operation.get("occurrence", 1),
        operation.get("selection_text", ""),
    )
    if target is None:
        return image_b64, f"Could not find target: {operation['target']}"

    if operation["tool"] == "draw_box":
        boxed_image_b64 = _draw_box(
            image_b64,
            target["box"],
            operation.get("color", "yellow"),
        )
        return boxed_image_b64, None

    cropped_img, safe_box = _crop_region(image_b64, target["box"])
    cropped_b64 = _encode_image(cropped_img)
    processed_crop_b64 = _execute_whole_image_edit(cropped_b64, operation)
    return _paste_region(image_b64, processed_crop_b64, safe_box), None


def execute_image_edit_plan(operations: list[dict[str, Any]]) -> dict[str, Any]:
    image_b64 = _get_image_b64()
    if not image_b64:
        return {"error": "No image was provided by the user."}

    working_image_b64 = image_b64
    detections = None
    errors = []

    for operation in operations:
        if operation.get("object_label"):
            if detections is None:
                try:
                    prediction = _detect_uploaded_image(working_image_b64)
                    detections = prediction.get("detection_objects", [])
                except ValueError as error:
                    return {"error": str(error)}
                except Exception:
                    logging.exception("Object detection request failed")
                    return {
                        "error": (
                            "The object detection service could not process the image."
                        )
                    }

            working_image_b64, error = _execute_object_edit(
                working_image_b64,
                operation,
                detections,
            )
            if error:
                errors.append(error)
        else:
            working_image_b64 = _execute_whole_image_edit(working_image_b64, operation)
            if operation["tool"] in {"rotate", "flip", "resize", "crop"}:
                detections = None

        _set_working_image_b64(working_image_b64)

    return {
        "operation": "multi_edit",
        "scope": "sequential_edits",
        "operations": operations,
        "errors": errors,
        "image_base64": working_image_b64,
    }


def run_multi_edit_request() -> Optional[dict[str, Any]]:
    user_text = _current_user_text.get()
    if not _get_image_b64() or not user_text:
        return None

    operations = plan_image_edits(user_text)
    if len(operations) < 2:
        return None

    return execute_image_edit_plan(operations)


@tool
def apply_image_edit_plan() -> str:
    """Parse and execute multiple image edits from the user's current message."""
    result = run_multi_edit_request()
    if result is None:
        return json.dumps(
            {"error": "Could not find multiple image-edit operations to run."}
        )
    return json.dumps(result)


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
    apply_image_edit_plan.name: apply_image_edit_plan,
}
