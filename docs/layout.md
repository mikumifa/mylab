# Layout

## Run Root

run 根目录只保留全局编排级内容：

```text
<run>/
├── assets/
│   └── repo.md
├── inputs/
├── trials/
│   ├── index.md
│   ├── index.jsonl
│   └── trial-xxx/
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
- `trials/index.*` 是 run 级 trial catalog

## Trial Layout

单个 trial 目录当前统一为：

```text
trials/<trial_id>/
├── trial.md
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
│   └── trial-skill.md
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
    ├── trial.prompt.md
    ├── executor.prompt.md
    ├── card.json
    └── status.json
```

## Layout Principles

这套结构遵循几条原则：

1. 最小单位是 `trial`
2. `trial.md` 只放关键事实
3. 深度内容全部放到 `references/`
4. 单轮执行痕迹尽量 trial-local
5. 仓库级共性知识只放进 `assets/repo.md`
6. run 根只保留全局编排状态
