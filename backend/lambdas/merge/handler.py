"""Merge Lambda handler.

Combines outputs from all four AI agents into a cohesive day-by-day
itinerary using Amazon Bedrock (Nova Pro). Annotates sections that used
fallback data, generates a summary, and persists the merged itinerary
to DynamoDB and S3.

Runtime: Python 3.12
Trigger: Step Functions MergeResults state
Timeout: 90 seconds

Environment variables:
    ITINERARY_TABLE_NAME: DynamoDB ItineraryStore table name.
    CIRCUIT_BREAKER_TABLE_NAME: DynamoDB CircuitBreakerTable name.
    ARTIFACT_BUCKET_NAME: S3 ArtifactStore bucket name.
"""

import json
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3

from Agentic_AI_With_step_functions.backend.shared.bedrock_client import BedrockClient
from Agentic_AI_With_step_functions.backend.shared.circuit_breaker import CircuitBreaker
from Agentic_AI_With_step_functions.backend.shared.prompts import build_system_prompt, build_user_message

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

AGENT_NAMES = [
    "destination_researcher",
    "budget_optimizer",
    "weather_analyzer",
    "experience_curator",
]

MERGE_SYSTEM_PROMPT_NAME = "Itinerary Merge Agent"
MERGE_SYSTEM_PROMPT_ROLE = (
    "Synthesize outputs from four travel agents into a cohesive, "
    "day-by-day travel itinerary for Indian travelers."
)

MERGE_INSTRUCTIONS = """You are merging outputs from four travel agents into a single itinerary.

You will receive:
- trip_request: the original user request with query, dates, budget, preferences
- destination_output: destinations, transport options, accommodations
- budget_output: budget tiers (economy/comfort), breakdown, savings tips
- weather_output: daily forecasts, advisories, monsoon warnings
- experience_output: curated experiences, festival events

Produce a JSON object with this EXACT structure:
{
  "days": [
    {
      "date": "YYYY-MM-DD",
      "destination": "City Name",
      "weather": {
        "temp_min": <number>,
        "temp_max": <number>,
        "precipitation_pct": <number>,
        "conditions": "<string>",
        "advisory": "<string or null>"
      },
      "slots": {
        "morning": {
          "activity": "<name>",
          "type": "<food|culture|adventure|relaxation|shopping|transit|sightseeing>",
          "description": "<string>",
          "estimated_cost_inr": <number>,
          "is_festival_event": <boolean>
        },
        "afternoon": { ... same structure ... },
        "evening": { ... same structure ... }
      },
      "transport": {
        "mode": "<train|flight|bus|car>",
        "from": "<city>",
        "to": "<city>",
        "duration_hours": <number>,
        "cost_inr": <number>
      } or null,
      "accommodation": {
        "name": "<string>",
        "type": "<hotel|hostel|homestay|resort>",
        "cost_per_night_inr": <number>
      },
      "day_cost_inr": <number>
    }
  ],
  "summary": {
    "total_cost_inr": <number>,
    "packing_advisory": ["<item1>", "<item2>", ...],
    "highlighted_experiences": ["<exp1>", "<exp2>", ...],
    "budget_tier_selected": "<economy|comfort>"
  }
}

Rules:
- Create one DayPlan for each date in the travel date range.
- Each day MUST have morning, afternoon, and evening activity slots.
- Use weather data to inform activity suggestions and packing advisory.
- Use budget data to select appropriate tier and cost estimates.
- Include festival events from experience data when dates match.
- total_cost_inr must equal the sum of all day_cost_inr values.
- packing_advisory must be non-empty and weather-informed.
- highlighted_experiences must be non-empty.
- Respond ONLY with valid JSON. No text outside the JSON object.
"""


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


def _get_s3_client():
    """Return a boto3 S3 client."""
    return boto3.client("s3")


def _build_notices(agent_outputs: list[dict]) -> list[dict]:
    """Build Notice objects for agents that returned fallback data.

    Inspects each agent output for ``is_fallback: true`` and creates a
    Notice with the appropriate section name and message.

    Args:
        agent_outputs: List of the four agent output dicts.

    Returns:
        List of Notice dicts.
    """
    notices: list[dict] = []
    for output in agent_outputs:
        if output.get("is_fallback", False):
            agent_name = output.get("agent", "unknown")
            notices.append({
                "section": agent_name,
                "message": (
                    f"Data from {agent_name.replace('_', ' ').title()} "
                    f"used fallback or cached information and may not "
                    f"reflect the latest availability."
                ),
                "type": "fallback_data",
            })
    return notices


