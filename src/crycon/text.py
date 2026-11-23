"""Text cleanup preserving the original database/scoring semantics."""
from typing import Any


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    text = str(value).strip()

    if text.lower() in {"nan", "none", "null"}:
        return ""

    return text
