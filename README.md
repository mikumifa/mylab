# mylab

`mylab` 是一个基于 `codex` CLI 的实验编排工具，目标是把“研究目标 -> 计划 -> 实现 -> 执行 -> 总结 -> 下一轮迭代”固定成可追踪、可复盘、可自动化的流程。

这一版按“单一迭代 agent”来组织流程，而不是依赖多个角色化 agent 彼此接力。

## 包结构

```text
src/mylab/
  commands/      CLI 入口和命令分发
  config.py      常量和目录约定
  domain/        运行时数据模型
  orchestrator/  内部阶段编排
  services/      计划、执行、总结、格式审计
  storage/       文件系统读写与 manifest 持久化
  utils/         git/时间/文本工具
```

## 设计目标

- 输入一个实验目标，可以直接通过 `--goal` 传入文本，或者把 `--goal` 指向一个文件；也兼容 `--lab-md`。
- 输入一个被 Git 追踪的论文实验仓库路径。
- 由同一个迭代 agent 在每轮内部完成：
  - 仓库编排检查
  - 生成或迭代 `plan.md`
  - 准备可复用执行脚本
  - 执行 plan
  - 生成标准化总结
  - 更新仓库级共享资产和 `plans/` 索引
- 所有中间结果统一保存在环境变量 `MYLAB_RUNS_DIR` 指定的位置；未设置时默认为当前目录下的 `.mylab_runs/`。
- 如果 run 目录落在论文实验仓库内部，程序会自动把对应路径写入该仓库的 `.gitignore`，避免实验产物被 Git 跟踪。
- 新 run 开始前，目标仓库必须已有提交且工作区干净；bootstrap 阶段会自动补齐运行目录 `.gitignore` 条目，并把仓库级 `mylab-job-monitor` skill 安装到 `.codex/skills/`。这些 bootstrap 资产会被自动提交一次，方便后续 Codex 在该仓库直接复用。
- 每个 run 在自己的 `assets/` 目录下维护独立共享资产，不读取其他 run 的资产，保证 run 之间完全隔离。
- `plans/index.md` 和 `plans/index.jsonl` 维护每轮最短摘要，便于后续模型先做快速检索。
- 通知层基于 Apprise，单次接入即可复用 Telegram、Discord、Slack、邮件、Webhook 等多个平台，配置固定放在用户目录 `~/.mylab/config.toml`。
- 计划生成现在显式依赖两类 workflow skill：`mylab-structure-tuning` 和 `mylab-parameter-tuning`。它们定义 frontmatter 精华字段、正文叙事风格和引用文件组织方式。
- 两类 workflow skill 也各自提供 plan template 和引用文件 template，避免“调结构”和“调参”写成同一种 plan。

## 目录约定

每次实验对应一个 `run_id`，目录结构如下：

```text
$MYLAB_RUNS_DIR/<run_id>/
  inputs/
  assets/
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

- `assets/`: 当前 run 独享的仓库级共享资产，例如 `assets/repo.md`
- `plans/`: `index.md` / `index.jsonl` 加上每个 plan 自己的子目录
- `prompts/`: 给 codex 执行上下文的 prompt 文件
- `logs/`: 结构化 `jsonl` 日志和 codex 事件流，统一主日志为 `iteration-agent.jsonl`
- `results/`: 执行结果、格式检查报告、codex 最后一条消息
- `summaries/`: 面向复盘的标准总结
- `commands/`: 可重复执行的 shell 脚本
- `queue/`: 内部阶段状态，不作为用户层概念

plan 现在按最小执行单元分目录组织：

```text
$MYLAB_RUNS_DIR/<run_id>/plans/plan-001/
  plan.md
  plan.prompt.md
  executor.prompt.md
  executor.sh
  result.md
  summary.md
  git.md
  codex.last.md
  codex.events.jsonl
  executor.jsonl
  references/
    shared-asset.md
    persistent-feedback.md
    recent-feedback.md
    parent-plan.md
```

其中 `plan.md` 使用三层结构：

1. YAML frontmatter: 让模型先快速判断这个 plan 是否值得复用。
2. Markdown 正文: 只保留关键事实和关键判断，不展开复杂逻辑。
3. `references/` 引用文件: 承接详细的代码变动逻辑、深度异常分析、完整 artifact 清单等重内容，只有正文需要时才继续加载。

frontmatter 不只放定位字段，还会放由 workflow skill 约束出来的“精华摘要”，例如：

- `plan_essence`
- `decision_focus`
- `expected_signal`
- `code_checkpoint`
- `code_checkpoint_ref`

这几个字段在“调结构”和“调参”两种流程下会有不同风格。

## 轮询结构

对外抽象是单 iteration agent：一轮 plan 完成后，直接进入下一轮 plan 的补充/迭代/扩展。

内部仍保留阶段状态文件来保证恢复能力和稳定性，但这不是用户需要操作的“队列”概念：

```text
plan -> prepare -> execute -> summarize -> update-assets
```

现在统一通过 `run` 驱动整轮迭代闭环：

```text
run
  -> 如果没有现成 run-dir，则自动初始化 run
  -> 自动入队 format_repo / create_plan / prepare_branch / prepare_executor / run_executor ...
  -> 直接执行，不需要单独 allow-exec
