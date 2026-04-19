"""Base prompt template structure used by all four AI agents.

Provides a consistent system prompt format and a helper to build
user messages in the Bedrock Converse API message format.
"""

SYSTEM_PROMPT_TEMPLATE = (
    "You are the {agent_name} for an AI Travel Concierge system.\n"
    "Your role: {agent_role}\n\n"
    "{agent_instructions}\n\n"
    "Respond ONLY with valid JSON matching the required output schema. "
    "Do not include any text outside the JSON object."
)


def build_system_prompt(
    agent_name: str,
    agent_role: str,
    agent_instructions: str,
) -> str:
    """Build a system prompt for an agent.

    Args:
        agent_name: Display name (e.g. "Destination Researcher").
        agent_role: One-line description of the agent's purpose.
        agent_instructions: Detailed instructions and output schema.

    Returns:
        A formatted system prompt string.
    """
    return SYSTEM_PROMPT_TEMPLATE.format(
        agent_name=agent_name,
        agent_role=agent_role,
        agent_instructions=agent_instructions,
    )


def build_user_message(text: str) -> list[dict]:
    """Build a user message list in Bedrock Converse API format.

    Args:
        text: The user-facing message content.

    Returns:
        A list with a single user message dict ready for the Converse API.
    """
    return [{"role": "user", "content": [{"text": text}]}]
