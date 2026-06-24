from models import DetectionObject, PredictionSession


def test_returns_objects_with_score_greater_than_or_equal_to_min_score(
    client,
    db_session,
):
    prediction = PredictionSession(
        uid="abc-123",
        original_image="uploads/original/abc-123.jpg",
        predicted_image="uploads/predicted/abc-123.jpg",
    )
    prediction.detection_objects = [
        DetectionObject(label="person", score=0.91, box="[10, 20, 100, 200]"),
        DetectionObject(label="car", score=0.40, box="[30, 40, 150, 250]"),
    ]
    db_session.add(prediction)
    db_session.commit()

    response = client.get("/predictions/score/0.5")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["prediction_uid"] == "abc-123"
    assert data[0]["label"] == "person"
    assert data[0]["score"] == 0.91

def test_returns_empty_list_when_no_scores_match(client):
    response = client.get("/predictions/score/0.9")

    assert response.status_code == 200
    assert response.json() == []

def test_min_score_below_zero_returns_400(client):
    response = client.get("/predictions/score/-0.1")

    assert response.status_code == 400
    assert response.json() == {
        "detail": "min_score must be between 0.0 and 1.0"
    }

def test_min_score_above_one_returns_400(client):
    response = client.get("/predictions/score/1.1")

    assert response.status_code == 400
    assert response.json() == {
        "detail": "min_score must be between 0.0 and 1.0"
    }
