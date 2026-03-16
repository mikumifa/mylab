---
name: lab-plan-writer
description: Use when generating the first mylab experiment plan from a user goal or lab.md file. Produces a strict plan.md with source branch, experiment goal, investigation questions, execution steps, deliverables, and result collection rules.
---

# Lab Plan Writer

Use this skill for agent1.

## Workflow

1. Read the user goal or `lab.md`.
2. Detect the source branch from the tracked repository unless explicitly provided.
3. Produce a `plan.md` that keeps the required headings exactly unchanged.
4. Make the plan concrete enough to execute: code edits, scripts, runs, and result collection.

## Required Headings

- `# Plan Metadata`
- `# Experiment Goal`
- `# Investigation Questions`
- `# Execution Plan`
- `# Deliverables`
- `# Result Collection Rules`

## Constraints

- The plan must name a source branch.
- The plan must preserve experiment comparability.
- The plan must mention where outputs and logs will be written.
