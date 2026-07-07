"""Model-agnostic client interface — Section 04 R4 ("Model-agnostic architecture.
Model swapping must not require agent logic rebuilds"), Section 86 N6 ("Model
interface is a replaceable component from day one. No coupling to any specific AI
provider.").

Every agent module calls generate_json() through this interface, never the Anthropic
SDK directly. Swapping MODEL_NAME, or swapping providers entirely, means changing
AnthropicModelClient's implementation — no agent module changes.

Also the seam tests use to avoid real network calls: agent unit tests inject a
FakeModelClient returning canned, schema-shaped JSON (arx/tests/fakes.py) instead of
calling the live API, so the whole pipeline — prompt loading, JSON parsing, Pydantic
schema validation, math validation, snapshot writing — is exercised without needing a
real ANTHROPIC_API_KEY.
"""
import json
import re
from dataclasses import dataclass
from typing import Protocol

import anthropic

from arx.api.config import get_settings


@dataclass(frozen=True)
class ModelResponse:
    parsed: dict
    raw_text: str
    input_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class ModelClient(Protocol):
    def generate_json(self, system_prompt: str, user_message: str, max_tokens: int) -> ModelResponse: ...


def _extract_json(text: str) -> dict:
    """Models sometimes wrap JSON in a markdown code fence despite instructions not to.
    Strip that defensively rather than letting a cosmetic wrapper become a hard failure
    — the actual JSON.decode of malformed content still raises and is treated as an
    unrecoverable error upstream (Section 10 EH3)."""
    stripped = text.strip()
    fence_match = re.match(r"^```(?:json)?\s*(.*)```\s*$", stripped, re.DOTALL)
    if fence_match:
        stripped = fence_match.group(1).strip()
    return json.loads(stripped)


class AnthropicModelClient:
    """Section 05: AI model claude-sonnet-4-20250514, primary. Configured via
    MODEL_NAME so swapping models is a config change, not a code change (R4)."""

    def __init__(self, api_key: str | None = None, model_name: str | None = None):
        settings = get_settings()
        self._client = anthropic.Anthropic(api_key=api_key or settings.anthropic_api_key)
        self._model_name = model_name or settings.model_name

    def generate_json(self, system_prompt: str, user_message: str, max_tokens: int) -> ModelResponse:
        response = self._client.messages.create(
            model=self._model_name,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        raw_text = "".join(block.text for block in response.content if block.type == "text")
        parsed = _extract_json(raw_text)
        return ModelResponse(
            parsed=parsed,
            raw_text=raw_text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )


_default_client: ModelClient | None = None


def get_default_model_client() -> ModelClient:
    global _default_client
    if _default_client is None:
        _default_client = AnthropicModelClient()
    return _default_client


def model_client_dependency() -> ModelClient:
    """FastAPI dependency wrapping get_default_model_client(). Routes depend on this
    (not the agent modules' own model_client=None default) specifically so tests can
    swap in a FakeModelClient via app.dependency_overrides — the real Anthropic client
    is never constructed, let alone called, when this is overridden."""
    return get_default_model_client()
