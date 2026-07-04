from unittest.mock import MagicMock, patch

from models import PredictionSession


def test_predict_with_s3_key(client, db_session, tmp_path):
    result = MagicMock()
    result.boxes = []
    result.plot.return_value = object()
    fake_model = MagicMock(return_value=[result])

    original_dir = tmp_path / "original"
    predicted_dir = tmp_path / "predicted"
    original_dir.mkdir()
    predicted_dir.mkdir()

    with (
        patch("app.model", fake_model),
        patch("app.Image.fromarray") as image_from_array,
        patch("app.UPLOAD_DIR", str(original_dir)),
        patch("app.PREDICTED_DIR", str(predicted_dir)),
        patch("app.download_bytes_from_s3", return_value=b"fake image"),
        patch("app.upload_file_to_s3") as upload_file,
    ):
        response = client.post(
            "/predict",
            params={
                "image_s3_key": "chat-1/pred-1/original/image.jpg",
            },
        )

    assert response.status_code == 200
    data = response.json()

    assert data["uid"] == "pred-1"
    assert data["original_image"] == "chat-1/pred-1/original/image.jpg"
    assert data["predicted_image"] == "chat-1/pred-1/predicted/image.jpg"
    assert data["detection_count"] >= 0
    assert "time_took" in data

    image_from_array.return_value.save.assert_called_once()
    upload_file.assert_called_once_with(
        str(predicted_dir / "pred-1.jpg"),
        "chat-1/pred-1/predicted/image.jpg",
        "image/jpeg",
    )

    db_session.expire_all()
    prediction = db_session.get(PredictionSession, "pred-1")
    assert prediction.original_image == "chat-1/pred-1/original/image.jpg"
    assert prediction.predicted_image == "chat-1/pred-1/predicted/image.jpg"
