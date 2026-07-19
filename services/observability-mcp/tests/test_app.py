import gzip
import io
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app  # noqa: E402


def test_env_name_accepts_dev_and_prod_case_insensitive():
    assert app._env_name("dev") == "dev"
    assert app._env_name("PROD") == "prod"


def test_env_name_rejects_unknown_environment():
    with pytest.raises(ValueError, match="environment must be dev or prod"):
        app._env_name("staging")


def test_required_env_raises_when_missing(monkeypatch):
    monkeypatch.delenv("PROD_PROMETHEUS_URL", raising=False)

    with pytest.raises(RuntimeError, match="Missing required environment variable"):
        app._required_env("PROD_PROMETHEUS_URL")


def test_decode_log_object_reads_gzip_payload():
    body = gzip.compress(b'{"log":"hello"}\n')

    assert app._decode_log_object(body, "logs/2026/07/15/example.gz-object") == '{"log":"hello"}\n'


def test_decode_log_object_falls_back_to_plain_text_when_gzip_is_invalid():
    assert app._decode_log_object(b"plain log", "logs/file.gz-object") == "plain log"


def test_parse_log_lines_handles_json_and_plain_text():
    records = app._parse_log_lines('{"log":"json log","stream":"stdout"}\nplain log\n\n')

    assert records == [
        {"log": "json log", "stream": "stdout"},
        {"log": "plain log"},
    ]


class FakeS3Body:
    def __init__(self, body: bytes):
        self.body = body

    def read(self):
        return self.body


class FakePaginator:
    def __init__(self, pages):
        self.pages = pages

    def paginate(self, **kwargs):
        return self.pages


class FakeS3Client:
    def __init__(self, now):
        self.now = now
        self.objects = [
            {
                "Key": "logs/old.gz-object",
                "Size": 10,
                "LastModified": now - timedelta(hours=2),
            },
            {
                "Key": "logs/new.gz-object",
                "Size": 20,
                "LastModified": now,
            },
        ]

    def list_objects_v2(self, **kwargs):
        return {"Contents": list(self.objects)}

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return FakePaginator([{"Contents": list(self.objects)}])

    def get_object(self, Bucket, Key):
        assert Bucket == "test-logs"
        assert Key == "logs/new.gz-object"
        body = gzip.compress(b'{"log":"new log","stream":"stdout"}\n')
        return {"Body": FakeS3Body(body)}


def test_list_log_objects_sorts_newest_first_and_limits(monkeypatch):
    now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    monkeypatch.setenv("PROD_S3_LOGS_BUCKET", "test-logs")
    monkeypatch.setattr(app, "_s3_client", lambda: FakeS3Client(now))

    objects = app.list_log_objects("prod", limit=1)

    assert objects == [
        {
            "bucket": "test-logs",
            "key": "logs/new.gz-object",
            "size": 20,
            "last_modified": "2026-07-15T12:00:00+00:00",
        }
    ]


def test_get_recent_logs_reads_only_recent_objects(monkeypatch):
    now = datetime.now(UTC)
    monkeypatch.setenv("PROD_S3_LOGS_BUCKET", "test-logs")
    monkeypatch.setattr(app, "_s3_client", lambda: FakeS3Client(now))

    logs = app.get_recent_logs("prod", minutes=30, limit=5)

    assert len(logs) == 1
    assert logs[0]["log"] == "new log"
    assert logs[0]["stream"] == "stdout"
    assert logs[0]["_s3_key"] == "logs/new.gz-object"


class FakePrometheusResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps({"status": "success", "data": {"result": []}}).encode("utf-8")


def test_query_prometheus_builds_query_url(monkeypatch):
    captured = {}
    monkeypatch.setenv("PROD_PROMETHEUS_URL", "http://prometheus.example/")

    def fake_urlopen(url, timeout):
        captured["url"] = url
        captured["timeout"] = timeout
        return FakePrometheusResponse()

    monkeypatch.setattr(app, "urlopen", fake_urlopen)

    result = app.query_prometheus("prod", 'up{job="agent"}')

    assert result["status"] == "success"
    assert captured["timeout"] == 15
    assert captured["url"] == (
        "http://prometheus.example/api/v1/query?"
        "query=up%7Bjob%3D%22agent%22%7D"
    )


def test_get_cpu_usage_uses_expected_prometheus_query(monkeypatch):
    captured = {}

    def fake_query_prometheus(environment, query):
        captured["environment"] = environment
        captured["query"] = query
        return {"status": "success"}

    monkeypatch.setattr(app, "query_prometheus", fake_query_prometheus)

    assert app.get_cpu_usage("prod", minutes=15) == {"status": "success"}
    assert captured["environment"] == "prod"
    assert 'environment="prod"' in captured["query"]
    assert 'job=~"agent|frontend|yolo"' in captured["query"]
    assert "[15m]" in captured["query"]
