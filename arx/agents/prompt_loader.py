"""Prompt loader — Section 86 prompt versioning convention.

"Never hardcode a prompt string in Python source code... Prompts live in /arx/prompts/
in versioned YAML files." Each agent folder (arx/prompts/a01/ .. a13/) holds every
version of that agent's prompt plus a current.txt pointer naming the active one. This
module is the only code path that reads prompt_text out of those files — agent modules
call load_active_prompt(agent_id) and never open a prompt file themselves.
"""
from dataclasses import dataclass
from pathlib import Path

import yaml

PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"

REQUIRED_HEADER_FIELDS = ("agent_id", "version", "created_at", "author", "description", "financial_track")


@dataclass(frozen=True)
class PromptDefinition:
    agent_id: str
    version: str
    created_at: str
    author: str
    description: str
    financial_track: str  # "acquisition" | "development" | "both"
    prompt_text: str


def _validate_header(data: dict, path: Path) -> None:
    for field in REQUIRED_HEADER_FIELDS:
        value = data.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError(f"Prompt file {path} is missing required field '{field}' (Section 86: no field may be blank)")
    if not data.get("prompt_text", "").strip():
        raise ValueError(f"Prompt file {path} has blank prompt_text")


def load_active_prompt(agent_id: str) -> PromptDefinition:
    """Reads current.txt for agent_id, loads the YAML file it names, validates the
    header, and returns a PromptDefinition. Raises if current.txt or the target file
    is missing — a missing active prompt is a deploy-time configuration error, not
    something to default around silently (Section 06 N3: never fabricate)."""
    agent_dir = PROMPTS_ROOT / agent_id
    current_pointer = agent_dir / "current.txt"
    if not current_pointer.exists():
        raise FileNotFoundError(f"No current.txt for agent '{agent_id}' at {current_pointer}")

    active_filename = current_pointer.read_text().strip()
    if not active_filename:
        raise ValueError(f"current.txt for agent '{agent_id}' is blank")

    prompt_path = agent_dir / active_filename
    if not prompt_path.exists():
        raise FileNotFoundError(f"current.txt for '{agent_id}' points at missing file {prompt_path}")

    data = yaml.safe_load(prompt_path.read_text())
    _validate_header(data, prompt_path)

    return PromptDefinition(
        agent_id=data["agent_id"],
        version=str(data["version"]),
        created_at=str(data["created_at"]),
        author=data["author"],
        description=data["description"],
        financial_track=data["financial_track"],
        prompt_text=data["prompt_text"],
    )
