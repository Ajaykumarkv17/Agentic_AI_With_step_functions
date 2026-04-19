"""Experience Curator Agent Lambda handler.

Curates local experiences, street food, festivals, and cultural activities
for Indian travel destinations using Amazon Bedrock and external tourism
APIs. Cross-references travel dates with the Indian Holiday Calendar to
include festival events when dates overlap.

Runtime: Python 3.12
Trigger: Step Functions parallel branch
Timeout: 60 seconds

Environment variables:
    ITINERARY_TABLE_NAME: DynamoDB ItineraryStore table name.
    CIRCUIT_BREAKER_TABLE_NAME: DynamoDB CircuitBreakerTable name.
    ARTIFACT_BUCKET_NAME: S3 ArtifactStore bucket name.
"""

import json
import logging
import os
from datetime import date, datetime, timezone

import boto3

from Agentic_AI_With_step_functions.backend.shared.bedrock_client import BedrockClient
from Agentic_AI_With_step_functions.backend.shared.circuit_breaker import CircuitBreaker
from Agentic_AI_With_step_functions.backend.shared.api_client import ApiClient
from Agentic_AI_With_step_functions.backend.shared.cache import read_cache
from Agentic_AI_With_step_functions.backend.shared.prompts import build_system_prompt, build_user_message
from Agentic_AI_With_step_functions.backend.lambdas.experience_curator.prompts import (
    AGENT_NAME,
    AGENT_ROLE,
    AGENT_INSTRUCTIONS,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

AGENT_KEY = "experience_curator"
VALID_EXPERIENCE_TYPES = {"food", "culture", "adventure", "relaxation", "shopping"}
HOLIDAY_CALENDAR_S3_KEY = "reference/indian_holiday_calendar.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_table():
    """Return a boto3 DynamoDB Table resource for the ItineraryStore."""
    dynamodb = boto3.resource("dynamodb")
    return dynamodb.Table(os.environ["ITINERARY_TABLE_NAME"])


def _get_cb_table():
    """Return a boto3 DynamoDB Table resource for the CircuitBreakerTable."""
    dynamodb = boto3.resource("dynamodb")
    return dynamodb.Table(os.environ["CIRCUIT_BREAKER_TABLE_NAME"])


def _update_agent_status(table, itinerary_id: str, status: str) -> None:
    """Update this agent's status in the ItineraryStore.

    Args:
        table: DynamoDB Table resource.
        itinerary_id: The itinerary identifier.
        status: New status value (e.g. "running", "completed", "failed").
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    table.update_item(
        Key={"itinerary_id": itinerary_id},
        UpdateExpression=(
            "SET agents_status.#agent = :status, updated_at = :now"
        ),
        ExpressionAttributeNames={"#agent": AGENT_KEY},
        ExpressionAttributeValues={":status": status, ":now": now_iso},
    )


def _load_holiday_calendar() -> list[dict]:
    """Load the Indian Holiday Calendar JSON from S3 via the cache module.

    Reads from ``reference/indian_holiday_calendar.json`` in the
    ArtifactStore bucket. Returns an empty list if the file cannot be
    loaded.

    Returns:
        List of holiday entry dicts.
    """
    bucket = os.environ.get("ARTIFACT_BUCKET_NAME", "")
    if not bucket:
        logger.warning("ARTIFACT_BUCKET_NAME not set — skipping holiday calendar")
        return []

    try:
        s3 = boto3.client("s3")
        response = s3.get_object(Bucket=bucket, Key=HOLIDAY_CALENDAR_S3_KEY)
        body = response["Body"].read().decode("utf-8")
        calendar = json.loads(body)
        if isinstance(calendar, list):
            return calendar
        # Handle wrapper object with a list inside
        return calendar.get("holidays", calendar.get("entries", []))
    except Exception:
        logger.warning(
            "Failed to load holiday calendar from s3://%s/%s",
            bucket,
            HOLIDAY_CALENDAR_S3_KEY,
            exc_info=True,
        )
        return []


def filter_holidays_for_dates(
    calendar: list[dict], start_date: str, end_date: str
) -> list[dict]:
    """Filter holiday entries whose date falls within [start, end].

    This filtering is done in Python code — not by the LLM — to ensure
    deterministic, correct holiday inclusion.

    Args:
        calendar: Full list of holiday entry dicts from the calendar JSON.
        start_date: ISO8601 date string (YYYY-MM-DD) for trip start.
        end_date: ISO8601 date string (YYYY-MM-DD) for trip end.

    Returns:
        List of holiday entries that overlap with the travel dates.
    """
    if not start_date or not end_date:
        return []

    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError:
        logger.warning("Invalid date format: start=%s, end=%s", start_date, end_date)
        return []

    overlapping = []
    for entry in calendar:
        entry_date_str = entry.get("date", "")
        if not entry_date_str:
            continue
        try:
            entry_date = date.fromisoformat(entry_date_str)
        except ValueError:
            continue
        if start <= entry_date <= end:
            overlapping.append(entry)

    return overlapping


def _query_external_apis(api_clients: dict, trip_request: dict) -> dict:
    """Query external tourism APIs for experience data.

    Uses a circuit-breaker-wrapped API client for tourism board APIs.

    Args:
        api_clients: Dict mapping service name to ApiClient instance.
        trip_request: The original trip request dict.

    Returns:
        Dict with key ``tourism`` containing the API response data
        (or fallback data).
    """
    dates = trip_request.get("dates", {})
    cache_suffix = f"{dates.get('start', '')}_{dates.get('end', '')}"

    results: dict = {}

    tourism_client = api_clients.get("tourism")
    if tourism_client:
        results["tourism"] = tourism_client.get_json(
            url=os.environ.get("MOCK_API_URL", "").rstrip("/") + "/tourism/experiences",
            cache_key=f"experiences_{cache_suffix}",
            timeout=10,
            fallback_fn=lambda: {"experiences": [], "_generated": True},
        )

    return results


def _parse_llm_response(response: dict) -> dict:
    """Extract and parse the JSON body from a Bedrock Converse response.

    Args:
        response: Raw Bedrock Converse API response dict.

    Returns:
        Parsed dict matching the ExperienceOutput schema.

    Raises:
        ValueError: If the response cannot be parsed as JSON.
    """
    try:
        content_blocks = response["output"]["message"]["content"]
        text = content_blocks[0]["text"]
        return json.loads(text)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise ValueError(f"Failed to parse LLM response: {exc}") from exc


def _validate_experience_types(output: dict) -> dict:
    """Ensure all experiences have a valid type from the allowed set.

    Invalid types are replaced with "culture" as a safe default.

    Args:
        output: The parsed ExperienceOutput dict.

    Returns:
        The same dict with validated experience types.
    """
    for exp in output.get("experiences", []):
        if exp.get("type") not in VALID_EXPERIENCE_TYPES:
            logger.warning(
                "Invalid experience type '%s' for '%s' — defaulting to 'culture'",
                exp.get("type"),
                exp.get("name"),
            )
            exp["type"] = "culture"
    return output


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------


def handler(event, context):
    """Lambda entry point invoked by Step Functions.

    Expects ``event`` to contain ``itinerary_id`` and ``trip_request``.

    Steps:
        1. Parse input from Step Functions.
        2. Update agent status to "running".
        3. Load Indian Holiday Calendar from S3.
        4. Filter holidays that overlap with travel dates [start, end].
        5. Query tourism APIs through circuit breaker.
        6. Call Bedrock to generate experience recommendations, passing
           overlapping holidays as context.
        7. Validate experience types.
        8. Prioritize festival-related experiences when travel dates
           coincide with major festivals.
        9. Update agent status to "completed" (or "failed" on error).
       10. Return ExperienceOutput dict.

    Args:
        event: Step Functions task input dict.
        context: Lambda context (unused).

    Returns:
        ExperienceOutput dict.
    """
    itinerary_id = event["itinerary_id"]
    trip_request = event["trip_request"]

    table = _get_table()
    cb_table = _get_cb_table()

    # Mark agent as running
    _update_agent_status(table, itinerary_id, "running")

    try:
        # --- Load and filter holiday calendar ---
        calendar = _load_holiday_calendar()
        dates = trip_request.get("dates", {})
        start_date = dates.get("start", "")
        end_date = dates.get("end", "")
        overlapping_holidays = filter_holidays_for_dates(
            calendar, start_date, end_date
        )

        logger.info(
            "Found %d holidays overlapping with travel dates %s to %s",
            len(overlapping_holidays),
            start_date,
            end_date,
        )

        # --- Set up circuit-breaker-wrapped API client ---
        api_clients = {
            "tourism": ApiClient(
                "tourism",
                CircuitBreaker("tourism_api", cb_table),
            ),
        }

        # --- Query external tourism APIs ---
        external_data = _query_external_apis(api_clients, trip_request)

        # --- Build prompt and call Bedrock ---
        system_prompt = build_system_prompt(
            agent_name=AGENT_NAME,
            agent_role=AGENT_ROLE,
            agent_instructions=AGENT_INSTRUCTIONS,
        )

        holiday_context = ""
        if overlapping_holidays:
            holiday_context = (
                "\n\nOverlapping Indian holidays/festivals during travel dates:\n"
                f"{json.dumps(overlapping_holidays, indent=2)}\n"
                "IMPORTANT: Include festival-specific experiences for these "
                "holidays and add each to the festival_events list."
            )

        user_text = (
            f"Trip request: {json.dumps(trip_request)}\n\n"
            f"Tourism API data:\n{json.dumps(external_data)}"
            f"{holiday_context}"
        )
        messages = build_user_message(user_text)

        bedrock_cb = CircuitBreaker("bedrock_nova_pro", cb_table)
        bedrock = BedrockClient(bedrock_cb)
        response = bedrock.converse(messages, system_prompt)

        # --- Parse and validate output ---
        output = _parse_llm_response(response)
        output["agent"] = AGENT_KEY
        output.setdefault("is_fallback", False)
        output.setdefault("experiences", [])
        output.setdefault("festival_events", [])

        # Validate experience types
        output = _validate_experience_types(output)

        # Mark agent as completed
        _update_agent_status(table, itinerary_id, "completed")

        return output

    except Exception:
        logger.exception("Experience Curator agent failed")
        _update_agent_status(table, itinerary_id, "failed")
        raise
