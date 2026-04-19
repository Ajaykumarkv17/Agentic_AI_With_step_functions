"""Unit tests for the Trip Submission Lambda handler."""

import json
import os
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

import pytest

from Agentic_AI_With_step_functions.backend.lambdas.trip_submission.handler import (
    handler,
    validate_trip_request,
    _MAX_QUERY_LENGTH,
)


# ---------------------------------------------------------------------------
# validate_trip_request tests
# ---------------------------------------------------------------------------


class TestValidateTripRequest:
    """Tests for the validate_trip_request function."""

    def test_valid_request_returns_no_errors(self):
        body = {
            "query": "Trip to Goa",
            "dates": {"start": "2025-01-10", "end": "2025-01-15"},
            "budget": 50000,
        }
        assert validate_trip_request(body) == []

    def test_valid_request_with_preferences(self):
        body = {
            "query": "Trip to Kerala",
            "dates": {"start": "2025-02-01", "end": "2025-02-07"},
            "budget": 30000,
            "preferences": ["food", "culture"],
        }
        assert validate_trip_request(body) == []

    def test_missing_query(self):
        body = {
            "dates": {"start": "2025-01-10", "end": "2025-01-15"},
            "budget": 50000,
        }
        errors = validate_trip_request(body)
        assert any("'query' is required" in e for e in errors)

    def test_empty_query(self):
        body = {
            "query": "   ",
            "dates": {"start": "2025-01-10", "end": "2025-01-15"},
            "budget": 50000,
        }
        errors = validate_trip_request(body)
        assert any("'query' is required" in e for e in errors)

    def test_query_exceeds_max_length(self):
        body = {
            "query": "x" * (_MAX_QUERY_LENGTH + 1),
            "dates": {"start": "2025-01-10", "end": "2025-01-15"},
            "budget": 50000,
        }
        errors = validate_trip_request(body)
        assert any("at most" in e for e in errors)

    def test_query_at_max_length_is_valid(self):
        body = {
            "query": "x" * _MAX_QUERY_LENGTH,
            "dates": {"start": "2025-01-10", "end": "2025-01-15"},
            "budget": 50000,
        }
        assert validate_trip_request(body) == []

    def test_missing_dates(self):
        body = {"query": "Trip to Goa", "budget": 50000}
        errors = validate_trip_request(body)
        assert any("'dates.start' is required" in e for e in errors)
        assert any("'dates.end' is required" in e for e in errors)

    def test_missing_dates_start(self):
        body = {
            "query": "Trip to Goa",
            "dates": {"end": "2025-01-15"},
            "budget": 50000,
        }
        errors = validate_trip_request(body)
        assert any("'dates.start' is required" in e for e in errors)
        assert len(errors) == 1

    def test_missing_dates_end(self):
        body = {
            "query": "Trip to Goa",
            "dates": {"start": "2025-01-10"},
            "budget": 50000,
        }
        errors = validate_trip_request(body)
        assert any("'dates.end' is required" in e for e in errors)
        assert len(errors) == 1

    def test_missing_budget(self):
        body = {
            "query": "Trip to Goa",
            "dates": {"start": "2025-01-10", "end": "2025-01-15"},
        }
        errors = validate_trip_request(body)
        assert any("'budget' is required" in e for e in errors)

    def test_negative_budget(self):
        body = {
            "query": "Trip to Goa",
            "dates": {"start": "2025-01-10", "end": "2025-01-15"},
            "budget": -100,
        }
        errors = validate_trip_request(body)
        assert any("positive" in e for e in errors)

    def test_zero_budget(self):
        body = {
            "query": "Trip to Goa",
            "dates": {"start": "2025-01-10", "end": "2025-01-15"},
            "budget": 0,
        }
        errors = validate_trip_request(body)
        assert any("positive" in e for e in errors)

    def test_non_numeric_budget(self):
        body = {
            "query": "Trip to Goa",
            "dates": {"start": "2025-01-10", "end": "2025-01-15"},
            "budget": "fifty thousand",
        }
        errors = validate_trip_request(body)
        assert any("must be a number" in e for e in errors)

    def test_all_fields_missing(self):
        errors = validate_trip_request({})
        assert len(errors) == 4  # query, dates.start, dates.end, budget

    def test_non_string_query(self):
        body = {
            "query": 12345,
            "dates": {"start": "2025-01-10", "end": "2025-01-15"},
            "budget": 50000,
        }
        errors = validate_trip_request(body)
        assert any("must be a string" in e for e in errors)


