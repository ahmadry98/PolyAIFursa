from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app import format_timestamp
from models import PredictionSession


def post_mock_prediction(client, tmp_path):
    box = MagicMock()
    box.cls[0].item.return_value = 0
    box.conf[0] = 0.91
    box.xyxy[0].tolist.return_value = [10, 20, 100, 200]

    result = MagicMock()
    result.boxes = [box]
    result.plot.return_value = object()

    fake_model = MagicMock(return_value=[result])
    fake_model.names = {0: "person"}

    annotated_image = MagicMock()
    original_dir = tmp_path / "original"
    predicted_dir = tmp_path / "predicted"
    original_dir.mkdir()
    predicted_dir.mkdir()

    with (
        patch("app.model", fake_model),
        patch("app.Image.fromarray", return_value=annotated_image),
        patch("app.UPLOAD_DIR", str(original_dir)),
        patch("app.PREDICTED_DIR", str(predicted_dir)),
    ):
        return client.post(
            "/predict/upload",
            files={"file": ("image.jpeg", b"fake image", "image/jpeg")},
        )


def test_predict_includes_processing_time(client, tmp_path):
    response = post_mock_prediction(client, tmp_path)

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {
        "uid",
        "timestamp",
        "original_image",
        "predicted_image",
        "detection_objects",
        "detection_count",
        "labels",
        "time_took",
    }
    assert data["detection_count"] == 1
    assert data["labels"] == ["person"]
    assert isinstance(data["time_took"], (int, float))
    assert data["time_took"] >= 0


def test_predict_returns_rfc3339_utc_timestamp(client, tmp_path):
    response = post_mock_prediction(client, tmp_path)

    timestamp = response.json()["timestamp"]
    parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

    assert timestamp.endswith("Z")
    assert parsed_timestamp.tzinfo == timezone.utc


def test_predict_returns_the_persisted_timestamp(client, db_session, tmp_path):
    response = post_mock_prediction(client, tmp_path)
    data = response.json()

    db_session.expire_all()
    prediction = db_session.get(PredictionSession, data["uid"])

    assert prediction is not None
    assert data["timestamp"] == format_timestamp(prediction.timestamp)
    assert len(prediction.detection_objects) == 1
    assert prediction.detection_objects[0].label == "person"
