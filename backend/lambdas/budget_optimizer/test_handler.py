"""Unit tests for the Budget Optimizer Agent handler."""

import json
from unittest.mock import MagicMock, patch

import pytest

from Agentic_AI_With_step_functions.backend.lambdas.budget_optimizer.handler import (
    _apply_overage_detection,
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
                        {"text": json.dumps({"budget_tiers": []})}
                    ]
                }
            }
        }
        result = _parse_llm_response(response)
        assert result == {"budget_tiers": []}

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
# _apply_overage_detection
# ---------------------------------------------------------------------------


class TestApplyOverageDetection:
    def test_sets_overage_when_economy_exceeds_budget(self):
        output = {
            "budget_tiers": [
                {"tier": "economy", "total_inr": 60000, "breakdown": {}},
                {"tier": "comfort", "total_inr": 80000, "breakdown": {}},
            ],
            "savings_tips": ["Take buses"],
        }
        result = _apply_overage_detection(output, 50000)
        assert result["overage_flag"] is True
        assert result["overage_amount_inr"] == 10000
        assert len(result["savings_tips"]) > 0

    def test_no_overage_when_within_budget(self):
        output = {
            "budget_tiers": [
                {"tier": "economy", "total_inr": 40000, "breakdown": {}},
                {"tier": "comfort", "total_inr": 60000, "breakdown": {}},
            ],
            "savings_tips": [],
        }
        result = _apply_overage_detection(output, 50000)
        assert result["overage_flag"] is False
        assert "overage_amount_inr" not in result

    def test_provides_default_savings_tips_on_overage(self):
        output = {
            "budget_tiers": [
                {"tier": "economy", "total_inr": 70000, "breakdown": {}},
            ],
        }
        result = _apply_overage_detection(output, 50000)
        assert result["overage_flag"] is True
        assert len(result["savings_tips"]) >= 1

    def test_handles_empty_tiers(self):
        output = {"budget_tiers": []}
        result = _apply_overage_detection(output, 50000)
        assert result["overage_flag"] is False
        assert result["savings_tips"] == []

    def test_falls_back_to_lowest_tier_when_no_economy_label(self):
        output = {
            "budget_tiers": [
                {"tier": "basic", "total_inr": 55000, "breakdown": {}},
                {"tier": "premium", "total_inr": 90000, "breakdown": {}},
            ],
        }
        result = _apply_overage_detection(output, 50000)
        assert result["overage_flag"] is True
        assert result["overage_amount_inr"] == 5000

    def test_exact_budget_is_not_overage(self):
        output = {
            "budget_tiers": [
                {"tier": "economy", "total_inr": 50000, "breakdown": {}},
            ],
        }
        result = _apply_overage_detection(output, 50000)
        assert result["overage_flag"] is False


# ---------------------------------------------------------------------------
# handler (integration-style with mocks)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _env_vars(monkeypatch):
    monkeypatch.setenv("ITINERARY_TABLE_NAME", "test-itinerary-table")
    monkeypatch.setenv("CIRCUIT_BREAKER_TABLE_NAME", "test-cb-table")
    monkeypatch.setenv("ARTIFACT_BUCKET_NAME", "test-bucket")


class TestHandler:
    @patch("backend.lambdas.budget_optimizer.handler.BedrockClient")
    @patch("backend.lambdas.budget_optimizer.handler.ApiClient")
    @patch("backend.lambdas.budget_optimizer.handler.CircuitBreaker")
    @patch("backend.lambdas.budget_optimizer.handler.boto3")
    def test_successful_execution(
        self, mock_boto3, mock_cb_cls, mock_api_cls, mock_bedrock_cls
    ):
        mock_table = MagicMock()
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3.resource.return_value = mock_resource

        mock_api_instance = MagicMock()
        mock_api_instance.get_json.return_value = {"prices": []}
        mock_api_cls.return_value = mock_api_instance

        llm_output = {
            "agent": "budget_optimizer",
            "is_fallback": False,
            "budget_tiers": [
                {
                    "tier": "economy",
                    "total_inr": 35000,
                    "breakdown": {
                        "transport": 10000,
                        "accommodation": 10000,
                        "food": 7000,
                        "activities": 5000,
                        "contingency": 3000,
                    },
                },
                {
                    "tier": "comfort",
                    "total_inr": 55000,
                    "breakdown": {
                        "transport": 15000,
                        "accommodation": 18000,
                        "food": 10000,
                        "activities": 7000,
                        "contingency": 5000,
                    },
                },
            ],
            "overage_flag": False,
            "savings_tips": ["Book trains early for lower fares."],
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
            "itinerary_id": "test-budget-123",
            "trip_request": {
                "query": "Beach vacation in Goa",
                "dates": {"start": "2025-01-01", "end": "2025-01-07"},
                "budget": 50000,
            },
        }

        result = handler(event, None)

        assert result["agent"] == "budget_optimizer"
        assert result["is_fallback"] is False
        assert result["overage_flag"] is False
        assert len(result["budget_tiers"]) == 2
        assert mock_table.update_item.call_count == 2

    @patch("backend.lambdas.budget_optimizer.handler.BedrockClient")
    @patch("backend.lambdas.budget_optimizer.handler.ApiClient")
    @patch("backend.lambdas.budget_optimizer.handler.CircuitBreaker")
    @patch("backend.lambdas.budget_optimizer.handler.boto3")
    def test_overage_detected_when_over_budget(
        self, mock_boto3, mock_cb_cls, mock_api_cls, mock_bedrock_cls
    ):
        mock_table = MagicMock()
        mock_resource = MagicMock()
        mock_resource.Table.return_value = mock_table
        mock_boto3.resource.return_value = mock_resource

        mock_api_instance = MagicMock()
        mock_api_instance.get_json.return_value = {"prices": []}
        mock_api_cls.return_value = mock_api_instance

        llm_output = {
            "budget_tiers": [
                {
                    "tier": "economy",
                    "total_inr": 60000,
                    "breakdown": {
                        "transport": 15000,
                        "accommodation": 20000,
                        "food": 10000,
                        "activities": 10000,
                        "contingency": 5000,
                    },
                },
            ],
            "savings_tips": [],
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
            "itinerary_id": "test-budget-456",
            "trip_request": {
                "query": "Luxury trip to Rajasthan",
                "dates": {"start": "2025-02-01", "end": "2025-02-10"},
                "budget": 40000,
            },
        }

        result = handler(event, None)

        assert result["overage_flag"] is True
        assert result["overage_amount_inr"] == 20000
        assert len(result["savings_tips"]) >= 1

    @patch("backend.lambdas.budget_optimizer.handler.BedrockClient")
    @patch("backend.lambdas.budget_optimizer.handler.ApiClient")
    @patch("backend.lambdas.budget_optimizer.handler.CircuitBreaker")
    @patch("backend.lambdas.budget_optimizer.handler.boto3")
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
            "itinerary_id": "test-budget-789",
            "trip_request": {
                "query": "Mountain trek",
                "dates": {"start": "2025-03-01", "end": "2025-03-05"},
                "budget": 30000,
            },
        }

        with pytest.raises(RuntimeError):
            handler(event, None)

        assert mock_table.update_item.call_count == 2