def _parse_llm_response(response: dict) -> dict:
    """Extract and parse the JSON body from a Bedrock Converse response.

    Args:
        response: Raw Bedrock Converse API response dict.

    Returns:
        Parsed dict with ``days`` and ``summary`` keys.

    Raises:
        ValueError: If the response cannot be parsed as JSON.
    """
    try:
        content_blocks = response["output"]["message"]["content"]
        text = content_blocks[0]["text"]
        return json.loads(text)
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise ValueError(f"Failed to parse LLM response: {exc}") from exc


def _index_agent_outputs(agent_outputs: list[dict]) -> dict[str, dict]:
    """Index agent outputs by agent name for easy lookup.

    Args:
        agent_outputs: List of agent output dicts, each with an ``agent`` key.

    Returns:
        Dict mapping agent name to its output dict.
    """
    indexed: dict[str, dict] = {}
    for output in agent_outputs:
        agent = output.get("agent", "")
        if agent:
            indexed[agent] = output
    return indexed


def _persist_to_s3(
    s3_client, bucket: str, itinerary_id: str,
    itinerary: dict, agent_outputs: list[dict],
) -> None:
    """Persist the merged itinerary and individual agent outputs to S3.

    Stores:
    - ``itineraries/{id}/itinerary.json`` — full merged itinerary
    - ``itineraries/{id}/agent_outputs/{agent}.json`` — per-agent output

    Args:
        s3_client: boto3 S3 client.
        bucket: ArtifactStore bucket name.
        itinerary_id: Unique itinerary identifier.
        itinerary: The complete merged itinerary dict.
        agent_outputs: List of the four agent output dicts.
    """
    # Store merged itinerary
    s3_client.put_object(
        Bucket=bucket,
        Key=f"itineraries/{itinerary_id}/itinerary.json",
        Body=json.dumps(itinerary, default=str),
        ContentType="application/json",
    )
    logger.info("Stored merged itinerary to s3://%s/itineraries/%s/itinerary.json", bucket, itinerary_id)

    # Store individual agent outputs
    for output in agent_outputs:
        agent_name = output.get("agent", "unknown")
        s3_client.put_object(
            Bucket=bucket,
            Key=f"itineraries/{itinerary_id}/agent_outputs/{agent_name}.json",
            Body=json.dumps(output, default=str),
            ContentType="application/json",
        )
    logger.info("Stored %d agent outputs to S3", len(agent_outputs))


def _floats_to_decimal(obj):
    """Recursively convert float values to Decimal for DynamoDB compatibility."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_floats_to_decimal(v) for v in obj]
    return obj


def _persist_to_dynamodb(table, itinerary_id: str, itinerary: dict) -> None:
    """Update the ItineraryStore record with the merged itinerary.

    Sets the ``itinerary`` attribute, updates ``status`` to "completed",
    and records the ``updated_at`` timestamp.

    Args:
        table: DynamoDB Table resource.
        itinerary_id: Unique itinerary identifier.
        itinerary: The complete merged itinerary dict.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    table.update_item(
        Key={"itinerary_id": itinerary_id},
        UpdateExpression=(
            "SET itinerary = :itinerary, #st = :status, "
            "updated_at = :now"
        ),
        ExpressionAttributeNames={"#st": "status"},
        ExpressionAttributeValues={
            ":itinerary": _floats_to_decimal(itinerary),
            ":status": "completed",
            ":now": now_iso,
        },
    )
    logger.info("Updated DynamoDB record for itinerary %s to completed", itinerary_id)


