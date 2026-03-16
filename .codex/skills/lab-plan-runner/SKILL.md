---
name: lab-plan-runner
description: Use when executing a prepared mylab experiment plan through codex. Focuses on long-running execution, log preservation, result capture, and final structured summaries.
---

# Lab Plan Runner

Use this skill for agent4 and the summary stage.

## Workflow

1. Start from the prepared executor prompt and command script.
2. Run the experiment with a cost-conscious model when possible.
3. Preserve codex event logs, shell logs, intermediate outputs, and final messages.
4. Write a strict summary for the finished plan.

## Constraints

- Never discard partial logs after a failed run.
- Final summaries must cite concrete artifact paths.
- If execution blocks, leave a resumable state instead of deleting evidence.
