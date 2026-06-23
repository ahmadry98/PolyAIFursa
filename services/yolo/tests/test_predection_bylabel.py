from models import DetectionObject, PredictionSession


def test_returns_predictions_with_given_label(client, db_session):
    prediction = PredictionSession(
        uid="abc-123",
        original_image="uploads/original/abc-123.jpg",
        predicted_image="uploads/predicted/abc-123.jpg",
    )
    prediction.detection_objects.append(
        DetectionObject(label="person", score=0.91, box="[10, 20, 100, 200]")
    )
    db_session.add(prediction)
    db_session.commit()

    response = client.get("/predictions/label/person")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["uid"] == "abc-123"
    assert data[0]["detection_objects"][0]["label"] == "person"
    assert data[0]["detection_objects"][0]["score"] == 0.91

def test_returns_empty_list_when_no_label_matches(client):
    response = client.get("/predictions/label/car")

    assert response.status_code == 200
    assert response.json() == []

def test_empty_label_returns_400(client):
    response = client.get("/predictions/label/")

    assert response.status_code == 400
    assert response.json() == {"detail": "Label cannot be empty"}