def _synthesize_itinerary(
    bedrock: BedrockClient,
    trip_request: dict,
    agent_outputs_indexed: dict[str, dict],
) -> dict:
    """Call Bedrock to synthesize a day-by-day itinerary from agent outputs.

    Args:
        bedrock: BedrockClient instance with circuit breaker.
        trip_request: The original trip request dict.
        agent_outputs_indexed: Dict mapping agent name to output.

    Returns:
        Parsed dict with ``days`` and ``summary`` keys.
    """
    system_prompt = build_system_prompt(
        agent_name=MERGE_SYSTEM_PROMPT_NAME,
        agent_role=MERGE_SYSTEM_PROMPT_ROLE,
        agent_instructions=MERGE_INSTRUCTIONS,
    )

    user_text = (
        f"Trip request:\n{json.dumps(trip_request)}\n\n"
        f"Destination Researcher output:\n"
        f"{json.dumps(agent_outputs_indexed.get('destination_researcher', {}))}\n\n"
        f"Budget Optimizer output:\n"
        f"{json.dumps(agent_outputs_indexed.get('budget_optimizer', {}))}\n\n"
        f"Weather Analyzer output:\n"
        f"{json.dumps(agent_outputs_indexed.get('weather_analyzer', {}))}\n\n"
        f"Experience Curator output:\n"
        f"{json.dumps(agent_outputs_indexed.get('experience_curator', {}))}"
    )
    messages = build_user_message(user_text)

    response = bedrock.converse(messages, system_prompt)
    return _parse_llm_response(response)


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------


def handler(event, context):
    """Lambda entry point invoked by Step Functions MergeResults state.

    Expects ``event`` to contain:
    - ``itinerary_id``: unique identifier
    - ``trip_request``: original trip request dict
    - ``agent_outputs``: list of 4 agent output dicts

    Steps:
        1. Parse input from Step Functions.
        2. Identify agents that used fallback data and build Notice objects.
        3. Call Bedrock to synthesize a day-by-day itinerary.
        4. Assemble the complete itinerary with notices and metadata.
        5. Persist to DynamoDB ItineraryStore (update existing record).
        6. Persist full itinerary JSON and agent outputs to S3.
        7. Update workflow status to "completed".
        8. Return the merged itinerary.

    Args:
        event: Step Functions task input dict.
        context: Lambda context (unused).

    Returns:
        Complete Itinerary dict.
    """
    itinerary_id = event["itinerary_id"]
    trip_request = event["trip_request"]
    agent_outputs = event.get("agent_outputs", [])

    table = _get_table()
    cb_table = _get_cb_table()
    s3_client = _get_s3_client()
    bucket = os.environ.get("ARTIFACT_BUCKET_NAME", "")

    try:
        # --- Build fallback notices ---
        notices = _build_notices(agent_outputs)
        if notices:
            logger.info(
                "Fallback data detected for agents: %s",
                [n["section"] for n in notices],
            )

        # --- Index agent outputs by name ---
        agent_outputs_indexed = _index_agent_outputs(agent_outputs)

        # --- Call Bedrock to synthesize itinerary ---
        bedrock_cb = CircuitBreaker("bedrock_nova_pro", cb_table)
        bedrock = BedrockClient(bedrock_cb)
        merged = _synthesize_itinerary(bedrock, trip_request, agent_outputs_indexed)

        # --- Assemble complete itinerary ---
        now_iso = datetime.now(timezone.utc).isoformat()
        itinerary = {
            "itinerary_id": itinerary_id,
            "trip_request": trip_request,
            "days": merged.get("days", []),
            "summary": merged.get("summary", {}),
            "notices": notices,
            "created_at": now_iso,
        }

        # --- Persist to S3 ---
        if bucket:
            _persist_to_s3(s3_client, bucket, itinerary_id, itinerary, agent_outputs)

        # --- Persist to DynamoDB (update existing record, set status completed) ---
        _persist_to_dynamodb(table, itinerary_id, itinerary)

        return itinerary

    except Exception:
        logger.exception("Merge Lambda failed for itinerary %s", itinerary_id)
        # Update status to failed
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            table.update_item(
                Key={"itinerary_id": itinerary_id},
                UpdateExpression="SET #st = :status, updated_at = :now",
                ExpressionAttributeNames={"#st": "status"},
                ExpressionAttributeValues={
                    ":status": "failed",
                    ":now": now_iso,
                },
            )
        except Exception:
            logger.exception("Failed to update status to failed")
        raise
