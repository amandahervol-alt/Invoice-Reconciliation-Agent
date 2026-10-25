"""Helpers shared by the Claude-backed services."""
import os

# claude-3-7-sonnet-20250219 was retired on February 19, 2026; Anthropic recommends claude-sonnet-5-5.
DEFAULT_MODEL = "claude-sonnet-5-5"

# Current Claude models reject temperature/top_p/top_k with a 400 error, so they are never sent.
# Low effort keeps adaptive thinking minimal for these simple extraction/classification tasks.
REQUEST_EXTRA_BODY = {"output_config": {"effort": "low"}}


def model_name() -> str:
    return (os.getenv("ANTHROPIC_MODEL") or "").strip() or DEFAULT_MODEL


def first_text(response) -> str:
    """Return the first text block of a Messages API response.

    With adaptive thinking, thinking blocks can come before the answer,
    so content[0] is not guaranteed to be text.
    """
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "text":
            return (block.text or "").strip()
    raise ValueError("Claude response contained no text block.")

