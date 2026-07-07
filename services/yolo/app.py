from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from prometheus_fastapi_instrumentator import Instrumentator
from ultralytics import YOLO
from PIL import Image
import logging
import os
import uuid
import time
import signal
from s3_utils import download_bytes_from_s3, upload_file_to_s3
import sys
from pydantic import BaseModel
from sqlalchemy.orm import Session

import database
from database import get_db
from repositories import (
    add_prediction,
    find_detections_by_score,
    find_prediction,
    find_predictions_by_label,
)
# Configure logging so the app prints useful information while running
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Disable GPU usage and force YOLO to run on CPU
import torch
torch.cuda.is_available = lambda: False

# Create the FastAPI application

app = FastAPI()


class DetectionObjectResponse(BaseModel):
    id: int
    label: str
    score: float
    box: list[float]


class PredictionResponse(BaseModel):
    uid: str
    timestamp: str
    original_image: str
    predicted_image: str
    detection_objects: list[DetectionObjectResponse]
    detection_count: int
    labels: list[str]
    time_took: float


@app.on_event("startup")
def startup_event():
    database.Base.metadata.create_all(bind=database.engine)


@app.on_event("shutdown")
def shutdown_event():
    logging.info("Received SIGTERM - shutting down gracefully")


logging.basicConfig(level=logging.INFO)


def graceful_shutdown(signum, frame):
    logging.info("Received SIGTERM - shutting down gracefully")
    sys.exit(0)


signal.signal(signal.SIGTERM, graceful_shutdown)
# Add Prometheus metrics endpoint at /metrics
Instrumentator().instrument(app).expose(app)


def get_confidence_threshold():
    """
    Read the confidence threshold from an environment variable.
    If it is not set, use the default value 0.5.
    """
    raw_threshold = os.environ.get("CONFIDENCE_THRESHOLD")

    if raw_threshold is not None:
        threshold = float(raw_threshold)
        logging.info(f"CONFIDENCE_THRESHOLD set to {threshold} (from environment)")
        return threshold

    logging.info("CONFIDENCE_THRESHOLD not set, using default: 0.5")
    return 0.5


def format_timestamp(timestamp: datetime) -> str:
    """Serialize a database timestamp as RFC 3339 UTC."""
    if timestamp.tzinfo is None:
        # SQLite may return a naive datetime even for DateTime(timezone=True).
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    utc_timestamp = timestamp.astimezone(timezone.utc)
    return utc_timestamp.isoformat().replace("+00:00", "Z")


# Global configuration
CONFIDENCE_THRESHOLD = get_confidence_threshold()
UPLOAD_DIR = "uploads/original"
PREDICTED_DIR = "uploads/predicted"

# Create folders for uploaded and predicted images if they do not exist
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(PREDICTED_DIR, exist_ok=True)

# Load the YOLOv8 nano model once when the app starts
model = YOLO("yolov8n.pt")


@app.post("/predict", response_model=PredictionResponse)
def predict(
    db: Session = Depends(get_db),
    image_s3_key: str | None = None,
    file: UploadFile | None = File(default=None),
):
    """
    Run object detection from either the original multipart upload or an S3 key.

    The optional image_s3_key query parameter is used by the agent. Multipart
    uploads keep the original /predict API contract.
    """
    start_time = time.time()

    allowed_extensions = [".jpg", ".jpeg", ".png"]

    if image_s3_key is None and file is None:
        raise HTTPException(
            status_code=400,
            detail="Provide an image file or image_s3_key",
        )

    if image_s3_key is not None and file is not None:
        raise HTTPException(
            status_code=400,
            detail="Provide either an image file or image_s3_key, not both",
        )

    if image_s3_key is not None:
        key_parts = image_s3_key.split("/")
        if len(key_parts) != 4 or key_parts[2] != "original":
            raise HTTPException(
                status_code=400,
                detail="image_s3_key must use chat/prediction/original/filename",
            )

        chat_id = key_parts[0]
        uid = key_parts[1]
        image_name = key_parts[3]
    else:
        assert file is not None
        chat_id = None
        uid = str(uuid.uuid4())
        image_name = file.filename or ""

    ext = os.path.splitext(image_name)[1].lower()

    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail="Only image files are supported"
        )

    original_path = os.path.join(UPLOAD_DIR, uid + ext)
    predicted_path = os.path.join(PREDICTED_DIR, uid + ext)

    if image_s3_key is not None:
        image_bytes = download_bytes_from_s3(image_s3_key)
        with open(original_path, "wb") as image_file:
            image_file.write(image_bytes)
        original_image_value = image_s3_key
    else:
        with open(original_path, "wb") as image_file:
            image_file.write(file.file.read())
        original_image_value = original_path

    # Run YOLO prediction on CPU
    results = model(original_path, device="cpu", conf=CONFIDENCE_THRESHOLD)

    # Create annotated image with bounding boxes
    annotated_frame = results[0].plot()
    annotated_image = Image.fromarray(annotated_frame)
    annotated_image.save(predicted_path)

    if image_s3_key is not None:
        predicted_key = f"{chat_id}/{uid}/predicted/{image_name}"
        content_type = "image/png" if ext == ".png" else "image/jpeg"
        upload_file_to_s3(predicted_path, predicted_key, content_type)
        predicted_image_value = predicted_key
    else:
        predicted_image_value = predicted_path

    detected_labels = []
    detection_objects = []
    detections_to_save = []
    for box in results[0].boxes:
        label_idx = int(box.cls[0].item())
        label = model.names[label_idx]
        score = float(box.conf[0])
        bbox = box.xyxy[0].tolist()

        detected_labels.append(label)
        detections_to_save.append(
            {
                "label": label,
                "score": score,
                "box": bbox,
            }
        )

        detection_objects.append(
            DetectionObjectResponse(
                id=len(detection_objects),
                label=label,
                score=score,
                box=bbox,
            )
        )

    # Store the session and all of its objects in one transaction.
    prediction = add_prediction(
        db,
        uid,
        original_image_value,
        predicted_image_value,
        detections_to_save,
    )
    # Calculate total processing time
    processing_time = round(time.time() - start_time, 2)

    return PredictionResponse(
        uid=uid,
        timestamp=format_timestamp(prediction.timestamp),
        original_image=original_image_value,
        predicted_image=predicted_image_value,
        detection_objects=detection_objects,
        detection_count=len(detection_objects),
        labels=detected_labels,
        time_took=processing_time,
    )


