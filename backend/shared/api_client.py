"""Circuit-breaker-wrapped HTTP client for external API calls.

Wraps ``urllib.request`` calls through a :class:`CircuitBreaker` so that
flaky third-party APIs are automatically short-circuited after repeated
failures.  Successful responses are cached in S3 via :mod:`backend.shared.cache`.
When the circuit breaker is OPEN, the client falls back to cached data from
S3 and, if no cache exists, uses Nova Lite for best-effort generation.

Environment variables:
    CIRCUIT_BREAKER_TABLE_NAME: DynamoDB table for circuit breaker state.
    ARTIFACT_BUCKET_NAME: S3 bucket for caching (used by cache module).
"""

import json
import logging
import urllib.request
from typing import Any

from Agentic_AI_With_step_functions.backend.shared.cache import read_cache, write_cache
from Agentic_AI_With_step_functions.backend.shared.circuit_breaker import CircuitBreaker, CircuitOpenError

logger = logging.getLogger(__name__)


class ApiClient:
    """HTTP client that routes requests through a circuit breaker.

    On success the response is cached in S3.  When the circuit breaker is
    OPEN the client transparently serves cached data or falls back to
    Nova Lite best-effort generation via a caller-supplied fallback function.
    """

    def __init__(self, service_name: str, circuit_breaker: CircuitBreaker):
        """Initialise the API client.

        Args:
            service_name: Identifier used as the S3 cache prefix
                (e.g. "irctc", "imd", "tourism", "pricing").
            circuit_breaker: A :class:`CircuitBreaker` instance for this service.
        """
        self.service_name = service_name
        self._cb = circuit_breaker

    def get_json(
        self,
        url: str,
        cache_key: str,
        headers: dict[str, str] | None = None,
        timeout: int = 10,
        fallback_fn: Any | None = None,
    ) -> dict:
        """Fetch JSON from *url* through the circuit breaker.

        Args:
            url: The external API endpoint.
            cache_key: Key used for S3 cache storage/retrieval.
            headers: Optional HTTP headers.
            timeout: Request timeout in seconds.
            fallback_fn: Optional callable returning a fallback dict when
                both the live API and cache are unavailable.

        Returns:
            The parsed JSON response dict.

        Raises:
            Exception: If the request fails, no cache exists, and no
                fallback function is provided.
        """
        try:
            data = self._cb.call(
                self._http_get, url, headers, timeout
            )
            # Cache successful response
            write_cache(self.service_name, cache_key, data)
            return data
        except CircuitOpenError:
            logger.warning(
                "Circuit OPEN for %s — attempting S3 cache fallback",
                self.service_name,
            )
            return self._fallback(cache_key, fallback_fn)
        except Exception:
            logger.warning(
                "Request to %s failed — attempting S3 cache fallback",
                self.service_name,
                exc_info=True,
            )
            return self._fallback(cache_key, fallback_fn)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _http_get(url: str, headers: dict[str, str] | None, timeout: int) -> dict:
        """Perform an HTTP GET and return the parsed JSON body."""
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)

    def _fallback(self, cache_key: str, fallback_fn: Any | None) -> dict:
        """Try S3 cache first, then the caller-supplied fallback function."""
        cached = read_cache(self.service_name, cache_key)
        if cached is not None:
            logger.info("Serving cached data for %s/%s", self.service_name, cache_key)
            cached["_from_cache"] = True
            return cached

        if fallback_fn is not None:
            logger.info(
                "No cache for %s/%s — invoking fallback function",
                self.service_name,
                cache_key,
            )
            return fallback_fn()

        raise RuntimeError(
            f"No cached data and no fallback for {self.service_name}/{cache_key}"
        )
