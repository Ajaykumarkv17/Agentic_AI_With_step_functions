"""Budget Optimizer Agent Lambda handler.

Analyzes a trip request's budget constraints in INR using Amazon Bedrock
and external pricing APIs to produce a two-tier budget breakdown with
overage detection and savings tips.

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
from Agentic_AI_With_step_functions.backend.lambdas.budget_optimizer.prompts import (
    AGENT_NAME,
    AGENT_ROLE,
    AGENT_INSTRUCTIONS,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

AGENT_KEY = "budget_optimizer"


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
    """Query external pricing APIs for transport, accommodation, and activity costs.

    Uses circuit-breaker-wrapped API clients for pricing data.

    Args:
        api_clients: Dict mapping service name to ApiClient instance.
        trip_request: The original trip request dict.

    Returns:
        Dict with keys ``transport_pricing``, ``accommodation_pricing``,
        ``activity_pricing`` containing the API response data (or fallback).
    """
    dates = trip_request.get("dates", {})
    cache_suffix = f"{dates.get('start', '')}_{dates.get('end', '')}"

    results: dict = {}

    transport_client = api_clients.get("transport_pricing")
    if transport_client:
        results["transport_pricing"] = transport_client.get_json(
            url=os.environ.get("MOCK_API_URL", "").rstrip("/") + "/pricing/transport",
            cache_key=f"transport_{cache_suffix}",
            timeout=10,
            fallback_fn=lambda: {"prices": [], "_generated": True},
        )

    accommodation_client = api_clients.get("accommodation_pricing")
    if accommodation_client:
        results["accommodation_pricing"] = accommodation_client.get_json(
            url=os.environ.get("MOCK_API_URL", "").rstrip("/") + "/pricing/accommodation",
            cache_key=f"accommodation_{cache_suffix}",
            timeout=10,
            fallback_fn=lambda: {"prices": [], "_generated": True},
        )

    activity_client = api_clients.get("activity_pricing")
    if activity_client:
        results["activity_pricing"] = activity_client.get_json(
            url=os.environ.get("MOCK_API_URL", "").rstrip("/") + "/pricing/activities",
            cache_key=f"activities_{cache_suffix}",
            timeout=10,
            fallback_fn=lambda: {"prices": [], "_generated": True},
        )

    return results


def _parse_llm_response(response: dict) -> dict:
    """Extract and parse the JSON body from a Bedrock Converse response.

    Args:
        response: Raw Bedrock Converse API response dict.

    Returns:
        Parsed dict matching the BudgetOutput schema.

    Raises:
        ValueError: If the response cannot be parsed as JSON.
    """
    try:
        content_blocks = response["output"]["message"]["content"]
        text = content_blocks[0]["text"]
        return json.loads(text)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise ValueError(f"Failed to parse LLM response: {exc}") from exc


def _apply_overage_detection(output: dict, trip_budget: float) -> dict:
    """Set overage_flag and overage_amount_inr based on the economy tier.

    If the economy (lowest) tier total exceeds the trip budget, sets
    overage_flag=True and computes the overage amount. Ensures
    savings_tips is a non-empty list when over budget.

    Args:
        output: The parsed BudgetOutput dict.
        trip_budget: The traveler's stated budget in INR.

    Returns:
        The same dict with overage fields applied.
    """
    tiers = output.get("budget_tiers", [])

    # Find the economy tier (lowest total)
    economy_tier = None
    for tier in tiers:
        if tier.get("tier") == "economy":
            economy_tier = tier
            break

    if economy_tier is None and tiers:
        # Fallback: use the tier with the lowest total
        economy_tier = min(tiers, key=lambda t: t.get("total_inr", 0))

    if economy_tier is not None:
        economy_total = economy_tier.get("total_inr", 0)
        if economy_total > trip_budget:
            output["overage_flag"] = True
            output["overage_amount_inr"] = round(economy_total - trip_budget, 2)
            if not output.get("savings_tips"):
                output["savings_tips"] = [
                    "Consider traveling during off-peak season for lower prices.",
                    "Look for budget accommodations like hostels or homestays.",
                    "Use trains instead of flights for shorter routes.",
                ]
        else:
            output["overage_flag"] = False
            output.pop("overage_amount_inr", None)
    else:
        output["overage_flag"] = False

    output.setdefault("savings_tips", [])
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
        3. Query external pricing APIs through circuit breakers.
        4. Call Bedrock to analyze budget and generate two-tier breakdown.
        5. Apply overage detection against the trip budget.
        6. Update agent status to "completed" (or "failed" on error).
        7. Return BudgetOutput dict.

    Args:
        event: Step Functions task input dict.
        context: Lambda context (unused).

    Returns:
        BudgetOutput dict.
    """
    itinerary_id = event["itinerary_id"]
    trip_request = event["trip_request"]
    trip_budget = float(trip_request.get("budget", 0))

    table = _get_table()
    cb_table = _get_cb_table()

    # Mark agent as running
    _update_agent_status(table, itinerary_id, "running")

    try:
        # --- Set up circuit-breaker-wrapped API clients ---
        api_clients = {
            "transport_pricing": ApiClient(
                "pricing",
                CircuitBreaker("transport_pricing_api", cb_table),
            ),
            "accommodation_pricing": ApiClient(
                "pricing",
                CircuitBreaker("accommodation_pricing_api", cb_table),
            ),
            "activity_pricing": ApiClient(
                "pricing",
                CircuitBreaker("activity_pricing_api", cb_table),
            ),
        }

        # --- Query external pricing APIs ---
        external_data = _query_external_apis(api_clients, trip_request)

        # --- Build prompt and call Bedrock ---
        system_prompt = build_system_prompt(
            agent_name=AGENT_NAME,
            agent_role=AGENT_ROLE,
            agent_instructions=AGENT_INSTRUCTIONS,
        )

        user_text = (
            f"Trip request: {json.dumps(trip_request)}\n\n"
            f"External pricing data:\n{json.dumps(external_data)}"
        )
        messages = build_user_message(user_text)

        bedrock_cb = CircuitBreaker("bedrock_nova_pro", cb_table)
        bedrock = BedrockClient(bedrock_cb)
        response = bedrock.converse(messages, system_prompt)

        # --- Parse and validate output ---
        output = _parse_llm_response(response)
        output["agent"] = AGENT_KEY
        output.setdefault("is_fallback", False)
        output = _apply_overage_detection(output, trip_budget)

        # Mark agent as completed
        _update_agent_status(table, itinerary_id, "completed")

        return output

    except Exception:
        logger.exception("Budget Optimizer agent failed")
        _update_agent_status(table, itinerary_id, "failed")
        raise
