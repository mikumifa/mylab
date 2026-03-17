# Complete Example

Use this pattern when a prepared executor script already exists at `commands/plan-001.executor.sh` and you need to run a long training job under mylab monitoring.

## Preconditions

- You already have a run directory such as `.mylab_runs/20260316_120000_example`.
- The plan id is known, for example `plan-001`.
- The actual long-running command has been wrapped in a reusable shell entrypoint.

## Start The Job

```bash
mylab tool start-job \
  --run-dir /abs/path/to/.mylab_runs/20260316_120000_example \
  --plan-id plan-001 \
  --name train \
  --command 'bash /abs/path/to/.mylab_runs/20260316_120000_example/commands/plan-001.executor.sh train'
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
mylab tool wait-job \
  --run-dir /abs/path/to/.mylab_runs/20260316_120000_example \
  --job-id plan-001-train-20260317t175913z
```

If the returned status is `running`, call `wait-job` again later. Do not replace it with a direct long-running shell command.

## Inspect Logs On Demand

```bash
mylab tool tail-job \
  --run-dir /abs/path/to/.mylab_runs/20260316_120000_example \
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
