from __future__ import annotations

from pathlib import Path
import sys
import time
from typing import Callable

from mylab.domain import QueueState, TaskRecord
from mylab.logging import emit_progress, logger
from mylab.orchestrator.queue import load_queue, save_queue
from mylab.services.executor import prepare_executor, run_executor
from mylab.services.formatting import format_for_manifest
from mylab.services.git_lifecycle import (
    commit_iteration_changes,
    ensure_run_branch,
    restore_original_branch,
)
from mylab.services.notifications import NotificationClient, load_notification_settings
from mylab.services.plans import create_initial_plan, create_iterated_plan
from mylab.services.reports import write_summary
from mylab.services.run_control import (
    FLOW_MODE_LIMIT,
    FLOW_MODE_STEP,
    FLOW_MODE_UNLIMIT,
)
from mylab.services.telegram_bot import (
    TelegramBotClient,
    feedback_record_count,
    consume_feedback_since,
    load_telegram_settings,
)
from mylab.storage.runs import init_run_dirs, load_manifest, save_manifest
from mylab.utils import utc_now


class SerialFlowRunner:
    def __init__(
        self,
        run_dir: Path,
        allow_exec: bool,
        *,
        mode: str = FLOW_MODE_LIMIT,
        confirm_continue: Callable[[int], bool] | None = None,
    ) -> None:
        self.run_dir = run_dir
        self.allow_exec = allow_exec
        self.mode = mode
        self.confirm_continue = confirm_continue
        self.paths = init_run_dirs(run_dir)
        self.notifier = NotificationClient(run_dir, load_notification_settings(run_dir))
        self._telegram_poll_warned = False

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
            "commit_changes": "git delivery",
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

    def _is_iteration_task(self, task: TaskRecord) -> bool:
        return task.kind in {
            "create_plan",
            "iterate_plan",
            "prepare_branch",
            "prepare_executor",
            "run_executor",
            "commit_changes",
            "write_summary",
            "restore_branch",
        }

    def _starts_iteration(self, task: TaskRecord) -> bool:
        return self._is_iteration_task(task)

    def _ends_iteration(self, task: TaskRecord) -> bool:
        return task.kind == "restore_branch"

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
        self.notifier.notify(
            f"mylab run {manifest.run_id} started",
            (
                f"repo={manifest.repo_path}\n"
                f"branch={manifest.source_branch}\n"
                f"latest_plan={manifest.latest_plan_id or '-'}\n"
                f"pending={pending} done={done} failed={failed}"
            ),
            notify_type="info",
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
            self._append_task(queue, "commit_changes", {"plan_id": plan_id})
            return
        if task.kind == "commit_changes":
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
        if task.kind == "commit_changes":
            return str(
                commit_iteration_changes(
                    self.run_dir, manifest, str(task.payload["plan_id"])
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

    def _restore_after_interruption(self) -> None:
        try:
            manifest = load_manifest(self.run_dir)
            if manifest.work_branch and manifest.original_branch:
                restore_original_branch(self.run_dir, manifest)
        except Exception:
            logger.exception("Failed to restore branch after interruption")

    def _step_limit(self, limit: int | None) -> int:
        if isinstance(limit, int) and limit > 0:
            return limit
        return 1

    def _enqueue_iteration_request(
        self, queue: QueueState, parent_plan_id: str, feedback: str
    ) -> None:
        self._append_task(
            queue,
            "iterate_plan",
            {
                "parent_plan_id": parent_plan_id,
                "feedback": feedback,
                "model": None,
            },
        )

    def _auto_feedback(self) -> str:
        return (
            "Continue to the next full iteration based on the latest plan, summary, "
            "result report, repository shared asset, and preserved execution evidence."
        )

    def _poll_telegram_feedback(self, settings=None) -> None:
        telegram_settings = settings or load_telegram_settings()
        if not telegram_settings.enabled:
            return
        try:
            TelegramBotClient(telegram_settings).poll_once()
            self._telegram_poll_warned = False
        except Exception as exc:
            if not self._telegram_poll_warned:
                logger.info("Telegram polling failed during flow wait: {}", exc)
                self._telegram_poll_warned = True

    def _wait_for_step_feedback(self, completed_iterations: int) -> str | None:
        settings = load_telegram_settings()
        poll_seconds = max(settings.poll_interval_seconds, 1)
        telegram_enabled = settings.enabled
        wait_cursor: int | None = None
        warned = False
        while True:
            if telegram_enabled:
                self._poll_telegram_feedback(settings)
            manifest = load_manifest(self.run_dir)
            if wait_cursor is None:
                # Ignore stale step feedback that already existed before this wait began.
                wait_cursor = max(
                    int(manifest.feedback_cursor),
                    feedback_record_count(scopes={"step"}),
                )
            feedback, cursor = consume_feedback_since(wait_cursor)
            if feedback:
                manifest.feedback_cursor = cursor
                save_manifest(self.paths, manifest)
                return feedback
            wait_cursor = cursor
            if self.confirm_continue is not None:
                if not self.confirm_continue(completed_iterations):
                    return None
                return self._auto_feedback()
            if not telegram_enabled and sys.stdin.isatty():
                text = input(
                    f"Step mode: iteration {completed_iterations} finished. "
                    "Enter next instruction, /continue to keep going, or /stop to stop waiting: "
                ).strip()
                if not text:
                    continue
                if text.lower() in {"/continue", "continue"}:
                    return self._auto_feedback()
                if text.lower() in {"/stop", "stop"}:
                    return None
                return text
            if not warned:
                wait_source = (
                    "waiting for next-iteration instruction from Telegram"
                    if telegram_enabled
                    else "waiting for next-iteration instruction"
                )
                logger.info(
                    "Step mode waiting after {} completed iteration(s); source={}",
                    completed_iterations,
                    "telegram" if telegram_enabled else "background feedback",
                )
                emit_progress(
                    "[wait]",
                    "step mode",
                    wait_source,
                    color="yellow",
                )
                warned = True
            time.sleep(poll_seconds)

    def _maybe_chain_next_iteration(
        self,
        queue: QueueState,
        *,
        completed_iterations: int,
        step_limit: int,
    ) -> bool:
        if self._next_pending(queue) is not None:
            return True
        manifest = load_manifest(self.run_dir)
        if not manifest.latest_plan_id:
            return True
        settings = load_telegram_settings()
        if settings.enabled:
            self._poll_telegram_feedback(settings)
        if self.mode == FLOW_MODE_UNLIMIT:
            feedback, cursor = consume_feedback_since(manifest.feedback_cursor)
            if feedback:
                manifest.feedback_cursor = cursor
                save_manifest(self.paths, manifest)
                self._enqueue_iteration_request(
                    queue, manifest.latest_plan_id, feedback
                )
            else:
                self._enqueue_iteration_request(
                    queue, manifest.latest_plan_id, self._auto_feedback()
                )
            return True
        if self.mode == FLOW_MODE_STEP:
            if completed_iterations < step_limit:
                feedback, cursor = consume_feedback_since(manifest.feedback_cursor)
                if feedback:
                    manifest.feedback_cursor = cursor
                    save_manifest(self.paths, manifest)
                    self._enqueue_iteration_request(
                        queue, manifest.latest_plan_id, feedback
                    )
                else:
                    self._enqueue_iteration_request(
                        queue, manifest.latest_plan_id, self._auto_feedback()
                    )
                return True
            feedback = self._wait_for_step_feedback(completed_iterations)
            if not feedback:
                return False
            self._enqueue_iteration_request(queue, manifest.latest_plan_id, feedback)
            return True
        return True

    def run_until_blocked(self, limit: int | None) -> list[dict[str, str]]:
        logger.info(
            "Starting serial flow for {} with mode={} limit={}",
            self.run_dir,
            self.mode,
            limit,
        )
        queue = load_queue(self.run_dir)
        self._log_run_overview(queue)
        processed: list[dict[str, str]] = []
        completed_iterations = 0
        iteration_in_progress = False
        step_limit = self._step_limit(limit) if self.mode == FLOW_MODE_STEP else 0
        while True:
            if (
                self.mode == FLOW_MODE_LIMIT
                and isinstance(limit, int)
                and completed_iterations >= limit
                and not iteration_in_progress
            ):
                break
            task = self._next_pending(queue)
            if task is None:
                if self.mode in {FLOW_MODE_STEP, FLOW_MODE_UNLIMIT}:
                    if not self._maybe_chain_next_iteration(
                        queue,
                        completed_iterations=completed_iterations,
                        step_limit=step_limit,
                    ):
                        break
                    task = self._next_pending(queue)
                    if task is None:
                        break
                else:
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
            if self._starts_iteration(task):
                iteration_in_progress = True
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
                    logger.info(
                        "Task start | {} | {}", task.task_id, self._task_label(task)
                    )
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
                if self._ends_iteration(task):
                    completed_iterations += 1
                    iteration_in_progress = False
                    if not self._maybe_chain_next_iteration(
                        queue,
                        completed_iterations=completed_iterations,
                        step_limit=step_limit,
                    ):
                        break
            except KeyboardInterrupt:
                logger.info(
                    "Task interrupted | {} | {}", task.task_id, self._task_label(task)
                )
                emit_progress(
                    "[interrupt]",
                    f"{task.task_id} {self._task_label(task)}",
                    "received Ctrl+C",
                    color="yellow",
                )
                if task.kind != "restore_branch":
                    self._restore_after_interruption()
                task.status = "failed"
                task.finished_at = utc_now()
                task.error = "interrupted by user"
                processed.append(
                    {
                        "task_id": task.task_id,
                        "kind": task.kind,
                        "output": "INTERRUPTED: user requested stop",
                    }
                )
                self.notifier.notify(
                    f"mylab task interrupted: {task.kind}",
                    (
                        f"run={self.run_dir.name}\n"
                        f"task={task.task_id}\n"
                        f"kind={task.kind}\n"
                        "reason=user_interrupt"
                    ),
                    notify_type="warning",
                )
                break
            except Exception as exc:
                logger.exception(
                    "Task failed | {} | {}", task.task_id, self._task_label(task)
                )
                emit_progress(
                    "[fail]",
                    f"{task.task_id} {self._task_label(task)}",
                    str(exc),
                    color="red",
                )
                if task.kind != "restore_branch":
                    self._restore_after_interruption()
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
                self.notifier.notify(
                    f"mylab task failed: {task.kind}",
                    (
                        f"run={self.run_dir.name}\n"
                        f"task={task.task_id}\n"
                        f"kind={task.kind}\n"
                        f"error={exc}"
                    ),
                    notify_type="failure",
                )
                break
        save_queue(self.run_dir, queue)
        logger.info(
            "Serial flow finished after processing {} task(s), completed_iterations={}",
            len(processed),
            completed_iterations,
        )
        emit_progress(
            "[flow]",
            "serial flow finished",
            f"processed={len(processed)} iterations={completed_iterations}",
            color="blue",
        )
        self.notifier.notify(
            f"mylab flow finished: {self.run_dir.name}",
            f"processed={len(processed)} allow_exec={self.allow_exec}",
            notify_type="info",
        )
        return processed
