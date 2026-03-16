from __future__ import annotations

from pathlib import Path

from mylab.domain import QueueState, TaskRecord
from mylab.logging import emit_progress, logger
from mylab.orchestrator.queue import load_queue, save_queue
from mylab.services.executor import prepare_executor, run_executor
from mylab.services.formatting import format_for_manifest
from mylab.services.git_lifecycle import ensure_run_branch, restore_original_branch
from mylab.services.plans import create_initial_plan, create_iterated_plan
from mylab.services.reports import write_summary
from mylab.storage.runs import init_run_dirs, load_manifest
from mylab.utils import utc_now


class SerialFlowRunner:
    def __init__(self, run_dir: Path, allow_exec: bool) -> None:
        self.run_dir = run_dir
        self.allow_exec = allow_exec
        self.paths = init_run_dirs(run_dir)

    def _next_pending(self, queue: QueueState) -> TaskRecord | None:
        for task in queue.tasks:
            if task.status == "pending":
                return task
        return None

    def _task_label(self, task: TaskRecord) -> str:
        labels = {
            "format_repo": "repo audit",
            "create_plan": "initial plan",
            "iterate_plan": "plan iteration",
            "prepare_branch": "git branch setup",
            "prepare_executor": "executor preparation",
            "run_executor": "codex execution",
            "write_summary": "summary writing",
            "restore_branch": "branch restore",
        }
        return labels.get(task.kind, task.kind)

    def _task_context(self, task: TaskRecord) -> str:
        parts: list[str] = []
        plan_id = task.payload.get("plan_id")
        if plan_id:
            parts.append(f"plan={plan_id}")
        parent_plan = task.payload.get("parent_plan_id")
        if parent_plan:
            parts.append(f"parent={parent_plan}")
        model = self._payload_model(task)
        if model:
            parts.append(f"model={model}")
        feedback = task.payload.get("feedback")
        if isinstance(feedback, str) and feedback.strip():
            brief = feedback.strip().replace("\n", " ")
            parts.append(f"feedback={brief[:80]}")
        return ", ".join(parts)

    def _log_run_overview(self, queue: QueueState) -> None:
        manifest = load_manifest(self.run_dir)
        pending = sum(1 for task in queue.tasks if task.status == "pending")
        done = sum(1 for task in queue.tasks if task.status == "done")
        failed = sum(1 for task in queue.tasks if task.status == "failed")
        logger.info(
            "Run overview | run={} repo={} source_branch={} latest_plan={} queued(pending={}, done={}, failed={})",
            manifest.run_id,
            manifest.repo_path,
            manifest.source_branch,
            manifest.latest_plan_id or "-",
            pending,
            done,
            failed,
        )
        emit_progress(
            "[run]",
            f"{manifest.run_id}",
            f"repo={manifest.repo_path} branch={manifest.source_branch} plan={manifest.latest_plan_id or '-'} pending={pending} done={done} failed={failed}",
            color="blue",
        )

    def _append_task(
        self, queue: QueueState, kind: str, payload: dict[str, object]
    ) -> None:
        queue.tasks.append(
            TaskRecord(
                task_id=f"task-{len(queue.tasks) + 1:04d}",
                kind=kind,
                status="pending",
                created_at=utc_now(),
                payload=dict(payload),
            )
        )

    def _payload_model(self, task: TaskRecord) -> str | None:
        value = task.payload.get("model")
        if isinstance(value, str) and value.strip():
            return value
        return None

    def _enqueue_followups(self, queue: QueueState, task: TaskRecord) -> None:
        manifest = load_manifest(self.run_dir)
        if task.kind in {"create_plan", "iterate_plan"}:
            self._append_task(
                queue,
                "prepare_branch",
                {
                    "plan_id": manifest.latest_plan_id,
                    "model": self._payload_model(task),
                },
            )
            return
        if task.kind == "prepare_branch":
            self._append_task(
                queue,
                "prepare_executor",
                {
                    "plan_id": str(task.payload["plan_id"]),
                    "model": self._payload_model(task),
                },
            )
            return
        if task.kind == "prepare_executor":
            self._append_task(
                queue,
                "run_executor",
                {
                    "plan_id": str(task.payload["plan_id"]),
                    "model": self._payload_model(task),
                    "full_auto": False,
                },
            )
            return
        if task.kind == "run_executor":
            plan_id = str(task.payload["plan_id"])
            self._append_task(
                queue,
                "write_summary",
                {
                    "plan_id": plan_id,
                    "status": "completed",
                    "outcome": "Execution finished. Replace this placeholder with an evidence-based summary.",
                    "evidence": [
                        f"logs/{plan_id}.codex.events.jsonl",
                        f"results/{plan_id}.codex.last.md",
                    ],
                    "artifacts": [
                        f"commands/{plan_id}.executor.sh",
                        f"plans/{plan_id}.md",
                    ],
                    "next_iteration": [
                        "Inspect the result report and replace this placeholder summary."
                    ],
                },
            )
            self._append_task(queue, "restore_branch", {})

    def _dispatch(self, task: TaskRecord) -> str:
        manifest = load_manifest(self.run_dir)
        if task.kind == "format_repo":
            return str(format_for_manifest(self.run_dir))
        if task.kind == "create_plan":
            return str(create_initial_plan(self.paths, manifest))
        if task.kind == "iterate_plan":
            return str(
                create_iterated_plan(
                    self.paths,
                    manifest,
                    parent_plan_id=str(task.payload["parent_plan_id"]),
                    feedback=str(task.payload["feedback"]),
                )
            )
        if task.kind == "prepare_branch":
            return ensure_run_branch(
                self.run_dir, manifest, str(task.payload["plan_id"])
            )
        if task.kind == "prepare_executor":
            return str(
                prepare_executor(
                    self.run_dir,
                    str(task.payload["plan_id"]),
                    model=self._payload_model(task),
                )
            )
        if task.kind == "run_executor":
            if not self.allow_exec:
                raise RuntimeError("execution task encountered but allow_exec is false")
            return str(
                run_executor(
                    self.run_dir,
                    str(task.payload["plan_id"]),
                    model=self._payload_model(task),
                    full_auto=bool(task.payload.get("full_auto", False)),
                )
            )
        if task.kind == "write_summary":
            return str(
                write_summary(
                    self.run_dir,
                    plan_id=str(task.payload["plan_id"]),
                    status=str(task.payload.get("status", "unknown")),
                    outcome=str(task.payload.get("outcome", "Summary placeholder.")),
                    evidence=[str(item) for item in task.payload.get("evidence", [])],
                    artifacts=[str(item) for item in task.payload.get("artifacts", [])],
                    next_iteration=[
                        str(item) for item in task.payload.get("next_iteration", [])
                    ],
                )
            )
        if task.kind == "restore_branch":
            return restore_original_branch(self.run_dir, manifest)
        raise ValueError(f"unsupported task kind: {task.kind}")

    def run_until_blocked(self, limit: int) -> list[dict[str, str]]:
        logger.info("Starting serial flow for {} with limit={}", self.run_dir, limit)
        queue = load_queue(self.run_dir)
        self._log_run_overview(queue)
        processed: list[dict[str, str]] = []
        remaining = limit
        while remaining > 0:
            task = self._next_pending(queue)
            if task is None:
                break
            if task.kind == "run_executor" and not self.allow_exec:
                logger.info(
                    "Serial flow blocked on {} ({})",
                    task.task_id,
                    self._task_label(task),
                )
                emit_progress(
                    "[wait]",
                    f"{task.task_id} {self._task_label(task)}",
                    "execution gate is closed",
                    color="yellow",
                )
                break
            task.status = "running"
            task.started_at = utc_now()
            try:
                context = self._task_context(task)
                if context:
                    logger.info(
                        "Task start | {} | {} | {}",
                        task.task_id,
                        self._task_label(task),
                        context,
                    )
                    emit_progress(
                        "[task]",
                        f"{task.task_id} {self._task_label(task)}",
                        context,
                        color="cyan",
                    )
                else:
                    logger.info("Task start | {} | {}", task.task_id, self._task_label(task))
                    emit_progress(
                        "[task]",
                        f"{task.task_id} {self._task_label(task)}",
                        color="cyan",
                    )
                output = self._dispatch(task)
                task.status = "done"
                task.finished_at = utc_now()
                self._enqueue_followups(queue, task)
                logger.info("Task done  | {} | output={}", task.task_id, output)
                emit_progress(
                    "[done]",
                    f"{task.task_id} {self._task_label(task)}",
                    str(output),
                    color="green",
                )
                processed.append(
                    {"task_id": task.task_id, "kind": task.kind, "output": output}
                )
            except Exception as exc:
                logger.exception("Task failed | {} | {}", task.task_id, self._task_label(task))
                emit_progress(
                    "[fail]",
                    f"{task.task_id} {self._task_label(task)}",
                    str(exc),
                    color="red",
                )
                if task.kind != "restore_branch":
                    try:
                        manifest = load_manifest(self.run_dir)
                        if manifest.work_branch and manifest.original_branch:
                            restore_original_branch(self.run_dir, manifest)
                    except Exception:
                        logger.exception("Failed to restore branch after task failure")
                task.status = "failed"
                task.finished_at = utc_now()
                task.error = str(exc)
                logger.info("Task error | {} | {}", task.task_id, str(exc))
                processed.append(
                    {
                        "task_id": task.task_id,
                        "kind": task.kind,
                        "output": f"ERROR: {exc}",
                    }
                )
                break
            remaining -= 1
        save_queue(self.run_dir, queue)
        logger.info("Serial flow finished after processing {} task(s)", len(processed))
        emit_progress(
            "[flow]",
            "serial flow finished",
            f"processed={len(processed)}",
            color="blue",
        )
        return processed
