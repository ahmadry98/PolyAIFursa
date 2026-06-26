from pathlib import Path
from unittest.mock import patch


def test_predict_with_s3_key(client):
    image_bytes = (Path(__file__).resolve().parents[1] / "beatles.jpeg").read_bytes()
    with patch("app.download_bytes_from_s3", return_value=image_bytes), \
         patch("app.upload_file_to_s3", return_value="chat-1/pred-1/predicted/image.jpg"):

        response = client.post(
            "/predict",
            json={
                "image_s3_key": "chat-1/pred-1/original/image.jpg",
                "chat_id": "chat-1",
                "prediction_id": "pred-1",
                "image_name": "image.jpg",
            },
        )

    assert response.status_code == 200
    data = response.json()

    assert data["uid"] == "pred-1"
    assert data["original_image"] == "chat-1/pred-1/original/image.jpg"
    assert data["predicted_image"] == "chat-1/pred-1/predicted/image.jpg"
    assert data["detection_count"] >= 0
    assert "time_took" in data