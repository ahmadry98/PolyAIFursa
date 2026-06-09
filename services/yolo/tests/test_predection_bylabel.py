import unittest
import tempfile
from fastapi.testclient import TestClient

import app as app_module
from app import app, init_db, save_prediction_session, save_detection_object


class TestPredictionsByLabel(unittest.TestCase):
    def setUp(self):
        # Use a temporary database for each test
        _, app_module.DB_PATH = tempfile.mkstemp(suffix=".db")
        init_db()

        # Create FastAPI test client
        self.client = TestClient(app)

    def test_returns_predictions_with_given_label(self):
        # Create a prediction with one detected label
        save_prediction_session(
            "abc-123",
            "uploads/original/abc-123.jpg",
            "uploads/predicted/abc-123.jpg"
        )

        save_detection_object("abc-123", "person", 0.91, [10, 20, 100, 200])

        response = self.client.get("/predictions/label/person")

        self.assertEqual(response.status_code, 200)

        data = response.json()

        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["uid"], "abc-123")
        self.assertEqual(data[0]["detection_objects"][0]["label"], "person")
        self.assertEqual(data[0]["detection_objects"][0]["score"], 0.91)

    def test_returns_empty_list_when_no_label_matches(self):
        # Verify empty result when no prediction contains the label
        response = self.client.get("/predictions/label/car")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_empty_label_returns_400(self):
        # Verify empty label URL returns bad request
        response = self.client.get("/predictions/label/")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "Label cannot be empty"})