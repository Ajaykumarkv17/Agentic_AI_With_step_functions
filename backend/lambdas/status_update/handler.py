"""Status Update Lambda handler.

Updates the workflow status in DynamoDB ItineraryStore during
Step Functions execution. Called at state transitions (started,
agents_running, merging, completed, failed).

Runtime: Python 3.12
Trigger: Step Functions task states
Timeout: 10 seconds

Environment variables:
    ITINERARY_TABLE_NAME: DynamoDB ItineraryStore table name.
"""

import os
from datetime import datetime, timezone

import boto3


def handler(event, context):
    """Update workflow status in DynamoDB.

    Args:
        event: Dict with ``itinerary_id`` and ``status`` keys.
        context: Lambda context (unused).

    Returns:
        Dict echoing the itinerary_id and new status.
    """
    itinerary_id = event["itinerary_id"]
    status = event["status"]

    table_name = os.environ["ITINERARY_TABLE_NAME"]
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    now_iso = datetime.now(timezone.utc).isoformat()

    table.update_item(
        Key={"itinerary_id": itinerary_id},
        UpdateExpression="SET #s = :status, updated_at = :now",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": status, ":now": now_iso},
    )

    return {"itinerary_id": itinerary_id, "status": status}
