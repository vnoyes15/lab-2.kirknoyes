"""Test doubles. FakeModelClient satisfies the ModelClient protocol
(arx/agents/model_client.py) without ever calling the real Anthropic API — every agent
test in this suite runs against it, which is what makes the whole pipeline (prompt
loading, schema validation, math validation, snapshot writing) testable without a real
ANTHROPIC_API_KEY.
"""
from arx.agents.model_client import ModelResponse


class FakeModelClient:
    def __init__(self, response_json: dict, input_tokens: int = 100, output_tokens: int = 200):
        self._response_json = response_json
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self.calls: list[dict] = []

    def generate_json(self, system_prompt: str, user_message: str, max_tokens: int) -> ModelResponse:
        self.calls.append({"system_prompt": system_prompt, "user_message": user_message, "max_tokens": max_tokens})
        return ModelResponse(
            parsed=self._response_json,
            raw_text="<fake>",
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
        )
