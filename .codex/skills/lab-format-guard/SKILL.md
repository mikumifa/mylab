---
name: lab-format-guard
description: Use when preparing or auditing a research experiment repository for mylab orchestration. Enforces configurable output roots, stable logs, preserved intermediate artifacts, and strict run-directory discipline.
---

# Lab Format Guard

Use this skill when the task is to prepare an experiment repo so later agents can run reproducible plans safely.

## Workflow

1. Check whether output paths, cache paths, log paths, and result paths are hardcoded.
2. Prefer CLI flags or environment variables over embedded constants.
3. Route all experiment artifacts under `MYLAB_RUNS_DIR/<run_id>/...` or a path derived from it.
4. Preserve raw stdout/stderr logs and command lines.
5. Record findings in a concise audit report and avoid broad refactors unrelated to reproducibility.

## Required Output Constraints

- Do not invent new markdown headings for `plan.md` or `summary.md`.
- Keep changes minimal and tied to experiment traceability.
- If a repo cannot be fully fixed, leave a concrete TODO list with file paths.
