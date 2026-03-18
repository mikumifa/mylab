# mylab

`mylab` 是一个面向论文实验仓库的编排工具。

它的核心目标不是“跑一次实验”，而是维护一个可持续消费的实验上下文：

- `run` 是一次连续的实验上下文
- `plan` 是 run 内最小的实验记忆单元
- 每个 plan 都是自包含目录
- `plan.md` 只放关键事实
- 详细内容都外置到 `references/`

## 核心概念

### 1. Run

`run` 表示围绕同一个用户目标的一次持续实验上下文。

run 负责：

- 维护当前目标
- 维护仓库级共享资产
- 维护所有 plan 的索引
- 维护调度状态

你不再需要手动指定 run 路径。
正常使用时只需要 run 名称。

### 2. Plan

`plan` 是最小实验单元。

每个 plan 都应该独立、自包含，并且能被后续模型单独复用。

一个 plan 目录当前统一为：

```text
plans/<plan_id>/
├── plan.md
├── executor.sh
├── references/
│   ├── design.md
│   ├── experiment.md
│   ├── analysis.md
│   ├── conclusion.md
│   ├── result.md
│   ├── summary.md
│   ├── codex.last.md
│   ├── git.md
│   ├── all-guidance.md
│   ├── next-guidance.md
│   └── plan-skill.md
├── logs/
│   ├── executor.jsonl
│   ├── codex.events.jsonl
│   ├── iteration-agent.jsonl
│   └── <job>.stdout.log / <job>.stderr.log
├── jobs/
│   ├── <job>.json
│   ├── <job>.runner.sh
│   ├── <job>.exitcode
│   └── <job>.finished_at
└── control/
    ├── plan.prompt.md
    ├── executor.prompt.md
    ├── card.json
    └── status.json
```

### 3. plan.md

`plan.md` 是入口文件，不是详细实验报告。

它只保留：

- frontmatter
- 关键实验目标
- 关键问题
- 关键执行主线
- 关键交付要求

详细内容不要堆在正文里，而应该写到 `references/*.md`。

### 4. Shared Asset

`assets/repo.md` 是仓库级 runbook，不是实验总结。

它应该只记录通用、可迁移的内容，例如：

- 这个仓库怎么跑
- 输出目录约束
- 关键代码入口
- 常见坑点
- 稳定可复用命令

它不应该记录：

- 某个 plan 的 hypothesis
- 某次实验的结果
- 某次迭代的下一步建议

## Telegram Guidance

Telegram 现在有两类 guidance：

- `/all <text>`
  对后续所有 plan 生效，相当于对原始用户输入的长期补充
- `/next <text>`
  只对下一个 plan 生效，并且应该被重点关注

这两类 guidance 会被写入各个 plan 的 reference：

- `references/all-guidance.md`
- `references/next-guidance.md`

`plan.md` 只保留它们的引用，不在正文里展开。

## Workflow Skill

当前内置两种主流程 skill：

- `mylab-structure-tuning`
  对应“调结构”
- `mylab-parameter-tuning`
  对应“调参”

它们控制：

- frontmatter 应该强调什么
- `plan.md` 正文怎么写
- `references/` 该如何拆分

## CLI

### 启动

`start` 是主入口。

新建并启动一个 run：

```bash
mylab start --repo /path/to/repo --goal "reproduce table 1"
```

给 run 指定名字：

```bash
mylab start --repo /path/to/repo --goal ./goal.md --run run_xx
```

恢复一个已有 run：

```bash
mylab start --run run_xx
```

如果已经通过 `mylab run use` 选中了当前 run，也可以直接：

```bash
mylab start
```

### Run 管理

列出 run：

```bash
mylab run ls
```

选择当前 run：

```bash
mylab run use run_xx
```

删除一个 run：

```bash
mylab run rm run_xx
```

### Plan 管理

如果没有先 `run use`，plan 管理命令会提示先选择 active run。

列出当前 run 的 plan：

```bash
mylab plan ls
```

查看某个 plan：

```bash
mylab plan cat plan-001
```

删除某个 plan：

```bash
mylab plan rm plan-001
```

删除 plan 时会做三件事：

- 删除该 plan 目录
- 从 queue 和 plan index 中移除它
- 尝试删除该 plan 对应的 git branch

目标是让这个 plan 尽量从上下文中消失，不继续影响后续迭代。

## Run 根目录

当前 run 根目录只保留全局编排级内容：

```text
<run>/
├── assets/
│   └── repo.md
├── inputs/
├── plans/
│   ├── index.md
│   ├── index.jsonl
│   └── plan-xxx/
├── manifests/
│   └── run.json
├── queue/
│   └── pipeline.json
└── logs/
    ├── git-lifecycle.jsonl
    └── run-lifecycle.jsonl
```

其中：

- `manifests/run.json` 是 run 级状态机
- `queue/pipeline.json` 是 run 级调度状态
- `plans/index.*` 是 run 级 plan catalog

## 设计原则

这套结构遵循几条原则：

1. 最小单位是 `plan`
2. `plan.md` 只放关键事实
3. 深度内容全部放到 `references/`
4. 单轮执行痕迹尽量 plan-local
5. 仓库级共性知识只放进 `assets/repo.md`
6. run 根只保留全局编排状态

## 低级命令

`mylab tool ...` 仍然保留，用于调试或手动控制底层流程。

例如：

- `mylab tool start-job`
- `mylab tool wait-job`
- `mylab tool tail-job`
- `mylab tool prepare-executor`
- `mylab tool run-executor`

这些命令目前仍允许直接使用 `--run-dir`，因为它们定位是低级接口，不是日常主流程入口。
