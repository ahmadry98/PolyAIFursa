



⸻

name: yolo-api-data-layer
description: Use this skill when modifying the YOLO FastAPI service database layer, refactoring raw SQLite to SQLAlchemy, adding or changing database-backed API endpoints, adding tables or columns, changing persistence logic, writing data-layer tests, or making the database backend configurable for SQLite and PostgreSQL.

YOLO API Data Layer

Use this skill for database-layer work in the YOLO FastAPI service.

This includes requests such as:

* Refactor the API to use SQLAlchemy.
* Replace raw SQLite code.
* Add or modify database models.
* Add a database-backed endpoint.
* Add columns or tables.
* Delete prediction sessions and related detection objects.
* Make the database backend configurable.
* Support PostgreSQL in production.
* Update tests after database changes.
* Fix data-layer architecture problems.

Project Context

The YOLO service is a FastAPI application located under:

services/yolo/

The service currently exposes API endpoints such as:

GET /health
POST /predict
GET /prediction/{uid}
GET /prediction/{uid}/image
GET /predictions/label/{label}
GET /predictions/score/{min_score}
GET /metrics

The service stores prediction sessions and detected objects.

Existing tables are conceptually:

prediction_sessions
- uid
- timestamp
- original_image
- predicted_image
detection_objects
- id
- prediction_uid
- label
- score
- box

The refactor must preserve the external API contract.

Critical Requirement

All existing endpoint URLs, status codes, and JSON response shapes must remain exactly the same unless the user explicitly asks for a new behavior.

Do not break backwards compatibility.

Database implementation may change, but API behavior must not change.

Target Architecture

The database layer must use SQLAlchemy ORM instead of raw SQLite.

Create or maintain this structure:

services/yolo/
├── app.py
├── db.py
├── models.py
├── requirements.txt
└── tests/

models.py

Create SQLAlchemy declarative models.

Required model:

PredictionSession

It should map to:

prediction_sessions

Required columns:

uid: primary key string
timestamp: datetime, default current UTC time
original_image: string
predicted_image: string

Required model:

DetectionObject

It should map to:

detection_objects

Required columns:

id: integer primary key autoincrement
prediction_uid: string foreign key or relationship target
label: string
score: float
box: string

Prefer defining an ORM relationship between PredictionSession and DetectionObject.

Use cascade delete when deleting a prediction session should also delete its detection objects.

Recommended pattern:

Base = declarative_base()

or the SQLAlchemy 2.x equivalent, as long as the code is simple and compatible with the project.

db.py

Create the database connection and session factory.

The database backend must be configurable using environment variables.

Default behavior:

DB_BACKEND=sqlite

SQLite should be used by default.

Production behavior:

DB_BACKEND=postgres
DB_USER=user
DB_PASSWORD=pass

PostgreSQL should be used when DB_BACKEND=postgres.

Use a database URL equivalent to:

sqlite:///./predictions.db

for SQLite.

Use a PostgreSQL URL equivalent to:

postgresql://DB_USER:DB_PASSWORD@localhost/predictions

for PostgreSQL unless the existing project uses a different database name.

Required objects/functions:

engine
SessionLocal
get_db()

get_db() must yield a SQLAlchemy session and close it afterward.

For SQLite only, use:

connect_args={"check_same_thread": False}

Do not use SQLite-specific connection arguments for PostgreSQL.

Table Creation

Tables must be created through SQLAlchemy metadata.

Do not manually create tables with raw SQL.

Acceptable:

Base.metadata.create_all(bind=engine)

Not acceptable:

CREATE TABLE ...
sqlite3.connect(...)
conn.execute(...)

If the app currently calls init_db(), replace that behavior with SQLAlchemy table creation during application startup or initialization.

FastAPI Integration

Use FastAPI dependency injection for database sessions.

Endpoints that read or write database data should accept:

db: Session = Depends(get_db)

Do not manually call next(get_db()).

Do not keep global raw SQLite connections.

Use SQLAlchemy ORM operations:

db.add(...)
db.commit()
db.refresh(...)
db.query(...).filter(...).first()
db.query(...).filter(...).all()

or modern SQLAlchemy equivalents.

Persistence Logic

When /predict is called:

