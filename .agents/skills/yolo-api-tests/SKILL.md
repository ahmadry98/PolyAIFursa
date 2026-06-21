⸻

name: yolo-api-tests
description: Use this skill when writing, modifying, or refactoring tests for the YOLO FastAPI service, including endpoints such as /predict, /health, /prediction/{uid}, /predictions/label/{label}, and /predictions/score/{min_score}. Supports SQLAlchemy-based database testing.

YOLO API Tests

When writing tests for the YOLO FastAPI service:

General Principles

* Prefer HTTP-level tests using FastAPI TestClient.
* Use pytest unless there is a strong reason to use unittest.
* Test files must start with test_.
* Keep tests deterministic and isolated.
* Avoid dependencies on external services, network access, or production infrastructure.
* Mock the YOLO model so tests do not load or execute the real model.
* Assert both HTTP status codes and response bodies.
* Verify important response fields and response structure.
* Test success paths and failure paths.

Database Testing

The YOLO service uses SQLAlchemy as its data layer.

* Never use the production database.
* Never import or use sqlite3 directly.
* Never test implementation details such as raw SQL queries.
* Use a dedicated SQLAlchemy test database.
* Override FastAPI’s get_db() dependency during tests.
* Create database tables using SQLAlchemy metadata.
* Clean up test data between tests.
* Insert test data through SQLAlchemy models and sessions.
* Test API behavior rather than database internals.

Dependency Override Pattern

Use FastAPI dependency overrides when testing endpoints that interact with the database.

Example:

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app import app
from db import get_db
from models import Base
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)
Base.metadata.create_all(bind=engine)
def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

Model Usage

When preparing test data:

* Create records using SQLAlchemy model classes.
* Use SQLAlchemy sessions to insert records.
* Commit transactions explicitly when needed.
* Query data through SQLAlchemy ORM methods.

Example:

session = TestingSessionLocal()
prediction = PredictionSession(
    uid="test-uid",
    original_image="original.jpg",
    predicted_image="predicted.jpg",
)
session.add(prediction)
session.commit()

Endpoint Expectations

/health

Verify:

* Status code is 200.
* Response body matches expected structure.

/predict

Verify:

* Valid image uploads succeed.
* Invalid file types return the correct error.
* Response contains prediction_uid.
* Response contains detection_count.
* Response contains labels.
* Response contains time_took.

/prediction/{uid}

Verify:

* Existing prediction returns correct data.
* Missing prediction returns the expected error response.

/predictions/label/{label}

Verify:

* Existing labels return matching prediction sessions.
* Empty labels return the expected error response.

/predictions/score/{min_score}

Verify:

* Returned detections satisfy the score threshold.
* Invalid thresholds return the expected validation error.

Refactor Safety

When the database layer changes:

* Preserve all existing endpoint URLs.
* Preserve all status codes.
* Preserve all response formats.
* Preserve API behavior.
* Update tests to match the new data layer implementation.
* Do not reduce test coverage.

Completion Checklist

Before considering the work complete:

* Run all tests.
* Ensure tests pass.
* Ensure no production database is used.
* Ensure SQLAlchemy dependency overrides are used correctly.
* Verify endpoint behavior remains unchanged.
* Verify coverage does not regress significantly.

⸻