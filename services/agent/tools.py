import asyncio
import json
import logging
from contextvars import ContextVar
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse

from langchain_core.tools import tool
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from config import IMG_PROC_MCP_URL
from image_utils import (
    _compact_detection_result,
    _crop_region,
    _detect_uploaded_image,
    _encode_image,
    _paste_region,
    _sort_detections_horizontally,
)

_current_image_b64: ContextVar[Optional[str]] = ContextVar(
    "current_image_b64",
    default=None,
)
_current_user_text: ContextVar[str] = ContextVar("current_user_text", default="")


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
    image_b64 = _current_image_b64.get()
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
                "For rotate_object, the crop was resized back into the original "
                "object bounding box after rotation."
            ),
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
