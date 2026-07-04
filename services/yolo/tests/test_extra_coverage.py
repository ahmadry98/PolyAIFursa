import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app import (
    get_confidence_threshold,
    get_predictions_by_empty_label,
    get_predictions_by_label,
)
from models import DetectionObject, PredictionSession


def add_prediction(db_session, uid, predicted_image):
    prediction = PredictionSession(
        uid=uid,
        original_image=f"uploads/original/{uid}.jpg",
        predicted_image=predicted_image,
    )
    db_session.add(prediction)
    db_session.commit()
    return prediction


def test_predict_rejects_non_image_file(client):
    response = client.post(
        "/predict",
        files={"file": ("test.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Only image files are supported"}


def test_predict_upload_route_does_not_exist(client):
    response = client.post(
        "/predict/upload",
        files={"file": ("image.jpg", b"image", "image/jpeg")},
    )

    assert response.status_code == 404


def test_predict_requires_one_image_source(client):
    response = client.post("/predict")

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Provide an image file or image_s3_key"
    }


def test_get_prediction_by_uid_success(client, db_session):
    prediction = add_prediction(
        db_session,
        "abc-123",
        "uploads/predicted/abc-123.jpg",
    )
    prediction.detection_objects.append(
        DetectionObject(
            label="person",
            score=0.91,
            box="[10, 20, 100, 200]",
        )
    )
    db_session.commit()

    response = client.get("/prediction/abc-123")

    assert response.status_code == 200
    data = response.json()
    assert data["uid"] == "abc-123"
    assert data["original_image"] == "uploads/original/abc-123.jpg"
    assert data["predicted_image"] == "uploads/predicted/abc-123.jpg"
    parsed_timestamp = datetime.fromisoformat(
        data["timestamp"].replace("Z", "+00:00")
    )
    assert parsed_timestamp.tzinfo == timezone.utc
    assert len(data["detection_objects"]) == 1
    assert data["detection_objects"][0]["label"] == "person"


def test_get_prediction_by_uid_not_found(client):
    response = client.get("/prediction/not-exist")

    assert response.status_code == 404
    assert response.json() == {"detail": "Prediction not found"}


def test_get_prediction_image_success(client, db_session, tmp_path):
    image_path = tmp_path / "test-image.jpg"
    image_path.write_bytes(b"fake image content")
    add_prediction(db_session, "img-123", str(image_path))

    response = client.get("/prediction/img-123/image")

    assert response.status_code == 200
    assert response.content == b"fake image content"


def test_get_prediction_image_downloads_s3_object(client, db_session):
    add_prediction(
        db_session,
        "s3-image",
        "chat-1/s3-image/predicted/image.png",
    )

    with patch("app.download_bytes_from_s3", return_value=b"png bytes"):
        response = client.get("/prediction/s3-image/image")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == b"png bytes"


def test_get_prediction_image_not_found_when_uid_missing(client):
    response = client.get("/prediction/missing/image")

    assert response.status_code == 404
    assert response.json() == {"detail": "Image not found"}


def test_get_prediction_image_not_found_when_file_missing(client, db_session):
    add_prediction(
        db_session,
        "img-missing",
        "uploads/predicted/does-not-exist.jpg",
    )

    response = client.get("/prediction/img-missing/image")

    assert response.status_code == 404
    assert response.json() == {"detail": "Image not found"}


def test_empty_label_function_returns_400():
    with pytest.raises(HTTPException) as error:
        get_predictions_by_empty_label()

    assert error.value.status_code == 400
    assert error.value.detail == "Label cannot be empty"


def test_confidence_threshold_from_env():
    with patch.dict(os.environ, {"CONFIDENCE_THRESHOLD": "0.7"}):
        assert get_confidence_threshold() == 0.7


def test_confidence_threshold_default():
    with patch.dict(os.environ, {}, clear=True):
        assert get_confidence_threshold() == 0.5


def test_label_with_only_spaces_returns_400():
    with pytest.raises(HTTPException) as error:
        get_predictions_by_label("   ")

    assert error.value.status_code == 400
    assert error.value.detail == "Label cannot be empty"
