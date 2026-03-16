# mylab

`mylab` 是一个基于 `codex` CLI 的实验编排工具，目标是把“研究目标 -> 计划 -> 实现 -> 执行 -> 总结 -> 下一轮迭代”固定成可追踪、可复盘、可自动化的流程。

这一版已经按“大项目”方向拆包，并把流程改成队列化轮询，而不是把所有逻辑塞在一个 CLI 文件里。

## 包结构

```text
src/mylab/
  commands/      CLI 入口和命令分发
  config.py      常量和目录约定
  domain/        运行时数据模型
  orchestrator/  队列与轮询推进
  services/      计划、执行、总结、格式审计
  storage/       文件系统读写与 manifest 持久化
  utils/         git/时间/文本工具
```

## 设计目标

- 输入一个实验目标，可以直接通过 `--goal` 传入文本，或者把 `--goal` 指向一个文件；也兼容 `--lab-md`。
- 输入一个被 Git 追踪的论文实验仓库路径。
- 由多个职责明确的 agent 分工完成：
  - `format-agent`：先检查仓库是否支持可配置输出目录、日志保留和中间结果落盘。
  - `agent1-planner`：生成首轮 `plan.md`。
  - `agent2-iterator`：根据前一轮结果继续迭代 `plan.md`。
  - `agent3-preparer`：为执行 agent 生成 prompt、命令脚本和结果路径。
  - `agent4-runner`：调用 `codex exec` 执行 plan。
  - `summary-agent`：生成标准化总结。
- 所有中间结果统一保存在环境变量 `MYLAB_RUNS_DIR` 指定的位置；未设置时默认为当前目录下的 `.mylab_runs/`。
- 如果 run 目录落在论文实验仓库内部，程序会自动把对应路径写入该仓库的 `.gitignore`，避免实验产物被 Git 跟踪。

## 目录约定

每次实验对应一个 `run_id`，目录结构如下：

```text
$MYLAB_RUNS_DIR/<run_id>/
  inputs/
  plans/
  prompts/
  logs/
  results/
  summaries/
  commands/
  manifests/
  queue/
```

说明：

- `plans/`: 严格格式的 `plan-XXX.md`
- `prompts/`: 给 codex agent 的 prompt 文件
- `logs/`: 结构化 `jsonl` 日志和 codex 事件流
- `results/`: 执行结果、格式检查报告、agent 最后一条消息
- `summaries/`: 面向复盘的标准总结
- `commands/`: 可重复执行的 shell 脚本
- `queue/`: 轮询推进使用的任务队列

## 轮询结构

旧结构更像是手工顺序执行：

```text
create-plan -> prepare-executor -> run-executor -> write-summary
```

现在改成 `run` 直接驱动内部任务队列：

```text
run
  -> 如果没有现成 run-dir，则自动初始化 run
  -> 自动入队 format_repo / create_plan / prepare_branch / prepare_executor / run_executor ...
  -> 直接执行，不需要单独 allow-exec
```

这样后续扩展新 agent、新 stage、新检查项时，不需要继续膨胀 CLI 参数层。

## 严格格式

`plan.md` 必须包含以下 heading：

```markdown
# Plan Metadata
# Experiment Goal
# Investigation Questions
# Execution Plan
# Deliverables
# Result Collection Rules
```

`summary.md` 必须包含以下 heading：

```markdown
# Summary Metadata
# Outcome
# Evidence
# Artifacts
# Next Iteration
```

## 安装

```bash
pip install -e .
```

## 使用示例

最常用方式是直接运行：

```bash
mylab run \
  --repo /path/to/paper-repo \
  --goal "复现论文 A 的主实验，并验证把视觉分支替换成更轻量编码器后的效果"
```

如果 `goal` 已经写在文件里：

```bash
mylab run \
  --repo /path/to/paper-repo \
  --goal /path/to/goal.md
```

如果已有 `lab.md`：

```bash
mylab run \
  --repo /path/to/paper-repo \
  --lab-md /path/to/lab.md
```

如果你已经有一个已有 run 目录，也可以直接续跑：

```bash
mylab run \
  --run-dir .mylab_runs/20260316_120000_example
```

低层命令都放到 `tool` 下面，只建议调试时用：

```bash
mylab tool init-run --repo /path/to/paper-repo --goal "只初始化，不直接执行"
mylab tool prepare-executor --run-dir .mylab_runs/20260316_120000_example
```

基于已有结果，把下一轮计划加入队列：

```bash
mylab queue-iteration \
  --run-dir .mylab_runs/20260316_120000_example \
  --parent-plan plan-001 \
  --feedback "主实验跑通，但输出目录仍写死在 repo/tmp，下轮先改输出根目录注入" \
  --model gpt-5-mini
```

仍然可以手工迭代生成：

```bash
mylab tool iterate-plan \
  --run-dir .mylab_runs/20260316_120000_example \
  --parent-plan plan-001 \
  --feedback "补充下一轮具体目标"
```

为执行 agent 准备 prompt 和命令：

```bash
mylab tool prepare-executor \
  --run-dir .mylab_runs/20260316_120000_example \
  --plan-id plan-001 \
  --model gpt-5-mini
```

写总结：

```bash
mylab tool write-summary \
  --run-dir .mylab_runs/20260316_120000_example \
  --plan-id plan-001 \
  --status success \
  --outcome "主实验已完成，新增输出目录参数已生效。" \
  --evidence logs/plan-001.codex.events.jsonl results/plan-001.result.md \
  --artifacts commands/plan-001.executor.sh summaries/plan-001.summary.md \
  --next-iteration "补跑消融实验" "补充和 baseline 的指标对比"
```

## 后续建议

当前版本已经把最关键的编排骨架落好了。下一步适合继续增强：

- 增加 `plan.md` 和 `summary.md` 的更严格机器校验
- 在执行 agent prompt 中注入仓库上下文摘要
- 为特定实验仓库生成 patch 前的预检查和后验检查
- 将结果汇总成单一的 `run-report.md`
