# YOLO Object Detection Service

This is a FastAPI-based web service that performs object detection on uploaded images using the YOLOv8 model. The application analyzes images, detects objects, and stores prediction results through SQLAlchemy for later retrieval.

## Setup Instructions

1. Make sure the shared project virtualenv is activated (see the root README).

1. Install requirements (from `services/yolo/`):

```bash
pip install -r torch-requirements.txt
pip install -r requirements.txt
```

1. Run the application:

```bash
python app.py
```

The service will be available at http://<your_server_ip>:8080

You can test the api endpoints using `curl` or Postman. See the API Endpoints section below for details on available endpoints and how to use them.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `CONFIDENCE_THRESHOLD` | `0.5` | Minimum confidence score (0.0–1.0) for a detection to be reported. Raise it to get only high-confidence results; lower it to catch more objects. |
| `DATABASE_URL` | `sqlite:///./predictions.db` | SQLAlchemy database URL. Use SQLite locally or a PostgreSQL URL in deployment. |
| `TEST_DATABASE_URL` | `sqlite://` | Optional disposable database used by tests. |

Example:
```bash
export CONFIDENCE_THRESHOLD=0.7
python app.py
```

For PostgreSQL, set `DATABASE_URL` before starting the service. Existing deployed
databases should be migrated with a schema migration tool; `create_all()` only
bootstraps new local or test databases.

## Timestamps

`timestamp` is the UTC creation time of a prediction session. API responses use
RFC 3339 and end in `Z`, for example `2026-06-24T12:34:56.789000Z`. This differs
from `time_took`, which is the number of seconds spent processing the request.

New ORM rows use timezone-aware UTC values. Existing PostgreSQL databases whose
column is `timestamp without time zone` need a migration that interprets old
values as UTC and converts the column to `timestamp with time zone`.

## Running Tests

The test suite uses `pytest` and FastAPI's built-in test client — no running server needed.

```bash
pytest tests/
```

To verify PostgreSQL portability, point `TEST_DATABASE_URL` at a dedicated,
disposable PostgreSQL database before running the same command. The suite creates
and drops its tables, so never point it at a development or production database.


## API Endpoints

* `POST /predict` - Upload an image for object detection
* `GET /prediction/{uid}` - Get details of a specific prediction by ID
* `GET /predictions/label/{label}` - Get all predictions containing a specific object label (e.g., "person", "car")
* `GET /predictions/score/{min_score}` - Get predictions with confidence score above threshold (e.g., 0.5)
* `GET /prediction/{uid}/image` - Get the processed image with detection boxes
* `GET /image/{type}/{filename}` - Get original or predicted image by filename

## Testing the API

You can use tools like curl, Postman, or a web browser to test the endpoints. For example:

1. Upload an image:
```bash
curl -X POST -F "file=@your_image.jpg" http://localhost:8080/predict
```

2. View detection results (replace {uid} with the ID returned from the upload):
```bash
curl http://localhost:8080/prediction/{uid}
```
