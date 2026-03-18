from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mylab.storage.io import ensure_dir


@dataclass(frozen=True)
class TrialPaths:
    trial_id: str
    root: Path
    references: Path
    control: Path
    jobs: Path
    logs: Path
    trial: Path
    trial_prompt: Path
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


def trial_root(run_dir: Path, trial_id: str) -> Path:
    return run_dir / "trials" / trial_id


def trial_paths(run_dir: Path, trial_id: str, *, ensure: bool = False) -> TrialPaths:
    root = trial_root(run_dir, trial_id)
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
    return TrialPaths(
        trial_id=trial_id,
        root=root,
        references=references,
        control=control,
        jobs=jobs,
        logs=logs,
        trial=root / "trial.md",
        trial_prompt=control / "trial.prompt.md",
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


def trial_iteration_log_path(run_dir: Path, trial_id: str) -> Path:
    return trial_paths(run_dir, trial_id, ensure=True).logs / "iteration-agent.jsonl"
