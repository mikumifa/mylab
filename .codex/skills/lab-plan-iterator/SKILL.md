---
name: lab-plan-iterator
description: Use when updating a mylab experiment after a previous plan has run. Consumes prior plan artifacts, logs, summaries, and user feedback to produce the next strict plan iteration.
---

# Lab Plan Iterator

Use this skill for agent2.

## Workflow

1. Read the parent `plan.md`.
2. Inspect preserved logs, summaries, and result artifacts from the same run.
3. Convert observed failures or partial success into the next smallest defensible plan.
4. Keep branch provenance and artifact continuity explicit.

## Constraints

- Do not overwrite prior plans.
- Keep the next plan comparable to the parent plan.
- Reference concrete prior artifacts in the new plan when they matter.
