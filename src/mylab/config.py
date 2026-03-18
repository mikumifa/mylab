from __future__ import annotations

from pathlib import Path


MYLAB_HOME = Path.home() / ".mylab"
RUNS_ENV_VAR = "MYLAB_RUNS_DIR"
DEFAULT_RUNS_DIR = ".mylab_runs"
CONFIG_DIR = MYLAB_HOME
CONFIG_FILE = CONFIG_DIR / "config.toml"
CURRENT_RUN_FILE = CONFIG_DIR / "current_run.json"
TELEGRAM_DIR = MYLAB_HOME / "telegram"
TELEGRAM_STATE_FILE = TELEGRAM_DIR / "state.json"
TELEGRAM_INBOX_DIR = TELEGRAM_DIR / "inbox"
TELEGRAM_INBOX_FILE = TELEGRAM_INBOX_DIR / "messages.jsonl"
TELEGRAM_FILE_DIR = TELEGRAM_INBOX_DIR / "files"

TRIAL_HEADINGS = [
    "# Trial Metadata",
    "# Experiment Goal",
    "# Investigation Questions",
    "# Execution Steps",
    "# Deliverables",
    "# Human Review",
    "# Result Collection Rules",
]

SUMMARY_HEADINGS = [
    "# Summary Metadata",
    "# Outcome",
    "# Evidence",
    "# Artifacts",
    "# Next Iteration",
]

RUN_SUBDIRS = (
    "inputs",
    "assets",
    "trials",
    "logs",
    "commands",
    "manifests",
    "queue",
)

ROOT = Path(__file__).resolve().parents[2]
