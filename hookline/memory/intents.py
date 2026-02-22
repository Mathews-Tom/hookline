"""Intent tag parser for message classification."""
from __future__ import annotations

import re

# Pattern matches [REMEMBER], [GOAL], [DONE] with optional content after colon
_INTENT_PATTERN = re.compile(
    r"\[(REMEMBER|GOAL|DONE)(?:\s*:\s*([^\]]*))?\]",
    re.IGNORECASE,
)

_HASHTAG_PATTERN = re.compile(r"#(\w{2,})")

_INTENT_MAP: dict[str, str] = {
    "REMEMBER": "remember",
    "GOAL": "goal",
    "DONE": "done",
}


def parse_intent(text: str) -> tuple[str, str, str]:
    """Parse intent tags from message text.

    Returns (intent, tag_content, clean_text) where:
    - intent: "remember", "goal", "done", or "" if no tag
    - tag_content: text inside [TAG: content] or ""
    - clean_text: original text with the tag stripped
    """
    match = _INTENT_PATTERN.search(text)
    if not match:
        return "", "", text

    tag_name = match.group(1).upper()
    tag_content = (match.group(2) or "").strip()
    intent = _INTENT_MAP.get(tag_name, "")
    clean_text = text[:match.start()] + text[match.end():]
    clean_text = clean_text.strip()

    return intent, tag_content, clean_text


def extract_tags(text: str) -> list[str]:
    """Extract all #hashtags from text."""
    return _HASHTAG_PATTERN.findall(text)
