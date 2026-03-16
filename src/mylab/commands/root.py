from __future__ import annotations

import argparse
from pathlib import Path

from mylab.flow import SerialFlowRunner
from mylab.orchestrator import enqueue_initial_pipeline, enqueue_iteration_pipeline
from mylab.services import (
    bootstrap_run,
    create_initial_plan,
    create_iterated_plan,
    format_repo_report,
    make_run_id,
    prepare_executor,
    run_executor,
    write_summary,
)
from mylab.services.plans import lab_input_text
from mylab.storage import init_run_dirs, runs_root
from mylab.storage.runs import load_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mylab",
        description="Codex-based experiment orchestration CLI for research repositories.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_run_cmd = subparsers.add_parser("init-run", help="Bootstrap a run and enqueue the initial pipeline.")
    init_run_cmd.add_argument("--repo", required=True, type=Path)
    init_run_group = init_run_cmd.add_mutually_exclusive_group(required=True)
    init_run_group.add_argument("--goal")
    init_run_group.add_argument("--lab-md", type=Path)
    init_run_cmd.add_argument("--source-branch")
    init_run_cmd.add_argument("--run-id")
    init_run_cmd.add_argument("--model", default="gpt-5-mini")

    poll_cmd = subparsers.add_parser("poll-run", help="Advance queued tasks for a run.")
    poll_cmd.add_argument("--run-dir", required=True, type=Path)
    poll_cmd.add_argument("--limit", type=int, default=3)
    poll_cmd.add_argument("--allow-exec", action="store_true")

    flow_cmd = subparsers.add_parser("run-flow", help="Run the serial main flow until blocked or complete.")
    flow_cmd.add_argument("--run-dir", required=True, type=Path)
    flow_cmd.add_argument("--limit", type=int, default=20)
    flow_cmd.add_argument("--allow-exec", action="store_true")

    create_cmd = subparsers.add_parser("create-plan", help="Create the first structured plan.")
    create_cmd.add_argument("--run-dir", type=Path)
    create_cmd.add_argument("--repo", type=Path)
    create_group = create_cmd.add_mutually_exclusive_group(required=False)
    create_group.add_argument("--goal")
    create_group.add_argument("--lab-md", type=Path)
    create_cmd.add_argument("--source-branch")
    create_cmd.add_argument("--run-id")

    iterate_cmd = subparsers.add_parser("iterate-plan", help="Create the next plan from prior results.")
    iterate_cmd.add_argument("--run-dir", required=True, type=Path)
    iterate_cmd.add_argument("--feedback", required=True)
    iterate_cmd.add_argument("--parent-plan", required=True)

    queue_iter_cmd = subparsers.add_parser("queue-iteration", help="Enqueue a plan iteration pipeline.")
    queue_iter_cmd.add_argument("--run-dir", required=True, type=Path)
    queue_iter_cmd.add_argument("--parent-plan", required=True)
    queue_iter_cmd.add_argument("--feedback", required=True)
    queue_iter_cmd.add_argument("--model", default="gpt-5-mini")

    format_cmd = subparsers.add_parser("format-repo", help="Emit a repo formatting audit.")
    format_cmd.add_argument("--repo", type=Path)
    format_cmd.add_argument("--run-dir", type=Path)

    prepare_cmd = subparsers.add_parser("prepare-executor", help="Generate executor prompts and commands.")
    prepare_cmd.add_argument("--run-dir", required=True, type=Path)
    prepare_cmd.add_argument("--plan-id")
    prepare_cmd.add_argument("--model", default="gpt-5-mini")

    run_cmd = subparsers.add_parser("run-executor", help="Run the prepared executor agent via codex.")
    run_cmd.add_argument("--run-dir", required=True, type=Path)
    run_cmd.add_argument("--plan-id")
    run_cmd.add_argument("--model", default="gpt-5-mini")
    run_cmd.add_argument("--full-auto", action="store_true")

    summary_cmd = subparsers.add_parser("write-summary", help="Write a strict summary file.")
    summary_cmd.add_argument("--run-dir", required=True, type=Path)
    summary_cmd.add_argument("--plan-id", required=True)
    summary_cmd.add_argument("--status", required=True)
    summary_cmd.add_argument("--outcome", required=True)
    summary_cmd.add_argument("--evidence", nargs="+", required=True)
    summary_cmd.add_argument("--artifacts", nargs="+", required=True)
    summary_cmd.add_argument("--next-iteration", nargs="+", required=True)
    return parser


