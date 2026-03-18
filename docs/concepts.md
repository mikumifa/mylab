# Concepts

## Run

`run` 表示围绕同一个用户目标的一次持续实验上下文。

一个 run 负责：

- 维护当前目标
- 维护仓库级共享资产
- 维护所有 trial 的索引
- 维护调度状态

正常使用时只需要 run 名称，不需要手动管理 run 路径。

## Trial

`trial` 是最小实验单元。

每个 trial 都应该独立、自包含，并且能被后续模型单独复用。

`trial` 的重点不是堆积长报告，而是把一轮实验需要的目标、执行主线、日志、结果和引用材料组织到稳定位置。

## trial.md

`trial.md` 是当前兼容文件名，对应的是一个 trial 的入口文件，而不是详细实验报告。

它只保留：

- frontmatter
- 关键实验目标
- 关键问题
- 关键执行主线
- 关键交付要求
- 人类点评入口

详细内容不应该塞在正文里，而应该拆到引用文档中。

## Shared Asset

`assets/repo.md` 是仓库级 runbook，不是某次实验的总结。

它适合记录可复用、可迁移的内容，例如：

- 这个仓库怎么跑
- 输出目录约束
- 关键代码入口
- 常见坑点
- 稳定可复用命令

它不应该记录：

- 某个 trial 的 hypothesis
- 某次实验的结果
- 某次迭代的下一步建议

## Telegram Guidance

Telegram guidance 分为两类：

- `/all <text>`：对后续所有 trial 生效，相当于长期补充输入
- `/next <text>`：只对下一个 trial 生效，并且应被重点关注

这两类 guidance 会写入各个 trial 的引用文件：

- `references/all-guidance.md`
- `references/next-guidance.md`

`trial.md` 只保留引用，不在正文里展开。

## Workflow Skills

当前内置两类主流程 skill：

- `mylab-structure-tuning`：适合“调结构”
- `mylab-parameter-tuning`：适合“调参”

这些 skill 主要控制：

- frontmatter 应强调什么
- `trial.md` 正文如何组织 trial
- `references/` 应如何拆分