```

这样下一轮会自然消费上一轮交付，形成类似 RNN 的滚动迭代，而不是人为维护一堆 agent 边界。

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

运行控制支持三种模式：

- `limit`: 按“完整 iteration 轮数”限制本次调用最多跑多少轮，不按 plan 内部步骤计数。
- `step`: 默认先跑 1 轮，然后每完成一轮都要求用户在界面里确认是否继续；如果同时传 `--limit N`，则先自动跑 `N` 轮，再切换到逐轮确认。
- `unlimit`: 只要没有失败或人工中断，就持续完成一轮又一轮，不会因为当前轮结束而自动停下。

例如：

```bash
mylab run --repo /path/to/paper-repo --goal "复现实验" --mode limit --limit 2
mylab run --run-dir .mylab_runs/20260316_120000_example --mode step
mylab run --run-dir .mylab_runs/20260316_120000_example --mode step --limit 2
mylab run --run-dir .mylab_runs/20260316_120000_example --mode unlimit
```

如果没有传 `--mode`，并且当前是交互式终端，`mylab` 会提示用户选择；也可以在 `~/.mylab/config.toml` 里写默认值：

```toml
[runner]
mode = "limit"
limit = 100
```

如果希望启用 Telegram bot、飞书 webhook 机器人和通知，先在用户目录写配置：

```toml
# ~/.mylab/config.toml
[telegram]
bot_token = "123456:replace-me"
allowed_chat_ids = [123456789]
poll_interval_seconds = 5
feedback_context_limit = 5

[runner]
mode = "limit"
limit = 100

[notifications]
urls = ["tgram://<bot_token>/<chat_id>"]

[feishu]
webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/<token>"
```

如果希望交互式配置 Telegram，直接运行：

```bash
mylab bot telegram
```

如果只想配置飞书 webhook 机器人，直接运行：

```bash
mylab bot feishu
```

飞书交互式配置会询问默认检查命令，以及是否启用双向控制；如果启用双向控制，还会继续询问 `app_id`、`app_secret` 和 `chat_id`。如果当前还没有 webhook，它也会额外询问一次，用于现有通知链路。

`Telegram` 交互式配置现在只强制要求 `bot_token`，其余字段都可以直接使用默认值；只有在你选择高级配置时，才会继续询问 chat id、轮询间隔、反馈上下文长度和通知 chat id。

如果你只想先生成模板文件，也可以：

```bash
mylab tool init-config
```

然后启动 Telegram bot 轮询：

```bash
mylab tool telegram-bot
```

机器人支持这些简单指令：

```text
/on   开始通知
/off  暂停通知
```

用户也可以直接发送文字或文件。它们会被保存到 `~/.mylab/telegram/inbox/`，并自动注入下一轮 plan / executor prompt，作为后续迭代的额外上下文。

之后正常运行 `mylab` 即可，不需要每次重复传参数：

```bash
mylab run \
  --repo /path/to/paper-repo \
  --goal "复现实验并补跑分析"
```

如果 `~/.mylab/config.toml` 不存在，`mylab` 会直接跳过通知发送，Telegram bot 轮询命令会报配置缺失。

如果希望一次配置多个平台，建议仍然通过同一个用户级配置接入 Apprise；飞书也可以直接把 webhook URL 放进 `notifications.urls`：

```toml
# ~/.mylab/config.toml
[notifications]
urls = [
  "tgram://<bot_token>/<chat_id>",
  "https://open.feishu.cn/open-apis/bot/v2/hook/<token>",
]
config_path = "/path/to/apprise.yaml"
tag = "mylab"
```

低层命令都放到 `tool` 下面，只建议调试时用：

```bash
mylab tool init-run --repo /path/to/paper-repo --goal "只初始化，不直接执行"
mylab tool prepare-executor --run-dir .mylab_runs/20260316_120000_example
```

如果你确实需要手工注入下一轮反馈，兼容命令仍然保留：

```bash
mylab queue-iteration \
  --run-dir .mylab_runs/20260316_120000_example \
  --parent-plan plan-001 \
  --feedback "主实验跑通，但输出目录仍写死在 repo/tmp，下轮先改输出根目录注入"
```

但正常使用下，不应该把“queue”当成用户抽象；应直接继续同一个 run，让每轮 plan 结束后产生下一轮 plan。

仍然可以手工迭代生成：

```bash
mylab tool iterate-plan \
  --run-dir .mylab_runs/20260316_120000_example \
  --parent-plan plan-001 \
  --feedback "补充下一轮具体目标"
```

为执行阶段准备 prompt 和命令：

```bash
mylab tool prepare-executor \
  --run-dir .mylab_runs/20260316_120000_example \
  --plan-id plan-001 \
  --model gpt-5-mini
```

如果执行阶段需要启动长任务，优先直接用文档化的 job monitor CLI，不要让执行 agent 每次都去读 `mylab` 源码寻找替代入口：

```bash
mylab tool start-job \
  --run-dir .mylab_runs/20260316_120000_example \
  --plan-id plan-001 \
  --name train \
  --command 'bash commands/plan-001.executor.sh train'

mylab tool wait-job \
  --run-dir .mylab_runs/20260316_120000_example \
  --job-id <job_id>

mylab tool tail-job \
  --run-dir .mylab_runs/20260316_120000_example \
  --job-id <job_id>
```

如果你在 Codex 里反复做这类事情，可以直接让它使用仓库自带 skill：`mylab-job-monitor`。这个 skill 提供了完整的 start / wait / tail 示例和结构化日志写法，位置在 [SKILL.md](/root/xqz/mylab/.codex/skills/mylab-job-monitor/SKILL.md)。

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

当前版本的核心是“单 agent 迭代闭环 + 共享资产 + plan 索引”。下一步适合继续增强：

- 增加 `plan.md` 和 `summary.md` 的更严格机器校验
- 从结果与代码扫描中自动提炼共享资产里的稳定字段
- 为特定实验仓库生成 patch 前的预检查和后验检查
- 将结果汇总成单一的 `run-report.md`
