# Overview

`mylab` 是一个面向论文实验仓库的编排工具。

它的目标不是“帮你跑一次实验”，而是维护一个可以持续消费的实验上下文，让同一个用户目标能够在多轮 agent 迭代中稳定推进。

## Core Idea

在 `mylab` 里：

- `run` 表示围绕单一用户目标的一次持续实验上下文
- `trial` 是 run 内最小的实验记忆单元
- 每个 trial 都应该尽量独立、自包含、可被后续模型单独复用
- `trial.md` 仍是当前兼容文件名，但语义上表示 trial 的入口文件

这套设计的核心是把“上下文”当作一等公民管理，而不是只保留某次脚本运行的 stdout。

## What It Optimizes For

`mylab` 优先保证：

1. 实验过程可追踪
2. 结果能被后续迭代继续消费
3. 输出根目录可配置，不把运行产物硬编码进论文仓库
4. 原始 stdout/stderr 可以保留
5. 仓库级通用知识与单次 trial 结果解耦

## Stable Outputs

每一轮迭代默认应该产出这些稳定文件：

- `trials/trial-XXX.md`
- `summaries/trial-XXX.summary.md`
- `results/trial-XXX.result.md`
- `commands/trial-XXX.executor.sh`
- `logs/iteration-agent.jsonl`

此外还会持续维护：

- `trials/index.md`
- `trials/index.jsonl`
- 仓库级共享资产文件

## Design Boundary

`mylab` 的主目标始终来自用户原始请求。

这意味着：

- agent 不应该为了“可以继续迭代”而脱离原目标自我循环
- 新的子目标、补实验、补分析，都必须明确服务于原始目标
- follow-up 只是从属项，不能盖过当前任务

## Where To Read Next

- [Concepts](concepts.md)
- [CLI Reference](cli.md)
- [Layout](layout.md)
