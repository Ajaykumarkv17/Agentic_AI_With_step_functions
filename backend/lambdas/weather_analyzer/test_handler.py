"""Unit tests for the Weather Analyzer Agent handler."""

import json
from unittest.mock import MagicMock, patch

import pytest

from Agentic_AI_With_step_functions.backend.lambdas.weather_analyzer.handler import (
    _compute_monsoon_warning,
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
                        {"text": json.dumps({"daily_forecasts": []})}
                    ]
                }
            }
        }
        result = _parse_llm_response(response)
        assert result == {"daily_forecasts": []}

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
# _compute_monsoon_warning
# ---------------------------------------------------------------------------


class TestComputeMonsoonWarning:
    def test_true_when_dates_fully_in_monsoon(self):
        assert _compute_monsoon_warning("2025-07-01", "2025-07-15") is True

    def test_true_when_start_in_monsoon(self):
        assert _compute_monsoon_warning("2025-09-28", "2025-10-05") is True

    def test_true_when_end_in_monsoon(self):
        assert _compute_monsoon_warning("2025-05-25", "2025-06-03") is True

    def test_true_when_range_spans_monsoon(self):
        assert _compute_monsoon_warning("2025-05-01", "2025-10-31") is True

    def test_false_when_before_monsoon(self):
        assert _compute_monsoon_warning("2025-01-01", "2025-05-31") is False

    def test_false_when_after_monsoon(self):
        assert _compute_monsoon_warning("2025-10-01", "2025-12-31") is False

    def test_single_day_in_monsoon(self):
        assert _compute_monsoon_warning("2025-06-01", "2025-06-01") is True

    def test_single_day_outside_monsoon(self):
        assert _compute_monsoon_warning("2025-05-31", "2025-05-31") is False

    def test_boundary_june_1(self):
        assert _compute_monsoon_warning("2025-06-01", "2025-06-01") is True

    def test_boundary_september_30(self):
        assert _compute_monsoon_warning("2025-09-30", "2025-09-30") is True

    def test_boundary_october_1(self):
        assert _compute_monsoon_warning("2025-10-01", "2025-10-01") is False

    def test_boundary_may_31(self):
        assert _compute_monsoon_warning("2025-05-31", "2025-05-31") is False


# ---------------------------------------------------------------------------
# handler (integration-style with mocks)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _env_vars(monkeypatch):
    monkeypatch.setenv("ITINERARY_TABLE_NAME", "test-itinerary-table")
    monkeypatch.setenv("CIRCUIT_BREAKER_TABLE_NAME", "test-cb-table")
    monkeypatch.setenv("ARTIFACT_BUCKET_NAME", "test-bucket")


class TestHandler:
    @patch("backend.lambdas.weather_analyzer.handler.BedrockClient")
    @patch("backend.lambdas.weather_analyzer.handler.ApiClient")
    @patch("backend.lambdas.weather_analyzer.handler.CircuitBreaker")
    @patch("backend.lambdas.weather_analyzer.handler.boto3")
    def test_successful_execution_with_monsoon(
        self, mock_boto3, mock_cb_cls, mock_api_cls, mock_bedrock_cls
    ):
        # Mock DynamoDB table
        mock_table = MagicMock()
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3.resource.return_value = mock_resource

        # Mock ApiClient to return weather data
        mock_api_instance = MagicMock()
        mock_api_instance.get_json.return_value = {"forecasts": []}
        mock_api_cls.return_value = mock_api_instance

        # Mock Bedrock response
        llm_output = {
            "agent": "weather_analyzer",
            "is_fallback": False,
            "daily_forecasts": [
                {
                    "date": "2025-07-01",
                    "destination": "Mumbai",
                    "temp_min_c": 25,
                    "temp_max_c": 32,
                    "precipitation_pct": 80,
                    "conditions": "Heavy Rain",
                }
            ],
            "advisories": ["Carry waterproof gear"],
            "monsoon_warning": False,
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
                "query": "Monsoon trip to Mumbai",
                "dates": {"start": "2025-07-01", "end": "2025-07-05"},
                "budget": 30000,
            },
        }

        result = handler(event, None)

        assert result["agent"] == "weather_analyzer"
        assert result["is_fallback"] is False
        # Monsoon warning computed in Python, overrides LLM value
        assert result["monsoon_warning"] is True
        assert isinstance(result["advisories"], list)
        assert isinstance(result["daily_forecasts"], list)
        # Agent status updated twice: running + completed
        assert mock_table.update_item.call_count == 2

    @patch("backend.lambdas.weather_analyzer.handler.BedrockClient")
    @patch("backend.lambdas.weather_analyzer.handler.ApiClient")
    @patch("backend.lambdas.weather_analyzer.handler.CircuitBreaker")
    @patch("backend.lambdas.weather_analyzer.handler.boto3")
    def test_successful_execution_without_monsoon(
        self, mock_boto3, mock_cb_cls, mock_api_cls, mock_bedrock_cls
    ):
        mock_table = MagicMock()
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3.resource.return_value = mock_resource

        mock_api_instance = MagicMock()
        mock_api_instance.get_json.return_value = {"forecasts": []}
        mock_api_cls.return_value = mock_api_instance

        llm_output = {
            "daily_forecasts": [
                {
                    "date": "2025-01-15",
                    "destination": "Jaipur",
                    "temp_min_c": 8,
                    "temp_max_c": 22,
                    "precipitation_pct": 5,
                    "conditions": "Clear",
                }
            ],
            "advisories": ["Pack warm layers for evenings"],
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
            "itinerary_id": "test-456",
            "trip_request": {
                "query": "Winter trip to Rajasthan",
                "dates": {"start": "2025-01-15", "end": "2025-01-20"},
                "budget": 40000,
            },
        }

        result = handler(event, None)

        assert result["agent"] == "weather_analyzer"
        assert result["monsoon_warning"] is False

    @patch("backend.lambdas.weather_analyzer.handler.BedrockClient")
    @patch("backend.lambdas.weather_analyzer.handler.ApiClient")
    @patch("backend.lambdas.weather_analyzer.handler.CircuitBreaker")
    @patch("backend.lambdas.weather_analyzer.handler.boto3")
    def test_failure_updates_status_to_failed(
        self, mock_boto3, mock_cb_cls, mock_api_cls, mock_bedrock_cls
    ):
        mock_table = MagicMock()
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3.resource.return_value = mock_resource

        mock_api_instance = MagicMock()
        mock_api_instance.get_json.side_effect = RuntimeError("IMD API down")
        mock_api_cls.return_value = mock_api_instance

        event = {
            "itinerary_id": "test-789",
            "trip_request": {
                "query": "Beach trip",
                "dates": {"start": "2025-03-01", "end": "2025-03-05"},
                "budget": 25000,
            },
        }

        with pytest.raises(RuntimeError):
            handler(event, None)

        # Should have updated status to "running" then "failed"
        assert mock_table.update_item.call_count == 2
