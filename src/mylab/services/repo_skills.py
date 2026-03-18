from __future__ import annotations

from pathlib import Path

from mylab.config import ROOT
from mylab.logging import logger


_JOB_MONITOR_SKILL = """---
name: mylab-job-monitor
description: Use when a mylab executor needs to start, poll, or inspect a long-running job. Prefer the documented `mylab tool start-job`, `wait-job`, and `tail-job` CLI flow instead of reading source code or inventing alternate entrypoints.
---

# Mylab Job Monitor

Use this skill when the task is to launch or track long-running work inside a mylab run.

## Workflow

1. Assume the documented CLI is the default path.
2. Start the job with `mylab tool start-job`.
3. Record the returned `job_id`, `stdout_path`, and `stderr_path` in structured logs when the surrounding workflow expects it.
4. Poll with `mylab tool wait-job` instead of switching back to a foreground shell command.
5. Inspect logs only when needed with `mylab tool tail-job`.

## Rules

- Do not read `mylab` source code just to discover an alternative way to start jobs unless the documented CLI fails in the current run.
- Do not construct ad hoc `python -c` wrappers around `cmd_start_job` or `start_job` when the CLI already works.
- Preserve the monitored command as a reusable shell script when the run will likely need retries or repeated execution.
- Keep outputs and logs under the run directory.

## Complete Example

Read [references/complete-example.md](references/complete-example.md) for a full end-to-end example, including the expected JSON payload and structured log append.
"""


_JOB_MONITOR_REFERENCE = """# Complete Example

Use this pattern when a prepared executor script already exists at `plans/plan-001/executor.sh` and you need to run a long training job under mylab monitoring.

## Preconditions

- You already have a run directory such as `.mylab_runs/20260316_120000_example`.
- The plan id is known, for example `plan-001`.
- The actual long-running command has been wrapped in a reusable shell entrypoint.

## Start The Job

```bash
mylab tool start-job \\
  --run-dir /abs/path/to/.mylab_runs/20260316_120000_example \\
  --plan-id plan-001 \\
  --name train \\
  --command 'bash /abs/path/to/.mylab_runs/20260316_120000_example/plans/plan-001/executor.sh train'
```

Expected stdout is a single JSON object like:

```json
{
  "job_id": "plan-001-train-20260317t175913z",
  "status": "running",
  "pid": 381571,
  "stdout_path": "/abs/path/to/.mylab_runs/20260316_120000_example/logs/plan-001-train-20260317t175913z.stdout.log",
  "stderr_path": "/abs/path/to/.mylab_runs/20260316_120000_example/logs/plan-001-train-20260317t175913z.stderr.log",
  "wait_command": "mylab tool wait-job --run-dir /abs/path/to/.mylab_runs/20260316_120000_example --job-id plan-001-train-20260317t175913z",
  "tail_command": "mylab tool tail-job --run-dir /abs/path/to/.mylab_runs/20260316_120000_example --job-id plan-001-train-20260317t175913z"
}
```

## Poll For Completion

```bash
mylab tool wait-job \\
  --run-dir /abs/path/to/.mylab_runs/20260316_120000_example \\
  --job-id plan-001-train-20260317t175913z
```

If the returned status is `running`, call `wait-job` again later. Do not replace it with a direct long-running shell command.

## Inspect Logs On Demand

```bash
mylab tool tail-job \\
  --run-dir /abs/path/to/.mylab_runs/20260316_120000_example \\
  --job-id plan-001-train-20260317t175913z
```

Only inspect tails when needed for diagnosis. Avoid printing large logs in every polling step.

## Structured Log Append

If the plan maintains an executor JSONL log, append the returned metadata in a stable shape:

```json
{"ts":"2026-03-17T17:59:13Z","plan_id":"plan-001","event":"started_job","job_id":"plan-001-train-20260317t175913z","stdout":"/abs/path/to/.mylab_runs/20260316_120000_example/logs/plan-001-train-20260317t175913z.stdout.log","stderr":"/abs/path/to/.mylab_runs/20260316_120000_example/logs/plan-001-train-20260317t175913z.stderr.log"}
```

## Anti-Pattern

Avoid this unless the documented CLI is actually broken in the current environment:

```python
from argparse import Namespace
from mylab.commands.root import cmd_start_job
cmd_start_job(Namespace(...))
```

That path exists only as a compatibility fallback. The normal interface is the CLI.
"""

def _write_if_missing(path: Path, content: str) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _local_skill_files(skill_name: str) -> dict[Path, str]:
    source_root = ROOT / ".codex" / "skills" / skill_name
    files: dict[Path, str] = {}
    for path in sorted(source_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source_root)
        files[Path(".codex") / "skills" / skill_name / relative] = path.read_text(
            encoding="utf-8"
        )
    return files


def ensure_repo_skills_installed(repo_path: Path) -> list[str]:
    repo_path = repo_path.resolve()
    created: list[str] = []
    files = {
        repo_path / ".codex" / "skills" / "mylab-job-monitor" / "SKILL.md": _JOB_MONITOR_SKILL,
        repo_path
        / ".codex"
        / "skills"
        / "mylab-job-monitor"
        / "references"
        / "complete-example.md": _JOB_MONITOR_REFERENCE,
    }
    for relative, content in _local_skill_files("mylab-structure-tuning").items():
        files[repo_path / relative] = content
    for relative, content in _local_skill_files("mylab-parameter-tuning").items():
        files[repo_path / relative] = content
    for path, content in files.items():
        if _write_if_missing(path, content):
            logger.info("Installed repository skill file {}", path)
            created.append(str(path.relative_to(repo_path).as_posix()))
    return created
