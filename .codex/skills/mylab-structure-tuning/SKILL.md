---
name: mylab-structure-tuning
description: Use when the main loop is idea -> implementation -> training -> eval -> analysis for a structural experiment round.
plan_kind: structure-tuning
---

# Mylab Structure Tuning

Use this skill when the user is trying new model structures, new training logic, new loss wiring, or new module combinations.

## Flow

1. Idea
2. Implement
3. Train
4. Eval
5. Analyze

## Frontmatter Essence

- current hypothesis or structural idea being tested
- exact implementation delta relative to the previous stable baseline
- expected learning signal from train plus eval plus analysis
- reason this round matters for the next design decision
- exact code checkpoint this round should start from

## Plan Body Rules

- The execution plan should read like a causal chain from idea to analysis.
- The plan must make the implementation delta explicit.
- The plan must separate training from evaluation and analysis.
- The analysis step must say what kind of structural conclusion will be drawn.
- Deliverables should emphasize code diff, train/eval evidence, and design conclusions for this round only.

## Reference Files

- references/plan-skill.md: the workflow contract that explains how this structure-tuning plan should be interpreted
- references/design.md: detailed hypothesis rationale and code-change logic
- references/experiment.md: detailed execution environment and artifact inventory
- references/analysis.md: detailed explanation of successes, failures, and anomalies
- references/conclusion.md: expanded verdict, limitations, and follow-up memory
- references/shared-asset.md: durable repository knowledge already learned in this run
- references/persistent-feedback.md: long-lived user guidance that should constrain future design choices
- references/recent-feedback.md: short-lived user feedback for this round
- references/parent-plan.md: previous plan body when iterating from an earlier plan

## Templates

- Use [templates/plan.template.md](templates/plan.template.md) as the primary plan skeleton.
- Use [templates/references/implementation-delta.template.md](templates/references/implementation-delta.template.md) inside `references/design.md` when the code delta is complex.
- Use [templates/references/analysis-focus.template.md](templates/references/analysis-focus.template.md) inside `references/analysis.md` when the analysis needs a dedicated structure.
