"""Bedrock Converse API client with automatic model fallback.

Uses Amazon Nova Pro as the primary model and Amazon Nova Lite as the
fallback model. When the primary model's circuit breaker is OPEN,
requests are automatically routed to the fallback model to maintain
service continuity.
"""

import boto3

from Agentic_AI_With_step_functions.backend.shared.circuit_breaker import CircuitBreaker, CircuitOpenError


class BedrockClient:
    """Bedrock Converse API wrapper with primary/fallback model support.

    Routes LLM inference calls through a circuit breaker. If the primary
    model (Nova Pro) is unavailable or its circuit breaker is OPEN, the
    client automatically falls back to Nova Lite.
    """

    PRIMARY_MODEL = "us.amazon.nova-pro-v1:0"
    FALLBACK_MODEL = "us.amazon.nova-lite-v1:0"

    def __init__(self, circuit_breaker: CircuitBreaker):
        """Initialize the Bedrock client.

        Args:
            circuit_breaker: A CircuitBreaker instance configured for the
                primary model (e.g., service_name="bedrock_nova_pro").
        """
        self.client = boto3.client("bedrock-runtime")
        self.cb = circuit_breaker

    def converse(self, messages: list, system_prompt: str) -> dict:
        """Call Bedrock Converse API with automatic fallback.

        Tries the primary model through the circuit breaker first. If the
        circuit breaker is OPEN (primary model has been failing), falls
        back to Nova Lite directly.

        Args:
            messages: List of message dicts in Bedrock Converse format,
                e.g. [{"role": "user", "content": [{"text": "..."}]}].
            system_prompt: System-level instruction for the model.

        Returns:
            The Bedrock Converse API response dict.
        """
        try:
            return self.cb.call(
                self._invoke, self.PRIMARY_MODEL, messages, system_prompt
            )
        except CircuitOpenError:
            return self._invoke(self.FALLBACK_MODEL, messages, system_prompt)

    def _invoke(self, model_id: str, messages: list, system_prompt: str) -> dict:
        """Call the Bedrock Converse API for a specific model.

        Args:
            model_id: The Bedrock model identifier.
            messages: List of message dicts in Converse format.
            system_prompt: System-level instruction for the model.

        Returns:
            The Bedrock Converse API response dict.
        """
        return self.client.converse(
            modelId=model_id,
            messages=messages,
            system=[{"text": system_prompt}],
        )