def cmd_init_run(args: argparse.Namespace) -> int:
    repo_path = args.repo.expanduser().resolve()
    lab_md = args.lab_md.expanduser().resolve() if args.lab_md else None
    goal_text = lab_input_text(args.goal, lab_md)
    run_id = args.run_id or make_run_id(goal_text)
    paths = init_run_dirs(runs_root() / run_id)
    input_name = "lab.md" if args.lab_md else "goal.txt"
    bootstrap_run(
        repo_path=repo_path,
        goal_text=goal_text if args.goal else lab_md.read_text(encoding="utf-8"),
        run_id=run_id,
        paths=paths,
        source_branch=args.source_branch,
        input_file_name=input_name,
    )
    enqueue_initial_pipeline(paths.root, args.model)
    print(paths.root)
    return 0


def cmd_poll_run(args: argparse.Namespace) -> int:
    outputs = SerialFlowRunner(args.run_dir.expanduser().resolve(), allow_exec=args.allow_exec).run_until_blocked(
        limit=args.limit
    )
    for item in outputs:
        print(f"{item['task_id']} {item['kind']} {item['output']}")
    return 0


def cmd_run_flow(args: argparse.Namespace) -> int:
    outputs = SerialFlowRunner(args.run_dir.expanduser().resolve(), allow_exec=args.allow_exec).run_until_blocked(
        limit=args.limit
    )
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
        raise ValueError("either --run-dir or (--repo and one of --goal/--lab-md) is required")
    repo_path = args.repo.expanduser().resolve()
    lab_md = args.lab_md.expanduser().resolve() if args.lab_md else None
    goal_text = lab_input_text(args.goal, lab_md)
    run_id = args.run_id or make_run_id(goal_text)
    paths = init_run_dirs(runs_root() / run_id)
    manifest = bootstrap_run(
        repo_path=repo_path,
        goal_text=goal_text if args.goal else lab_md.read_text(encoding="utf-8"),
        run_id=run_id,
        paths=paths,
        source_branch=args.source_branch,
        input_file_name="lab.md" if args.lab_md else "goal.txt",
    )
    return paths, manifest


def cmd_create_plan(args: argparse.Namespace) -> int:
    paths, manifest = ensure_manifest_or_bootstrap(args)
    print(create_initial_plan(paths, manifest))
    return 0


def cmd_iterate_plan(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.expanduser().resolve()
    paths = init_run_dirs(run_dir)
    manifest = load_manifest(run_dir)
    print(create_iterated_plan(paths, manifest, args.parent_plan, args.feedback))
    return 0


def cmd_queue_iteration(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.expanduser().resolve()
    enqueue_iteration_pipeline(run_dir, args.parent_plan, args.feedback, args.model)
    print(run_dir / "queue" / "pipeline.json")
    return 0


def cmd_format_repo(args: argparse.Namespace) -> int:
    if args.run_dir:
        run_dir = args.run_dir.expanduser().resolve()
        manifest = load_manifest(run_dir)
        print(format_repo_report(Path(manifest.repo_path), run_dir))
        return 0
    if not args.repo:
        raise ValueError("--repo is required when --run-dir is omitted")
    run_dir = runs_root() / f"format_{args.repo.expanduser().resolve().name}"
    paths = init_run_dirs(run_dir)
    print(format_repo_report(args.repo.expanduser().resolve(), paths.root))
    return 0


def cmd_prepare_executor(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.expanduser().resolve()
    manifest = load_manifest(run_dir)
    plan_id = args.plan_id or manifest.latest_plan_id
    if not plan_id:
        raise ValueError("missing plan id and manifest.latest_plan_id is empty")
    print(prepare_executor(run_dir, plan_id, args.model))
    return 0


def cmd_run_executor(args: argparse.Namespace) -> int:
    run_dir = args.run_dir.expanduser().resolve()
    manifest = load_manifest(run_dir)
    plan_id = args.plan_id or manifest.latest_plan_id
    if not plan_id:
        raise ValueError("missing plan id and manifest.latest_plan_id is empty")
    print(run_executor(run_dir, plan_id, args.model, args.full_auto))
    return 0


def cmd_write_summary(args: argparse.Namespace) -> int:
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    commands = {
        "init-run": cmd_init_run,
        "poll-run": cmd_poll_run,
        "run-flow": cmd_run_flow,
        "create-plan": cmd_create_plan,
        "iterate-plan": cmd_iterate_plan,
        "queue-iteration": cmd_queue_iteration,
        "format-repo": cmd_format_repo,
        "prepare-executor": cmd_prepare_executor,
        "run-executor": cmd_run_executor,
        "write-summary": cmd_write_summary,
    }
    return commands[args.command](args)
