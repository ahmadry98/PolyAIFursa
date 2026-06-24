from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def utc_now() -> datetime:
    """Return a timezone-aware timestamp in UTC."""
    return datetime.now(timezone.utc)


class PredictionSession(Base):
    __tablename__ = "prediction_sessions"

    uid: Mapped[str] = mapped_column(String, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    original_image: Mapped[str] = mapped_column(String, nullable=False)
    predicted_image: Mapped[str] = mapped_column(String, nullable=False)

    detection_objects: Mapped[list["DetectionObject"]] = relationship(
        back_populates="prediction",
        cascade="all, delete-orphan",
        order_by="DetectionObject.id",
    )


class DetectionObject(Base):
    __tablename__ = "detection_objects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prediction_uid: Mapped[str] = mapped_column(
        ForeignKey("prediction_sessions.uid"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String, nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    box: Mapped[str] = mapped_column(Text, nullable=False)

    prediction: Mapped[PredictionSession] = relationship(
        back_populates="detection_objects"
    )
