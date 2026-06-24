import pytest
from datetime import datetime, timezone
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from models import PredictionSession
from repositories import add_prediction


def test_add_prediction_saves_session_and_detections(db_session):
    prediction = add_prediction(
        db_session,
        "abc-123",
        "uploads/original/abc-123.jpg",
        "uploads/predicted/abc-123.jpg",
        [{"label": "person", "score": 0.91, "box": [10, 20, 100, 200]}],
    )

    assert prediction.uid == "abc-123"
    assert len(prediction.detection_objects) == 1
    assert prediction.detection_objects[0].label == "person"


def test_add_prediction_records_current_utc_timestamp(db_session):
    before = datetime.now(timezone.utc)

    prediction = add_prediction(
        db_session,
        "timestamp-test",
        "original.jpg",
        "predicted.jpg",
        [],
    )

    after = datetime.now(timezone.utc)
    timestamp = prediction.timestamp
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    assert before <= timestamp <= after


def test_add_prediction_rolls_back_after_duplicate_uid(db_session):
    add_prediction(
        db_session,
        "duplicate",
        "original.jpg",
        "predicted.jpg",
        [],
    )

    with pytest.raises(IntegrityError):
        add_prediction(
            db_session,
            "duplicate",
            "another-original.jpg",
            "another-predicted.jpg",
            [],
        )

    count = db_session.scalar(select(func.count()).select_from(PredictionSession))
    assert count == 1
