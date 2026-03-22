from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile

from mylab.codex import get_codex_status
from mylab.config import CURRENT_RUN_FILE
from mylab.flow import SerialFlowRunner
from mylab.gittools import GitManager
from mylab.logging import configure_logging, emit_progress, logger
from mylab.orchestrator import (
    enqueue_initial_pipeline,
    enqueue_iteration_pipeline,
    load_queue,
    save_queue,
)
from mylab.domain import QueueState
from mylab.services import (
    FLOW_MODE_LIMIT,
    FLOW_MODE_RESIDENT,
    FLOW_MODE_STEP,
    FLOW_MODE_UNLIMIT,
    NotificationClient,
    TelegramBotClient,
    bootstrap_run,
    create_initial_trial,
    create_iterated_trial,
    interactive_feishu_setup,
    interactive_telegram_setup,
    format_repo_report,
    load_feishu_settings,
    load_telegram_settings,
    load_run_control_settings,
    make_run_id,
    prepare_executor,
    prompt_for_flow_mode,
    resolve_notification_settings,
    run_adapter,
    run_executor,
    send_feishu_test_message,
    start_job,
    tail_job,
    telegram_notifications_enabled,
    terminate_all_jobs,
    wait_for_job,
    write_sample_config,
    write_summary,
)
from mylab.services.git_lifecycle import restore_original_branch
from mylab.services.trials import lab_input_text
from mylab.storage import ensure_dir, init_run_dirs, read_json, runs_root, write_json
from mylab.storage.trial_layout import trial_paths
from mylab.storage.runs import load_manifest, planned_run_dirs, save_manifest
from mylab.utils import slugify


HELP_FORMATTER = argparse.RawDescriptionHelpFormatter


def _current_run_file() -> Path:
    return CURRENT_RUN_FILE


def list_named_runs() -> list[Path]:
    root = runs_root()
    runs: list[Path] = []
    for candidate in sorted(root.iterdir()):
        if candidate.is_dir() and (candidate / "manifests" / "run.json").exists():
            runs.append(candidate)
    return runs


def resolve_run_dir_by_name(name: str) -> Path:
    return runs_root() / name


def set_current_run(name: str) -> None:
    write_json(_current_run_file(), {"run": name})


def get_current_run_name() -> str | None:
    path = _current_run_file()
    if not path.exists():
        return None
    payload = read_json(path)
    value = payload.get("run")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def clear_current_run_if_matches(name: str) -> None:
    if get_current_run_name() == name:
        try:
            _current_run_file().unlink()
        except FileNotFoundError:
            pass


def require_selected_run_dir() -> Path:
    name = get_current_run_name()
    if not name:
        raise ValueError("no active run selected; use `mylab run use <name>` first")
    run_dir = resolve_run_dir_by_name(name)
    if not (run_dir / "manifests" / "run.json").exists():
        raise ValueError(
            f"selected run `{name}` does not exist anymore; use `mylab run ls` and `mylab run use <name>`"
        )
    return run_dir


def _trial_branch_name(run_id: str, trial_id: str) -> str:
    return f"mylab/{slugify(run_id, max_length=24)}/{trial_id}"


def _delete_trial_branch_if_present(run_dir: Path, trial_id: str) -> None:
    manifest = load_manifest(run_dir)
    repo_path = Path(manifest.repo_path)
    git = GitManager(repo_path, run_dir / "logs" / "git-lifecycle.jsonl")
    branch = _trial_branch_name(manifest.run_id, trial_id)
    if not git.branch_exists(branch):
        return
    current = git.current_branch()
    if current == branch:
        git.checkout(manifest.original_branch or manifest.source_branch)
    git.delete_branch(branch, force=True)


def _remove_trial_from_queue(run_dir: Path, trial_id: str) -> None:
    queue = load_queue(run_dir)
    filtered = []
    for task in queue.tasks:
        payload = task.payload or {}
        if payload.get("trial_id") == trial_id or payload.get("parent_trial_id") == trial_id:
            continue
        filtered.append(task)
    save_queue(run_dir, QueueState(tasks=filtered))


