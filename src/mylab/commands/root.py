from __future__ import annotations

import argparse
from pathlib import Path
import sys

from mylab.codex import get_codex_status
from mylab.flow import SerialFlowRunner
from mylab.logging import configure_logging, emit_progress, logger
from mylab.orchestrator import enqueue_initial_pipeline, enqueue_iteration_pipeline
from mylab.services import (
    FLOW_MODE_LIMIT,
    FLOW_MODE_STEP,
    FLOW_MODE_UNLIMIT,
    TelegramBotClient,
    bootstrap_run,
    create_initial_plan,
    create_iterated_plan,
    interactive_telegram_setup,
    format_repo_report,
    load_telegram_settings,
    load_run_control_settings,
    make_run_id,
    prepare_executor,
    prompt_for_flow_mode,
    resolve_notification_settings,
    run_executor,
    write_sample_config,
    write_summary,
)
from mylab.services.git_lifecycle import restore_original_branch
from mylab.services.plans import lab_input_text
from mylab.storage import init_run_dirs, runs_root
from mylab.storage.runs import load_manifest


HELP_FORMATTER = argparse.RawDescriptionHelpFormatter


def resolve_goal_input(goal: str | None, lab_md: Path | None) -> tuple[str, str]:
    if goal:
        goal_path = Path(goal).expanduser()
        if goal_path.exists() and goal_path.is_file():
            return goal_path.read_text(encoding="utf-8"), goal_path.name
        return goal, "goal.txt"
    if lab_md:
        return lab_md.read_text(encoding="utf-8"), lab_md.name
    raise ValueError("either goal or lab_md must be provided")


def print_codex_preflight(model_override: str | None) -> None:
    status = get_codex_status(model_override)
    emit_progress(
        "[codex]",
        "preflight",
        f"login={status.login_status}",
        color="blue",
    )
    emit_progress(
        "[codex]",
        "runtime",
        f"effective_model={status.effective_model or 'default'} configured_model={status.configured_model or '-'} reasoning={status.reasoning_effort or '-'} cli={status.cli_version or '-'} mode=danger-bypass",
        color="cyan",
    )
    emit_progress(
        "[codex]",
        "quota",
        status.quota_status,
        color="yellow",
    )


def resolve_flow_control(
    *,
    mode: str | None,
    limit: int | None,
    prompt_if_missing: bool,
) -> tuple[str, int | None]:
    settings = load_run_control_settings()
    resolved_mode = mode or settings.mode
    if not resolved_mode and prompt_if_missing and sys.stdin.isatty():
        resolved_mode = prompt_for_flow_mode()
    resolved_mode = resolved_mode or FLOW_MODE_LIMIT
    resolved_limit = limit if limit is not None else settings.limit
    if resolved_mode == FLOW_MODE_LIMIT and resolved_limit is None:
        resolved_limit = 100
    return resolved_mode, resolved_limit


