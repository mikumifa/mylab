from __future__ import annotations

from pathlib import Path


RUNS_ENV_VAR = "MYLAB_RUNS_DIR"
DEFAULT_RUNS_DIR = ".mylab_runs"

PLAN_HEADINGS = [
    "# Plan Metadata",
    "# Experiment Goal",
    "# Investigation Questions",
    "# Execution Plan",
    "# Deliverables",
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
    "plans",
    "prompts",
    "logs",
    "results",
    "summaries",
    "commands",
    "manifests",
    "queue",
)

ROOT = Path(__file__).resolve().parents[2]
