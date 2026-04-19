"""Fallback Lambda handler for failed agent recovery.

Invoked by Step Functions Catch blocks when an agent fails after all
retries.  Attempts to serve cached data from S3 first; if no cache
exists, calls Bedrock with Nova Lite directly to generate best-effort
recommendations.

Runtime: Python 3.12
Trigger: Step Functions Catch block
Timeout: 30 seconds

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

from Agentic_AI_With_step_functions.backend.shared.cache import read_cache
from Agentic_AI_With_step_functions.backend.shared.prompts import build_system_prompt, build_user_message

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

FALLBACK_MODEL = "us.amazon.nova-lite-v1:0"

# Maps agent names to the S3 cache service prefixes they use.
AGENT_CACHE_PREFIXES: dict[str, list[str]] = {
    "destination_researcher": ["irctc", "flights", "accommodations"],
    "budget_optimizer": ["pricing"],
    "weather_analyzer": ["imd"],
    "experience_curator": ["tourism"],
}

# Agent-specific fallback prompt instructions for Nova Lite best-effort generation.
AGENT_FALLBACK_PROMPTS: dict[str, dict[str, str]] = {
    "destination_researcher": {
        "name": "Destination Researcher (Fallback)",
        "role": (
            "Generate best-effort Indian destination recommendations "
            "when live data is unavailable."
        ),
        "instructions": (
            "Based on the trip request, suggest relevant Indian destinations, "
            "transport options, and accommodations. Use your general knowledge. "
            "Respond ONLY with valid JSON matching this schema:\n"
            '{"destinations": [{"name": str, "relevance_score": float, '
            '"highlights": [str], "travel_tips": [str]}], '
            '"transport_options": [{"mode": str, "from": str, "to": str, '
            '"duration_hours": float, "estimated_cost_inr": int}], '
            '"accommodations": [{"name": str, "type": str, "location": str, '
            '"cost_per_night_inr": int}]}'
        ),
    },
    "budget_optimizer": {
        "name": "Budget Optimizer (Fallback)",
        "role": (
            "Generate best-effort budget breakdown in INR "
            "when live pricing data is unavailable."
        ),
        "instructions": (
            "Based on the trip request, produce economy and comfort budget tiers "
            "with breakdowns. Use your general knowledge of Indian travel costs. "
            "Respond ONLY with valid JSON matching this schema:\n"
            '{"budget_tiers": [{"tier": "economy"|"comfort", "total_inr": int, '
            '"breakdown": {"transport": int, "accommodation": int, "food": int, '
            '"activities": int, "contingency": int}}], '
            '"overage_flag": bool, "savings_tips": [str]}'
        ),
    },
    "weather_analyzer": {
        "name": "Weather Analyzer (Fallback)",
        "role": (
            "Generate best-effort weather forecasts and advisories "
            "when the IMD API is unavailable."
        ),
        "instructions": (
            "Based on the trip request destinations and dates, produce daily "
            "weather forecasts and seasonal advisories using general knowledge. "
            "Respond ONLY with valid JSON matching this schema:\n"
            '{"daily_forecasts": [{"date": str, "destination": str, '
            '"temp_min_c": float, "temp_max_c": float, '
            '"precipitation_pct": int, "conditions": str}], '
            '"advisories": [str], "monsoon_warning": bool}'
        ),
    },
    "experience_curator": {
        "name": "Experience Curator (Fallback)",
        "role": (
            "Generate best-effort local experience recommendations "
            "when tourism APIs are unavailable."
        ),
        "instructions": (
            "Based on the trip request, suggest local experiences including "
            "street food, cultural activities, and festivals. "
            "Respond ONLY with valid JSON matching this schema:\n"
            '{"experiences": [{"name": str, "type": '
            '"food"|"culture"|"adventure"|"relaxation"|"shopping", '
            '"description": str, "estimated_cost_inr": int, "location": str}], '
            '"festival_events": [{"name": str, "date": str, '
            '"description": str, "location": str}]}'
        ),
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_table():
    """Return a boto3 DynamoDB Table resource for the ItineraryStore."""
    dynamodb = boto3.resource("dynamodb")
    return dynamodb.Table(os.environ["ITINERARY_TABLE_NAME"])


def _update_agent_status(table, itinerary_id: str, agent_name: str, status: str) -> None:
    """Update the failed agent's status in the ItineraryStore.

    Args:
        table: DynamoDB Table resource.
        itinerary_id: The itinerary identifier.
        agent_name: The agent key (e.g. "destination_researcher").
        status: New status value (e.g. "fallback").
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    table.update_item(
        Key={"itinerary_id": itinerary_id},
        UpdateExpression="SET agents_status.#agent = :status, updated_at = :now",
        ExpressionAttributeNames={"#agent": agent_name},
        ExpressionAttributeValues={":status": status, ":now": now_iso},
    )