def build_step_confirmation(run_dir: Path):
    def confirm(completed_iterations: int) -> bool:
        prompt = (
            f"Run {run_dir.name} completed {completed_iterations} iteration(s). "
            "Continue to the next iteration? [y/N]: "
        )
        answer = input(prompt).strip().lower()
        return answer in {"y", "yes"}

    return confirm


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mylab",
        description="Codex-based experiment orchestration CLI for research repositories.",
        epilog=(
            "Common workflows:\n"
            "  1. Start a new experiment and run it immediately:\n"
            "     mylab run --repo /path/to/repo --goal 'reproduce main experiment'\n"
            "     mylab run --repo /path/to/repo --goal ./goal.md\n"
            "  2. Resume an existing run directory:\n"
            "     mylab run --run-dir .mylab_runs/<run_id>\n"
            "  3. Add a new iteration after reviewing results:\n"
            "     mylab queue-iteration --run-dir .mylab_runs/<run_id> --parent-plan plan-001 --feedback 'next step'\n\n"
            "Advanced tools:\n"
            "  - Internal/low-level commands live under `mylab tool ...`\n"
            "  - Example: mylab tool prepare-executor --run-dir .mylab_runs/<run_id>\n\n"
            "Notes:\n"
            "  - MYLAB_RUNS_DIR controls where run artifacts are stored.\n"
            "  - If the run directory is inside the experiment repo, mylab will add it to that repo's .gitignore.\n"
            "  - run is the main entrypoint for normal use.\n"
            "  - run executes the flow directly; it does not need a separate allow-exec flag."
        ),
        formatter_class=HELP_FORMATTER,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    flow_cmd = subparsers.add_parser(
        "run",
        help="Start or resume an experiment run and execute it directly.",
        description=(
            "Main entrypoint.\n"
            "Use --repo with --goal/--lab-md to create a new run and execute it immediately,\n"
            "or use --run-dir to resume an existing run."
        ),
        epilog=(
            "Example:\n"
            "  mylab run --repo /path/to/repo --goal 'reproduce table 1'\n"
            "  mylab run --repo /path/to/repo --goal ./goal.md\n"
            "  mylab run --repo /path/to/repo --lab-md ./lab.md\n"
            "  mylab run --run-dir .mylab_runs/<run_id>"
        ),
        formatter_class=HELP_FORMATTER,
    )
    flow_cmd.add_argument(
        "--run-dir", type=Path, help="Existing run directory to resume."
    )
    flow_cmd.add_argument(
        "--repo",
        type=Path,
        help="Git-tracked experiment repository path for a new run.",
    )
    flow_group = flow_cmd.add_mutually_exclusive_group(required=False)
    flow_group.add_argument(
        "--goal",
        help="Plain-text experiment goal, or a file path whose contents should be used as the goal.",
    )
    flow_group.add_argument(
        "--lab-md", type=Path, help="Markdown file containing the experiment goal/spec."
    )
    flow_cmd.add_argument(
        "--source-branch",
        help="Base Git branch for later experiment work. Defaults to current branch.",
    )
    flow_cmd.add_argument(
        "--run-id",
        help="Explicit run identifier for a new run. Defaults to a timestamp-based value.",
    )
    flow_cmd.add_argument(
        "--model",
        help="Optional Codex model override. If omitted, Codex uses its configured default.",
    )
    flow_cmd.add_argument(
        "--mode",
        choices=[FLOW_MODE_LIMIT, FLOW_MODE_STEP, FLOW_MODE_UNLIMIT],
        help="Execution mode: limit, step, or unlimit. If omitted in an interactive shell, mylab can prompt for it.",
    )
    flow_cmd.add_argument(
        "--limit",
        type=int,
        help="Iteration count. In limit mode it is the hard cap. In step mode it is the number of iterations to auto-run before per-iteration confirmation.",
    )

    queue_iter_cmd = subparsers.add_parser(
        "queue-iteration",
        help="Enqueue a plan iteration pipeline.",
        description="Append an iteration request to the run queue. The serial runner will create the new plan later.",
        formatter_class=HELP_FORMATTER,
    )
    queue_iter_cmd.add_argument(
        "--run-dir", required=True, type=Path, help="Existing run directory."
    )
    queue_iter_cmd.add_argument(
        "--parent-plan", required=True, help="Parent plan id, for example plan-001."
    )
    queue_iter_cmd.add_argument(
        "--feedback", required=True, help="Observed result or next-step instruction."
    )
    queue_iter_cmd.add_argument(
        "--model", help="Optional Codex model override for the follow-up executor."
    )

    bot_cmd = subparsers.add_parser(
        "bot",
        help="Interactive bot configuration commands.",
        description="Configure chat integrations such as Telegram.",
        formatter_class=HELP_FORMATTER,
    )
    bot_subparsers = bot_cmd.add_subparsers(dest="bot_command", required=True)

    bot_telegram_cmd = bot_subparsers.add_parser(
        "telegram",
        help="Interactively configure Telegram bot settings.",
        description="Prompt for Telegram settings and write them into ~/.mylab/config.toml.",
        formatter_class=HELP_FORMATTER,
    )
    bot_telegram_cmd.add_argument(
        "--config-path",
        type=Path,
        help="Optional config path override. Defaults to ~/.mylab/config.toml.",
    )

    tool_cmd = subparsers.add_parser(
        "tool",
        help="Advanced low-level commands.",
        description=(
            "Low-level or internal commands for debugging, inspection, and manual control.\n"
            "Most users should prefer: run, queue-iteration."
        ),
        formatter_class=HELP_FORMATTER,
    )
    tool_subparsers = tool_cmd.add_subparsers(dest="tool_command", required=True)

    init_run_cmd = tool_subparsers.add_parser(
        "init-run",
        help="Bootstrap a run without executing it.",
        description=(
            "Low-level helper to create a run directory, write the initial manifest,\n"
            "copy the goal input, and enqueue the first serial stages."
        ),
        formatter_class=HELP_FORMATTER,
    )
    init_run_cmd.add_argument(
        "--repo",
        required=True,
        type=Path,
        help="Git-tracked experiment repository path.",
    )
    init_run_group = init_run_cmd.add_mutually_exclusive_group(required=True)
    init_run_group.add_argument(
        "--goal",
        help="Plain-text experiment goal, or a file path whose contents should be used as the goal.",
    )
    init_run_group.add_argument(
        "--lab-md", type=Path, help="Markdown file containing the experiment goal/spec."
    )
    init_run_cmd.add_argument(
        "--source-branch",
        help="Base Git branch for later experiment work. Defaults to current branch.",
    )
    init_run_cmd.add_argument(
        "--run-id", help="Explicit run identifier. Defaults to a timestamp-based value."
    )
    init_run_cmd.add_argument(
        "--model", help="Optional Codex model override stored in the queued tasks."
    )

    poll_cmd = tool_subparsers.add_parser(
        "poll-run",
        help="Advance queued tasks for a run.",
        description="Run the serial flow for a small number of pending tasks and then stop.",
        epilog=(
            "Example:\n"
            "  mylab tool poll-run --run-dir .mylab_runs/<run_id> --limit 3\n"
            "  mylab tool poll-run --run-dir .mylab_runs/<run_id> --allow-exec"
        ),
        formatter_class=HELP_FORMATTER,
    )
    poll_cmd.add_argument(
        "--run-dir", required=True, type=Path, help="Run directory created by init-run."
    )
    poll_cmd.add_argument(
        "--mode",
        choices=[FLOW_MODE_LIMIT, FLOW_MODE_STEP, FLOW_MODE_UNLIMIT],
        help="Execution mode: limit, step, or unlimit.",
    )
    poll_cmd.add_argument(
        "--limit",
        type=int,
        help="Iteration count. In limit mode it is the hard cap. In step mode it is the number of iterations to auto-run before per-iteration confirmation.",
    )
    poll_cmd.add_argument(
        "--allow-exec",
        action="store_true",
        help="Allow the run_executor stage to actually call codex.",
    )

    create_cmd = tool_subparsers.add_parser(
        "create-plan",
        help="Create the first structured plan.",
        description="Direct command to create a first plan without using the queued serial flow.",
        formatter_class=HELP_FORMATTER,
    )
    create_cmd.add_argument(
        "--run-dir",
        type=Path,
        help="Existing run directory. If omitted, a new run will be bootstrapped.",
    )
    create_cmd.add_argument(
        "--repo", type=Path, help="Repository path used when bootstrapping a new run."
    )
    create_group = create_cmd.add_mutually_exclusive_group(required=False)
    create_group.add_argument(
        "--goal",
        help="Plain-text experiment goal, or a file path whose contents should be used for a new run.",
    )
    create_group.add_argument(
        "--lab-md", type=Path, help="Markdown file used for a new run."
    )
    create_cmd.add_argument(
        "--source-branch", help="Base branch used when bootstrapping a new run."
    )
    create_cmd.add_argument(
        "--run-id", help="Run identifier used when bootstrapping a new run."
    )

    iterate_cmd = tool_subparsers.add_parser(
        "iterate-plan",
        help="Create the next plan from prior results.",
        description="Create a new plan directly from an existing run, parent plan, and feedback string.",
        formatter_class=HELP_FORMATTER,
    )
    iterate_cmd.add_argument(
        "--run-dir", required=True, type=Path, help="Existing run directory."
    )
    iterate_cmd.add_argument(
        "--feedback",
        required=True,
        help="Observed result or instruction for the next iteration.",
    )
    iterate_cmd.add_argument(
        "--parent-plan", required=True, help="Parent plan id, for example plan-001."
    )

    format_cmd = tool_subparsers.add_parser(
        "format-repo",
        help="Emit a repo formatting audit.",
        description="Scan a repository for likely output/result/log files and write a simple format audit report.",
        formatter_class=HELP_FORMATTER,
    )
    format_cmd.add_argument(
        "--repo", type=Path, help="Repository path. Required when --run-dir is omitted."
    )
    format_cmd.add_argument(
        "--run-dir",
        type=Path,
        help="Existing run directory. If set, repo is taken from the run manifest.",
    )

    prepare_cmd = tool_subparsers.add_parser(
        "prepare-executor",
        help="Generate executor prompts and commands.",
        description="Write the executor prompt and a reusable codex shell script for a plan.",
        formatter_class=HELP_FORMATTER,
    )
    prepare_cmd.add_argument(
        "--run-dir", required=True, type=Path, help="Existing run directory."
    )
    prepare_cmd.add_argument(
        "--plan-id", help="Plan id. Defaults to manifest.latest_plan_id."
    )
    prepare_cmd.add_argument(
        "--model", help="Optional Codex model override for the generated command."
    )

    run_cmd = tool_subparsers.add_parser(
        "run-executor",
        help="Run the prepared plan via codex.",
        description="Directly execute a previously prepared Codex command for the selected plan.",
        formatter_class=HELP_FORMATTER,
    )
    run_cmd.add_argument(
        "--run-dir", required=True, type=Path, help="Existing run directory."
    )
    run_cmd.add_argument(
        "--plan-id", help="Plan id. Defaults to manifest.latest_plan_id."
    )
    run_cmd.add_argument("--model", help="Optional Codex model override for execution.")
    run_cmd.add_argument(
        "--full-auto",
        action="store_true",
        help="Pass Codex full-auto mode through to execution.",
    )

    summary_cmd = tool_subparsers.add_parser(
        "write-summary",
        help="Write a strict summary file.",
        description="Write a summary markdown file that follows the fixed mylab summary schema.",
        formatter_class=HELP_FORMATTER,
    )
    summary_cmd.add_argument(
        "--run-dir", required=True, type=Path, help="Existing run directory."
    )
    summary_cmd.add_argument("--plan-id", required=True, help="Plan id to summarize.")
    summary_cmd.add_argument(
        "--status",
        required=True,
        help="Short status label, for example success or failed.",
    )
    summary_cmd.add_argument(
        "--outcome", required=True, help="Human-readable one-line outcome summary."
    )
    summary_cmd.add_argument(
        "--evidence",
        nargs="+",
        required=True,
        help="One or more evidence paths or notes.",
    )
    summary_cmd.add_argument(
        "--artifacts",
        nargs="+",
        required=True,
        help="One or more produced artifact paths.",
    )
    summary_cmd.add_argument(
        "--next-iteration",
        nargs="+",
        required=True,
        help="One or more next-step items.",
    )

    telegram_cmd = tool_subparsers.add_parser(
        "telegram-bot",
        help="Poll the Telegram bot and ingest commands or feedback.",
        description="Run one polling cycle or a long-lived polling loop for the configured Telegram bot.",
        formatter_class=HELP_FORMATTER,
    )
    telegram_cmd.add_argument("--once", action="store_true", help="Poll once and exit.")

    init_config_cmd = tool_subparsers.add_parser(
        "init-config",
        help="Write a sample ~/.mylab/config.toml if it does not exist.",
        description="Create a starter user configuration file for Telegram and notifications.",
        formatter_class=HELP_FORMATTER,
    )
    return parser


