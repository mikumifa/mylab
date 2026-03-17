from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib

from mylab.config import CONFIG_FILE


FLOW_MODE_LIMIT = "limit"
FLOW_MODE_STEP = "step"
FLOW_MODE_UNLIMIT = "unlimit"
FLOW_MODES = (FLOW_MODE_LIMIT, FLOW_MODE_STEP, FLOW_MODE_UNLIMIT)


@dataclass
class RunControlSettings:
    mode: str | None = None
    limit: int | None = None


def normalize_flow_mode(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    lowered = value.strip().lower()
    if lowered in FLOW_MODES:
        return lowered
    return None


def load_run_control_settings(config_path: Path | None = None) -> RunControlSettings:
    target = config_path or CONFIG_FILE
    if not target.exists():
        return RunControlSettings()
    with target.open("rb") as handle:
        payload = tomllib.load(handle)
    if not isinstance(payload, dict):
        return RunControlSettings()
    section = payload.get("runner", {})
    if not isinstance(section, dict):
        return RunControlSettings()
    raw_limit = section.get("limit")
    limit = raw_limit if isinstance(raw_limit, int) and raw_limit >= 0 else None
    return RunControlSettings(
        mode=normalize_flow_mode(section.get("mode")),
        limit=limit,
    )


def prompt_for_flow_mode(
    *,
    input_fn=input,
    current_mode: str | None = None,
) -> str:
    default_value = current_mode or FLOW_MODE_LIMIT
    prompt = f"Execution mode [1=limit, 2=step, 3=unlimit, default={default_value}]: "
    while True:
        value = input_fn(prompt).strip().lower()
        if not value:
            return default_value
        if value in {"1", FLOW_MODE_LIMIT}:
            return FLOW_MODE_LIMIT
        if value in {"2", FLOW_MODE_STEP}:
            return FLOW_MODE_STEP
        if value in {"3", FLOW_MODE_UNLIMIT}:
            return FLOW_MODE_UNLIMIT
        print("Invalid mode. Choose 1/2/3 or limit/step/unlimit.")
