"""Destination Researcher Agent Lambda handler.

Analyzes a trip request using Amazon Bedrock and external travel APIs
to produce ranked Indian destination recommendations with transport
options and accommodation suggestions.

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
from datetime import datetime, timezone

import boto3

from Agentic_AI_With_step_functions.backend.shared.bedrock_client import BedrockClient
from Agentic_AI_With_step_functions.backend.shared.circuit_breaker import CircuitBreaker
from Agentic_AI_With_step_functions.backend.shared.api_client import ApiClient
from Agentic_AI_With_step_functions.backend.shared.prompts import build_system_prompt, build_user_message
from Agentic_AI_With_step_functions.backend.lambdas.destination_researcher.prompts import (
    AGENT_NAME,
    AGENT_ROLE,
    AGENT_INSTRUCTIONS,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

AGENT_KEY = "destination_researcher"


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


def _query_external_apis(api_clients: dict, trip_request: dict) -> dict:
    """Query external travel APIs for transport and accommodation data.

    Uses circuit-breaker-wrapped API clients for IRCTC (trains),
    flights, and accommodations.

    Args:
        api_clients: Dict mapping service name to ApiClient instance.
        trip_request: The original trip request dict.

    Returns:
        Dict with keys ``trains``, ``flights``, ``accommodations``
        containing the API response data (or fallback data).
    """
    query = trip_request.get("query", "")
    dates = trip_request.get("dates", {})
    cache_suffix = f"{dates.get('start', '')}_{dates.get('end', '')}"

    results: dict = {}

    # IRCTC trains
    irctc_client = api_clients.get("irctc")
    if irctc_client:
        results["trains"] = irctc_client.get_json(
            url=os.environ.get("MOCK_API_URL", "").rstrip("/") + "/trains/search",
            cache_key=f"trains_{cache_suffix}",
            timeout=10,
            fallback_fn=lambda: {"routes": [], "_generated": True},
        )

    # Domestic flights
    flights_client = api_clients.get("flights")
    if flights_client:
        results["flights"] = flights_client.get_json(
            url=os.environ.get("MOCK_API_URL", "").rstrip("/") + "/flights/search",
            cache_key=f"flights_{cache_suffix}",
            timeout=10,
            fallback_fn=lambda: {"flights": [], "_generated": True},
        )

    # Accommodations
    accom_client = api_clients.get("accommodations")
    if accom_client:
        results["accommodations"] = accom_client.get_json(
            url=os.environ.get("MOCK_API_URL", "").rstrip("/") + "/accommodations/search",
            cache_key=f"accommodations_{cache_suffix}",
            timeout=10,
            fallback_fn=lambda: {"listings": [], "_generated": True},
        )

    return results


def _parse_llm_response(response: dict) -> dict:
    """Extract and parse the JSON body from a Bedrock Converse response.

    Args:
        response: Raw Bedrock Converse API response dict.

    Returns:
        Parsed dict matching the DestinationOutput schema.

    Raises:
        ValueError: If the response cannot be parsed as JSON.
    """
    try:
        content_blocks = response["output"]["message"]["content"]
        text = content_blocks[0]["text"]
        return json.loads(text)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise ValueError(f"Failed to parse LLM response: {exc}") from exc


def _ensure_sorted_destinations(output: dict) -> dict:
    """Sort destinations by relevance_score descending in-place.

    Args:
        output: The parsed DestinationOutput dict.

    Returns:
        The same dict with destinations sorted.
    """
    destinations = output.get("destinations", [])
    destinations.sort(key=lambda d: d.get("relevance_score", 0), reverse=True)
    output["destinations"] = destinations
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
        3. Query external APIs through circuit breakers.
        4. Call Bedrock to analyze trip request and generate recommendations.
        5. Sort destinations by relevance_score descending.
        6. Update agent status to "completed" (or "failed" on error).
        7. Return DestinationOutput dict.

    Args:
        event: Step Functions task input dict.
        context: Lambda context (unused).

    Returns:
        DestinationOutput dict.
    """
    itinerary_id = event["itinerary_id"]
    trip_request = event["trip_request"]

    table = _get_table()
    cb_table = _get_cb_table()

    # Mark agent as running
    _update_agent_status(table, itinerary_id, "running")

    try:
        # --- Set up circuit-breaker-wrapped API clients ---
        api_clients = {
            "irctc": ApiClient(
                "irctc",
                CircuitBreaker("irctc_api", cb_table),
            ),
            "flights": ApiClient(
                "flights",
                CircuitBreaker("flights_api", cb_table),
            ),
            "accommodations": ApiClient(
                "accommodations",
                CircuitBreaker("accommodations_api", cb_table),
            ),
        }

        # --- Query external APIs ---
        external_data = _query_external_apis(api_clients, trip_request)

        # --- Build prompt and call Bedrock ---
        system_prompt = build_system_prompt(
            agent_name=AGENT_NAME,
            agent_role=AGENT_ROLE,
            agent_instructions=AGENT_INSTRUCTIONS,
        )

        user_text = (
            f"Trip request: {json.dumps(trip_request)}\n\n"
            f"External API data:\n{json.dumps(external_data)}"
        )
        messages = build_user_message(user_text)

        bedrock_cb = CircuitBreaker("bedrock_nova_pro", cb_table)
        bedrock = BedrockClient(bedrock_cb)
        response = bedrock.converse(messages, system_prompt)

        # --- Parse and validate output ---
        output = _parse_llm_response(response)
        output["agent"] = AGENT_KEY
        output.setdefault("is_fallback", False)
        output = _ensure_sorted_destinations(output)

        # Mark agent as completed
        _update_agent_status(table, itinerary_id, "completed")

        return output

    except Exception:
        logger.exception("Destination Researcher agent failed")
        _update_agent_status(table, itinerary_id, "failed")
        raise
