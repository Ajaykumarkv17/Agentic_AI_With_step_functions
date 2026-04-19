"""Unit tests for the Merge Lambda handler."""

import json
import os
from unittest.mock import MagicMock, patch, call

import pytest

from Agentic_AI_With_step_functions.backend.lambdas.merge.handler import (
    _build_notices,
    _index_agent_outputs,
    _parse_llm_response,
    _persist_to_s3,
    _persist_to_dynamodb,
    handler,
)


# ---------------------------------------------------------------------------
# _build_notices
# ---------------------------------------------------------------------------


class TestBuildNotices:
    def test_no_fallback_agents(self):
        outputs = [
            {"agent": "destination_researcher", "is_fallback": False},
            {"agent": "budget_optimizer", "is_fallback": False},
            {"agent": "weather_analyzer", "is_fallback": False},
            {"agent": "experience_curator", "is_fallback": False},
        ]
        assert _build_notices(outputs) == []

    def test_single_fallback_agent(self):
        outputs = [
            {"agent": "destination_researcher", "is_fallback": True},
            {"agent": "budget_optimizer", "is_fallback": False},
        ]
        notices = _build_notices(outputs)
        assert len(notices) == 1
        assert notices[0]["section"] == "destination_researcher"
        assert notices[0]["type"] == "fallback_data"

    def test_multiple_fallback_agents(self):
        outputs = [
            {"agent": "destination_researcher", "is_fallback": True},
            {"agent": "budget_optimizer", "is_fallback": False},
            {"agent": "weather_analyzer", "is_fallback": True},
            {"agent": "experience_curator", "is_fallback": False},
        ]
        notices = _build_notices(outputs)
        assert len(notices) == 2
        sections = {n["section"] for n in notices}
        assert sections == {"destination_researcher", "weather_analyzer"}

    def test_all_fallback_agents(self):
        outputs = [
            {"agent": "destination_researcher", "is_fallback": True},
            {"agent": "budget_optimizer", "is_fallback": True},
            {"agent": "weather_analyzer", "is_fallback": True},
            {"agent": "experience_curator", "is_fallback": True},
        ]
        notices = _build_notices(outputs)
        assert len(notices) == 4

    def test_missing_is_fallback_treated_as_false(self):
        outputs = [{"agent": "destination_researcher"}]
        assert _build_notices(outputs) == []


# ---------------------------------------------------------------------------
# _parse_llm_response
# ---------------------------------------------------------------------------


class TestParseLlmResponse:
    def test_parses_valid_response(self):
        response = {
            "output": {
                "message": {
                    "content": [
                        {"text": json.dumps({"days": [], "summary": {}})}
                    ]
                }
            }
        }
        result = _parse_llm_response(response)
        assert result == {"days": [], "summary": {}}

    def test_raises_on_empty_content(self):
        with pytest.raises(ValueError, match="Failed to parse"):
            _parse_llm_response({"output": {"message": {"content": []}}})

    def test_raises_on_invalid_json(self):
        response = {
            "output": {
                "message": {
                    "content": [{"text": "not valid json"}]
                }
            }
        }
        with pytest.raises(ValueError, match="Failed to parse"):
            _parse_llm_response(response)


# ---------------------------------------------------------------------------
# _index_agent_outputs
# ---------------------------------------------------------------------------


class TestIndexAgentOutputs:
    def test_indexes_by_agent_name(self):
        outputs = [
            {"agent": "destination_researcher", "data": "dest"},
            {"agent": "budget_optimizer", "data": "budget"},
        ]
        indexed = _index_agent_outputs(outputs)
        assert "destination_researcher" in indexed
        assert "budget_optimizer" in indexed
        assert indexed["destination_researcher"]["data"] == "dest"

    def test_skips_outputs_without_agent_key(self):
        outputs = [{"data": "no agent"}, {"agent": "budget_optimizer"}]
        indexed = _index_agent_outputs(outputs)
        assert len(indexed) == 1
        assert "budget_optimizer" in indexed


# ---------------------------------------------------------------------------
# _persist_to_s3
# ---------------------------------------------------------------------------


class TestPersistToS3:
    def test_stores_itinerary_and_agent_outputs(self):
        mock_s3 = MagicMock()
        itinerary = {"itinerary_id": "abc", "days": []}
        agent_outputs = [
            {"agent": "destination_researcher"},
            {"agent": "budget_optimizer"},
        ]

        _persist_to_s3(mock_s3, "test-bucket", "abc", itinerary, agent_outputs)

        # 1 itinerary + 2 agent outputs = 3 put_object calls
        assert mock_s3.put_object.call_count == 3

        # Verify itinerary key
        first_call = mock_s3.put_object.call_args_list[0]
        assert first_call.kwargs["Key"] == "itineraries/abc/itinerary.json"

        # Verify agent output keys
        agent_keys = [
            c.kwargs["Key"] for c in mock_s3.put_object.call_args_list[1:]
        ]
        assert "itineraries/abc/agent_outputs/destination_researcher.json" in agent_keys
        assert "itineraries/abc/agent_outputs/budget_optimizer.json" in agent_keys


