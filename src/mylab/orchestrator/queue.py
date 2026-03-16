from __future__ import annotations

from pathlib import Path

from mylab.domain import QueueState, TaskRecord
from mylab.services.executor import prepare_executor, run_executor
from mylab.services.formatting import format_for_manifest
from mylab.services.plans import create_initial_plan, create_iterated_plan
from mylab.services.reports import write_summary
from mylab.storage import read_json, write_json
from mylab.storage.runs import load_manifest
from mylab.utils import utc_now


QUEUE_FILE = "queue/pipeline.json"


def load_queue(run_dir: Path) -> QueueState:
    queue_path = run_dir / QUEUE_FILE
    if not queue_path.exists():
        return QueueState(tasks=[])
    return QueueState.from_dict(read_json(queue_path))


def save_queue(run_dir: Path, queue: QueueState) -> None:
    write_json(run_dir / QUEUE_FILE, queue.to_dict())


def next_task_id(queue: QueueState) -> str:
    return f"task-{len(queue.tasks) + 1:04d}"


def enqueue_task(run_dir: Path, kind: str, payload: dict[str, object]) -> TaskRecord:
    queue = load_queue(run_dir)
    task = TaskRecord(
        task_id=next_task_id(queue),
        kind=kind,
        status="pending",
        created_at=utc_now(),
        payload=dict(payload),
    )
    queue.tasks.append(task)
    save_queue(run_dir, queue)
    return task


def enqueue_initial_pipeline(run_dir: Path, model: str) -> None:
    enqueue_task(run_dir, "format_repo", {})
    enqueue_task(run_dir, "create_plan", {"model": model})


def enqueue_iteration_pipeline(
    run_dir: Path, parent_plan_id: str, feedback: str, model: str
) -> None:
    enqueue_task(
        run_dir,
        "iterate_plan",
        {"parent_plan_id": parent_plan_id, "feedback": feedback, "model": model},
    )


def complete(task: TaskRecord) -> None:
    task.status = "done"
    task.finished_at = utc_now()


def fail(task: TaskRecord, exc: Exception) -> None:
    task.status = "failed"
    task.finished_at = utc_now()
    task.error = str(exc)


def dispatch(run_dir: Path, task: TaskRecord, allow_exec: bool) -> str:
    manifest = load_manifest(run_dir)
    if task.kind == "format_repo":
        return str(format_for_manifest(run_dir))
    if task.kind == "create_plan":
        return str(create_initial_plan(run_dir_to_paths(run_dir), manifest))
    if task.kind == "iterate_plan":
        return str(
            create_iterated_plan(
                run_dir_to_paths(run_dir),
                manifest,
                parent_plan_id=str(task.payload["parent_plan_id"]),
                feedback=str(task.payload["feedback"]),
            )
        )
    if task.kind == "prepare_executor":
        plan_id = str(task.payload.get("plan_id") or manifest.latest_plan_id)
        if not plan_id:
            raise ValueError("no latest plan available for executor preparation")
        return str(
            prepare_executor(
                run_dir, plan_id, model=str(task.payload.get("model", "gpt-5-mini"))
            )
        )
    if task.kind == "run_executor":
        if not allow_exec:
            raise RuntimeError("execution task encountered but allow_exec is false")
        plan_id = str(task.payload["plan_id"])
        return str(
            run_executor(
                run_dir,
                plan_id,
                model=str(task.payload.get("model", "gpt-5-mini")),
                full_auto=bool(task.payload.get("full_auto", False)),
            )
        )
    if task.kind == "write_summary":
        return str(
            write_summary(
                run_dir,
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
    raise ValueError(f"unsupported task kind: {task.kind}")


def run_dir_to_paths(run_dir: Path):
    from mylab.storage.runs import init_run_dirs

    return init_run_dirs(run_dir)


def enqueue_followups(run_dir: Path, queue: QueueState, task: TaskRecord) -> None:
    manifest = load_manifest(run_dir)
    if task.kind in {"create_plan", "iterate_plan"}:
        if not manifest.latest_plan_id:
            raise ValueError("manifest.latest_plan_id is empty after plan creation")
        queue.tasks.append(
            TaskRecord(
                task_id=next_task_id(queue),
                kind="prepare_executor",
                status="pending",
                created_at=utc_now(),
                payload={
                    "plan_id": manifest.latest_plan_id,
                    "model": str(task.payload.get("model", "gpt-5-mini")),
                },
            )
        )
        return
    if task.kind == "prepare_executor":
        queue.tasks.append(
            TaskRecord(
                task_id=next_task_id(queue),
                kind="run_executor",
                status="pending",
                created_at=utc_now(),
                payload={
                    "plan_id": str(
                        task.payload.get("plan_id") or manifest.latest_plan_id
                    ),
                    "model": str(task.payload.get("model", "gpt-5-mini")),
                    "full_auto": False,
                },
            )
        )
        return
    if task.kind == "run_executor":
        plan_id = str(task.payload["plan_id"])
        queue.tasks.append(
            TaskRecord(
                task_id=next_task_id(queue),
                kind="write_summary",
                status="pending",
                created_at=utc_now(),
                payload={
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
        )


def poll_run(run_dir: Path, limit: int, allow_exec: bool) -> list[dict[str, str]]:
    queue = load_queue(run_dir)
    processed: list[dict[str, str]] = []
    remaining = limit
    for task in queue.tasks:
        if remaining <= 0:
            break
        if task.status != "pending":
            continue
        if task.kind == "run_executor" and not allow_exec:
            break
        task.status = "running"
        task.started_at = utc_now()
        try:
            output = dispatch(run_dir, task, allow_exec=allow_exec)
            complete(task)
            enqueue_followups(run_dir, queue, task)
            processed.append(
                {"task_id": task.task_id, "kind": task.kind, "output": output}
            )
        except Exception as exc:
            fail(task, exc)
            processed.append(
                {"task_id": task.task_id, "kind": task.kind, "output": f"ERROR: {exc}"}
            )
            break
        remaining -= 1
    save_queue(run_dir, queue)
    return processed
