from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from models import DetectionObject, PredictionSession


def add_prediction(
    db: Session,
    uid: str,
    original_image: str,
    predicted_image: str,
    detections: list[dict],
) -> PredictionSession:
    prediction = PredictionSession(
        uid=uid,
        original_image=original_image,
        predicted_image=predicted_image,
    )

    for detection in detections:
        prediction.detection_objects.append(
            DetectionObject(
                label=detection["label"],
                score=detection["score"],
                box=str(detection["box"]),
            )
        )

    db.add(prediction)
    try:
        db.commit()
        db.refresh(prediction)
    except Exception:
        db.rollback()
        raise
    return prediction


def find_prediction(db: Session, uid: str) -> PredictionSession | None:
    statement = (
        select(PredictionSession)
        .options(selectinload(PredictionSession.detection_objects))
        .where(PredictionSession.uid == uid)
    )
    return db.scalar(statement)


def find_predictions_by_label(
    db: Session,
    label: str,
) -> list[PredictionSession]:
    statement = (
        select(PredictionSession)
        .join(PredictionSession.detection_objects)
        .where(DetectionObject.label == label)
        .options(selectinload(PredictionSession.detection_objects))
        .distinct()
        .order_by(PredictionSession.timestamp.desc(), PredictionSession.uid)
    )
    return list(db.scalars(statement).all())


def find_detections_by_score(
    db: Session,
    min_score: float,
) -> list[DetectionObject]:
    statement = (
        select(DetectionObject)
        .where(DetectionObject.score >= min_score)
        .order_by(DetectionObject.score.desc(), DetectionObject.id)
    )
    return list(db.scalars(statement).all())
