import os
import pytest
from fastapi.testclient import TestClient

# Set default confidence threshold for tests
os.environ.setdefault("CONFIDENCE_THRESHOLD", "0.5")

from app import app, init_db

# Sample image used by prediction tests
TEST_IMAGE = os.path.join(os.path.dirname(__file__), "data", "beatles.jpeg")


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    # Create a temporary database for each test
    db_file = str(tmp_path / "test_predictions.db")

    # Replace the application's database path
    monkeypatch.setattr("app.DB_PATH", db_file)

    # Create database tables
    init_db()


@pytest.fixture
def client():
    # FastAPI test client
    return TestClient(app)


def test_health(client):
    # Verify that the health endpoint is working

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}