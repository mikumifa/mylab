---
name: mylab-structure-tuning
description: Use when the main loop is idea -> implementation -> training -> eval -> analysis, and the next iteration should propose the next structural design based on what was learned.
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
6. Propose the next structural combination for the next iteration

## Frontmatter Essence

- current hypothesis or structural idea being tested
- exact implementation delta relative to the previous stable baseline
- expected learning signal from train plus eval plus analysis
- reason this round matters for the next design decision
- next-design hook that can seed the next iteration

## Plan Body Rules

- The execution plan should read like a causal chain from idea to analysis.
- The plan must make the implementation delta explicit.
- The plan must separate training from evaluation and analysis.
- The analysis step must say what kind of structural conclusion will be drawn.
- Deliverables should emphasize code diff, train/eval evidence, and design conclusions.

## Reference Files

- references/plan-skill.md: the workflow contract that explains how this structure-tuning plan should be interpreted
- references/shared-asset.md: durable repository knowledge already learned in this run
- references/persistent-feedback.md: long-lived user guidance that should constrain future design choices
- references/recent-feedback.md: short-lived user feedback for this round
- references/parent-plan.md: previous plan body when iterating from an earlier plan

