from __future__ import annotations

import re
import shlex
from datetime import datetime, timezone


def detect_preferred_language(text: str) -> str:
    cjk_count = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    ascii_letters = sum(1 for char in text if char.isascii() and char.isalpha())
    if cjk_count and cjk_count >= max(3, ascii_letters // 4):
        return "zh"
    return "en"


def describe_language(language: str) -> str:
    return "Chinese" if language == "zh" else "English"


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def slugify(value: str, max_length: int = 40) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return (cleaned or "run")[:max_length].strip("-") or "run"


def shell_join(parts: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)
