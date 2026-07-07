import re

import pytest

from arx.agents.prompt_loader import load_active_prompt

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


@pytest.mark.parametrize("agent_id", ["a01", "a02", "a07", "a09"])
def test_active_prompt_loads_with_required_header(agent_id):
    prompt = load_active_prompt(agent_id)
    assert prompt.agent_id == agent_id
    assert SEMVER.match(prompt.version), f"version {prompt.version!r} is not semver (Section 86)"
    assert prompt.author.strip()
    assert prompt.description.strip()
    assert prompt.financial_track in ("acquisition", "development", "both")
    assert len(prompt.prompt_text.strip()) > 100


def test_missing_agent_raises():
    with pytest.raises(FileNotFoundError):
        load_active_prompt("a99")