def _remove_trial_from_index(run_dir: Path, trial_id: str) -> None:
    index_path = run_dir / "trials" / "index.jsonl"
    if not index_path.exists():
        return
    lines = index_path.read_text(encoding="utf-8").splitlines()
    kept = []
    for line in lines:
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("trial_id") == trial_id:
            continue
        kept.append(record)
    write_jsonl_path = run_dir / "trials" / "index.jsonl"
    write_jsonl_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=True) for item in kept) + ("\n" if kept else ""),
        encoding="utf-8",
    )
    markdown = ["# Trial Catalog", f"- run_id: {run_dir.name}"]
    for record in kept:
        markdown.extend(
            [
                "",
                f"## {record['trial_id']}",
                f"- trial_kind: {record.get('trial_kind', 'unknown')}",
                f"- status: {record['status']}",
                f"- goal_summary: {record.get('goal_summary', '-')}",
                f"- trial_path: {record.get('trial_path', '-')}",
                f"- summary_path: {record.get('summary_path', '-')}",
            ]
        )
    (run_dir / "trials" / "index.md").write_text(
        "\n".join(markdown).rstrip() + "\n", encoding="utf-8"
    )


def _remove_trial(run_dir: Path, trial_id: str) -> None:
    paths = trial_paths(run_dir, trial_id)
    if not paths.root.exists():
        raise ValueError(f"trial `{trial_id}` does not exist in run `{run_dir.name}`")
    _delete_trial_branch_if_present(run_dir, trial_id)
    _remove_trial_from_queue(run_dir, trial_id)
    _remove_trial_from_index(run_dir, trial_id)
    shutil.rmtree(paths.root)
    manifest = load_manifest(run_dir)
    if manifest.latest_trial_id == trial_id:
        remaining = [
            item.name
            for item in sorted((run_dir / "trials").iterdir())
            if item.is_dir() and item.name.startswith("trial-")
        ]
        manifest.latest_trial_id = remaining[-1] if remaining else None
        save_manifest(init_run_dirs(run_dir), manifest)


def _latest_unfinished_trial_id(run_dir: Path) -> str | None:
    manifest = load_manifest(run_dir)
    trial_id = manifest.latest_trial_id
    if not trial_id:
        return None
    paths = trial_paths(run_dir, trial_id)
    if not paths.root.exists():
        return None
    if not paths.summary.exists():
        return trial_id
    return None


def _cleanup_unfinished_trial(run_dir: Path) -> str | None:
    trial_id = _latest_unfinished_trial_id(run_dir)
    if not trial_id:
        return None
    _remove_trial(run_dir, trial_id)
    return trial_id


