from __future__ import annotations

import json
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CodexStatus:
    login_status: str
    configured_model: str | None
    effective_model: str | None
    reasoning_effort: str | None
    cli_version: str | None
    quota_status: str


def _read_config() -> dict[str, object]:
    config_path = Path.home() / ".codex" / "config.toml"
    if not config_path.exists():
        return {}
    with config_path.open("rb") as handle:
        return tomllib.load(handle)


def _login_status() -> str:
    try:
        result = subprocess.run(
            ["codex", "login", "status"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return "unknown"
    return result.stdout.strip() or "unknown"


def _cli_version() -> str | None:
    version_path = Path.home() / ".codex" / "version.json"
    if not version_path.exists():
        return None
    try:
        payload = json.loads(version_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    value = payload.get("latest_version")
    return value if isinstance(value, str) else None


def get_codex_status(model_override: str | None = None) -> CodexStatus:
    config = _read_config()
    configured_model = config.get("model") if isinstance(config.get("model"), str) else None
    reasoning_effort = (
        config.get("model_reasoning_effort")
        if isinstance(config.get("model_reasoning_effort"), str)
        else None
    )
    effective_model = model_override or configured_model
    return CodexStatus(
        login_status=_login_status(),
        configured_model=configured_model,
        effective_model=effective_model,
        reasoning_effort=reasoning_effort,
        cli_version=_cli_version(),
        quota_status="unknown (Codex CLI does not expose account quota directly)",
    )