# ---------------------------------------------------------------------------
# _persist_to_dynamodb
# ---------------------------------------------------------------------------


class TestPersistToDynamodb:
    def test_updates_record_with_itinerary_and_completed_status(self):
        mock_table = MagicMock()
        itinerary = {"itinerary_id": "abc", "days": []}

        _persist_to_dynamodb(mock_table, "abc", itinerary)

        mock_table.update_item.assert_called_once()
        call_kwargs = mock_table.update_item.call_args.kwargs
        assert call_kwargs["Key"] == {"itinerary_id": "abc"}
        assert call_kwargs["ExpressionAttributeValues"][":status"] == "completed"
        assert call_kwargs["ExpressionAttributeValues"][":itinerary"] == itinerary


# ---------------------------------------------------------------------------
# handler (integration-style with mocks)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _env_vars(monkeypatch):
    monkeypatch.setenv("ITINERARY_TABLE_NAME", "test-itinerary-table")
    monkeypatch.setenv("CIRCUIT_BREAKER_TABLE_NAME", "test-cb-table")
    monkeypatch.setenv("ARTIFACT_BUCKET_NAME", "test-bucket")


def _make_llm_itinerary():
    """Return a sample LLM-generated itinerary for mocking."""
    return {
        "days": [
            {
                "date": "2025-03-01",
                "destination": "Jaipur",
                "weather": {
                    "temp_min": 15,
                    "temp_max": 30,
                    "precipitation_pct": 5,
                    "conditions": "Sunny",
                    "advisory": None,
                },
                "slots": {
                    "morning": {
                        "activity": "Amber Fort Visit",
                        "type": "sightseeing",
                        "description": "Explore the historic Amber Fort",
                        "estimated_cost_inr": 500,
                        "is_festival_event": False,
                    },
                    "afternoon": {
                        "activity": "Local Cuisine Tour",
                        "type": "food",
                        "description": "Try dal baati churma",
                        "estimated_cost_inr": 800,
                        "is_festival_event": False,
                    },
                    "evening": {
                        "activity": "Bazaar Shopping",
                        "type": "shopping",
                        "description": "Shop at Johari Bazaar",
                        "estimated_cost_inr": 1500,
                        "is_festival_event": False,
                    },
                },
                "transport": None,
                "accommodation": {
                    "name": "Heritage Haveli",
                    "type": "hotel",
                    "cost_per_night_inr": 2500,
                },
                "day_cost_inr": 5300,
            }
        ],
        "summary": {
            "total_cost_inr": 5300,
            "packing_advisory": ["Sunscreen", "Light cotton clothes"],
            "highlighted_experiences": ["Amber Fort Visit", "Local Cuisine Tour"],
            "budget_tier_selected": "economy",
        },
    }


def _make_agent_outputs(fallback_agents=None):
    """Return sample agent outputs. Agents in fallback_agents are marked fallback."""
    fallback_agents = fallback_agents or []
    return [
        {
            "agent": "destination_researcher",
            "is_fallback": "destination_researcher" in fallback_agents,
            "destinations": [{"name": "Jaipur", "relevance_score": 0.9}],
        },
        {
            "agent": "budget_optimizer",
            "is_fallback": "budget_optimizer" in fallback_agents,
            "budget_tiers": [{"tier": "economy", "total_inr": 5000}],
        },
        {
            "agent": "weather_analyzer",
            "is_fallback": "weather_analyzer" in fallback_agents,
            "daily_forecasts": [{"date": "2025-03-01", "conditions": "Sunny"}],
        },
        {
            "agent": "experience_curator",
            "is_fallback": "experience_curator" in fallback_agents,
            "experiences": [{"name": "Amber Fort", "type": "culture"}],
        },
    ]


