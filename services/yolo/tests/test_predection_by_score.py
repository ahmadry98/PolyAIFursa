import unittest
import tempfile
from fastapi.testclient import TestClient

import app as app_module
from app import app, init_db, save_prediction_session, save_detection_object


class TestPredictionsByScore(unittest.TestCase):
    def setUp(self):
        _, app_module.DB_PATH = tempfile.mkstemp(suffix=".db")
        init_db()
        self.client = TestClient(app)

    def test_returns_objects_with_score_greater_than_or_equal_to_min_score(self):
        save_prediction_session(
            "abc-123",
            "uploads/original/abc-123.jpg",
            "uploads/predicted/abc-123.jpg"
        )
        save_detection_object("abc-123", "person", 0.91, [10, 20, 100, 200])
        save_detection_object("abc-123", "car", 0.40, [30, 40, 150, 250])

        response = self.client.get("/predictions/score/0.5")

        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["prediction_uid"], "abc-123")
        self.assertEqual(data[0]["label"], "person")
        self.assertEqual(data[0]["score"], 0.91)

    def test_returns_empty_list_when_no_scores_match(self):
        response = self.client.get("/predictions/score/0.9")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_min_score_below_zero_returns_400(self):
        response = self.client.get("/predictions/score/-0.1")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"detail": "min_score must be between 0.0 and 1.0"}
        )

    def test_min_score_above_one_returns_400(self):
        response = self.client.get("/predictions/score/1.1")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"detail": "min_score must be between 0.0 and 1.0"}
        )