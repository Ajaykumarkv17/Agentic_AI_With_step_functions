"""Unit tests for the Destination Researcher Agent handler."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from Agentic_AI_With_step_functions.backend.lambdas.destination_researcher.handler import (
    _ensure_sorted_destinations,
    _parse_llm_response,
    handler,
)


# ---------------------------------------------------------------------------
# _parse_llm_response
# ---------------------------------------------------------------------------


class TestParseLlmResponse:
    def test_parses_valid_response(self):
        response = {
            "output": {
                "message": {
                    "content": [
                        {"text": json.dumps({"destinations": []})}
                    ]
                }
            }
        }
        result = _parse_llm_response(response)
        assert result == {"destinations": []}

    def test_raises_on_missing_content(self):
        with pytest.raises(ValueError, match="Failed to parse"):
            _parse_llm_response({"output": {"message": {"content": []}}})

    def test_raises_on_invalid_json(self):
        response = {
            "output": {
                "message": {
                    "content": [{"text": "not json"}]
                }
            }
        }
        with pytest.raises(ValueError, match="Failed to parse"):
            _parse_llm_response(response)


# ---------------------------------------------------------------------------
# _ensure_sorted_destinations
# ---------------------------------------------------------------------------


class TestEnsureSortedDestinations:
    def test_sorts_descending_by_relevance(self):
        output = {
            "destinations": [
                {"name": "A", "relevance_score": 0.3},
                {"name": "B", "relevance_score": 0.9},
                {"name": "C", "relevance_score": 0.6},
            ]
        }
        result = _ensure_sorted_destinations(output)
        scores = [d["relevance_score"] for d in result["destinations"]]
        assert scores == [0.9, 0.6, 0.3]

    def test_handles_empty_destinations(self):
        output = {"destinations": []}
        result = _ensure_sorted_destinations(output)
        assert result["destinations"] == []

    def test_handles_missing_destinations_key(self):
        output = {}
        result = _ensure_sorted_destinations(output)
        assert result["destinations"] == []

    def test_handles_missing_relevance_score(self):
        output = {
            "destinations": [
                {"name": "A"},
                {"name": "B", "relevance_score": 0.5},
            ]
        }
        result = _ensure_sorted_destinations(output)
        assert result["destinations"][0]["name"] == "B"
        assert result["destinations"][1]["name"] == "A"


# ---------------------------------------------------------------------------
# handler (integration-style with mocks)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _env_vars(monkeypatch):
    monkeypatch.setenv("ITINERARY_TABLE_NAME", "test-itinerary-table")
    monkeypatch.setenv("CIRCUIT_BREAKER_TABLE_NAME", "test-cb-table")
    monkeypatch.setenv("ARTIFACT_BUCKET_NAME", "test-bucket")


class TestHandler:
    @patch("backend.lambdas.destination_researcher.handler.BedrockClient")
    @patch("backend.lambdas.destination_researcher.handler.ApiClient")
    @patch("backend.lambdas.destination_researcher.handler.CircuitBreaker")
    @patch("backend.lambdas.destination_researcher.handler.boto3")
    def test_successful_execution(
        self, mock_boto3, mock_cb_cls, mock_api_cls, mock_bedrock_cls
    ):
        # Mock DynamoDB table
        mock_table = MagicMock()
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3.resource.return_value = mock_resource

        # Mock ApiClient to return empty data
        mock_api_instance = MagicMock()
        mock_api_instance.get_json.return_value = {"routes": []}
        mock_api_cls.return_value = mock_api_instance

        # Mock Bedrock response
        llm_output = {
            "agent": "destination_researcher",
            "is_fallback": False,
            "destinations": [
                {"name": "Goa", "relevance_score": 0.7,
                 "highlights": ["Beaches"], "travel_tips": ["Pack sunscreen"]},
                {"name": "Jaipur", "relevance_score": 0.9,
                 "highlights": ["Forts"], "travel_tips": ["Visit Amber Fort"]},
            ],
            "transport_options": [],
            "accommodations": [],
        }
        mock_bedrock = MagicMock()
        mock_bedrock.converse.return_value = {
            "output": {
                "message": {
                    "content": [{"text": json.dumps(llm_output)}]
                }
            }
        }
        mock_bedrock_cls.return_value = mock_bedrock

        event = {
            "itinerary_id": "test-123",
            "trip_request": {
                "query": "Beach vacation in India",
                "dates": {"start": "2025-01-01", "end": "2025-01-07"},
                "budget": 50000,
            },
        }

        result = handler(event, None)

        # Destinations should be sorted descending
        assert result["destinations"][0]["name"] == "Jaipur"
        assert result["destinations"][1]["name"] == "Goa"
        assert result["agent"] == "destination_researcher"
        assert result["is_fallback"] is False

        # Agent status should have been updated twice: running + completed
        assert mock_table.update_item.call_count == 2

    @patch("backend.lambdas.destination_researcher.handler.BedrockClient")
    @patch("backend.lambdas.destination_researcher.handler.ApiClient")
    @patch("backend.lambdas.destination_researcher.handler.CircuitBreaker")
    @patch("backend.lambdas.destination_researcher.handler.boto3")
    def test_failure_updates_status_to_failed(
        self, mock_boto3, mock_cb_cls, mock_api_cls, mock_bedrock_cls
    ):
        mock_table = MagicMock()
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3.resource.return_value = mock_resource

        mock_api_instance = MagicMock()
        mock_api_instance.get_json.side_effect = RuntimeError("API down")
        mock_api_cls.return_value = mock_api_instance

        event = {
            "itinerary_id": "test-456",
            "trip_request": {
                "query": "Mountain trek",
                "dates": {"start": "2025-03-01", "end": "2025-03-05"},
                "budget": 30000,
            },
        }

        with pytest.raises(RuntimeError):
            handler(event, None)

        # Should have updated status to "running" then "failed"
        assert mock_table.update_item.call_count == 2
