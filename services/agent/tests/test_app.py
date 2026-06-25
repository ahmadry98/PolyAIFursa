import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app

client = TestClient(app.app)


def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_api_mocks_run_agent(monkeypatch):
    def fake_run_agent(history, max_iterations=10):
        return {
            "response": "Mocked response",
            "prediction_id": "test-prediction-id",
            "annotated_image": None,
            "annotated_image_url": None,
            "agent_loop_time_s": 0.1,
            "iterations": 1,
            "tools_called": [],
            "context_limit_exceeded": False,
            "tokens_used": {
                "input": 10,
                "output": 5,
                "total": 15,
            },
        }

    monkeypatch.setattr(app, "run_agent", fake_run_agent)

    response = client.post(
        "/chat",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": "hello",
                }
            ]
        },
    )

    assert response.status_code == 200

    data = response.json()
    assert data["response"] == "Mocked response"
    assert data["prediction_id"] == "test-prediction-id"
    assert data["iterations"] == 1
    assert data["tools_called"] == []
    assert data["tokens_used"]["total"] == 15
