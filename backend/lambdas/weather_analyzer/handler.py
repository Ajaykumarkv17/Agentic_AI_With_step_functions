"""Weather Analyzer Agent Lambda handler.

Retrieves weather forecasts from the IMD API (or equivalent) and uses
Amazon Bedrock to interpret weather data and generate seasonal advisories
for Indian travel destinations.

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
from datetime import date, datetime, timedelta, timezone

import boto3

from Agentic_AI_With_step_functions.backend.shared.bedrock_client import BedrockClient
from Agentic_AI_With_step_functions.backend.shared.circuit_breaker import CircuitBreaker
from Agentic_AI_With_step_functions.backend.shared.api_client import ApiClient
from Agentic_AI_With_step_functions.backend.shared.prompts import build_system_prompt, build_user_message
from Agentic_AI_With_step_functions.backend.lambdas.weather_analyzer.prompts import (
    AGENT_NAME,
    AGENT_ROLE,
    AGENT_INSTRUCTIONS,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

AGENT_KEY = "weather_analyzer"


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


def _compute_monsoon_warning(start_date: str, end_date: str) -> bool:
    """Check if any date in the travel range falls within monsoon season.

    Monsoon season is defined as June 1 through September 30 (months 6-9).

    Args:
        start_date: ISO8601 date string (YYYY-MM-DD) for trip start.
        end_date: ISO8601 date string (YYYY-MM-DD) for trip end.

    Returns:
        True if any date in [start_date, end_date] falls in June-September.
    """
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)

    current = start
    while current <= end:
        if 6 <= current.month <= 9:
            return True
        current += timedelta(days=1)

    return False


def _query_external_apis(api_clients: dict, trip_request: dict) -> dict:
    """Query the IMD weather API for forecast data.

    Uses a circuit-breaker-wrapped API client for the Indian
    Meteorological Department (IMD) API.

    Args:
        api_clients: Dict mapping service name to ApiClient instance.
        trip_request: The original trip request dict.

    Returns:
        Dict with key ``weather`` containing the API response data
        (or fallback data).
    """
    dates = trip_request.get("dates", {})
    cache_suffix = f"{dates.get('start', '')}_{dates.get('end', '')}"

    results: dict = {}

    imd_client = api_clients.get("imd")
    if imd_client:
        results["weather"] = imd_client.get_json(
            url=os.environ.get("MOCK_API_URL", "").rstrip("/") + "/weather/forecast",
            cache_key=f"weather_{cache_suffix}",
            timeout=10,
            fallback_fn=lambda: {"forecasts": [], "_generated": True},
        )

    return results


def _parse_llm_response(response: dict) -> dict:
    """Extract and parse the JSON body from a Bedrock Converse response.

    Args:
        response: Raw Bedrock Converse API response dict.

    Returns:
        Parsed dict matching the WeatherOutput schema.

    Raises:
        ValueError: If the response cannot be parsed as JSON.
    """
    try:
        content_blocks = response["output"]["message"]["content"]
        text = content_blocks[0]["text"]
        return json.loads(text)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise ValueError(f"Failed to parse LLM response: {exc}") from exc


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------


def handler(event, context):
    """Lambda entry point invoked by Step Functions.

    Expects ``event`` to contain ``itinerary_id`` and ``trip_request``.

    Steps:
        1. Parse input from Step Functions.
        2. Update agent status to "running".
        3. Query IMD weather API through circuit breaker.
        4. Call Bedrock to interpret weather data and generate advisories.
        5. Compute monsoon_warning in Python (true if any travel date
           falls in June-September).
        6. Update agent status to "completed" (or "failed" on error).
        7. Return WeatherOutput dict.

    Args:
        event: Step Functions task input dict.
        context: Lambda context (unused).

    Returns:
        WeatherOutput dict.
    """
    itinerary_id = event["itinerary_id"]
    trip_request = event["trip_request"]

    table = _get_table()
    cb_table = _get_cb_table()

    # Mark agent as running
    _update_agent_status(table, itinerary_id, "running")

    try:
        # --- Set up circuit-breaker-wrapped API client ---
        api_clients = {
            "imd": ApiClient(
                "imd",
                CircuitBreaker("imd_api", cb_table),
            ),
        }

        # --- Query external weather API ---
        external_data = _query_external_apis(api_clients, trip_request)

        # --- Build prompt and call Bedrock ---
        system_prompt = build_system_prompt(
            agent_name=AGENT_NAME,
            agent_role=AGENT_ROLE,
            agent_instructions=AGENT_INSTRUCTIONS,
        )

        user_text = (
            f"Trip request: {json.dumps(trip_request)}\n\n"
            f"Weather API data:\n{json.dumps(external_data)}"
        )
        messages = build_user_message(user_text)

        bedrock_cb = CircuitBreaker("bedrock_nova_pro", cb_table)
        bedrock = BedrockClient(bedrock_cb)
        response = bedrock.converse(messages, system_prompt)

        # --- Parse and validate output ---
        output = _parse_llm_response(response)
        output["agent"] = AGENT_KEY
        output.setdefault("is_fallback", False)

        # --- Compute monsoon_warning in Python (not LLM) ---
        dates = trip_request.get("dates", {})
        start_date = dates.get("start", "")
        end_date = dates.get("end", "")
        if start_date and end_date:
            output["monsoon_warning"] = _compute_monsoon_warning(
                start_date, end_date
            )
        else:
            output["monsoon_warning"] = False

        # Ensure advisories is a list
        output.setdefault("advisories", [])
        output.setdefault("daily_forecasts", [])

        # Mark agent as completed
        _update_agent_status(table, itinerary_id, "completed")

        return output

    except Exception:
        logger.exception("Weather Analyzer agent failed")
        _update_agent_status(table, itinerary_id, "failed")
        raise
