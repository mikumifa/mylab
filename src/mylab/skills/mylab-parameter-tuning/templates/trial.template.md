---
trial_id: trial-XXX
run_id: <run-id>
trial_kind: parameter-tuning
trial_skill: mylab-parameter-tuning
repo_path: /abs/path/to/repo
source_branch: <source-branch>
code_checkpoint: <commit-sha>
code_checkpoint_ref: <branch-or-work-branch>
generated_at: 2026-03-18T00:00:00Z
goal_summary: "<one-line tuning goal summary>"
trial_essence: "<the parameter family or search region being explored>"
decision_focus: "<the ranking rule or search decision this batch should support>"
expected_signal: "<what comparison output should come out of the batch>"
entrypoint: trials/trial-XXX/trial.md
references_dir: trials/trial-XXX/references
---

# Trial Metadata
- trial_id: trial-XXX
- run_id: <run-id>
- repo_path: /abs/path/to/repo
- source_branch: <source-branch>
- code_checkpoint: <commit-sha>
- code_checkpoint_ref: <branch-or-work-branch>
- trial_kind: parameter-tuning
- trial_skill: mylab-parameter-tuning
- trial_essence: <the parameter family or search region being explored>
- decision_focus: <the ranking rule or search decision this batch should support>
- expected_signal: <what comparison output should come out of the batch>
- generated_at: 2026-03-18T00:00:00Z

# Experiment Goal
Describe the tuning objective in one paragraph:
- which parameter family is under study
- why this region matters now
- what ranking result should be used to narrow the next search space

## Design
- hypothesis:
- architecture:
- parameters:

Detailed search-space rationale and batch-generation logic live in `trials/trial-XXX/references/design.md`.

# Investigation Questions
1. Which parameter family or search region is being explored in this round?
2. How will combinations be generated and tracked so the batch stays reproducible?
3. Which metric or ranking rule will decide the next search region?

# Execution Steps
1. Inspect the parameter entrypoints and write the candidate search space to `trials/trial-XXX/references/search-space.md`.
2. Generate the concrete parameter combinations for this round and save them under the current trial directory.
3. Run the batch while preserving per-trial raw logs and outputs.
4. Collect the batch results into a comparable table or machine-readable summary.
5. Compare and rank the combinations according to the chosen rule, and write that rule to `trials/trial-XXX/references/comparison-schema.md`.

## Experiment
- dataset:
- environment:
- artifacts_path:

Detailed execution environment, commands, and artifact inventory live in `trials/trial-XXX/references/experiment.md`.

# Deliverables
1. Search-space definition plus the generated parameter combinations for this round.
2. Aggregated comparison artifact for the batch.
3. Ranked conclusion that explains what this batch established in the current round.

## Analysis
- metrics:
- observations:

Deep comparison analysis and anomaly explanation live in `trials/trial-XXX/references/analysis.md`.

## Conclusion
- is_hypothesis_validated:
- summary:
- limitations_and_future_directions:

Extended conclusion notes live in `trials/trial-XXX/references/conclusion.md`.

# Result Collection Rules
1. All batch definitions, trial outputs, and aggregated results must stay under the current run directory.
2. Every parameter combination must be reproducible from saved trial artifacts.
3. The comparison output must state the exact ranking rule and winning criteria.
4. The final result must distinguish raw trial outputs from aggregated comparison artifacts.