@app.get("/prediction/{uid}")
def get_prediction_by_uid(uid: str, db: Session = Depends(get_db)):
    """
    Return one prediction session by UID,
    including all detected objects.
    """
    prediction = find_prediction(db, uid)
    if prediction is None:
        raise HTTPException(status_code=404, detail="Prediction not found")

    return {
        "uid": prediction.uid,
        "timestamp": format_timestamp(prediction.timestamp),
        "original_image": prediction.original_image,
        "predicted_image": prediction.predicted_image,
        "detection_objects": [
            {
                "id": detection.id,
                "label": detection.label,
                "score": detection.score,
                "box": detection.box,
            }
            for detection in prediction.detection_objects
        ],
    }


@app.get("/prediction/{uid}/image")
def get_prediction_image(uid: str, db: Session = Depends(get_db)):
    """
    Return the annotated image for a prediction.
    """
    prediction = find_prediction(db, uid)
    if prediction is None:
        raise HTTPException(status_code=404, detail="Image not found")

    if os.path.exists(prediction.predicted_image):
        return FileResponse(prediction.predicted_image)

    key_parts = prediction.predicted_image.split("/")
    if len(key_parts) != 4 or key_parts[2] != "predicted":
        raise HTTPException(status_code=404, detail="Image not found")

    try:
        image_bytes = download_bytes_from_s3(prediction.predicted_image)
    except Exception:
        logging.exception("Could not download predicted image from S3")
        raise HTTPException(status_code=404, detail="Image not found")

    extension = os.path.splitext(prediction.predicted_image)[1].lower()
    media_type = "image/png" if extension == ".png" else "image/jpeg"
    return Response(content=image_bytes, media_type=media_type)


@app.get("/predictions/label/")
def get_predictions_by_empty_label():
    """
    Handle empty label requests.
    Example: /predictions/label/
    """
    raise HTTPException(status_code=400, detail="Label cannot be empty")


@app.get("/predictions/label/{label}")
def get_predictions_by_label(label: str, db: Session = Depends(get_db)):
    """
    Return all prediction sessions that contain at least one object
    with the requested label.
    Example: /predictions/label/person
    """
    if label.strip() == "":
        raise HTTPException(status_code=400, detail="Label cannot be empty")

    predictions = find_predictions_by_label(db, label)
    return [
        {
            "uid": prediction.uid,
            "timestamp": format_timestamp(prediction.timestamp),
            "detection_objects": [
                {
                    "id": detection.id,
                    "label": detection.label,
                    "score": detection.score,
                    "box": detection.box,
                }
                for detection in prediction.detection_objects
            ],
        }
        for prediction in predictions
    ]


@app.get("/predictions/score/{min_score}")
def get_predictions_by_score(min_score: float, db: Session = Depends(get_db)):
    """
    Return all detected objects whose confidence score
    is greater than or equal to min_score.
    Example: /predictions/score/0.8
    """
    if min_score < 0.0 or min_score > 1.0:
        raise HTTPException(
            status_code=400,
            detail="min_score must be between 0.0 and 1.0"
        )

    detections = find_detections_by_score(db, min_score)
    return [
        {
            "id": detection.id,
            "prediction_uid": detection.prediction_uid,
            "label": detection.label,
            "score": detection.score,
            "box": detection.box,
        }
        for detection in detections
    ]


@app.get("/health")
def health():
    """
    Health check endpoint.
    Used to verify that the API is running.
    """
    return {"status": "ok"}


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    # Run the FastAPI server on port 8080
    uvicorn.run(app, host="0.0.0.0", port=8080)# deploy test
