---
name: yolo-api-data-layer
description: Refactor or extend persistence, SQLAlchemy models, repositories, transactions, timestamps, database configuration, API schemas, and database-backed tests in the YOLO FastAPI service. Use for SQLite or PostgreSQL changes under services/yolo.
---

# Evolve the YOLO Data Layer

Treat persistence work as an API-preserving migration. Keep the code explicit enough for students to trace a request from the FastAPI route through the repository and transaction.

## Preserve the Project Contract

Keep these entities unless the user explicitly changes the domain:

- `PredictionSession`: `uid`, `timestamp`, `original_image`, `predicted_image`
- `DetectionObject`: `id`, `prediction_uid`, `label`, `score`, `box`

Preserve routes, methods, status codes, response field names and types, defaults, errors, and observable ordering. Inventory all routes before editing, including `/health`, `/predict`, `/prediction/{uid}`, image retrieval, label and score searches, and `/metrics`.

Keep request/response Pydantic schemas separate from ORM models. Keep image bytes out of the agent/LLM path.

## Use Explicit Layers

Keep responsibilities visible:

1. `database.py`: `DATABASE_URL`, dialect-aware engine options, session factory, declarative base, and `get_db`.
2. `models.py`: typed ORM models, constraints, relationships, indexes, and defaults.
3. `repositories.py`: small SQLAlchemy queries and write operations.
4. `app.py`: validation, service orchestration, transaction-error translation, and response formatting.
5. `tests/`: isolated engines and FastAPI dependency overrides.

Inject a short-lived `Session` with `Depends(get_db)` into every database-backed route. Never open raw connections in routes. Keep each write operation atomic: commit once when all related rows are ready, roll back on failure, and refresh only when generated values are needed.

## Timestamp Contract

Treat `timestamp` as the prediction session's creation time. It is distinct from `time_took`, which is the request's processing duration.

- Generate the timestamp once when the ORM object is created; do not independently generate a response timestamp.
- Store UTC with `DateTime(timezone=True)` and a timezone-aware Python default.
- Serialize API timestamps as RFC 3339 UTC, ending in `Z`, for example `2026-06-24T12:34:56.789000Z`.
- Normalize values at the API boundary because SQLite may return a naive `datetime` even when `timezone=True`; interpret such persisted values as UTC.
- Use the persisted timestamp in both create and read responses.
- Order time-based queries explicitly. Add a stable secondary key such as `uid` or `id` because timestamps can tie.
- Preserve old rows through a migration strategy when changing an existing timestamp column. Do not claim `create_all()` migrates deployed schemas.

Test timestamp creation, UTC serialization, equality between the create response and persisted value, read-response formatting, newest-first ordering, and tied timestamps.

## Maintain SQLite and PostgreSQL Portability

Use one configurable `DATABASE_URL`, defaulting to `sqlite:///./predictions.db`. Apply `check_same_thread=False` only to SQLite. Never pass SQLite engine options to PostgreSQL.

Prefer SQLAlchemy expressions and portable types. Avoid SQLite date functions, `INSERT OR REPLACE`, string-built SQL, SQLite boolean encodings, and implicit row ordering.

Use `create_all()` only for fresh local bootstrap and test databases. Use migrations for deployed schema evolution. A passing SQLite suite does not prove PostgreSQL compatibility; run a disposable PostgreSQL suite or report it as unverified.

## Follow This Workflow

1. Inspect routes, schemas, models, repositories, startup behavior, configuration, requirements, and every `services/yolo/tests/test*.py` file.
2. Record the observable HTTP and persistence contract before editing.
3. Add or strengthen black-box compatibility tests.
4. Introduce or modify database infrastructure without changing route behavior.
5. Map schema details explicitly: table names, types, nullability, defaults, keys, relationships, cascades, and indexes.
6. Replace or update one repository path at a time.
7. Verify atomic writes, rollback, deterministic ordering, and session cleanup.
8. Remove legacy helpers and raw SQL only after tests no longer depend on them.
9. Verify SQLite and PostgreSQL when available, and report exactly what ran.

## Build Isolated Tests

Create a fresh engine and session factory for tests. Override `get_db` through `app.dependency_overrides`; never patch a raw connection or point tests at a developer database. Use `StaticPool` for shared in-memory SQLite, or use a temporary file.

Mock external boundaries such as the YOLO model, not repositories or ORM behavior, when testing `/predict`. Assert both the HTTP response and committed rows.

Cover:

- Exact success responses and established errors.
- Missing records and invalid values.
- Duplicate/conflicting data and rollback without partial rows.
- Session/test isolation and dependency-override cleanup.
- Deterministic ordering, including equal sort values.
- Timestamp persistence and RFC 3339 UTC output.
- SQLite behavior and disposable PostgreSQL integration when available.

Do not restore `init_db`, `save_prediction_session`, or `save_detection_object` merely to satisfy stale tests. Seed ORM models or call repository functions with the isolated test session. Inspect oddly named duplicate test files before finishing.

## Avoid Common Failures

| Failure | Correction |
|---|---|
| ORM objects accidentally define the API | Keep explicit Pydantic response schemas and format ORM data at the boundary |
| One global request session | Yield and close one session per request |
| Multiple commits inside one logical write | Commit once after the complete object graph is ready |
| Database exception leaks to clients | Roll back and translate expected failures to the established API error |
| Response time differs from stored time | Serialize the persisted ORM timestamp |
| SQLite timestamp lacks `tzinfo` | Normalize it to UTC before API serialization |
| Query relies on insertion order | Add explicit primary and tie-break ordering |
| `create_all()` is called a migration | Provide a real non-destructive migration strategy |
| Tests mock repositories | Mock YOLO and other external boundaries; exercise the real data layer |
| Old copied tests still import legacy helpers | Inspect every test file and migrate or remove stale duplicates |

## Completion Gate

Before reporting completion, confirm:

- Routes contain no raw SQL or connection management.
- API compatibility is asserted rather than assumed.
- Sessions close and failed writes roll back.
- Timestamps have one documented UTC meaning and format.
- SQLite and PostgreSQL receive only compatible engine options.
- Tests override `get_db`, isolate data, and exercise real repositories.
- Deployed schema changes have a migration strategy.
- Every test file collects without legacy-helper imports.
- Exact test commands and backend dialects are reported; unavailable PostgreSQL coverage is named as a risk.

Do not claim completion from inspection alone.