* Keep the same file validation behavior.
* Keep the same image saving behavior.
* Keep the same YOLO model behavior.
* Save the prediction session through SQLAlchemy.
* Save detection objects through SQLAlchemy.
* Return the same response shape as before.

The response must still include:

prediction_uid
detection_count
labels
time_took

When retrieving by UID:

* Return the same JSON structure as before.
* Return the same status code for missing UID as before.

When retrieving by label:

* Return sessions containing that label.
* Preserve the existing response shape.
* Preserve the existing error behavior for empty labels or no results.

When retrieving by score:

* Return detection objects with score greater than or equal to the threshold.
* Preserve validation behavior.
* Preserve response shape.

Adding New Data-Layer Features

When the user asks to add a database-backed feature:

1. Add or update SQLAlchemy models.
2. Update persistence/query logic.
3. Add or update FastAPI endpoints.
4. Add or update tests.
5. Preserve existing behavior.
6. Run tests before completion.

Examples:

Add recent predictions endpoint

For a request such as:

add GET /predictions/recent that returns the 10 most recent sessions

Implement using SQLAlchemy ordering and limit:

db.query(PredictionSession)
  .order_by(PredictionSession.timestamp.desc())
  .limit(10)
  .all()

Return a concrete JSON response consistent with the existing API style.

Add UserFeedback table

For a request such as:

add a UserFeedback table to track user ratings per prediction

Create a SQLAlchemy model such as:

UserFeedback
- id
- prediction_uid
- rating
- comment
- created_at

Link it to PredictionSession.

Add tests for inserts and retrieval behavior if endpoints are added.

Delete prediction session by UID

For a request such as:

delete a prediction session and all its detection objects by uid

Use ORM deletion.

Detection objects must be deleted with the session, either through cascade relationship or explicit SQLAlchemy delete logic.

Do not leave orphaned detection objects.

Add processing_time_ms

For a request such as:

add processing_time_ms to prediction_sessions

Add the column to the SQLAlchemy model and update /predict persistence logic.

Keep existing time_took response behavior unless the user explicitly asks to change it.

Forbidden Patterns

Do not introduce or keep these patterns in data-layer code:

import sqlite3
sqlite3.connect(...)
conn.execute(...)
cursor.execute(...)
CREATE TABLE
INSERT INTO
SELECT *
DELETE FROM
UPDATE ...

Do not build SQL queries with string formatting.

Do not use production database state in tests.

Do not change endpoint paths unnecessarily.

Do not change response shapes unnecessarily.

Do not remove existing tests unless replacing them with equivalent or better tests.

Requirements

Update dependency files as needed.

The project must include SQLAlchemy.

If PostgreSQL support is implemented, include the required PostgreSQL driver, such as:

psycopg2-binary

or another compatible driver already used by the project.

Do not add unnecessary large dependencies.

Testing Requirements

When database behavior changes, update tests.

Use the yolo-api-tests skill when writing or modifying API tests.

Tests should:

* Use FastAPI TestClient.
* Override get_db().
* Use a temporary SQLAlchemy test database.
* Create tables with Base.metadata.create_all(bind=test_engine).
* Drop or clean tables between tests.
* Insert test data through SQLAlchemy models and sessions.
* Mock the YOLO model for /predict.
* Assert status codes.
* Assert exact response structures for existing endpoints.
* Ensure invalid inputs still return expected errors.
* Ensure no production database is used.

Do not test by patching old variables such as:

DB_PATH

Do not call old raw SQLite setup functions such as:

init_db()

unless they still exist only as compatibility wrappers around SQLAlchemy metadata creation.

Verification Before Completion

Before claiming the task is complete, run:

cd services/yolo
pytest tests/

If coverage was previously used in the project, also run:

pytest --cov=app --cov-report=term-missing

Also verify the application starts:

python app.py

or the existing project start command.

At minimum, test:

curl http://127.0.0.1:8080/health

Expected response:

{"status":"ok"}

For PostgreSQL support, verify the app can start with:

export DB_BACKEND=postgres
export DB_USER=user
export DB_PASSWORD=pass
python app.py

when a PostgreSQL server is available.

Completion Response

When finished, report:

* Files created.
* Files modified.
* Whether raw SQLite was removed.
* Whether SQLAlchemy models were added.
* Whether tests passed.
* Whether app startup was verified.
* Any limitations or failures.

Do not claim success if tests were not run or failed.