# ---------------------------------------------------------------------------
# handler() integration-style tests (mocked AWS services)
# ---------------------------------------------------------------------------


class TestHandler:
    """Tests for the Lambda handler function."""

    def _make_event(self, body: dict | None = None, body_str: str | None = None):
        """Build a minimal API Gateway proxy event."""
        return {
            "body": body_str if body_str is not None else json.dumps(body),
        }

    @patch.dict(os.environ, {
        "ITINERARY_TABLE_NAME": "test-table",
        "STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123456789012:stateMachine:test",
    })
    @patch("backend.lambdas.trip_submission.handler.boto3")
    def test_successful_submission(self, mock_boto3):
        mock_table = MagicMock()
        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.return_value = mock_table
        mock_sfn = MagicMock()

        def resource_side_effect(service):
            if service == "dynamodb":
                return mock_dynamodb
            raise ValueError(f"Unexpected resource: {service}")

        def client_side_effect(service):
            if service == "stepfunctions":
                return mock_sfn
            raise ValueError(f"Unexpected client: {service}")

        mock_boto3.resource.side_effect = resource_side_effect
        mock_boto3.client.side_effect = client_side_effect

        event = self._make_event({
            "query": "Trip to Rajasthan",
            "dates": {"start": "2025-03-01", "end": "2025-03-05"},
            "budget": 40000,
        })

        result = handler(event, None)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert "itinerary_id" in body

        # Verify DynamoDB put_item was called
        mock_table.put_item.assert_called_once()
        item = mock_table.put_item.call_args[1]["Item"]
        assert item["status"] == "started"
        assert item["agents_status"]["destination_researcher"] == "pending"
        assert item["agents_status"]["budget_optimizer"] == "pending"
        assert item["agents_status"]["weather_analyzer"] == "pending"
        assert item["agents_status"]["experience_curator"] == "pending"

        # Verify Step Functions start_execution was called
        mock_sfn.start_execution.assert_called_once()

    def test_invalid_json_body(self):
        event = self._make_event(body_str="not json")
        result = handler(event, None)
        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert "Invalid JSON" in body["error"]

    def test_missing_body(self):
        event = {"body": None}
        result = handler(event, None)
        assert result["statusCode"] == 400

    def test_validation_failure_returns_400_with_details(self):
        event = self._make_event({})
        result = handler(event, None)
        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body["error"] == "Validation failed"
        assert isinstance(body["details"], list)
        assert len(body["details"]) == 4

    @patch.dict(os.environ, {
        "ITINERARY_TABLE_NAME": "test-table",
        "STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123456789012:stateMachine:test",
    })
    @patch("backend.lambdas.trip_submission.handler.boto3")
    def test_preferences_included_when_provided(self, mock_boto3):
        mock_table = MagicMock()
        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.return_value = mock_table
        mock_sfn = MagicMock()

        mock_boto3.resource.return_value = mock_dynamodb
        mock_boto3.client.return_value = mock_sfn

        event = self._make_event({
            "query": "Trip to Kerala",
            "dates": {"start": "2025-02-01", "end": "2025-02-07"},
            "budget": 30000,
            "preferences": ["food", "culture"],
        })

        result = handler(event, None)
        assert result["statusCode"] == 200

        item = mock_table.put_item.call_args[1]["Item"]
        assert item["trip_request"]["preferences"] == ["food", "culture"]

    @patch.dict(os.environ, {
        "ITINERARY_TABLE_NAME": "test-table",
        "STATE_MACHINE_ARN": "arn:aws:states:us-east-1:123456789012:stateMachine:test",
    })
    @patch("backend.lambdas.trip_submission.handler.boto3")
    def test_itinerary_id_is_uuid_v4(self, mock_boto3):
        mock_table = MagicMock()
        mock_dynamodb = MagicMock()
        mock_dynamodb.Table.return_value = mock_table
        mock_sfn = MagicMock()

        mock_boto3.resource.return_value = mock_dynamodb
        mock_boto3.client.return_value = mock_sfn

        event = self._make_event({
            "query": "Trip to Goa",
            "dates": {"start": "2025-01-10", "end": "2025-01-15"},
            "budget": 50000,
        })

        result = handler(event, None)
        body = json.loads(result["body"])
        import uuid as uuid_mod
        parsed = uuid_mod.UUID(body["itinerary_id"])
        assert parsed.version == 4

    def test_cors_headers_present(self):
        event = self._make_event({})
        result = handler(event, None)
        assert result["headers"]["Access-Control-Allow-Origin"] == "*"
        assert result["headers"]["Content-Type"] == "application/json"
