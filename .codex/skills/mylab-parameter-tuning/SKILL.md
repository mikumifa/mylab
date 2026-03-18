---
name: mylab-parameter-tuning
description: Use when the main loop is parameter generation -> batch experiments -> result collection -> comparison -> proposal of the next search region for the next iteration.
plan_kind: parameter-tuning
---

# Mylab Parameter Tuning

Use this skill when the main goal is to search parameter combinations, compare results across a batch, and refine the next search space.

## Flow

1. Generate parameter combinations
2. Run the batch
3. Collect results
4. Compare and rank
5. Propose the next parameter region or new combination set for the next iteration

## Frontmatter Essence

- target parameter family or search space under study
- batch shape and comparison logic for this round
- ranking signal or decision metric that decides what wins
- reason this batch matters for narrowing the next search region
- next-search hook that can seed the next iteration

## Plan Body Rules

- The execution plan should read like a sweep pipeline, not like an implementation story.
- The plan must state how combinations are generated.
- The plan must state how results are collected into a comparable form.
- The comparison step must say how the next search region will be chosen.
- Deliverables should emphasize batch configs, aggregated tables, and ranking conclusions.

## Reference Files

- references/plan-skill.md: the workflow contract that explains how this parameter-tuning plan should be interpreted
- references/shared-asset.md: durable repository knowledge already learned in this run
- references/persistent-feedback.md: long-lived user guidance that should constrain future search choices
- references/recent-feedback.md: short-lived user feedback for this round
- references/parent-plan.md: previous plan body when iterating from an earlier plan
