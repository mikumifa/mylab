from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from mylab.storage import ensure_dir, read_json, write_json
from mylab.storage.plan_layout import plan_paths
from mylab.utils import shell_join, slugify, utc_now


DEFAULT_JOB_WAIT_SECONDS = 3600
DEFAULT_JOB_POLL_SECONDS = 10
DEFAULT_JOB_TAIL_LINES = 20


def _job_id(plan_id: str, name: str | None) -> str:
    stamp = utc_now().replace("-", "").replace(":", "").replace("T", "t")
    label = slugify(name or "job", max_length=24)
    return f"{plan_id}-{label}-{stamp.lower()}"


def _job_record_path(run_dir: Path, job_id: str, plan_id: str | None = None) -> Path:
    if plan_id:
        return plan_paths(run_dir, plan_id, ensure=True).jobs / f"{job_id}.json"
    matches = sorted(run_dir.glob(f"plans/*/jobs/{job_id}.json"))
    if matches:
        return matches[-1]
    return run_dir / "jobs" / f"{job_id}.json"


def _tail_text(path: Path, lines: int) -> str:
    if lines <= 0 or not path.exists():
        return ""
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-lines:])


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _persist_terminal_status(record: dict[str, Any], status: str, exit_code: int) -> None:
    if record.get("status") == status and record.get("exit_code") == exit_code:
        return
    record["status"] = status
    record["exit_code"] = exit_code
    if not record.get("finished_at"):
        record["finished_at"] = utc_now()
    write_json(Path(record["record_path"]), record)


def load_job_record(run_dir: Path, job_id: str) -> dict[str, Any]:
    return read_json(_job_record_path(run_dir, job_id))


def get_job_status(run_dir: Path, job_id: str) -> dict[str, Any]:
    record = load_job_record(run_dir, job_id)
    exit_code_path = Path(record["exit_code_path"])
    if exit_code_path.exists():
        exit_code = int(exit_code_path.read_text(encoding="utf-8").strip() or "0")
        status = "completed" if exit_code == 0 else "failed"
        _persist_terminal_status(record, status, exit_code)
        record = load_job_record(run_dir, job_id)
    elif _pid_is_alive(int(record["pid"])):
        record["status"] = "running"
    else:
        record["status"] = "unknown"
    return {
        "job_id": record["job_id"],
        "plan_id": record["plan_id"],
        "name": record["name"],
        "status": record["status"],
        "pid": record["pid"],
        "command": record["command"],
        "cwd": record["cwd"],
        "stdout_path": record["stdout_path"],
        "stderr_path": record["stderr_path"],
        "started_at": record["started_at"],
        "finished_at": record.get("finished_at"),
        "exit_code": record.get("exit_code"),
    }


def start_job(
    run_dir: Path,
    plan_id: str,
    command: str,
    *,
    name: str | None = None,
    cwd: str | None = None,
    shell: str = "/bin/bash",
) -> dict[str, Any]:
    scoped_paths = plan_paths(run_dir, plan_id, ensure=True)
    job_id = _job_id(plan_id, name)
    resolved_cwd = str(Path(cwd).expanduser().resolve()) if cwd else str(run_dir)
    stdout_path = scoped_paths.logs / f"{job_id}.stdout.log"
    stderr_path = scoped_paths.logs / f"{job_id}.stderr.log"
    exit_code_path = scoped_paths.jobs / f"{job_id}.exitcode"
    finished_at_path = scoped_paths.jobs / f"{job_id}.finished_at"
    runner_path = scoped_paths.jobs / f"{job_id}.runner.sh"
    runner_lines = [
        "#!/usr/bin/env bash",
        "set -uo pipefail",
        f"stdout_path={shell_join([str(stdout_path)])}",
        f"stderr_path={shell_join([str(stderr_path)])}",
        f"exit_code_path={shell_join([str(exit_code_path)])}",
        f"finished_at_path={shell_join([str(finished_at_path)])}",
        f"workdir={shell_join([resolved_cwd])}",
        "status=0",
        'mkdir -p "$(dirname "$stdout_path")" "$(dirname "$stderr_path")" "$(dirname "$exit_code_path")"',
        'if ! cd "$workdir"; then',
        "  status=$?",
        '  printf "%s\\n" "$status" > "$exit_code_path"',
        '  date -u +"%Y-%m-%dT%H:%M:%SZ" > "$finished_at_path"',
        "  exit \"$status\"",
        "fi",
        "set +e",
        shell_join([shell, "-lc", command]) + ' >> "$stdout_path" 2>> "$stderr_path"',
        "status=$?",
        'printf "%s\\n" "$status" > "$exit_code_path"',
        'date -u +"%Y-%m-%dT%H:%M:%SZ" > "$finished_at_path"',
        "exit \"$status\"",
    ]
    runner_path.write_text("\n".join(runner_lines) + "\n", encoding="utf-8")
    runner_path.chmod(0o755)
    process = subprocess.Popen(
        [str(runner_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    pid = process.pid
    # The detached runner is intentionally left in the background; mark the launcher
    # object as handled so Popen.__del__ does not emit a ResourceWarning.
    process.returncode = 0
    record = {
        "job_id": job_id,
        "plan_id": plan_id,
        "name": name or "job",
        "status": "running",
        "pid": pid,
        "command": command,
        "cwd": resolved_cwd,
        "runner_path": str(runner_path),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "exit_code_path": str(exit_code_path),
        "finished_at_path": str(finished_at_path),
        "record_path": str(_job_record_path(run_dir, job_id, plan_id)),
        "started_at": utc_now(),
        "finished_at": None,
        "exit_code": None,
    }
    write_json(_job_record_path(run_dir, job_id, plan_id), record)
    return {
        "job_id": job_id,
        "status": "running",
        "pid": pid,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "wait_command": (
            f"mylab tool wait-job --run-dir {shell_join([str(run_dir)])} "
            f"--job-id {shell_join([job_id])}"
        ),
        "tail_command": (
            f"mylab tool tail-job --run-dir {shell_join([str(run_dir)])} "
            f"--job-id {shell_join([job_id])}"
        ),
    }


def wait_for_job(
    run_dir: Path,
    job_id: str,
    *,
    wait_seconds: int = DEFAULT_JOB_WAIT_SECONDS,
    poll_seconds: int = DEFAULT_JOB_POLL_SECONDS,
) -> dict[str, Any]:
    started = time.monotonic()
    while True:
        status = get_job_status(run_dir, job_id)
        if status["status"] != "running":
            status["waited_seconds"] = int(time.monotonic() - started)
            return status
        if time.monotonic() - started >= max(wait_seconds, 0):
            status["waited_seconds"] = int(time.monotonic() - started)
            return status
        time.sleep(max(poll_seconds, 1))


def tail_job(
    run_dir: Path,
    job_id: str,
    *,
    lines: int = DEFAULT_JOB_TAIL_LINES,
) -> dict[str, Any]:
    status = get_job_status(run_dir, job_id)
    status["stdout_tail"] = _tail_text(Path(status["stdout_path"]), lines)
    status["stderr_tail"] = _tail_text(Path(status["stderr_path"]), lines)
    return status
