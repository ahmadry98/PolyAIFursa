import os
import tempfile
import unittest
from fastapi.testclient import TestClient
from fastapi import HTTPException
from unittest.mock import patch

from app import get_confidence_threshold, get_predictions_by_label
import app as app_module
from app import (
    app,
    init_db,
    save_prediction_session,
    save_detection_object,
    get_predictions_by_empty_label
)


class TestExtraCoverage(unittest.TestCase):
    def setUp(self):
        # Use a temporary database for each test
        _, app_module.DB_PATH = tempfile.mkstemp(suffix=".db")
        init_db()

        # Create FastAPI test client
        self.client = TestClient(app)

    def test_predict_rejects_non_image_file(self):
        # Verify non-image uploads are rejected
        response = self.client.post(
            "/predict",
            files={"file": ("test.txt", b"hello", "text/plain")}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"detail": "Only image files are supported"}
        )

    def test_get_prediction_by_uid_success(self):
        # Create a prediction and verify it can be retrieved by UID
        save_prediction_session(
            "abc-123",
            "uploads/original/abc-123.jpg",
            "uploads/predicted/abc-123.jpg"
        )

        save_detection_object(
            "abc-123",
            "person",
            0.91,
            [10, 20, 100, 200]
        )

        response = self.client.get("/prediction/abc-123")

        self.assertEqual(response.status_code, 200)

        data = response.json()

        self.assertEqual(data["uid"], "abc-123")
        self.assertEqual(
            data["original_image"],
            "uploads/original/abc-123.jpg"
        )
        self.assertEqual(
            data["predicted_image"],
            "uploads/predicted/abc-123.jpg"
        )
        self.assertEqual(len(data["detection_objects"]), 1)
        self.assertEqual(
            data["detection_objects"][0]["label"],
            "person"
        )

    def test_get_prediction_by_uid_not_found(self):
        # Verify missing prediction UID returns 404
        response = self.client.get("/prediction/not-exist")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {"detail": "Prediction not found"}
        )

    def test_get_prediction_image_success(self):
        # Verify annotated image endpoint returns file content
        os.makedirs("uploads/predicted", exist_ok=True)

        image_path = "uploads/predicted/test-image.jpg"

        with open(image_path, "wb") as f:
            f.write(b"fake image content")

        save_prediction_session(
            "img-123",
            "uploads/original/img-123.jpg",
            image_path
        )

        response = self.client.get("/prediction/img-123/image")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"fake image content")

    def test_get_prediction_image_not_found_when_uid_missing(self):
        # Verify missing UID returns image not found
        response = self.client.get("/prediction/missing/image")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {"detail": "Image not found"}
        )

    def test_get_prediction_image_not_found_when_file_missing(self):
        # Verify missing image file returns 404
        save_prediction_session(
            "img-missing",
            "uploads/original/img-missing.jpg",
            "uploads/predicted/does-not-exist.jpg"
        )

        response = self.client.get("/prediction/img-missing/image")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {"detail": "Image not found"}
        )

    def test_empty_label_function_returns_400(self):
        # Verify empty label helper raises HTTPException
        with self.assertRaises(HTTPException) as context:
            get_predictions_by_empty_label()

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail, "Label cannot be empty")

    def test_confidence_threshold_from_env(self):
        # Verify environment variable overrides default threshold
        with patch.dict(os.environ, {"CONFIDENCE_THRESHOLD": "0.7"}):
            self.assertEqual(get_confidence_threshold(), 0.7)

    def test_confidence_threshold_default(self):
        # Verify default threshold is used when env variable is missing
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(get_confidence_threshold(), 0.5)

    def test_label_with_only_spaces_returns_400(self):
        # Verify labels containing only spaces are rejected
        with self.assertRaises(HTTPException) as context:
            get_predictions_by_label("   ")

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail, "Label cannot be empty")