# mylab

mylab 是一个专为**科研实验**设计的基于Codex的Agent框架。

我们希望 AI 能够在一步步的试错中不断探索，从一次次的先前实验中学习到经验；同时，我们也能从 AI 的一次次试错中找到真正的重点，帮助 AI 完成任务。


## How It Works

我们把每一次的实验，变成一个**Trial**：

- mylab 不只执行一次命令，而是围绕同一个目标持续实验、沉淀总结，再进入下一轮试错
- 每一轮都会将关键信息沉淀为一个**Trial**，包括 trial 定义、总结、结果、执行脚本和结构化日志，能让经验一直留存下来
- 会持续积累“实验怎么跑、哪些方法有效、哪些坑已经踩过”，让后续mylab能直接站在前一轮经验上继续探索
- 人可以从这些稳定产物中快速看到 mylab 到底试了什么、为什么失败、下一个优化方向到哪里，选择最重要的Trial经验给 AI



## Quick Start

### Prerequisites

- Codex 安装并且登录
- 科研实验仓库使用Git管理

### Install

```bash
pip install -e .
```

### Start a Run

```bash
# 创建并启动一个新的 run
mylab start --repo /path/to/repo --goal "reproduce table 1"
# 给 run 指定名字
mylab start --repo /path/to/repo --goal ./goal.md --run run_xx
# 恢复一个已有 run
mylab start --run run_xx
```

### Manage Trials

```bash
# 先切到要管理的 run
mylab run use run_xx
# 列出当前 run 的 trial
mylab trial ls
# 查看某个 trial
mylab trial cat trial-001
# 删除某个 trial
mylab trial rm trial-001
```


## Documentation

Refer to the documentation for more information on MyLab:

- [Overview](docs/overview.md): 项目目标、核心工作方式和设计边界
- [Concepts](docs/concepts.md): `run`、`trial`、`trial.md`、shared asset、Telegram guidance、workflow skill
- [CLI Reference](docs/cli.md): 常用命令、运行方式和低级工具命令
- [Layout](docs/layout.md): run 根目录与 trial 目录结构说明
