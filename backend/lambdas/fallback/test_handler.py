"""Unit tests for the Fallback Lambda handler."""

import json
from unittest.mock import MagicMock, patch

import pytest

from Agentic_AI_With_step_functions.backend.lambdas.fallback.handler import (
    AGENT_CACHE_PREFIXES,
    AGENT_FALLBACK_PROMPTS,
    _try_cached_data,
    handler,
)


@pytest.fixture
def base_event():
    """Minimal Step Functions Catch block event."""
    return {
        "itinerary_id": "test-itinerary-123",
        "trip_request": {
            "query": "Trip to Goa",
            "dates": {"start": "2025-01-10", "end": "2025-01-15"},
            "budget": 50000,
        },
        "agent_name": "weather_analyzer",
        "error": {"Error": "States.TaskFailed", "Cause": "timeout"},
    }


# ---------------------------------------------------------------------------
# _try_cached_data
# ---------------------------------------------------------------------------

class TestTryCachedData:
    """Tests for the S3 cache lookup helper."""

    @patch("backend.lambdas.fallback.handler.read_cache")
    def test_returns_merged_cached_data(self, mock_read):
        mock_read.return_value = {"temp": 30}
        result = _try_cached_data(
            "weather_analyzer",
            {"dates": {"start": "2025-01-10", "end": "2025-01-15"}},
        )
        assert result is not None
        assert "imd" in result
        mock_read.assert_called_once_with("imd", "2025-01-10_2025-01-15")

    @patch("backend.lambdas.fallback.handler.read_cache")
    def test_returns_none_when_no_cache(self, mock_read):
        mock_read.return_value = None
        result = _try_cached_data(
            "weather_analyzer",
            {"dates": {"start": "2025-01-10", "end": "2025-01-15"}},
        )
        assert result is None

    def test_returns_none_for_unknown_agent(self):
        result = _try_cached_data(
            "unknown_agent",
            {"dates": {"start": "2025-01-10", "end": "2025-01-15"}},
        )
        assert result is None

    @patch("backend.lambdas.fallback.handler.read_cache")
    def test_merges_multiple_prefixes(self, mock_read):
        """Destination researcher has multiple cache prefixes."""
        mock_read.side_effect = [
            {"routes": []},   # irctc
            None,              # flights — miss
            {"listings": []},  # accommodations
        ]
        result = _try_cached_data(
            "destination_researcher",
            {"dates": {"start": "2025-02-01", "end": "2025-02-05"}},
        )
        assert result is not None
        assert "irctc" in result
        assert "flights" not in result
        assert "accommodations" in result


# ---------------------------------------------------------------------------
# handler — cached data path
# ---------------------------------------------------------------------------

class TestHandlerCachedPath:
    """Tests for the handler when cached data is available."""

    @patch("backend.lambdas.fallback.handler._get_table")
    @patch("backend.lambdas.fallback.handler.read_cache")
    def test_returns_stale_data_when_cache_exists(self, mock_read, mock_table, base_event):
        mock_read.return_value = {"temp": 30}
        mock_table.return_value = MagicMock()

        result = handler(base_event, None)

        assert result["agent"] == "weather_analyzer"
        assert result["is_fallback"] is True
        assert result["fallback_source"] == "stale_data"
        assert result["notice"]["type"] == "stale_data"
        assert "imd" in result["data"]

    @patch("backend.lambdas.fallback.handler._get_table")
    @patch("backend.lambdas.fallback.handler.read_cache")
    def test_updates_agent_status_to_fallback(self, mock_read, mock_table, base_event):
        mock_read.return_value = {"temp": 30}
        table_mock = MagicMock()
        mock_table.return_value = table_mock

        handler(base_event, None)

        table_mock.update_item.assert_called_once()
        call_kwargs = table_mock.update_item.call_args[1]
        assert call_kwargs["ExpressionAttributeValues"][":status"] == "fallback"


# ---------------------------------------------------------------------------
# handler — Nova Lite best-effort path
# ---------------------------------------------------------------------------

class TestHandlerBestEffortPath:
    """Tests for the handler when no cache exists and Nova Lite is used."""

    @patch("backend.lambdas.fallback.handler._get_table")
    @patch("backend.lambdas.fallback.handler.read_cache", return_value=None)
    @patch("backend.lambdas.fallback.handler.boto3")
    def test_returns_best_effort_from_nova_lite(self, mock_boto, mock_read, mock_table, base_event):
        mock_table.return_value = MagicMock()
        llm_output = {
            "daily_forecasts": [{"date": "2025-01-10", "destination": "Goa",
                                  "temp_min_c": 22, "temp_max_c": 32,
                                  "precipitation_pct": 10, "conditions": "Sunny"}],
            "advisories": [],
            "monsoon_warning": False,
        }
        bedrock_client = MagicMock()
        bedrock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": json.dumps(llm_output)}]}}
        }
        mock_boto.client.return_value = bedrock_client

        result = handler(base_event, None)

        assert result["agent"] == "weather_analyzer"
        assert result["is_fallback"] is True
        assert result["fallback_source"] == "best_effort"
        assert result["notice"]["type"] == "best_effort"
        assert "daily_forecasts" in result

    @patch("backend.lambdas.fallback.handler._get_table")
    @patch("backend.lambdas.fallback.handler.read_cache", return_value=None)
    @patch("backend.lambdas.fallback.handler.boto3")
    def test_returns_graceful_output_when_nova_lite_fails(self, mock_boto, mock_read, mock_table, base_event):
        mock_table.return_value = MagicMock()
        bedrock_client = MagicMock()
        bedrock_client.converse.side_effect = Exception("Bedrock unavailable")
        mock_boto.client.return_value = bedrock_client

        result = handler(base_event, None)

        assert result["agent"] == "weather_analyzer"
        assert result["is_fallback"] is True
        assert result["fallback_source"] == "best_effort"
        assert "incomplete" in result["notice"]["message"].lower()


# ---------------------------------------------------------------------------
# Configuration coverage
# ---------------------------------------------------------------------------

class TestConfiguration:
    """Verify that all agents have proper fallback configuration."""

    def test_all_agents_have_cache_prefixes(self):
        expected = {"destination_researcher", "budget_optimizer",
                    "weather_analyzer", "experience_curator"}
        assert set(AGENT_CACHE_PREFIXES.keys()) == expected

    def test_all_agents_have_fallback_prompts(self):
        expected = {"destination_researcher", "budget_optimizer",
                    "weather_analyzer", "experience_curator"}
        assert set(AGENT_FALLBACK_PROMPTS.keys()) == expected

    def test_fallback_prompts_have_required_keys(self):
        for agent, config in AGENT_FALLBACK_PROMPTS.items():
            assert "name" in config, f"{agent} missing 'name'"
            assert "role" in config, f"{agent} missing 'role'"
            assert "instructions" in config, f"{agent} missing 'instructions'"
