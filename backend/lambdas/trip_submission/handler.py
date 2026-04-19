"""Trip Submission Lambda handler.

Validates incoming trip requests from API Gateway, creates an initial
status record in DynamoDB ItineraryStore, starts a Step Functions
execution, and returns the generated itinerary ID to the caller.

Runtime: Python 3.12
Trigger: API Gateway POST /trips
Timeout: 10 seconds

Environment variables:
    ITINERARY_TABLE_NAME: DynamoDB table for itinerary records.
    STATE_MACHINE_ARN: (optional) Override. When absent, read from SSM.
"""

import json
import os
import uuid
from datetime import datetime, timezone, timedelta

import boto3

_ssm_client = boto3.client("ssm")
_cached_state_machine_arn: str | None = None


def _get_state_machine_arn() -> str:
    """Resolve the state machine ARN from env var or SSM (cached across invocations)."""
    global _cached_state_machine_arn
    if _cached_state_machine_arn is None:
        env_arn = os.environ.get("STATE_MACHINE_ARN")
        if env_arn:
            _cached_state_machine_arn = env_arn
        else:
            resp = _ssm_client.get_parameter(Name="/travel-concierge/state-machine-arn")
            _cached_state_machine_arn = resp["Parameter"]["Value"]
    return _cached_state_machine_arn


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_MAX_QUERY_LENGTH = 2000


def validate_trip_request(body: dict) -> list[str]:
    """Validate required trip request fields.

    Checks for presence and correctness of: query, dates.start,
    dates.end, and budget.

    Args:
        body: Parsed request body dict.

    Returns:
        A list of human-readable error strings. Empty when valid.
    """
    errors: list[str] = []

    # --- query ---
    query = body.get("query")
    if query is None or (isinstance(query, str) and query.strip() == ""):
        errors.append("'query' is required")
    elif not isinstance(query, str):
        errors.append("'query' must be a string")
    elif len(query) > _MAX_QUERY_LENGTH:
        errors.append(
            f"'query' must be at most {_MAX_QUERY_LENGTH} characters "
            f"(received {len(query)})"
        )

    # --- dates ---
    dates = body.get("dates")
    if dates is None or not isinstance(dates, dict):
        errors.append("'dates.start' is required")
        errors.append("'dates.end' is required")
    else:
        if not dates.get("start"):
            errors.append("'dates.start' is required")
        if not dates.get("end"):
            errors.append("'dates.end' is required")

    # --- budget ---
    budget = body.get("budget")
    if budget is None:
        errors.append("'budget' is required")
    elif not isinstance(budget, (int, float)):
        errors.append("'budget' must be a number")
    elif budget <= 0:
        errors.append("'budget' must be a positive number")

    return errors


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------


def handler(event, context):
    """Lambda entry point for POST /trips.

    Parses the API Gateway event body, validates the trip request,
    creates an initial DynamoDB record, starts the Step Functions
    workflow, and returns the itinerary ID.

    Args:
        event: API Gateway proxy integration event.
        context: Lambda context (unused).

    Returns:
        API Gateway proxy response dict with statusCode and body.
    """
    # Parse request body
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return _response(400, {"error": "Invalid JSON in request body"})

    # Validate
    errors = validate_trip_request(body)
    if errors:
        return _response(400, {"error": "Validation failed", "details": errors})

    # Generate itinerary ID
    itinerary_id = str(uuid.uuid4())

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    ttl = int((now + timedelta(days=30)).timestamp())

    # Build the trip request record stored alongside the itinerary
    trip_request = {
        "query": body["query"],
        "dates": body["dates"],
        "budget": body["budget"],
    }
    if body.get("preferences"):
        trip_request["preferences"] = body["preferences"]

    # Initial DynamoDB record
    table_name = os.environ["ITINERARY_TABLE_NAME"]
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    table.put_item(
        Item={
            "itinerary_id": itinerary_id,
            "status": "started",
            "agents_status": {
                "destination_researcher": "pending",
                "budget_optimizer": "pending",
                "weather_analyzer": "pending",
                "experience_curator": "pending",
            },
            "trip_request": trip_request,
            "created_at": now_iso,
            "updated_at": now_iso,
            "ttl": ttl,
        }
    )

    # Start Step Functions execution
    state_machine_arn = _get_state_machine_arn()
    sfn = boto3.client("stepfunctions")

    sfn.start_execution(
        stateMachineArn=state_machine_arn,
        name=itinerary_id,
        input=json.dumps(
            {
                "itinerary_id": itinerary_id,
                "trip_request": trip_request,
            }
        ),
    )

    return _response(200, {"itinerary_id": itinerary_id})


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
        "body": json.dumps(body),
    }
