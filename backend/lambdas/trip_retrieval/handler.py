"""Trip Retrieval Lambda handler.

Retrieves a full itinerary by ID from DynamoDB ItineraryStore. If the
itinerary record references large artifacts in S3, fetches and inlines
them so the caller receives a complete response.

Runtime: Python 3.12
Trigger: API Gateway GET /trips/{id}
Timeout: 10 seconds

Environment variables:
    ITINERARY_TABLE_NAME: DynamoDB ItineraryStore table name.
    ARTIFACT_BUCKET_NAME: S3 ArtifactStore bucket name.
"""

import json
import logging
import os
from decimal import Decimal

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def handler(event, context):
    """Lambda entry point for GET /trips/{id}.

    Reads the itinerary record from DynamoDB. When the record contains
    ``artifact_keys``, fetches each referenced object from S3 and merges
    the data into the response so the caller receives a self-contained
    itinerary payload.

    Args:
        event: API Gateway proxy integration event.
        context: Lambda context (unused).

    Returns:
        API Gateway proxy response dict.
    """
    itinerary_id = (event.get("pathParameters") or {}).get("id")
    if not itinerary_id:
        return _response(400, {"error": "Missing itinerary ID in path"})

    table_name = os.environ["ITINERARY_TABLE_NAME"]
    bucket_name = os.environ.get("ARTIFACT_BUCKET_NAME", "")

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    result = table.get_item(Key={"itinerary_id": itinerary_id})
    item = result.get("Item")

    if not item:
        return _response(404, {"error": f"Itinerary '{itinerary_id}' not found"})

    # If the itinerary field is missing but we have an S3 artifact, fetch it
    if not item.get("itinerary") and bucket_name:
        s3_itinerary = _fetch_s3_itinerary(bucket_name, itinerary_id)
        if s3_itinerary:
            item["itinerary"] = s3_itinerary

    return _response(200, _serialise_item(item))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fetch_s3_itinerary(bucket: str, itinerary_id: str) -> dict | None:
    """Attempt to fetch the merged itinerary JSON from S3.

    Args:
        bucket: ArtifactStore bucket name.
        itinerary_id: Unique itinerary identifier.

    Returns:
        Parsed itinerary dict, or ``None`` if not found.
    """
    s3_client = boto3.client("s3")
    key = f"itineraries/{itinerary_id}/itinerary.json"
    try:
        obj = s3_client.get_object(Bucket=bucket, Key=key)
        return json.loads(obj["Body"].read().decode("utf-8"))
    except s3_client.exceptions.NoSuchKey:
        logger.info("No S3 artifact found at s3://%s/%s", bucket, key)
        return None
    except Exception:
        logger.exception("Failed to fetch S3 artifact for %s", itinerary_id)
        return None


def _serialise_item(item: dict) -> dict:
    """Convert DynamoDB item to JSON-safe dict.

    DynamoDB returns ``Decimal`` types for numbers. This helper converts
    them to ``int`` or ``float`` as appropriate.

    Args:
        item: Raw DynamoDB item dict.

    Returns:
        JSON-serialisable dict.
    """
    def _convert(obj):
        if isinstance(obj, Decimal):
            return int(obj) if obj == obj.to_integral_value() else float(obj)
        if isinstance(obj, dict):
            return {k: _convert(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_convert(v) for v in obj]
        return obj

    return _convert(item)


def _response(status_code: int, body: dict) -> dict:
    """Build an API Gateway proxy response.

    Args:
        status_code: HTTP status code.
        body: Response body dict (will be JSON-serialised).

    Returns:
        API Gateway proxy response dict.
    """
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }
