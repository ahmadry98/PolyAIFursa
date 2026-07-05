import base64
import binascii
import io
import uuid
from typing import Any

import httpx
from PIL import Image

from config import YOLO_SERVICE_URL
from s3_utils import upload_bytes_to_s3


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


def _store_processed_image(image_b64: str) -> str:
    try:
        image_bytes = base64.b64decode(image_b64, validate=True)
    except (binascii.Error, ValueError, TypeError) as error:
        raise ValueError("The processed image is not valid base64 data.") from error

    image_id = str(uuid.uuid4())
    key = f"processed/{image_id}/image.png"
    upload_bytes_to_s3(
        data=image_bytes,
        key=key,
        content_type="image/png",
    )
    return f"/processed/{image_id}/image"


def _remove_none_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _remove_none_values(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, list):
        return [_remove_none_values(item) for item in value]
    return value


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
