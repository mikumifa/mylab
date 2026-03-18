from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RunPaths:
    root: Path
    inputs: Path
    assets: Path
    plans: Path
    logs: Path
    commands: Path
    manifests: Path
    queue: Path


@dataclass
class RunManifest:
    run_id: str
    repo_path: str
    source_branch: str
    goal_file: str
    runs_env_var: str
    goal_language: str = "en"
    status: str = "active"
    current_iteration: int = 1
    latest_plan_id: str | None = None
    original_branch: str | None = None
    original_head_commit: str | None = None
    work_branch: str | None = None
    latest_work_commit: str | None = None
    notify_urls: list[str] = field(default_factory=list)
    notify_config_path: str | None = None
    notify_tag: str | None = None
    feedback_cursor: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RunManifest":
        return cls(**payload)


@dataclass
class TaskRecord:
    task_id: str
    kind: str
    status: str
    created_at: str
    payload: dict[str, Any] = field(default_factory=dict)
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TaskRecord":
        return cls(**payload)


@dataclass
class QueueState:
    tasks: list[TaskRecord]

    def to_dict(self) -> dict[str, Any]:
        return {"tasks": [task.to_dict() for task in self.tasks]}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "QueueState":
        return cls(
            tasks=[TaskRecord.from_dict(item) for item in payload.get("tasks", [])]
        )
