---
name: lab-plan-implementer
description: Use when implementing a mylab experiment plan inside a tracked repository. Focuses on code changes, reusable execution scripts, configurable artifact roots, and writing result reports tied to real files.
---

# Lab Plan Implementer

Use this skill for agent3.

## Workflow

1. Read the current `plan.md`.
2. Modify code and scripts required by the plan.
3. Ensure output roots are configurable and point into the current run directory.
4. Emit reusable shell commands for long-running experiments.
5. Preserve raw logs and write a result report with artifact paths.

## Constraints

- Avoid unrelated cleanup.
- Prefer small, reviewable patches.
- Keep scripts rerunnable.
