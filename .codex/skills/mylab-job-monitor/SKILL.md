---
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
