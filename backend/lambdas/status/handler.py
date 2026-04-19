"""Workflow Status Lambda handler.

Retrieves the current workflow status record for a given itinerary ID
from DynamoDB ItineraryStore. Returns the overall status and per-agent
progress so the frontend can render the workflow visualization.

Runtime: Python 3.12
Trigger: API Gateway GET /trips/{id}/status
Timeout: 10 seconds

Environment variables:
    ITINERARY_TABLE_NAME: DynamoDB ItineraryStore table name.
"""

import json
import logging
import os

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def handler(event, context):
    """Lambda entry point for GET /trips/{id}/status.

    Fetches the itinerary record and returns only the status-related
    fields: ``itinerary_id``, ``status``, ``agents_status``, and
    ``updated_at``.

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
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    # Use a projection expression to fetch only status fields for speed
    result = table.get_item(
        Key={"itinerary_id": itinerary_id},
        ProjectionExpression="itinerary_id, #s, agents_status, updated_at",
        ExpressionAttributeNames={"#s": "status"},
    )
    item = result.get("Item")

    if not item:
        return _response(404, {"error": f"Itinerary '{itinerary_id}' not found"})

    status_record = {
        "itinerary_id": item.get("itinerary_id", itinerary_id),
        "status": item.get("status", "unknown"),
        "agents": item.get("agents_status", {}),
        "updated_at": item.get("updated_at", ""),
    }

    return _response(200, status_record)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
