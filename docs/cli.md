# CLI Reference

## Main Entry

`start` 是主入口。

创建并启动一个新的 run：

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

## Run Management

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

## Trial Management

如果没有先执行 `mylab run use`，trial 管理命令会提示先选择 active run。

当前兼容命令名仍然是 `trial`。列出当前 run 的 trial：

```bash
mylab trial ls
```

查看某个 trial：

```bash
mylab trial cat trial-001
```

删除某个 trial：

```bash
mylab trial rm trial-001
```

删除 trial 时会做三件事：

- 删除该 trial 目录
- 从 queue 和 trial index 中移除它
- 尝试删除该 trial 对应的 Git branch

目标是尽量让这个 trial 从后续上下文中退出，不再持续影响迭代。

## Low-Level Commands

`mylab tool ...` 保留给调试和手动控制底层流程。

常见例子：

- `mylab tool start-job`
- `mylab tool wait-job`
- `mylab tool tail-job`

其中 `mylab tool wait-job` 默认关闭计时器，会一直阻塞到任务完成；只有显式传 `--enable-timer` 时，才会按 `--wait-seconds` 提前返回 `running`。
