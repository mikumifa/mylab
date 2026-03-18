---
name: mylab-parameter-tuning
description: Use when the main loop is parameter generation -> batch experiments -> result collection -> comparison for a parameter experiment round.
plan_kind: parameter-tuning
---

# Mylab Parameter Tuning

Use this skill when the main goal is to search parameter combinations, compare results across a batch, and refine the next search space.

## Flow

1. Generate parameter combinations
2. Run the batch
3. Collect results
4. Compare and rank

## Frontmatter Essence

- target parameter family or search space under study
- batch shape and comparison logic for this round
- ranking signal or decision metric that decides what wins
- reason this batch matters for narrowing the next search region
- exact code checkpoint this round should start from

## Plan Body Rules

- The execution plan should read like a sweep pipeline, not like an implementation story.
- The plan must state how combinations are generated.
- The plan must state how results are collected into a comparable form.
- The comparison step must say how the current batch will be ranked.
- Deliverables should emphasize batch configs, aggregated tables, and ranking conclusions for this round only.

## Reference Files

- references/plan-skill.md: the workflow contract that explains how this parameter-tuning plan should be interpreted
- references/design.md: detailed search-space rationale and batch-generation logic
- references/experiment.md: detailed execution environment and artifact inventory
- references/analysis.md: detailed comparison logic, anomaly notes, and ranking interpretation
- references/conclusion.md: expanded verdict, limitations, and follow-up memory
- references/shared-asset.md: durable repository knowledge already learned in this run
- references/persistent-feedback.md: long-lived user guidance that should constrain future search choices
- references/recent-feedback.md: short-lived user feedback for this round
- references/parent-plan.md: previous plan body when iterating from an earlier plan

## Templates

- Use [templates/plan.template.md](templates/plan.template.md) as the primary plan skeleton.
- Use [templates/references/search-space.template.md](templates/references/search-space.template.md) inside `references/design.md` for the batch search-space definition.
- Use [templates/references/comparison-schema.template.md](templates/references/comparison-schema.template.md) inside `references/analysis.md` for the ranking logic and comparison schema.
