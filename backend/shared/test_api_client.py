"""Unit tests for the circuit-breaker-wrapped API client."""

import json
from unittest.mock import MagicMock, patch

import pytest

from Agentic_AI_With_step_functions.backend.shared.api_client import ApiClient
from Agentic_AI_With_step_functions.backend.shared.circuit_breaker import CircuitOpenError


@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    monkeypatch.setenv("ARTIFACT_BUCKET_NAME", "test-bucket")


@pytest.fixture()
def cb():
    return MagicMock()


@pytest.fixture()
def client(cb):
    return ApiClient(service_name="irctc", circuit_breaker=cb)


class TestGetJsonSuccess:
    def test_returns_data_and_caches(self, client, cb):
        expected = {"trains": [1, 2]}
        cb.call.return_value = expected

        with patch("backend.shared.api_client.write_cache") as mock_write:
            result = client.get_json(
                url="https://api.example.com/trains",
                cache_key="delhi-goa",
            )

        assert result == expected
        mock_write.assert_called_once_with("irctc", "delhi-goa", expected)


class TestGetJsonCircuitOpen:
    def test_falls_back_to_cache(self, client, cb):
        cb.call.side_effect = CircuitOpenError("irctc")
        cached = {"trains": [3]}

        with patch("backend.shared.api_client.read_cache", return_value=cached):
            result = client.get_json(
                url="https://api.example.com/trains",
                cache_key="delhi-goa",
            )

        assert result["trains"] == [3]
        assert result["_from_cache"] is True

    def test_falls_back_to_fn_when_no_cache(self, client, cb):
        cb.call.side_effect = CircuitOpenError("irctc")
        fallback_data = {"best_effort": True}

        with patch("backend.shared.api_client.read_cache", return_value=None):
            result = client.get_json(
                url="https://api.example.com/trains",
                cache_key="delhi-goa",
                fallback_fn=lambda: fallback_data,
            )

        assert result == fallback_data

    def test_raises_when_no_cache_and_no_fallback(self, client, cb):
        cb.call.side_effect = CircuitOpenError("irctc")

        with patch("backend.shared.api_client.read_cache", return_value=None):
            with pytest.raises(RuntimeError, match="No cached data"):
                client.get_json(
                    url="https://api.example.com/trains",
                    cache_key="delhi-goa",
                )


class TestGetJsonRequestFailure:
    def test_serves_cache_on_http_error(self, client, cb):
        cb.call.side_effect = Exception("Connection timeout")
        cached = {"stale": True}

        with patch("backend.shared.api_client.read_cache", return_value=cached):
            result = client.get_json(
                url="https://api.example.com/trains",
                cache_key="key1",
            )

        assert result["stale"] is True
        assert result["_from_cache"] is True