class TestHandler:
    @patch("backend.lambdas.merge.handler.BedrockClient")
    @patch("backend.lambdas.merge.handler.CircuitBreaker")
    @patch("backend.lambdas.merge.handler.boto3")
    def test_successful_merge(self, mock_boto3, mock_cb_cls, mock_bedrock_cls):
        # Mock DynamoDB table
        mock_table = MagicMock()
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3.resource.return_value = mock_resource

        # Mock S3 client
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        # Mock Bedrock response
        llm_itinerary = _make_llm_itinerary()
        mock_bedrock = MagicMock()
        mock_bedrock.converse.return_value = {
            "output": {
                "message": {
                    "content": [{"text": json.dumps(llm_itinerary)}]
                }
            }
        }
        mock_bedrock_cls.return_value = mock_bedrock

        event = {
            "itinerary_id": "test-merge-123",
            "trip_request": {
                "query": "Trip to Jaipur",
                "dates": {"start": "2025-03-01", "end": "2025-03-01"},
                "budget": 10000,
            },
            "agent_outputs": _make_agent_outputs(),
        }

        result = handler(event, None)

        assert result["itinerary_id"] == "test-merge-123"
        assert len(result["days"]) == 1
        assert result["summary"]["total_cost_inr"] == 5300
        assert result["notices"] == []
        assert "created_at" in result

        # DynamoDB should be updated (completed status)
        mock_table.update_item.assert_called_once()

        # S3 should have 5 put_object calls (1 itinerary + 4 agent outputs)
        assert mock_s3.put_object.call_count == 5

    @patch("backend.lambdas.merge.handler.BedrockClient")
    @patch("backend.lambdas.merge.handler.CircuitBreaker")
    @patch("backend.lambdas.merge.handler.boto3")
    def test_fallback_agents_produce_notices(
        self, mock_boto3, mock_cb_cls, mock_bedrock_cls
    ):
        mock_table = MagicMock()
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3.resource.return_value = mock_resource
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        llm_itinerary = _make_llm_itinerary()
        mock_bedrock = MagicMock()
        mock_bedrock.converse.return_value = {
            "output": {
                "message": {
                    "content": [{"text": json.dumps(llm_itinerary)}]
                }
            }
        }
        mock_bedrock_cls.return_value = mock_bedrock

        event = {
            "itinerary_id": "test-fallback-456",
            "trip_request": {
                "query": "Trip to Goa",
                "dates": {"start": "2025-03-01", "end": "2025-03-01"},
                "budget": 15000,
            },
            "agent_outputs": _make_agent_outputs(
                fallback_agents=["weather_analyzer", "budget_optimizer"]
            ),
        }

        result = handler(event, None)

        assert len(result["notices"]) == 2
        notice_sections = {n["section"] for n in result["notices"]}
        assert notice_sections == {"weather_analyzer", "budget_optimizer"}
        for notice in result["notices"]:
            assert notice["type"] == "fallback_data"

    @patch("backend.lambdas.merge.handler.BedrockClient")
    @patch("backend.lambdas.merge.handler.CircuitBreaker")
    @patch("backend.lambdas.merge.handler.boto3")
    def test_failure_updates_status_to_failed(
        self, mock_boto3, mock_cb_cls, mock_bedrock_cls
    ):
        mock_table = MagicMock()
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3.resource.return_value = mock_resource
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        # Make Bedrock raise an error
        mock_bedrock = MagicMock()
        mock_bedrock.converse.side_effect = RuntimeError("Bedrock down")
        mock_bedrock_cls.return_value = mock_bedrock

        event = {
            "itinerary_id": "test-fail-789",
            "trip_request": {
                "query": "Trip to Kerala",
                "dates": {"start": "2025-04-01", "end": "2025-04-03"},
                "budget": 20000,
            },
            "agent_outputs": _make_agent_outputs(),
        }

        with pytest.raises(RuntimeError):
            handler(event, None)

        # Should have updated status to "failed"
        update_calls = mock_table.update_item.call_args_list
        assert len(update_calls) == 1
        last_call = update_calls[-1].kwargs
        assert last_call["ExpressionAttributeValues"][":status"] == "failed"

    @patch("backend.lambdas.merge.handler.BedrockClient")
    @patch("backend.lambdas.merge.handler.CircuitBreaker")
    @patch("backend.lambdas.merge.handler.boto3")
    def test_no_bucket_skips_s3(self, mock_boto3, mock_cb_cls, mock_bedrock_cls, monkeypatch):
        monkeypatch.setenv("ARTIFACT_BUCKET_NAME", "")

        mock_table = MagicMock()
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3.resource.return_value = mock_resource
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        llm_itinerary = _make_llm_itinerary()
        mock_bedrock = MagicMock()
        mock_bedrock.converse.return_value = {
            "output": {
                "message": {
                    "content": [{"text": json.dumps(llm_itinerary)}]
                }
            }
        }
        mock_bedrock_cls.return_value = mock_bedrock

        event = {
            "itinerary_id": "test-no-s3",
            "trip_request": {
                "query": "Trip",
                "dates": {"start": "2025-03-01", "end": "2025-03-01"},
                "budget": 5000,
            },
            "agent_outputs": _make_agent_outputs(),
        }

        result = handler(event, None)

        # S3 should NOT have been called
        mock_s3.put_object.assert_not_called()
        # But DynamoDB should still be updated
        mock_table.update_item.assert_called_once()
        assert result["itinerary_id"] == "test-no-s3"
