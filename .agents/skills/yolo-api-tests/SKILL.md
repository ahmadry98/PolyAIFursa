---
name: yolo-api-tests
description: Use this skill when writing or modifying API tests for the YOLO FastAPI service, especially endpoints like /predict, /health, /prediction/{uid}, /predictions/label/{label}, or /predictions/score/{min_score}.
---

# YOLO API Tests

When writing tests for the YOLO FastAPI service:

- Prefer HTTP-level tests using FastAPI `TestClient`.
- Use `pytest` or `unittest`.
- Test files must start with `test_`.
- Never use the real SQLite database.
- Use a temporary SQLite database with `tmp_path` or `tempfile`.
- Mock the YOLO model so tests do not load or run the real YOLO model.
- Assert the HTTP status code.
- Assert the response body structure and important fields.
- For endpoints returning predictions, insert test data directly into the temporary database.
- Keep tests deterministic and independent from external files when possible.
- Optionally use `pydantic` models to validate response bodies.

Example pattern:

```python
from fastapi.testclient import TestClient
import app as app_module

def test_endpoint(tmp_path, monkeypatch):
    test_db = tmp_path / "test_predictions.db"
    monkeypatch.setattr(app_module, "DB_PATH", str(test_db))

    app_module.init_db()

    client = TestClient(app_module.app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}