def _resume_existing_run_if_idle(run_dir: Path, model: str | None) -> None:
    queue = load_queue(run_dir)
    if any(task.status in {"pending", "running"} for task in queue.tasks):
        return
    _cleanup_unfinished_trial(run_dir)
    manifest = load_manifest(run_dir)
    if manifest.latest_trial_id:
        enqueue_iteration_pipeline(
            run_dir,
            manifest.latest_trial_id,
            (
                "Continue to the next full iteration based on the latest trial, "
                "summary, result report, repository shared asset, and preserved "
                "execution evidence."
            ),
            model,
        )
        return
    enqueue_initial_pipeline(run_dir, model)


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
    resolved_mode = resolved_mode or FLOW_MODE_UNLIMIT
    resolved_limit = limit if limit is not None else settings.limit
    if resolved_mode == FLOW_MODE_LIMIT and resolved_limit is None:
        resolved_limit = 100
    return resolved_mode, resolved_limit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mylab",
        description="Codex-based experiment orchestration CLI for research repositories.",
        formatter_class=HELP_FORMATTER,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    flow_cmd = subparsers.add_parser(
        "start",
        help="Start or resume an experiment run and execute it directly.",
        description=(
            "Main entrypoint.\n"
            "Use --repo with --goal/--lab-md to create a new named run and execute it immediately,\n"
            "or use --run to resume an existing run by name."
        ),
        epilog=(
            "Example:\n"
            "  mylab start --repo /path/to/repo --goal 'reproduce table 1'\n"
            "  mylab start --repo /path/to/repo --goal ./goal.md --run run_xx\n"
            "  mylab start --run run_xx\n"
        ),
        formatter_class=HELP_FORMATTER,
    )
    flow_cmd.add_argument(
        "--run", help="Run name. If omitted for a new run, mylab creates one."
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
        "--model",
        help="Optional Codex model override. If omitted, Codex uses its configured default.",
    )
    flow_cmd.add_argument(
        "--mode",
        choices=[FLOW_MODE_LIMIT, FLOW_MODE_STEP, FLOW_MODE_UNLIMIT, FLOW_MODE_RESIDENT],
        help="Execution mode: limit, step, unlimit, or resident. If omitted in an interactive shell, mylab can prompt for it.",
    )
    flow_cmd.add_argument(
        "--limit",
        type=int,
        help="Iteration count. In limit mode it is the hard cap. In step mode it is the number of iterations to auto-run before per-iteration confirmation.",
    )

    adapter_cmd = subparsers.add_parser(
        "adapter",
        help="Adapt the current repository for direct single-trial execution.",
        description="Directly modify the current repository so one trial can run without creating a mylab run or switching branches.",
        formatter_class=HELP_FORMATTER,
    )
    adapter_cmd.add_argument(
        "--repo",
        type=Path,
        default=Path("."),
        help="Repository path to adapt. Defaults to the current directory.",
    )
    adapter_group = adapter_cmd.add_mutually_exclusive_group(required=False)
    adapter_group.add_argument(
        "--goal",
        help="Optional adaptation goal, or a file path whose contents should be used.",
    )
    adapter_group.add_argument(
        "--lab-md",
        type=Path,
        help="Optional markdown file containing the adaptation goal/spec.",
    )
    adapter_cmd.add_argument(
        "--model",
        help="Optional Codex model override for the adapter execution.",
    )

    run_cmd = subparsers.add_parser(
        "run",
        help="Manage named runs.",
        formatter_class=HELP_FORMATTER,
    )
    run_subparsers = run_cmd.add_subparsers(dest="run_command", required=True)

    run_use_cmd = run_subparsers.add_parser("use", help="Select the active run.")
    run_use_cmd.add_argument("name", help="Run name to select.")

    run_subparsers.add_parser("ls", help="List named runs.")

    run_rm_cmd = run_subparsers.add_parser("rm", help="Remove a named run.")
    run_rm_cmd.add_argument("name", help="Run name to remove.")

    trial_cmd = subparsers.add_parser(
        "trial",
        help="Manage trials inside the active run.",
        formatter_class=HELP_FORMATTER,
    )
    trial_subparsers = trial_cmd.add_subparsers(dest="trial_command", required=True)
    trial_ls_cmd = trial_subparsers.add_parser("ls", help="List trials in the active run.")
    trial_ls_cmd.add_argument("--run", help="Optional run name override.")
    trial_cat_cmd = trial_subparsers.add_parser("cat", help="Show one trial.")
    trial_cat_cmd.add_argument("trial_id", help="Trial id to inspect.")
    trial_cat_cmd.add_argument("--run", help="Optional run name override.")
    trial_rm_cmd = trial_subparsers.add_parser("rm", help="Remove one trial and its local context.")
    trial_rm_cmd.add_argument("trial_id", help="Trial id to remove.")
    trial_rm_cmd.add_argument("--run", help="Optional run name override.")

    queue_iter_cmd = subparsers.add_parser(
        "queue-iteration",
        help="Compatibility command for manually injecting the next iteration.",
        description="Compatibility-only command. Normal use should continue the run directly so each completed trial leads to the next trial.",
        formatter_class=HELP_FORMATTER,
    )
    queue_iter_cmd.add_argument(
        "--run-dir", required=True, type=Path, help="Existing run directory."
    )
    queue_iter_cmd.add_argument(
        "--parent-trial", required=True, help="Parent trial id, for example trial-001."
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
        description="Configure chat integrations such as Telegram or Feishu.",
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

    bot_test_cmd = bot_subparsers.add_parser(
        "test",
        help="Test all configured bot integrations.",
        description="Validate configured bot integrations and send a test notification when possible.",
        formatter_class=HELP_FORMATTER,
    )
    bot_test_cmd.add_argument(
        "--config-path",
        type=Path,
        help="Optional config path override. Defaults to ~/.mylab/config.toml.",
    )

    bot_feishu_cmd = bot_subparsers.add_parser(
        "feishu",
        help="Interactively configure Feishu webhook bot settings.",
        description="Prompt for Feishu webhook settings and write them into ~/.mylab/config.toml.",
        formatter_class=HELP_FORMATTER,
    )
    bot_feishu_cmd.add_argument(
        "--config-path",
        type=Path,
        help="Optional config path override. Defaults to ~/.mylab/config.toml.",
    )

    tool_cmd = subparsers.add_parser(
        "tool",
        help="Advanced low-level commands.",
        description=(
            "Low-level or internal commands for debugging, inspection, and manual control.\n"
            "Most users should prefer: run."
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
        choices=[FLOW_MODE_LIMIT, FLOW_MODE_STEP, FLOW_MODE_UNLIMIT, FLOW_MODE_RESIDENT],
        help="Execution mode: limit, step, unlimit, or resident.",
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
        "create-trial",
        help="Create the first structured trial.",
        description="Direct command to create a first trial without using the queued serial flow.",
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
        "iterate-trial",
        help="Create the next trial from prior results.",
        description="Create a new trial directly from an existing run, parent trial, and feedback string.",
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
        "--parent-trial", required=True, help="Parent trial id, for example trial-001."
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
        description="Write the executor prompt and a reusable codex shell script for a trial.",
        formatter_class=HELP_FORMATTER,
    )
    prepare_cmd.add_argument(
        "--run-dir", required=True, type=Path, help="Existing run directory."
    )
    prepare_cmd.add_argument(
        "--trial-id", help="Trial id. Defaults to manifest.latest_trial_id."
    )
    prepare_cmd.add_argument(
        "--model", help="Optional Codex model override for the generated command."
    )

    run_cmd = tool_subparsers.add_parser(
        "run-executor",
        help="Run the prepared trial via codex.",
        description="Directly execute a previously prepared Codex command for the selected trial.",
        formatter_class=HELP_FORMATTER,
    )
    run_cmd.add_argument(
        "--run-dir", required=True, type=Path, help="Existing run directory."
    )
    run_cmd.add_argument(
        "--trial-id", help="Trial id. Defaults to manifest.latest_trial_id."
    )
    run_cmd.add_argument("--model", help="Optional Codex model override for execution.")
    run_cmd.add_argument(
        "--full-auto",
        action="store_true",
        help="Pass Codex full-auto mode through to execution.",
    )

    start_job_cmd = tool_subparsers.add_parser(
        "start-job",
        help="Start a monitored long-running job.",
        description="Launch a long-running shell command through the mylab job monitor and return a job id for future polling.",
        formatter_class=HELP_FORMATTER,
    )
    start_job_cmd.add_argument(
        "--run-dir", required=True, type=Path, help="Existing run directory."
    )
    start_job_cmd.add_argument("--trial-id", required=True, help="Owning trial id.")
    start_job_cmd.add_argument("--name", help="Short job label.")
    start_job_cmd.add_argument("--cwd", help="Optional working directory override.")
    start_job_cmd.add_argument(
        "--command",
        dest="job_command",
        required=True,
        help="Shell command string to execute under the monitor.",
    )

    wait_job_cmd = tool_subparsers.add_parser(
        "wait-job",
        help="Wait for a monitored job to finish.",
        description="Wait for a monitored job. By default the timer is disabled and the command blocks until completion; enable the timer only when you want bounded polling.",
        formatter_class=HELP_FORMATTER,
    )
    wait_job_cmd.add_argument(
        "--run-dir", required=True, type=Path, help="Existing run directory."
    )
    wait_job_cmd.add_argument("--job-id", required=True, help="Tracked job id.")
    wait_job_cmd.add_argument(
        "--enable-timer",
        action="store_true",
        help="Enable the wait timer so the command can return early with status=running.",
    )
    wait_job_cmd.add_argument(
        "--wait-seconds",
        type=int,
        help="Maximum seconds to wait before returning when --enable-timer is set.",
    )
    wait_job_cmd.add_argument(
        "--poll-seconds",
        type=int,
        help="Polling cadence in seconds while waiting.",
    )

    tail_job_cmd = tool_subparsers.add_parser(
        "tail-job",
        help="Read the tail of a monitored job's logs.",
        description="Return a small tail from stdout/stderr for an existing monitored job.",
        formatter_class=HELP_FORMATTER,
    )
    tail_job_cmd.add_argument(
        "--run-dir", required=True, type=Path, help="Existing run directory."
    )
    tail_job_cmd.add_argument("--job-id", required=True, help="Tracked job id.")
    tail_job_cmd.add_argument(
        "--lines", type=int, default=20, help="Number of tail lines to return per stream."
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
    summary_cmd.add_argument("--trial-id", required=True, help="Trial id to summarize.")
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
    paths = planned_run_dirs(runs_root() / run_id)
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
    configure_logging(paths.logs)
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
    try:
        outputs = SerialFlowRunner(
            run_dir,
            allow_exec=args.allow_exec,
            mode=mode,
        ).run_until_blocked(limit=limit)
    finally:
        terminated = terminate_all_jobs(run_dir)
        if terminated:
            logger.info("Terminated mylab job monitor jobs on poll-run exit: {}", ", ".join(terminated))
            emit_progress("[jobs]", "terminated", ", ".join(terminated), color="yellow")
    for item in outputs:
        print(f"{item['task_id']} {item['kind']} {item['output']}")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    mode, limit = resolve_flow_control(
        mode=args.mode,
        limit=args.limit,
        prompt_if_missing=True,
    )
    run_name = args.run
    run_dir = resolve_run_dir_by_name(run_name).expanduser().resolve() if run_name else None
    if run_dir and (run_dir / "manifests" / "run.json").exists():
        init_run_dirs(run_dir)
        configure_logging(run_dir / "logs")
        print_codex_preflight(args.model)
        set_current_run(run_dir.name)
        _resume_existing_run_if_idle(run_dir, args.model)
    elif (args.repo or mode == FLOW_MODE_RESIDENT) and (args.goal or args.lab_md):
        repo_path = (args.repo or Path(".")).expanduser().resolve()
        lab_md = args.lab_md.expanduser().resolve() if args.lab_md else None
        goal_text = lab_input_text(args.goal, lab_md)
        run_id = run_name or make_run_id(goal_text)
        paths = planned_run_dirs(runs_root() / run_id)
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
        configure_logging(paths.logs)
        print_codex_preflight(args.model)
        if mode != FLOW_MODE_RESIDENT:
            enqueue_initial_pipeline(paths.root, args.model)
        run_dir = paths.root
        set_current_run(run_id)
        logger.info("Initialized run at {}", run_dir)
    else:
        run_dir = require_selected_run_dir()
        init_run_dirs(run_dir)
        configure_logging(run_dir / "logs")
        print_codex_preflight(args.model)
    try:
        outputs = SerialFlowRunner(
            run_dir,
            allow_exec=True,
            mode=mode,
        ).run_until_blocked(limit=limit)
    finally:
        terminated = terminate_all_jobs(run_dir)
        if terminated:
            logger.info("Terminated mylab job monitor jobs on start exit: {}", ", ".join(terminated))
            emit_progress("[jobs]", "terminated", ", ".join(terminated), color="yellow")
        deleted_trial_id = _cleanup_unfinished_trial(run_dir)
        if deleted_trial_id:
            logger.info("Deleted unfinished trial on start exit: {}", deleted_trial_id)
            emit_progress("[trial]", "deleted unfinished", deleted_trial_id, color="yellow")
    for item in outputs:
        print(f"{item['task_id']} {item['kind']} {item['output']}")
    return 0


def cmd_adapter(args: argparse.Namespace) -> int:
    repo_path = args.repo.expanduser().resolve()
    configure_logging(None)
    print_codex_preflight(args.model)
    goal_text = None
    if args.goal or args.lab_md:
        goal_text = lab_input_text(
            args.goal,
            args.lab_md.expanduser().resolve() if args.lab_md else None,
        )
    print(run_adapter(repo_path, goal_text, args.model))
    return 0


def cmd_run_use(args: argparse.Namespace) -> int:
    run_dir = resolve_run_dir_by_name(args.name)
    if not (run_dir / "manifests" / "run.json").exists():
        raise ValueError(f"run `{args.name}` does not exist")
    set_current_run(args.name)
    print(args.name)
    return 0


def cmd_run_ls(args: argparse.Namespace) -> int:
    current = get_current_run_name()
    for run_dir in list_named_runs():
        marker = "*" if run_dir.name == current else " "
        manifest = load_manifest(run_dir)
        print(
            f"{marker} {run_dir.name}\tstatus={manifest.status}\tlatest_trial={manifest.latest_trial_id or '-'}\trepo={manifest.repo_path}"
        )
    return 0


def cmd_run_rm(args: argparse.Namespace) -> int:
    run_dir = resolve_run_dir_by_name(args.name)
    if not (run_dir / "manifests" / "run.json").exists():
        raise ValueError(f"run `{args.name}` does not exist")
    manifest = load_manifest(run_dir)
    git = GitManager(Path(manifest.repo_path), run_dir / "logs" / "git-lifecycle.jsonl")
    if manifest.work_branch and git.branch_exists(manifest.work_branch):
        if git.current_branch() == manifest.work_branch:
            git.checkout(manifest.original_branch or manifest.source_branch)
        git.delete_branch(manifest.work_branch, force=True)
    shutil.rmtree(run_dir)
    clear_current_run_if_matches(args.name)
    print(args.name)
    return 0


def _resolve_trial_run_dir(run_name: str | None) -> Path:
    if run_name:
        run_dir = resolve_run_dir_by_name(run_name)
        if not (run_dir / "manifests" / "run.json").exists():
            raise ValueError(f"run `{run_name}` does not exist")
        return run_dir
    return require_selected_run_dir()


def cmd_trial_ls(args: argparse.Namespace) -> int:
    run_dir = _resolve_trial_run_dir(getattr(args, "run", None))
    trials_dir = run_dir / "trials"
    for candidate in sorted(trials_dir.iterdir()):
        if candidate.is_dir() and candidate.name.startswith("trial-"):
            print(candidate.name)
    return 0


def cmd_trial_cat(args: argparse.Namespace) -> int:
    run_dir = _resolve_trial_run_dir(getattr(args, "run", None))
    paths = trial_paths(run_dir, args.trial_id)
    if not paths.trial.exists():
        raise ValueError(f"trial `{args.trial_id}` does not exist in run `{run_dir.name}`")
    print(paths.trial.read_text(encoding="utf-8"))
    return 0


def cmd_trial_rm(args: argparse.Namespace) -> int:
    run_dir = _resolve_trial_run_dir(getattr(args, "run", None))
    _remove_trial(run_dir, args.trial_id)
    print(args.trial_id)
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
    paths = planned_run_dirs(runs_root() / run_id)
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


def cmd_create_trial(args: argparse.Namespace) -> int:
    paths, manifest = ensure_manifest_or_bootstrap(args)
    configure_logging(paths.logs)
    print(create_initial_trial(paths, manifest))
    return 0


def cmd_iterate_trial(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.expanduser().resolve()
    paths = init_run_dirs(run_dir)
    configure_logging(paths.logs)
    manifest = load_manifest(run_dir)
    print(create_iterated_trial(paths, manifest, args.parent_trial, args.feedback))
    return 0


def cmd_queue_iteration(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.expanduser().resolve()
    configure_logging(run_dir / "logs")
    enqueue_iteration_pipeline(run_dir, args.parent_trial, args.feedback, args.model)
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
    trial_id = args.trial_id or manifest.latest_trial_id
    if not trial_id:
        raise ValueError("missing trial id and manifest.latest_trial_id is empty")
    print(prepare_executor(run_dir, trial_id, args.model))
    return 0


def cmd_run_executor(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.expanduser().resolve()
    configure_logging(run_dir / "logs")
    print_codex_preflight(args.model)
    manifest = load_manifest(run_dir)
    trial_id = args.trial_id or manifest.latest_trial_id
    if not trial_id:
        raise ValueError("missing trial id and manifest.latest_trial_id is empty")
    try:
        print(run_executor(run_dir, trial_id, args.model, args.full_auto))
    finally:
        terminated = terminate_all_jobs(run_dir)
        if terminated:
            logger.info("Terminated mylab job monitor jobs on run-executor exit: {}", ", ".join(terminated))
            emit_progress("[jobs]", "terminated", ", ".join(terminated), color="yellow")
        manifest = load_manifest(run_dir)
        if manifest.work_branch and manifest.original_branch:
            restore_original_branch(run_dir, manifest)
    return 0


def cmd_start_job(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.expanduser().resolve()
    configure_logging(run_dir / "logs")
    job_command = getattr(args, "job_command", None)
    if job_command is None:
        # Backward-compatible fallback for older programmatic callers that
        # constructed Namespace(command=...) to bypass the CLI parser bug.
        job_command = getattr(args, "command", None)
    if not job_command:
        raise RuntimeError("missing job command")
    print(
        json.dumps(
            start_job(
                run_dir,
                args.trial_id,
                job_command,
                name=args.name,
                cwd=args.cwd,
            ),
            ensure_ascii=True,
        )
    )
    return 0


def cmd_wait_job(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.expanduser().resolve()
    configure_logging(run_dir / "logs")
    kwargs: dict[str, int | bool] = {"use_timer": bool(args.enable_timer)}
    if args.wait_seconds is not None:
        kwargs["wait_seconds"] = args.wait_seconds
    if args.poll_seconds is not None:
        kwargs["poll_seconds"] = args.poll_seconds
    print(json.dumps(wait_for_job(run_dir, args.job_id, **kwargs), ensure_ascii=True))
    return 0


def cmd_tail_job(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.expanduser().resolve()
    configure_logging(run_dir / "logs")
    print(
        json.dumps(
            tail_job(run_dir, args.job_id, lines=args.lines),
            ensure_ascii=True,
        )
    )
    return 0


def restore_branch_after_interrupt(run_dir: Path) -> None:
    try:
        terminated = terminate_all_jobs(run_dir)
        if terminated:
            logger.info("Terminated mylab job monitor jobs after Ctrl+C: {}", ", ".join(terminated))
            emit_progress(
                "[jobs]",
                "terminated",
                ", ".join(terminated),
                color="yellow",
            )
    except Exception:
        logger.exception("Failed to terminate mylab job monitor jobs after Ctrl+C")
    try:
        manifest = load_manifest(run_dir)
    except Exception:
        return
    if manifest.work_branch and manifest.original_branch:
        try:
            restore_original_branch(run_dir, manifest)
        except Exception:
            logger.exception("Failed to restore branch after Ctrl+C")
    try:
        deleted_trial_id = _cleanup_unfinished_trial(run_dir)
        if deleted_trial_id:
            logger.info("Deleted unfinished trial after Ctrl+C: {}", deleted_trial_id)
    except Exception:
        logger.exception("Failed to delete unfinished trial after Ctrl+C")


def cmd_write_summary(args: argparse.Namespace) -> int:
    configure_logging(args.run_dir.expanduser().resolve() / "logs")
    print(
        write_summary(
            args.run_dir.expanduser().resolve(),
            args.trial_id,
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
    path = interactive_telegram_setup(config_path=args.config_path)
    print(path)
    return 0


def cmd_bot_feishu(args: argparse.Namespace) -> int:
    path = interactive_feishu_setup(config_path=args.config_path)
    print(path)
    return 0


def cmd_bot_test(args: argparse.Namespace) -> int:
    config_path = args.config_path or None
    ok = True
    tested = 0

    telegram_settings = load_telegram_settings(config_path)
    if telegram_settings.enabled:
        tested += 1
        try:
            me = TelegramBotClient(telegram_settings).get_me()
            print(
                "telegram bot ok "
                f"id={me.get('id', '-')} username={me.get('username', '-')}"
            )
        except Exception as exc:
            emit_progress("[error]", f"telegram bot test failed: {exc}", color="red")
            ok = False
    else:
        print("telegram bot not configured")

    feishu_settings = load_feishu_settings(config_path)
    if feishu_settings.enabled:
        tested += 1
        try:
            if send_feishu_test_message(
                feishu_settings,
                message="This is a test notification from mylab bot test.",
            ):
                print("feishu bot ok")
            else:
                emit_progress(
                    "[error]",
                    "feishu bot test failed; check webhook url or app credentials",
                    color="red",
                )
                ok = False
        except Exception as exc:
            emit_progress("[error]", f"feishu bot test failed: {exc}", color="red")
            ok = False
    else:
        print("feishu bot not configured")

    notification_settings = resolve_notification_settings(config_path)
    if notification_settings.enabled:
        tested += 1
        if not telegram_notifications_enabled():
            emit_progress(
                "[error]",
                "notifications are currently paused by Telegram command /off",
                color="red",
            )
            ok = False
        else:
            with tempfile.TemporaryDirectory(prefix="mylab-bot-test-") as temp_dir:
                run_dir = Path(temp_dir) / "run"
                init_run_dirs(run_dir)
                notifier = NotificationClient(run_dir, notification_settings)
                sent = notifier.notify(
                    "mylab bot test",
                    "This is a test notification from mylab bot test.",
                    notify_type="info",
                )
                if sent:
                    print("notification endpoints ok")
                else:
                    emit_progress(
                        "[error]",
                        "notification test failed; check bot token, chat id, and apprise setup",
                        color="red",
                    )
                    ok = False
    else:
        print("notification endpoints not configured")

    if tested == 0:
        raise RuntimeError("no bot integrations are configured")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    interrupt_run_dir: Path | None = None
    commands = {
        "adapter": cmd_adapter,
        "start": cmd_start,
        "queue-iteration": cmd_queue_iteration,
    }
    tool_commands = {
        "init-run": cmd_init_run,
        "poll-run": cmd_poll_run,
        "create-trial": cmd_create_trial,
        "iterate-trial": cmd_iterate_trial,
        "format-repo": cmd_format_repo,
        "init-config": cmd_init_config,
        "prepare-executor": cmd_prepare_executor,
        "run-executor": cmd_run_executor,
        "start-job": cmd_start_job,
        "wait-job": cmd_wait_job,
        "tail-job": cmd_tail_job,
        "telegram-bot": cmd_telegram_bot,
        "write-summary": cmd_write_summary,
    }
    try:
        if getattr(args, "run_dir", None):
            interrupt_run_dir = args.run_dir.expanduser().resolve()
        if getattr(args, "run", None):
            candidate = resolve_run_dir_by_name(args.run)
            if (candidate / "manifests" / "run.json").exists():
                interrupt_run_dir = candidate
        if args.command == "tool":
            if args.tool_command in {"run-executor", "poll-run", "prepare-executor", "write-summary", "iterate-trial", "start-job", "wait-job", "tail-job"}:
                interrupt_run_dir = args.run_dir.expanduser().resolve()
            return tool_commands[args.tool_command](args)
        if args.command == "run":
            run_commands = {
                "use": cmd_run_use,
                "ls": cmd_run_ls,
                "rm": cmd_run_rm,
            }
            return run_commands[args.run_command](args)
        if args.command == "trial":
            trial_commands = {
                "ls": cmd_trial_ls,
                "cat": cmd_trial_cat,
                "rm": cmd_trial_rm,
            }
            return trial_commands[args.trial_command](args)
        if args.command == "bot":
            if args.bot_command == "test":
                return cmd_bot_test(args)
            if args.bot_command == "telegram":
                return cmd_bot_telegram(args)
            if args.bot_command == "feishu":
                return cmd_bot_feishu(args)
            raise RuntimeError(f"unsupported bot command: {args.bot_command}")
        return commands[args.command](args)
    except KeyboardInterrupt:
        if interrupt_run_dir is not None:
            restore_branch_after_interrupt(interrupt_run_dir)
        emit_progress("[interrupt]", "received Ctrl+C", "exiting gracefully", color="yellow")
        return 130
    except (RuntimeError, ValueError) as exc:
        emit_progress("[error]", str(exc), color="red")
        return 1
