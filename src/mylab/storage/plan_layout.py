from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mylab.storage.io import ensure_dir


@dataclass(frozen=True)
class PlanPaths:
    plan_id: str
    root: Path
    references: Path
    plan: Path
    plan_prompt: Path
    executor_prompt: Path
    result: Path
    codex_last: Path
    summary: Path
    command: Path
    git_report: Path
    executor_log: Path
    codex_events: Path


def plan_root(run_dir: Path, plan_id: str) -> Path:
    return run_dir / "plans" / plan_id


def plan_paths(run_dir: Path, plan_id: str, *, ensure: bool = False) -> PlanPaths:
    root = plan_root(run_dir, plan_id)
    references = root / "references"
    if ensure:
        ensure_dir(root)
        ensure_dir(references)
    return PlanPaths(
        plan_id=plan_id,
        root=root,
        references=references,
        plan=root / "plan.md",
        plan_prompt=root / "plan.prompt.md",
        executor_prompt=root / "executor.prompt.md",
        result=root / "result.md",
        codex_last=root / "codex.last.md",
        summary=root / "summary.md",
        command=root / "executor.sh",
        git_report=root / "git.md",
        executor_log=root / "executor.jsonl",
        codex_events=root / "codex.events.jsonl",
    )


def relative_to_run(path: Path, run_dir: Path) -> str:
    return str(path.relative_to(run_dir))
