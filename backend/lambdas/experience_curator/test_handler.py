"""Unit tests for the Experience Curator Agent handler."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from Agentic_AI_With_step_functions.backend.lambdas.experience_curator.handler import (
    _parse_llm_response,
    _validate_experience_types,
    filter_holidays_for_dates,
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
                        {"text": json.dumps({"experiences": []})}
                    ]
                }
            }
        }
        result = _parse_llm_response(response)
        assert result == {"experiences": []}

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
# filter_holidays_for_dates
# ---------------------------------------------------------------------------


class TestFilterHolidaysForDates:
    def test_returns_overlapping_holidays(self):
        calendar = [
            {"date": "2025-01-26", "name": "Republic Day", "type": "national"},
            {"date": "2025-03-14", "name": "Holi", "type": "national"},
            {"date": "2025-08-15", "name": "Independence Day", "type": "national"},
        ]
        result = filter_holidays_for_dates(calendar, "2025-01-01", "2025-02-28")
        assert len(result) == 1
        assert result[0]["name"] == "Republic Day"

    def test_returns_empty_for_no_overlap(self):
        calendar = [
            {"date": "2025-11-01", "name": "Diwali", "type": "national"},
        ]
        result = filter_holidays_for_dates(calendar, "2025-01-01", "2025-02-28")
        assert result == []

    def test_includes_boundary_dates(self):
        calendar = [
            {"date": "2025-03-01", "name": "Start Holiday", "type": "national"},
            {"date": "2025-03-10", "name": "End Holiday", "type": "national"},
        ]
        result = filter_holidays_for_dates(calendar, "2025-03-01", "2025-03-10")
        assert len(result) == 2

    def test_handles_empty_calendar(self):
        result = filter_holidays_for_dates([], "2025-01-01", "2025-12-31")
        assert result == []

    def test_handles_empty_dates(self):
        calendar = [{"date": "2025-01-26", "name": "Republic Day"}]
        assert filter_holidays_for_dates(calendar, "", "2025-02-28") == []
        assert filter_holidays_for_dates(calendar, "2025-01-01", "") == []

    def test_handles_invalid_date_format(self):
        calendar = [{"date": "2025-01-26", "name": "Republic Day"}]
        result = filter_holidays_for_dates(calendar, "not-a-date", "2025-02-28")
        assert result == []

    def test_skips_entries_with_invalid_dates(self):
        calendar = [
            {"date": "bad-date", "name": "Bad Entry"},
            {"date": "2025-01-26", "name": "Republic Day", "type": "national"},
        ]
        result = filter_holidays_for_dates(calendar, "2025-01-01", "2025-02-28")
        assert len(result) == 1
        assert result[0]["name"] == "Republic Day"

    def test_skips_entries_without_date(self):
        calendar = [
            {"name": "No Date Entry"},
            {"date": "2025-01-26", "name": "Republic Day"},
        ]
        result = filter_holidays_for_dates(calendar, "2025-01-01", "2025-02-28")
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _validate_experience_types
# ---------------------------------------------------------------------------


class TestValidateExperienceTypes:
    def test_valid_types_unchanged(self):
        output = {
            "experiences": [
                {"name": "Street Food Tour", "type": "food"},
                {"name": "Temple Visit", "type": "culture"},
                {"name": "Scuba Diving", "type": "adventure"},
                {"name": "Spa Day", "type": "relaxation"},
                {"name": "Market Walk", "type": "shopping"},
            ]
        }
        result = _validate_experience_types(output)
        types = [e["type"] for e in result["experiences"]]
        assert types == ["food", "culture", "adventure", "relaxation", "shopping"]

    def test_invalid_type_defaults_to_culture(self):
        output = {
            "experiences": [
                {"name": "Unknown Activity", "type": "sightseeing"},
            ]
        }
        result = _validate_experience_types(output)
        assert result["experiences"][0]["type"] == "culture"

    def test_missing_type_defaults_to_culture(self):
        output = {
            "experiences": [
                {"name": "No Type Activity"},
            ]
        }
        result = _validate_experience_types(output)
        assert result["experiences"][0]["type"] == "culture"

    def test_empty_experiences(self):
        output = {"experiences": []}
        result = _validate_experience_types(output)
        assert result["experiences"] == []


# ---------------------------------------------------------------------------
# handler (integration-style with mocks)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _env_vars(monkeypatch):
    monkeypatch.setenv("ITINERARY_TABLE_NAME", "test-itinerary-table")
    monkeypatch.setenv("CIRCUIT_BREAKER_TABLE_NAME", "test-cb-table")
    monkeypatch.setenv("ARTIFACT_BUCKET_NAME", "test-bucket")


class TestHandler:
    @patch("backend.lambdas.experience_curator.handler.BedrockClient")
    @patch("backend.lambdas.experience_curator.handler.ApiClient")
    @patch("backend.lambdas.experience_curator.handler.CircuitBreaker")
    @patch("backend.lambdas.experience_curator.handler._load_holiday_calendar")
    @patch("backend.lambdas.experience_curator.handler.boto3")
    def test_successful_execution(
        self, mock_boto3, mock_load_cal, mock_cb_cls, mock_api_cls, mock_bedrock_cls
    ):
        # Mock DynamoDB table
        mock_table = MagicMock()
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3.resource.return_value = mock_resource

        # Mock holiday calendar with one overlapping holiday
        mock_load_cal.return_value = [
            {
                "date": "2025-01-26",
                "name": "Republic Day",
                "type": "national",
                "travel_impact": {
                    "transport_demand": "high",
                    "price_impact": "elevated",
                    "closures": ["government offices"],
                },
            },
        ]

        # Mock ApiClient
        mock_api_instance = MagicMock()
        mock_api_instance.get_json.return_value = {"experiences": []}
        mock_api_cls.return_value = mock_api_instance

        # Mock Bedrock response
        llm_output = {
            "agent": "experience_curator",
            "is_fallback": False,
            "experiences": [
                {
                    "name": "Republic Day Parade Viewing",
                    "type": "culture",
                    "description": "Watch the grand parade at Rajpath",
                    "estimated_cost_inr": 0,
                    "location": "New Delhi",
                },
                {
                    "name": "Street Food Tour",
                    "type": "food",
                    "description": "Explore Chandni Chowk street food",
                    "estimated_cost_inr": 500,
                    "location": "Old Delhi",
                },
            ],
            "festival_events": [
                {
                    "name": "Republic Day",
                    "date": "2025-01-26",
                    "description": "National celebration with parade",
                    "location": "New Delhi",
                },
            ],
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
                "query": "Cultural trip to Delhi",
                "dates": {"start": "2025-01-24", "end": "2025-01-28"},
                "budget": 30000,
            },
        }

        result = handler(event, None)

        assert result["agent"] == "experience_curator"
        assert result["is_fallback"] is False
        assert len(result["experiences"]) == 2
        assert len(result["festival_events"]) == 1
        # All experience types should be valid
        for exp in result["experiences"]:
            assert exp["type"] in {"food", "culture", "adventure", "relaxation", "shopping"}

        # Agent status should have been updated twice: running + completed
        assert mock_table.update_item.call_count == 2

    @patch("backend.lambdas.experience_curator.handler.BedrockClient")
    @patch("backend.lambdas.experience_curator.handler.ApiClient")
    @patch("backend.lambdas.experience_curator.handler.CircuitBreaker")
    @patch("backend.lambdas.experience_curator.handler._load_holiday_calendar")
    @patch("backend.lambdas.experience_curator.handler.boto3")
    def test_failure_updates_status_to_failed(
        self, mock_boto3, mock_load_cal, mock_cb_cls, mock_api_cls, mock_bedrock_cls
    ):
        mock_table = MagicMock()
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3.resource.return_value = mock_resource

        mock_load_cal.return_value = []

        mock_api_instance = MagicMock()
        mock_api_instance.get_json.side_effect = RuntimeError("API down")
        mock_api_cls.return_value = mock_api_instance

        event = {
            "itinerary_id": "test-456",
            "trip_request": {
                "query": "Beach trip to Goa",
                "dates": {"start": "2025-03-01", "end": "2025-03-05"},
                "budget": 40000,
            },
        }

        with pytest.raises(RuntimeError):
            handler(event, None)

        # Should have updated status to "running" then "failed"
        assert mock_table.update_item.call_count == 2

    @patch("backend.lambdas.experience_curator.handler.BedrockClient")
    @patch("backend.lambdas.experience_curator.handler.ApiClient")
    @patch("backend.lambdas.experience_curator.handler.CircuitBreaker")
    @patch("backend.lambdas.experience_curator.handler._load_holiday_calendar")
    @patch("backend.lambdas.experience_curator.handler.boto3")
    def test_no_holidays_still_works(
        self, mock_boto3, mock_load_cal, mock_cb_cls, mock_api_cls, mock_bedrock_cls
    ):
        mock_table = MagicMock()
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3.resource.return_value = mock_resource

        mock_load_cal.return_value = []

        mock_api_instance = MagicMock()
        mock_api_instance.get_json.return_value = {"experiences": []}
        mock_api_cls.return_value = mock_api_instance

        llm_output = {
            "experiences": [
                {
                    "name": "Beach Relaxation",
                    "type": "relaxation",
                    "description": "Relax on the beach",
                    "estimated_cost_inr": 0,
                    "location": "Goa",
                },
            ],
            "festival_events": [],
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
            "itinerary_id": "test-789",
            "trip_request": {
                "query": "Relaxing beach trip",
                "dates": {"start": "2025-06-01", "end": "2025-06-05"},
                "budget": 25000,
            },
        }

        result = handler(event, None)

        assert result["agent"] == "experience_curator"
        assert result["festival_events"] == []
        assert len(result["experiences"]) == 1
