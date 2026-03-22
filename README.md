# MyLab

![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![Linux](https://img.shields.io/badge/platform-Linux-FCC624?logo=linux&logoColor=black)
![CLI](https://img.shields.io/badge/interface-CLI-2F855A?logo=gnubash&logoColor=white)
![Codex](https://img.shields.io/badge/agent-Codex-111111)

MyLab 是一个专为**科研实验**设计的基于Codex的Agent框架。

我们希望 AI 能够在一步步的试错中不断探索，从一次次的先前实验中学习到经验；同时，我们也能从 AI 的一次次试错中找到真正的重点，帮助 AI 完成任务。


## How It Works

我们把每一次的实验，变成一个**Trial**：

- MyLab 不只执行一次命令，而是围绕同一个目标持续实验、沉淀总结，再进入下一轮试错
- 每一轮都会将关键信息沉淀为一个**Trial**，包括 trial 定义、总结、结果、执行脚本和结构化日志，能让经验一直留存下来
- 会持续积累“实验怎么跑、哪些方法有效、哪些坑已经踩过”，后续的MyLab会根据当前的目标，从所有历史 **Trial** 中“选择性地”提取最相关的经验
- 人可以从这些 **Trial** 中快速看到 MyLab 到底试了什么、为什么失败、下一个优化方向到哪里，保留有价值的 **Trial** 作为基石，删除无用的 **Trial** 以剔除噪音，或者直接在 **Trial** 文件中写下你的点评



## Quick Start

### Prerequisites

- Codex 安装并且登录
- 科研实验仓库使用Git管理

### Install

```bash
pip install -e .
```

### Publish to PyPI

GitHub Actions 提供了基于 tag/release 的 PyPI 发布流程，见 `.github/workflows/publish.yml`。

发布前需要在 PyPI 项目里把这个 GitHub 仓库配置为 Trusted Publisher，然后创建一个 GitHub Release；工作流会自动构建并发布当前版本。

### Start a Run

```bash
# 创建并启动一个新的 run
mylab start --repo /path/to/repo --goal "reproduce table 1" --mode unlimit
# 给 run 指定名字
mylab start --repo /path/to/repo --goal ./goal.md --run run_xx --mode unlimit
# 恢复一个已有 run
mylab start --run run_xx --mode unlimit
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
