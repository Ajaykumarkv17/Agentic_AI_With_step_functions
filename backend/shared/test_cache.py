"""Unit tests for the S3 cache helpers."""

import json
from unittest.mock import MagicMock, patch

import pytest

from Agentic_AI_With_step_functions.backend.shared.cache import read_cache, write_cache


@pytest.fixture(autouse=True)
def _set_bucket_env(monkeypatch):
    monkeypatch.setenv("ARTIFACT_BUCKET_NAME", "test-artifact-bucket")


@pytest.fixture()
def mock_s3():
    with patch("backend.shared.cache._s3_client") as factory:
        client = MagicMock()
        factory.return_value = client
        yield client


class TestWriteCache:
    def test_writes_json_to_correct_key(self, mock_s3):
        data = {"trains": [{"id": 1}]}
        write_cache("irctc", "delhi-goa", data)

        mock_s3.put_object.assert_called_once_with(
            Bucket="test-artifact-bucket",
            Key="cache/irctc/delhi-goa.json",
            Body=json.dumps(data),
            ContentType="application/json",
        )

    def test_logs_warning_on_s3_failure(self, mock_s3):
        from botocore.exceptions import ClientError

        mock_s3.put_object.side_effect = ClientError(
            {"Error": {"Code": "InternalError", "Message": "boom"}}, "PutObject"
        )
        # Should not raise
        write_cache("irctc", "key1", {"a": 1})


class TestReadCache:
    def test_returns_cached_dict(self, mock_s3):
        payload = {"weather": "sunny"}
        mock_s3.get_object.return_value = {
            "Body": MagicMock(read=lambda: json.dumps(payload).encode())
        }

        result = read_cache("imd", "mumbai-2025-01")
        assert result == payload
        mock_s3.get_object.assert_called_once_with(
            Bucket="test-artifact-bucket",
            Key="cache/imd/mumbai-2025-01.json",
        )

    def test_returns_none_on_no_such_key(self, mock_s3):
        from botocore.exceptions import ClientError

        mock_s3.get_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "not found"}}, "GetObject"
        )
        assert read_cache("tourism", "missing") is None

    def test_returns_none_on_other_client_error(self, mock_s3):
        from botocore.exceptions import ClientError

        mock_s3.get_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "denied"}}, "GetObject"
        )
        assert read_cache("pricing", "key") is None