def _try_cached_data(agent_name: str, trip_request: dict) -> dict | None:
    """Attempt to read cached API responses for the failed agent from S3.

    Looks up each cache prefix associated with the agent and merges any
    cached data found into a single dict.

    Args:
        agent_name: The agent that failed (e.g. "weather_analyzer").
        trip_request: The original trip request dict (used to derive cache keys).

    Returns:
        A merged dict of cached data, or ``None`` if no cache entries exist.
    """
    prefixes = AGENT_CACHE_PREFIXES.get(agent_name, [])
    if not prefixes:
        return None

    dates = trip_request.get("dates", {})
    cache_suffix = f"{dates.get('start', '')}_{dates.get('end', '')}"

    merged: dict = {}
    for prefix in prefixes:
        cached = read_cache(prefix, cache_suffix)
        if cached is not None:
            merged[prefix] = cached

    return merged if merged else None


def _generate_with_nova_lite(agent_name: str, trip_request: dict) -> dict:
    """Call Bedrock Nova Lite directly to generate best-effort output.

    Bypasses the circuit breaker since this is already the fallback path.

    Args:
        agent_name: The agent that failed.
        trip_request: The original trip request dict.

    Returns:
        Parsed JSON dict from Nova Lite's response.

    Raises:
        ValueError: If the LLM response cannot be parsed as JSON.
    """
    prompt_config = AGENT_FALLBACK_PROMPTS.get(agent_name)
    if not prompt_config:
        logger.warning("No fallback prompt for agent %s", agent_name)
        return {}

    system_prompt = build_system_prompt(
        agent_name=prompt_config["name"],
        agent_role=prompt_config["role"],
        agent_instructions=prompt_config["instructions"],
    )

    user_text = f"Trip request: {json.dumps(trip_request)}"
    messages = build_user_message(user_text)

    client = boto3.client("bedrock-runtime")
    response = client.converse(
        modelId=FALLBACK_MODEL,
        messages=messages,
        system=[{"text": system_prompt}],
    )

    try:
        content_blocks = response["output"]["message"]["content"]
        text = content_blocks[0]["text"]
        return json.loads(text)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise ValueError(f"Failed to parse Nova Lite fallback response: {exc}") from exc


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------


def handler(event, context):
    """Lambda entry point invoked by Step Functions Catch block.

    Expects ``event`` to contain:
        - ``itinerary_id``: The itinerary identifier.
        - ``trip_request``: The original trip request dict.
        - ``agent_name``: Which agent failed (e.g. "destination_researcher").
        - ``error`` (optional): Error details from the failed agent.

    Steps:
        1. Extract agent name and trip request from the event.
        2. Update agent status to "fallback" in DynamoDB.
        3. Try to read cached data from S3 for the failed agent.
        4. If cached data exists, return it with is_fallback=true and
           "stale_data" annotation.
        5. If no cached data, call Nova Lite to generate best-effort output.
        6. Return fallback output with is_fallback=true and appropriate
           annotation.

    Args:
        event: Step Functions Catch block input dict.
        context: Lambda context (unused).

    Returns:
        Agent-compatible output dict with ``is_fallback: true``.
    """
    itinerary_id = event["itinerary_id"]
    trip_request = event["trip_request"]
    agent_name = event["agent_name"]
    error_info = event.get("error", {})

    logger.info(
        "Fallback invoked for agent=%s itinerary=%s error=%s",
        agent_name,
        itinerary_id,
        json.dumps(error_info) if isinstance(error_info, dict) else str(error_info),
    )

    table = _get_table()
    _update_agent_status(table, itinerary_id, agent_name, "fallback")

    # --- Attempt 1: Serve cached data from S3 ---
    cached_data = _try_cached_data(agent_name, trip_request)
    if cached_data is not None:
        logger.info("Serving cached fallback data for agent=%s", agent_name)
        return {
            "agent": agent_name,
            "is_fallback": True,
            "fallback_source": "stale_data",
            "notice": {
                "section": agent_name,
                "message": (
                    f"Data from {agent_name.replace('_', ' ').title()} "
                    f"is based on cached information and may not reflect "
                    f"the latest availability."
                ),
                "type": "stale_data",
            },
            "data": cached_data,
        }

    # --- Attempt 2: Generate best-effort output with Nova Lite ---
    logger.info("No cached data — generating best-effort output for agent=%s", agent_name)
    try:
        generated = _generate_with_nova_lite(agent_name, trip_request)
        return {
            "agent": agent_name,
            "is_fallback": True,
            "fallback_source": "best_effort",
            "notice": {
                "section": agent_name,
                "message": (
                    f"Data from {agent_name.replace('_', ' ').title()} "
                    f"was generated using a lightweight model and may be "
                    f"less detailed than usual."
                ),
                "type": "best_effort",
            },
            **generated,
        }
    except Exception:
        logger.exception("Nova Lite fallback also failed for agent=%s", agent_name)
        return {
            "agent": agent_name,
            "is_fallback": True,
            "fallback_source": "best_effort",
            "notice": {
                "section": agent_name,
                "message": (
                    f"Data from {agent_name.replace('_', ' ').title()} "
                    f"could not be generated. This section is incomplete."
                ),
                "type": "best_effort",
            },
        }