def cmd_init_run(args: argparse.Namespace) -> int:
    repo_path = args.repo.expanduser().resolve()
    lab_md = args.lab_md.expanduser().resolve() if args.lab_md else None
    goal_text = lab_input_text(args.goal, lab_md)
    run_id = args.run_id or make_run_id(goal_text)
    paths = init_run_dirs(runs_root() / run_id)
    configure_logging(paths.logs)
    input_text, input_name = resolve_goal_input(args.goal, lab_md)
    bootstrap_run(
        repo_path=repo_path,
        goal_text=input_text,
        run_id=run_id,
        paths=paths,
        source_branch=args.source_branch,
        input_file_name=input_name,
        notifications=resolve_notification_settings(),
    )
    enqueue_initial_pipeline(paths.root, args.model)
    logger.info("Initialized run at {}", paths.root)
    print(paths.root)
    return 0


def cmd_poll_run(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.expanduser().resolve()
    configure_logging(run_dir / "logs")
    mode, limit = resolve_flow_control(
        mode=args.mode,
        limit=args.limit,
        prompt_if_missing=True,
    )
    confirm_continue = (
        build_step_confirmation(run_dir)
        if mode == FLOW_MODE_STEP and sys.stdin.isatty()
        else None
    )
    outputs = SerialFlowRunner(
        run_dir,
        allow_exec=args.allow_exec,
        mode=mode,
        confirm_continue=confirm_continue,
    ).run_until_blocked(limit=limit)
    for item in outputs:
        print(f"{item['task_id']} {item['kind']} {item['output']}")
    return 0


def cmd_run_flow(args: argparse.Namespace) -> int:
    if args.run_dir:
        run_dir = args.run_dir.expanduser().resolve()
        init_run_dirs(run_dir)
        configure_logging(run_dir / "logs")
        print_codex_preflight(args.model)
    else:
        if not args.repo or not (args.goal or args.lab_md):
            raise ValueError(
                "run requires either --run-dir or (--repo and one of --goal/--lab-md)"
            )
        repo_path = args.repo.expanduser().resolve()
        lab_md = args.lab_md.expanduser().resolve() if args.lab_md else None
        goal_text = lab_input_text(args.goal, lab_md)
        run_id = args.run_id or make_run_id(goal_text)
        paths = init_run_dirs(runs_root() / run_id)
        configure_logging(paths.logs)
        print_codex_preflight(args.model)
        input_text, input_name = resolve_goal_input(args.goal, lab_md)
        bootstrap_run(
            repo_path=repo_path,
            goal_text=input_text,
            run_id=run_id,
            paths=paths,
            source_branch=args.source_branch,
            input_file_name=input_name,
            notifications=resolve_notification_settings(),
        )
        enqueue_initial_pipeline(paths.root, args.model)
        run_dir = paths.root
        logger.info("Initialized run at {}", run_dir)
    mode, limit = resolve_flow_control(
        mode=args.mode,
        limit=args.limit,
        prompt_if_missing=True,
    )
    confirm_continue = (
        build_step_confirmation(run_dir)
        if mode == FLOW_MODE_STEP and sys.stdin.isatty()
        else None
    )
    outputs = SerialFlowRunner(
        run_dir,
        allow_exec=True,
        mode=mode,
        confirm_continue=confirm_continue,
    ).run_until_blocked(limit=limit)
    for item in outputs:
        print(f"{item['task_id']} {item['kind']} {item['output']}")
    return 0


def ensure_manifest_or_bootstrap(args: argparse.Namespace):
    if args.run_dir:
        run_dir = args.run_dir.expanduser().resolve()
        paths = init_run_dirs(run_dir)
        manifest = load_manifest(run_dir)
        return paths, manifest
    if not args.repo or not (args.goal or args.lab_md):
        raise ValueError(
            "either --run-dir or (--repo and one of --goal/--lab-md) is required"
        )
    repo_path = args.repo.expanduser().resolve()
    lab_md = args.lab_md.expanduser().resolve() if args.lab_md else None
    goal_text = lab_input_text(args.goal, lab_md)
    run_id = args.run_id or make_run_id(goal_text)
    paths = init_run_dirs(runs_root() / run_id)
    input_text, input_name = resolve_goal_input(args.goal, lab_md)
    manifest = bootstrap_run(
        repo_path=repo_path,
        goal_text=input_text,
        run_id=run_id,
        paths=paths,
        source_branch=args.source_branch,
        input_file_name=input_name,
        notifications=resolve_notification_settings(),
    )
    return paths, manifest


def cmd_create_plan(args: argparse.Namespace) -> int:
    paths, manifest = ensure_manifest_or_bootstrap(args)
    configure_logging(paths.logs)
    print(create_initial_plan(paths, manifest))
    return 0


def cmd_iterate_plan(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.expanduser().resolve()
    paths = init_run_dirs(run_dir)
    configure_logging(paths.logs)
    manifest = load_manifest(run_dir)
    print(create_iterated_plan(paths, manifest, args.parent_plan, args.feedback))
    return 0


def cmd_queue_iteration(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.expanduser().resolve()
    configure_logging(run_dir / "logs")
    enqueue_iteration_pipeline(run_dir, args.parent_plan, args.feedback, args.model)
    print(run_dir / "queue" / "pipeline.json")
    return 0


def cmd_format_repo(args: argparse.Namespace) -> int:
    if args.run_dir:
        run_dir = args.run_dir.expanduser().resolve()
        configure_logging(run_dir / "logs")
        manifest = load_manifest(run_dir)
        print(format_repo_report(Path(manifest.repo_path), run_dir))
        return 0
    if not args.repo:
        raise ValueError("--repo is required when --run-dir is omitted")
    run_dir = runs_root() / f"format_{args.repo.expanduser().resolve().name}"
    paths = init_run_dirs(run_dir)
    configure_logging(paths.logs)
    print(format_repo_report(args.repo.expanduser().resolve(), paths.root))
    return 0


def cmd_prepare_executor(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.expanduser().resolve()
    configure_logging(run_dir / "logs")
    manifest = load_manifest(run_dir)
    plan_id = args.plan_id or manifest.latest_plan_id
    if not plan_id:
        raise ValueError("missing plan id and manifest.latest_plan_id is empty")
    print(prepare_executor(run_dir, plan_id, args.model))
    return 0


def cmd_run_executor(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.expanduser().resolve()
    configure_logging(run_dir / "logs")
    print_codex_preflight(args.model)
    manifest = load_manifest(run_dir)
    plan_id = args.plan_id or manifest.latest_plan_id
    if not plan_id:
        raise ValueError("missing plan id and manifest.latest_plan_id is empty")
    try:
        print(run_executor(run_dir, plan_id, args.model, args.full_auto))
    finally:
        manifest = load_manifest(run_dir)
        if manifest.work_branch and manifest.original_branch:
            restore_original_branch(run_dir, manifest)
    return 0


def cmd_write_summary(args: argparse.Namespace) -> int:
    configure_logging(args.run_dir.expanduser().resolve() / "logs")
    print(
        write_summary(
            args.run_dir.expanduser().resolve(),
            args.plan_id,
            args.status,
            args.outcome,
            args.evidence,
            args.artifacts,
            args.next_iteration,
        )
    )
    return 0


def cmd_telegram_bot(args: argparse.Namespace) -> int:
    settings = load_telegram_settings()
    bot = TelegramBotClient(settings)
    if args.once:
        print(bot.poll_once())
        return 0
    bot.run_forever()
    return 0


def cmd_init_config(args: argparse.Namespace) -> int:
    path = write_sample_config()
    print(path)
    return 0


def cmd_bot_telegram(args: argparse.Namespace) -> int:
    path = interactive_telegram_setup(config_path=args.config_path or None)
    print(path)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    commands = {
        "bot": cmd_bot_telegram,
        "run": cmd_run_flow,
        "queue-iteration": cmd_queue_iteration,
    }
    tool_commands = {
        "init-run": cmd_init_run,
        "poll-run": cmd_poll_run,
        "create-plan": cmd_create_plan,
        "iterate-plan": cmd_iterate_plan,
        "format-repo": cmd_format_repo,
        "init-config": cmd_init_config,
        "prepare-executor": cmd_prepare_executor,
        "run-executor": cmd_run_executor,
        "telegram-bot": cmd_telegram_bot,
        "write-summary": cmd_write_summary,
    }
    try:
        if args.command == "tool":
            return tool_commands[args.tool_command](args)
        if args.command == "bot":
            return commands[args.command](args)
        return commands[args.command](args)
    except (RuntimeError, ValueError) as exc:
        emit_progress("[error]", str(exc), color="red")
        return 1
