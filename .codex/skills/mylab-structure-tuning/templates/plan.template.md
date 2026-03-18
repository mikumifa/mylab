---
plan_id: plan-XXX
run_id: <run-id>
plan_kind: structure-tuning
plan_skill: mylab-structure-tuning
repo_path: /abs/path/to/repo
source_branch: <source-branch>
code_checkpoint: <commit-sha>
code_checkpoint_ref: <branch-or-work-branch>
generated_at: 2026-03-18T00:00:00Z
goal_summary: "<one-line goal summary>"
plan_essence: "<the structural hypothesis being tested in this round>"
decision_focus: "<the design decision this round should unlock>"
expected_signal: "<what train + eval + analysis should reveal>"
entrypoint: plans/plan-XXX/plan.md
references_dir: plans/plan-XXX/references
---

# Plan Metadata
- plan_id: plan-XXX
- run_id: <run-id>
- repo_path: /abs/path/to/repo
- source_branch: <source-branch>
- code_checkpoint: <commit-sha>
- code_checkpoint_ref: <branch-or-work-branch>
- plan_kind: structure-tuning
- plan_skill: mylab-structure-tuning
- plan_essence: <the structural hypothesis being tested in this round>
- decision_focus: <the design decision this round should unlock>
- expected_signal: <what train + eval + analysis should reveal>
- generated_at: 2026-03-18T00:00:00Z

# Experiment Goal
Describe the structural idea in one paragraph:
- what is changing
- why this change matters
- what baseline or prior design it should be compared against

## Design
- hypothesis:
- architecture:
- parameters:

Detailed design reasoning and code-change logic live in `plans/plan-XXX/references/design.md`.

# Investigation Questions
1. What exact structural hypothesis is being tested?
2. What is the implementation delta versus the current baseline?
3. Which train, eval, and analysis signals will decide whether this idea should be extended, revised, or dropped?

# Execution Plan
1. Inspect the current baseline and identify the exact code locations that implement the old structure.
2. Implement the new structural idea and save the code delta notes to `plans/plan-XXX/references/implementation-delta.md`.
3. Train the changed system with preserved raw logs and stable output paths under the run directory.
4. Run evaluation that is directly comparable with the baseline or parent plan.
5. Analyze the result and write the design conclusion to `plans/plan-XXX/references/analysis-focus.md`.

## Experiment
- dataset:
- environment:
- artifacts_path:

Detailed execution environment, commands, and artifact inventory live in `plans/plan-XXX/references/experiment.md`.

# Deliverables
1. Updated implementation plus a concise structural delta note.
2. Train and eval evidence for this round.
3. Analysis note that explains whether this design succeeded, failed, or remains inconclusive in this round.

## Analysis
- metrics:
- observations:

Deep analysis of why metrics succeeded or failed lives in `plans/plan-XXX/references/analysis.md`.

## Conclusion
- is_hypothesis_validated:
- summary:
- limitations_and_future_directions:

Extended conclusion notes live in `plans/plan-XXX/references/conclusion.md`.

# Result Collection Rules
1. All code, logs, metrics, and intermediate outputs must stay under the current run directory.
2. The result report must identify the structural delta that was actually executed.
3. Training and evaluation must stay comparable with the baseline or parent plan.
4. The final analysis must state whether the structural idea should be kept, changed, or abandoned.
