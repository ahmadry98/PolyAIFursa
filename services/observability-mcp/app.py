import gzip
import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlencode
from urllib.request import urlopen

import boto3
from mcp.server.fastmcp import FastMCP

Environment = Literal["dev", "prod"]

mcp = FastMCP("observability")


def _env_name(name: str) -> str:
    normalized = name.lower()
    if normalized not in {"dev", "prod"}:
        raise ValueError("environment must be dev or prod")
    return normalized


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _bucket_for(environment: str) -> str:
    env = _env_name(environment)
    return _required_env(f"{env.upper()}_S3_LOGS_BUCKET")


def _prometheus_url_for(environment: str) -> str:
    env = _env_name(environment)
    return _required_env(f"{env.upper()}_PROMETHEUS_URL").rstrip("/")


def _s3_client():
    return boto3.client("s3", region_name=os.getenv("AWS_REGION", "us-east-1"))


def _decode_log_object(body: bytes, key: str) -> str:
    if key.endswith(".gz") or ".gz-" in key:
        try:
            return gzip.decompress(body).decode("utf-8", errors="replace")
        except gzip.BadGzipFile:
            pass
    return body.decode("utf-8", errors="replace")


def _parse_log_lines(text: str) -> list[dict[str, Any]]:
    records = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            records.append({"log": line})
    return records


@mcp.tool()
def list_log_objects(
    environment: Environment,
    prefix: str = "logs/",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List recent log objects in the configured S3 logs bucket."""
    bucket = _bucket_for(environment)
    client = _s3_client()
    response = client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=limit)
    objects = response.get("Contents", [])
    objects.sort(key=lambda item: item["LastModified"], reverse=True)

    return [
        {
            "bucket": bucket,
            "key": item["Key"],
            "size": item["Size"],
            "last_modified": item["LastModified"].isoformat(),
        }
        for item in objects[:limit]
    ]


@mcp.tool()
def get_recent_logs(
    environment: Environment,
    minutes: int = 5,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return recent Docker container log records from S3."""
    bucket = _bucket_for(environment)
    client = _s3_client()
    cutoff = datetime.now(UTC) - timedelta(minutes=minutes)
    prefix = "logs/"

    paginator = client.get_paginator("list_objects_v2")
    matches: list[dict[str, Any]] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            if item["LastModified"] >= cutoff:
                matches.append(item)

    matches.sort(key=lambda item: item["LastModified"], reverse=True)
    records: list[dict[str, Any]] = []
    for item in matches:
        obj = client.get_object(Bucket=bucket, Key=item["Key"])
        text = _decode_log_object(obj["Body"].read(), item["Key"])
        for record in _parse_log_lines(text):
            record["_s3_key"] = item["Key"]
            record["_s3_last_modified"] = item["LastModified"].isoformat()
            records.append(record)
            if len(records) >= limit:
                return records

    return records


@mcp.tool()
def query_prometheus(environment: Environment, query: str) -> dict[str, Any]:
    """Run an instant PromQL query against the configured Prometheus URL."""
    base_url = _prometheus_url_for(environment)
    url = f"{base_url}/api/v1/query?{urlencode({'query': query})}"
    with urlopen(url, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


@mcp.tool()
def get_cpu_usage(environment: Environment, minutes: int = 10) -> dict[str, Any]:
    """Return recent CPU usage for the agent, frontend, and yolo services."""
    window = f"{minutes}m"
    query = (
        "sum by (job) (rate(process_cpu_seconds_total"
        f'{{job=~"agent|frontend|yolo"}}[{window}]))'
    )
    return query_prometheus(environment, query)


if __name__ == "__main__":
    mcp.run(transport="stdio")
