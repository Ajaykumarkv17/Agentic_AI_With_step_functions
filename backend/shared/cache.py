"""S3 cache read/write helpers for external API responses.

Stores and retrieves cached API responses in the S3 ArtifactStore bucket
under the ``cache/{service_prefix}/{key}.json`` key structure.  This allows
agents to serve stale-but-usable data when an external API is unavailable
or the circuit breaker is OPEN.

Environment variables:
    ARTIFACT_BUCKET_NAME: Name of the S3 ArtifactStore bucket.
"""

import json
import logging
import os

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_BUCKET_NAME = os.environ.get("ARTIFACT_BUCKET_NAME", "")


def _get_bucket_name() -> str:
    """Return the configured bucket name, raising if unset."""
    name = _BUCKET_NAME or os.environ.get("ARTIFACT_BUCKET_NAME", "")
    if not name:
        raise ValueError("ARTIFACT_BUCKET_NAME environment variable is not set")
    return name


def _s3_client():
    """Return a boto3 S3 client (module-level helper for testability)."""
    return boto3.client("s3")


def write_cache(service_prefix: str, key: str, data: dict) -> None:
    """Write a JSON response to the S3 cache.

    Args:
        service_prefix: Folder under ``cache/`` (e.g. "irctc", "imd").
        key: Unique identifier for this cached item.
        data: The JSON-serialisable response payload.
    """
    bucket = _get_bucket_name()
    s3_key = f"cache/{service_prefix}/{key}.json"
    try:
        _s3_client().put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=json.dumps(data),
            ContentType="application/json",
        )
        logger.info("Cached response at s3://%s/%s", bucket, s3_key)
    except ClientError:
        logger.warning("Failed to write cache at s3://%s/%s", bucket, s3_key, exc_info=True)


def read_cache(service_prefix: str, key: str) -> dict | None:
    """Read a cached JSON response from S3.

    Args:
        service_prefix: Folder under ``cache/`` (e.g. "irctc", "imd").
        key: Unique identifier for the cached item.

    Returns:
        The cached dict, or ``None`` if no cache entry exists or the read fails.
    """
    bucket = _get_bucket_name()
    s3_key = f"cache/{service_prefix}/{key}.json"
    try:
        response = _s3_client().get_object(Bucket=bucket, Key=s3_key)
        body = response["Body"].read().decode("utf-8")
        return json.loads(body)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code == "NoSuchKey":
            logger.info("No cache entry at s3://%s/%s", bucket, s3_key)
        else:
            logger.warning("Failed to read cache at s3://%s/%s", bucket, s3_key, exc_info=True)
        return None
