"""DynamoDB-backed circuit breaker for external API resilience.

Implements the Circuit Breaker pattern with three states:
- CLOSED: Requests pass through normally
- OPEN: Requests are blocked, fallback data is served
- HALF_OPEN: A single test request is allowed to check recovery

State is persisted in DynamoDB with conditional writes for atomic transitions.
"""

from datetime import datetime, timezone
from typing import Any, Callable


# Circuit breaker states
CLOSED = "CLOSED"
OPEN = "OPEN"
HALF_OPEN = "HALF_OPEN"

_VALID_STATES = {CLOSED, OPEN, HALF_OPEN}


class CircuitOpenError(Exception):
    """Raised when a call is attempted while the circuit breaker is OPEN."""

    def __init__(self, service_name: str):
        self.service_name = service_name
        super().__init__(f"Circuit breaker is OPEN for service: {service_name}")


class CircuitBreaker:
    """DynamoDB-backed circuit breaker for protecting external API calls.

    Tracks per-service failure counts and state transitions in DynamoDB.
    Uses conditional writes for atomic state changes to prevent race conditions.
    """

    def __init__(
        self,
        service_name: str,
        table,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
    ):
        """Initialize the circuit breaker.

        Args:
            service_name: Identifier for the external service (e.g., "irctc_api").
            table: A boto3 DynamoDB Table resource for the CircuitBreakerTable.
            failure_threshold: Consecutive failures before transitioning to OPEN.
            recovery_timeout: Seconds to wait before transitioning from OPEN to HALF_OPEN.
        """
        self.service_name = service_name
        self._table = table
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout

    def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Execute func through the circuit breaker.

        Checks the current state, executes the function if allowed,
        and handles state transitions based on the outcome.

        Args:
            func: The callable to execute.
            *args: Positional arguments for func.
            **kwargs: Keyword arguments for func.

        Returns:
            The return value of func.

        Raises:
            CircuitOpenError: If the circuit is OPEN and recovery timeout
                has not elapsed.
        """
        state = self._get_state()

        if state == OPEN:
            if self._recovery_timeout_elapsed():
                self._transition_to(HALF_OPEN)
                return self._try_call(func, *args, **kwargs)
            raise CircuitOpenError(self.service_name)
        elif state == HALF_OPEN:
            return self._try_call(func, *args, **kwargs)
        else:  # CLOSED
            return self._try_call(func, *args, **kwargs)

    def _get_state(self) -> str:
        """Retrieve the current circuit breaker state from DynamoDB.

        If no record exists for this service, initializes one in CLOSED state.

        Returns:
            The current state: CLOSED, OPEN, or HALF_OPEN.
        """
        response = self._table.get_item(Key={"service_name": self.service_name})
        item = response.get("Item")

        if item is None:
            # First time — initialize as CLOSED
            now = datetime.now(timezone.utc).isoformat()
            self._table.put_item(
                Item={
                    "service_name": self.service_name,
                    "state": CLOSED,
                    "failure_count": 0,
                    "last_failure_at": "",
                    "last_success_at": "",
                    "updated_at": now,
                },
                ConditionExpression="attribute_not_exists(service_name)",
            )
            return CLOSED

        return item.get("state", CLOSED)

    def _transition_to(self, new_state: str) -> None:
        """Atomically transition the circuit breaker to a new state.

        Uses DynamoDB conditional writes to prevent race conditions
        when multiple Lambda invocations update the same record.

        Args:
            new_state: Target state (CLOSED, OPEN, or HALF_OPEN).
        """
        now = datetime.now(timezone.utc).isoformat()

        update_expr = "SET #st = :new_state, updated_at = :now"
        expr_values = {
            ":new_state": new_state,
            ":now": now,
        }
        expr_names = {"#st": "state"}

        if new_state == CLOSED:
            # Reset failure count on transition to CLOSED
            update_expr += ", failure_count = :zero, last_success_at = :now"
            expr_values[":zero"] = 0
        elif new_state == OPEN:
            # Record the failure timestamp for recovery timeout calculation
            update_expr += ", last_failure_at = :now"

        self._table.update_item(
            Key={"service_name": self.service_name},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
        )

    def _try_call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Attempt to execute the function and handle success/failure transitions.

        On success:
            - If HALF_OPEN → transition to CLOSED (reset failure count)
            - If CLOSED → record success, reset failure count

        On failure:
            - Increment failure count
            - If CLOSED and failure count >= threshold → transition to OPEN
            - If HALF_OPEN → transition to OPEN (restart recovery timeout)

        Args:
            func: The callable to execute.
            *args: Positional arguments for func.
            **kwargs: Keyword arguments for func.

        Returns:
            The return value of func.

        Raises:
            The original exception from func after recording the failure.
        """
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        """Handle a successful call — reset failure count and transition to CLOSED if needed."""
        now = datetime.now(timezone.utc).isoformat()
        self._table.update_item(
            Key={"service_name": self.service_name},
            UpdateExpression=(
                "SET failure_count = :zero, last_success_at = :now, "
                "#st = :closed, updated_at = :now"
            ),
            ExpressionAttributeNames={"#st": "state"},
            ExpressionAttributeValues={
                ":zero": 0,
                ":now": now,
                ":closed": CLOSED,
            },
        )

    def _on_failure(self) -> None:
        """Handle a failed call — increment failure count and transition if threshold reached."""
        now = datetime.now(timezone.utc).isoformat()

        # Atomically increment failure count and get the new value
        response = self._table.update_item(
            Key={"service_name": self.service_name},
            UpdateExpression=(
                "SET failure_count = if_not_exists(failure_count, :zero) + :one, "
                "last_failure_at = :now, updated_at = :now"
            ),
            ExpressionAttributeValues={
                ":zero": 0,
                ":one": 1,
                ":now": now,
            },
            ReturnValues="ALL_NEW",
        )

        item = response.get("Attributes", {})
        failure_count = int(item.get("failure_count", 0))
        current_state = item.get("state", CLOSED)

        if current_state == HALF_OPEN:
            # Any failure in HALF_OPEN → back to OPEN
            self._transition_to(OPEN)
        elif current_state == CLOSED and failure_count >= self._failure_threshold:
            # Threshold exceeded in CLOSED → transition to OPEN
            self._transition_to(OPEN)

    def _recovery_timeout_elapsed(self) -> bool:
        """Check if the recovery timeout has elapsed since the last failure.

        Returns:
            True if enough time has passed to attempt a test request.
        """
        response = self._table.get_item(Key={"service_name": self.service_name})
        item = response.get("Item", {})
        last_failure_at = item.get("last_failure_at", "")

        if not last_failure_at:
            return True

        last_failure_time = datetime.fromisoformat(last_failure_at)
        now = datetime.now(timezone.utc)
        elapsed = (now - last_failure_time).total_seconds()
        return elapsed >= self._recovery_timeout
