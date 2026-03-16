# AGENTS

本仓库定义的 agent 面向“论文实验仓库的可追踪实验编排”。

## 全局规则

- 所有实验运行产物必须落在 `MYLAB_RUNS_DIR` 指定目录下。
- 不允许把输出目录、日志目录或中间结果目录硬编码到论文仓库内部。
- `plan.md`、`summary.md`、`jsonl` 日志格式必须保持稳定，方便下一轮 agent 继续消费。
- 每个 agent 的工作都必须写结构化日志到对应的 `logs/*.jsonl`。
- 大流程优先通过队列推进，不要默认要求用户手工逐条运行所有阶段命令。
- 如果修改实验仓库代码，优先保证：
  1. 输出根目录可配置
  2. 运行脚本可复用
  3. 原始 stdout/stderr 可以保留

## Agent Roles

### format-agent

- 目标：检查实验仓库是否满足实验可编排要求。
- 重点：
  - 输出路径是否可配置
  - 日志是否可保留
  - 中间结果是否有统一根目录

### agent1-planner

- 目标：从用户目标或 `lab.md` 生成首轮 `plan.md`。
- 输出：`plans/plan-XXX.md`

### agent2-iterator

- 目标：基于上一轮计划、执行结果和用户反馈迭代下一轮 plan。
- 输出：新的 `plans/plan-XXX.md`

### agent3-preparer

- 目标：为执行 agent 生成 prompt、命令脚本和目标产物路径。
- 输出：
  - `prompts/*.executor.prompt.md`
  - `commands/*.executor.sh`

### agent4-runner

- 目标：调用 `codex exec` 长时间执行 plan。
- 约束：
  - 尽量使用较小模型
  - 优先落可复用脚本，再跑长任务
  - 结果和日志必须完整保留
  - 默认由队列轮询触发，只有显式允许时才真的执行

### summary-agent

- 目标：把本轮结果整理为标准总结，便于下一轮继续。
- 输出：`summaries/*.summary.md`
