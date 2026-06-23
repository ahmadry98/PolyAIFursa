---
name: yolo-api-data-layer
description: Use when changing persistence, database models, queries, API schemas, or database-backed tests in the YOLO FastAPI service, especially for SQLAlchemy, SQLite, or PostgreSQL work.
---

# Evolving the YOLO Data Layer

## Overview
## YOLO Project Contract

The existing YOLO service stores two main entities:

Prediction sessions:

- `uid`
- `timestamp`
- `original_image`
- `predicted_image`

Detection objects:

- `id`
- `prediction_uid`
- `label`
- `score`
- `box`

The refactor must preserve the behavior of the existing YOLO endpoints, including:

- `GET /health`
- `POST /predict`
- `GET /prediction/{uid}`
- `GET /prediction/{uid}/image`
- `GET /predictions/label/{label}`
- `GET /predictions/score/{min_score}`
- `GET /metrics`

Do not remove endpoint behavior just because the storage layer changed.
Treat a database change as an API-preserving migration, not a storage rewrite. Keep HTTP behavior stable while moving persistence behind explicit SQLAlchemy models, sessions, and repository-style functions.

## Invariants

- Preserve routes, methods, status codes, JSON field names, field types, defaults, and ordering unless the task explicitly changes the API.
- Keep image bytes and base64 out of the LLM path. Detection remains the YOLO service's responsibility.
- Support both SQLite and PostgreSQL through one configurable `DATABASE_URL`.
- Keep request/response schemas separate from ORM models.
- Never use database-specific SQL when SQLAlchemy can express the operation portably.
- A request owns a short-lived session; tests own isolated databases.

## Workflow

1. **Inventory the contract.** Read the FastAPI routes, Pydantic schemas, raw SQL, table creation, startup lifecycle, configuration, and tests. Record existing endpoint behavior before editing.
2. **Characterize behavior.** Add or identify API tests that lock down responses, errors, ordering, and persistence. These tests are the migration safety net.
3. **Introduce infrastructure.** Add a database module containing the URL, engine, session factory, declarative base, and FastAPI session dependency. Do not change route behavior yet.
4. **Map the existing schema.** Create typed ORM models with explicit table names, columns, nullability, defaults, primary keys, foreign keys, relationships, and indexes. Match existing SQLite data semantics.
5. **Replace one query path at a time.** Move SQL into small data-access functions. Routes validate input and translate results; data-access functions query and persist.
6. **Preserve transaction boundaries.** Commit once per successful write operation, roll back on failure, and refresh objects only when generated values are required.
7. **Verify both backends.** Run the normal SQLite suite and the PostgreSQL integration suite. A SQLite-only pass does not prove portability.
8. **Remove legacy code last.** Delete raw connections, SQL strings, and duplicate schema initialization only after equivalent tests pass.

## Core Pattern

```python
# database.py
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./yolo.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

Inject `Session` with `Depends(get_db)`. In tests, override `get_db`; do not patch global connections or point tests at a developer database.

## Portability Rules

| Concern | Portable choice |
|---|---|
| Primary keys | SQLAlchemy integer identity/autoincrement |
| Timestamps | Explicit timezone policy and SQLAlchemy types |
| Booleans/JSON | SQLAlchemy `Boolean`/`JSON`, not SQLite encodings |
| SQL parameters | ORM expressions or `text()` with named parameters |
| SQLite threads | `check_same_thread=False` only for SQLite |
| Engine options | Branch by URL/dialect; never pass SQLite options to PostgreSQL |
| Schema changes | Migrations for deployed data; `create_all()` only for bootstrap/tests |

Do not infer production readiness from SQLite: it tolerates type and concurrency behavior PostgreSQL rejects. Avoid `INSERT OR REPLACE`, implicit row ordering, SQLite date functions, and string-built SQL.

## Adding a Database-Backed Feature

Define the contract in this order:

1. API schema and observable behavior.
2. ORM model and database constraints.
3. Data-access functions with typed inputs and explicit return values.
4. Route/service integration through session injection.
5. API tests plus persistence and rollback tests.
6. Migration when an existing deployed schema changes.

Database constraints protect invariants; API validation produces friendly errors. Use both where appropriate. Convert expected integrity failures into the established API error shape rather than leaking SQLAlchemy exceptions.

## Test Contract
Before finishing, inspect every file under `services/yolo/tests/`, including duplicate or copied files with spaces or suffixes such as:

- `test_extra_coverage 2.py`
- `test_predection_by_score 2.py`
- `test_predection_bylabel 2.py`

All tests must be migrated away from old raw-SQL helpers.

Tests must not import removed helpers from `app.py`, including:

- `init_db`
- `save_prediction_session`
- `save_detection_object`

Do not restore these helpers just to satisfy old tests. Update the tests to use SQLAlchemy models, sessions, and dependency overrides instead.
Tests must cover:

- Existing routes before and after the refactor, including exact response shape and status codes.
- Successful create/read/update/delete behavior that the service exposes.
- Missing records, invalid input, duplicate/conflicting data, and rollback after failed writes.
- Session isolation: one test cannot observe another test's data.
- Deterministic ordering using explicit `order_by` when order is observable.
- SQLite for fast tests and PostgreSQL for dialect/integration confidence.

Build a fresh engine/session factory for the test database, create the schema, override the FastAPI dependency, and tear the schema down. For in-memory SQLite shared across connections, use `StaticPool`; otherwise prefer a temporary file database. PostgreSQL tests must use a dedicated disposable database or schema.

## Common Mistakes
| Old tests import removed helpers from `app.py` | Update tests to use SQLAlchemy sessions and dependency overrides; do not restore raw-SQL helper functions |
| Duplicate test files with spaces still run in pytest | Inspect all `tests/test*.py` files and update or remove stale duplicates |
| Mistake | Correction |
|---|---|
| ORM objects become response schemas accidentally | Keep Pydantic schemas explicit and enable attribute-based validation deliberately |
| One global session | Inject one session per request |
| `create_all()` presented as migration support | Use a migration tool for deployed schema evolution |
| Commit hidden in many helpers | Make the write transaction boundary obvious |
| Tests replace API assertions with ORM assertions | Retain black-box API compatibility tests |
| Queries rely on insertion order | Add explicit ordering |
| PostgreSQL URL receives SQLite arguments | Choose engine options by dialect |
| Legacy SQL removed before equivalence is proven | Migrate incrementally, then delete it |

## Completion Checklist

- [ ] API compatibility is demonstrated by tests.
- [ ] Routes contain no raw SQL or connection management.
- [ ] Sessions close reliably and failed writes roll back.
- [ ] Configuration accepts SQLite and PostgreSQL URLs.
- [ ] Queries, types, defaults, and ordering are portable.
- [ ] Tests override the session dependency and isolate data.
- [ ] Both backend suites pass, or an unavailable backend is reported explicitly.
- [ ] Deployed schema changes include a migration strategy.
- [ ] Legacy persistence code is removed only after parity is proven.
- [ ] Every `services/yolo/tests/test*.py` file collects successfully under pytest.
- [ ] No test imports `init_db`, `save_prediction_session`, or `save_detection_object` from `app.py`.
- [ ] No stale duplicate test file still depends on the old raw SQLite implementation.
Do not claim completion from code inspection alone. Report the exact tests run, backend URLs by dialect only (never credentials), and any unverified compatibility risk.
