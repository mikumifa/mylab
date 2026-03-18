from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mylab.storage.io import ensure_dir


@dataclass(frozen=True)
class PlanPaths:
    plan_id: str
    root: Path
    references: Path
    control: Path
    jobs: Path
    logs: Path
    plan: Path
    plan_prompt: Path
    executor_prompt: Path
    card: Path
    status: Path
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
    control = root / "control"
    jobs = root / "jobs"
    logs = root / "logs"
    if ensure:
        ensure_dir(root)
        ensure_dir(references)
        ensure_dir(control)
        ensure_dir(jobs)
        ensure_dir(logs)
    return PlanPaths(
        plan_id=plan_id,
        root=root,
        references=references,
        control=control,
        jobs=jobs,
        logs=logs,
        plan=root / "plan.md",
        plan_prompt=control / "plan.prompt.md",
        executor_prompt=control / "executor.prompt.md",
        card=control / "card.json",
        status=control / "status.json",
        result=references / "result.md",
        codex_last=references / "codex.last.md",
        summary=references / "summary.md",
        command=root / "executor.sh",
        git_report=references / "git.md",
        executor_log=logs / "executor.jsonl",
        codex_events=logs / "codex.events.jsonl",
    )


def relative_to_run(path: Path, run_dir: Path) -> str:
    return str(path.relative_to(run_dir))


def plan_iteration_log_path(run_dir: Path, plan_id: str) -> Path:
    return plan_paths(run_dir, plan_id, ensure=True).logs / "iteration-agent.jsonl"
