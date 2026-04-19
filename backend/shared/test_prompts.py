"""Unit tests for the prompt template helpers."""

from Agentic_AI_With_step_functions.backend.shared.prompts import build_system_prompt, build_user_message


class TestBuildSystemPrompt:
    def test_contains_agent_name(self):
        prompt = build_system_prompt(
            agent_name="Destination Researcher",
            agent_role="Research Indian destinations",
            agent_instructions="Return JSON with destinations.",
        )
        assert "Destination Researcher" in prompt

    def test_contains_role_and_instructions(self):
        prompt = build_system_prompt(
            agent_name="Budget Optimizer",
            agent_role="Optimize travel budget in INR",
            agent_instructions="Include economy and comfort tiers.",
        )
        assert "Optimize travel budget in INR" in prompt
        assert "Include economy and comfort tiers." in prompt

    def test_includes_json_instruction(self):
        prompt = build_system_prompt("A", "B", "C")
        assert "JSON" in prompt


class TestBuildUserMessage:
    def test_returns_converse_format(self):
        msgs = build_user_message("Plan a trip to Goa")
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == [{"text": "Plan a trip to Goa"}]

    def test_preserves_text_exactly(self):
        text = "  spaces and\nnewlines  "
        msgs = build_user_message(text)
        assert msgs[0]["content"][0]["text"] == text
