from __future__ import annotations

import re
import shlex
from datetime import datetime, timezone


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
