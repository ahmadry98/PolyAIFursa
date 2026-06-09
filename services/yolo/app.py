from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import FileResponse, Response
from prometheus_fastapi_instrumentator import Instrumentator
from ultralytics import YOLO
from PIL import Image
import sqlite3
import logging
import os
import uuid
import shutil
import time

# Configure logging so the app prints useful information while running
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Disable GPU usage and force YOLO to run on CPU
import torch
torch.cuda.is_available = lambda: False

# Create the FastAPI application
app = FastAPI()

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


# Global configuration
CONFIDENCE_THRESHOLD = get_confidence_threshold()
UPLOAD_DIR = "uploads/original"
PREDICTED_DIR = "uploads/predicted"
DB_PATH = "predictions.db"

# Create folders for uploaded and predicted images if they do not exist
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(PREDICTED_DIR, exist_ok=True)

# Load the YOLOv8 nano model once when the app starts
model = YOLO("yolov8n.pt")


def init_db():
    """
    Initialize the SQLite database.
    Creates the required tables and indexes if they do not already exist.
    """
    with sqlite3.connect(DB_PATH) as conn:

        # Table for storing each prediction request/session
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prediction_sessions (
                uid TEXT PRIMARY KEY,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                original_image TEXT,
                predicted_image TEXT
            )
        """)

        # Table for storing each detected object from a prediction
        conn.execute("""
            CREATE TABLE IF NOT EXISTS detection_objects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prediction_uid TEXT,
                label TEXT,
                score REAL,
                box TEXT,
                FOREIGN KEY (prediction_uid) REFERENCES prediction_sessions (uid)
            )
        """)

        # Indexes make search queries faster
        conn.execute("CREATE INDEX IF NOT EXISTS idx_prediction_uid ON detection_objects (prediction_uid)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_label ON detection_objects (label)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_score ON detection_objects (score)")


def save_prediction_session(uid, original_image, predicted_image):
    """
    Save one prediction session to the database.
    A session represents one uploaded image.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO prediction_sessions (uid, original_image, predicted_image)
            VALUES (?, ?, ?)
        """, (uid, original_image, predicted_image))


def save_detection_object(prediction_uid, label, score, box):
    """
    Save one detected object to the database.
    Each object belongs to a prediction session.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO detection_objects (prediction_uid, label, score, box)
            VALUES (?, ?, ?, ?)
        """, (prediction_uid, label, score, str(box)))


@app.post("/predict")
def predict(file: UploadFile = File(...)):
    """
    Upload an image, run YOLO object detection, save the result,
    and return prediction details.
    """
    start_time = time.time()

    # Extract file extension, for example: .jpg or .png
    ext = os.path.splitext(file.filename)[1]
    print(ext)

    # Generate unique ID for this prediction
    uid = str(uuid.uuid4())

    # Only allow image files
    allowed_extensions = [".jpg", ".jpeg", ".png"]

    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail="Only image files are supported"
        )

    # Build paths for original and predicted images
    original_path = os.path.join(UPLOAD_DIR, uid + ext)
    predicted_path = os.path.join(PREDICTED_DIR, uid + ext)

    # Save uploaded image to disk
    with open(original_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Run YOLO prediction on CPU
    results = model(original_path, device="cpu", conf=CONFIDENCE_THRESHOLD)

    # Create annotated image with bounding boxes
    annotated_frame = results[0].plot()
    annotated_image = Image.fromarray(annotated_frame)
    annotated_image.save(predicted_path)

    # Save prediction session in database
    save_prediction_session(uid, original_path, predicted_path)

    # Save each detected object in the database
    detected_labels = []

    for box in results[0].boxes:
        label_idx = int(box.cls[0].item())
        label = model.names[label_idx]
        score = float(box.conf[0])
        bbox = box.xyxy[0].tolist()

        save_detection_object(uid, label, score, bbox)

        detected_labels.append(label)

    # Calculate total processing time
    processing_time = round(time.time() - start_time, 2)

    return {
        "prediction_uid": uid,
        "detection_count": len(results[0].boxes),
        "labels": detected_labels,
        "time_took": processing_time
    }


@app.get("/prediction/{uid}")
def get_prediction_by_uid(uid: str):
    """
    Return one prediction session by UID,
    including all detected objects.
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        # Find the prediction session
        session = conn.execute(
            "SELECT * FROM prediction_sessions WHERE uid = ?",
            (uid,)
        ).fetchone()

        if not session:
            raise HTTPException(status_code=404, detail="Prediction not found")

        # Get all objects connected to this prediction
        objects = conn.execute(
            "SELECT * FROM detection_objects WHERE prediction_uid = ?",
            (uid,)
        ).fetchall()

        return {
            "uid": session["uid"],
            "timestamp": session["timestamp"],
            "original_image": session["original_image"],
            "predicted_image": session["predicted_image"],
            "detection_objects": [
                {
                    "id": obj["id"],
                    "label": obj["label"],
                    "score": obj["score"],
                    "box": obj["box"]
                }
                for obj in objects
            ]
        }


@app.get("/prediction/{uid}/image")
def get_prediction_image(uid: str):
    """
    Return the annotated image for a prediction.
    """
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT predicted_image FROM prediction_sessions WHERE uid = ?",
            (uid,)
        ).fetchone()

    # If prediction does not exist or image file is missing, return 404
    if not row or not os.path.exists(row[0]):
        raise HTTPException(status_code=404, detail="Image not found")

    return FileResponse(row[0])


@app.get("/predictions/label/")
def get_predictions_by_empty_label():
    """
    Handle empty label requests.
    Example: /predictions/label/
    """
    raise HTTPException(status_code=400, detail="Label cannot be empty")


@app.get("/predictions/label/{label}")
def get_predictions_by_label(label: str):
    """
    Return all prediction sessions that contain at least one object
    with the requested label.
    Example: /predictions/label/person
    """
    if label.strip() == "":
        raise HTTPException(status_code=400, detail="Label cannot be empty")

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        # Find sessions that contain the requested label
        sessions = conn.execute("""
            SELECT DISTINCT ps.*
            FROM prediction_sessions ps
            JOIN detection_objects do
              ON ps.uid = do.prediction_uid
            WHERE do.label = ?
            ORDER BY ps.timestamp DESC
        """, (label,)).fetchall()

        response = []

        # For each matching session, return all detected objects in that session
        for session in sessions:
            objects = conn.execute("""
                SELECT id, label, score, box
                FROM detection_objects
                WHERE prediction_uid = ?
            """, (session["uid"],)).fetchall()

            response.append({
                "uid": session["uid"],
                "timestamp": session["timestamp"],
                "detection_objects": [
                    {
                        "id": obj["id"],
                        "label": obj["label"],
                        "score": obj["score"],
                        "box": obj["box"]
                    }
                    for obj in objects
                ]
            })

        return response


@app.get("/predictions/score/{min_score}")
def get_predictions_by_score(min_score: float):
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

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        objects = conn.execute("""
            SELECT id, prediction_uid, label, score, box
            FROM detection_objects
            WHERE score >= ?
            ORDER BY score DESC
        """, (min_score,)).fetchall()

        return [
            {
                "id": obj["id"],
                "prediction_uid": obj["prediction_uid"],
                "label": obj["label"],
                "score": obj["score"],
                "box": obj["box"]
            }
            for obj in objects
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

    # Create database tables before starting the server
    init_db()

    # Run the FastAPI server on port 8080
    uvicorn.run(app, host="0.0.0.0", port=8080)