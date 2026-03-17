from __future__ import annotations

from pathlib import Path

from mylab.domain import RunManifest
from mylab.gittools import GitManager
from mylab.logging import logger
from mylab.services.repo_ignore import ensure_run_dir_ignored
from mylab.storage import append_jsonl
from mylab.storage.runs import init_run_dirs, save_manifest
from mylab.utils import (
    detect_git_branch,
    has_commits,
    slugify,
    utc_now,
    working_tree_is_clean,
)


def prepare_repo_for_run(
    repo_path: Path, run_dir: Path, log_path: Path
) -> tuple[str, str]:
    repo_path = repo_path.resolve()
    git = GitManager(repo_path, log_path)
    if not has_commits(repo_path):
        raise RuntimeError(
            "repository has no commits; commit the current branch before running mylab"
        )
    if not working_tree_is_clean(repo_path):
        raise RuntimeError(
            "repository has uncommitted changes; commit or stash them before running mylab"
        )

    original_branch = detect_git_branch(repo_path)
    original_head = git.head_commit()
    ignored_added, ignored_entry = ensure_run_dir_ignored(repo_path, run_dir)
    if ignored_added:
        logger.info("Committing gitignore update for {}", ignored_entry)
        git.add(".gitignore")
        committed_head = git.commit("chore: ignore mylab run artifacts")
        append_jsonl(
            log_path,
            {
                "ts": utc_now(),
                "event": "run_gitignore_committed",
                "original_branch": original_branch,
                "ignored_entry": ignored_entry,
                "head_commit_before": original_head,
                "head_commit_after": committed_head,
            },
        )
        original_head = committed_head
    append_jsonl(
        log_path,
        {
            "ts": utc_now(),
            "event": "repo_preflight_passed",
            "original_branch": original_branch,
            "original_head_commit": original_head,
            "ignored_entry": ignored_entry,
        },
    )
    return original_branch, original_head


def ensure_run_branch(run_dir: Path, manifest: RunManifest, plan_id: str) -> str:
    paths = init_run_dirs(run_dir)
    git = GitManager(Path(manifest.repo_path), paths.logs / "git-lifecycle.jsonl")
    current = git.current_branch()
    if not manifest.original_branch:
        manifest.original_branch = current
    work_branch = (
        manifest.work_branch
        or f"mylab/{slugify(manifest.run_id, max_length=24)}/{plan_id}"
    )
    logger.info("Preparing work branch {} for plan {}", work_branch, plan_id)
    if manifest.work_branch and git.branch_exists(work_branch):
        git.checkout(work_branch)
    else:
        git.create_and_checkout_branch(work_branch, manifest.source_branch)
    manifest.work_branch = work_branch
    manifest.latest_work_commit = git.head_commit()
    save_manifest(paths, manifest)
    append_jsonl(
        paths.logs / "git-lifecycle.jsonl",
        {
            "ts": utc_now(),
            "event": "run_branch_prepared",
            "plan_id": plan_id,
            "source_branch": manifest.source_branch,
            "work_branch": work_branch,
            "returned_from": current,
        },
    )
    return work_branch


def commit_iteration_changes(run_dir: Path, manifest: RunManifest, plan_id: str) -> Path:
    paths = init_run_dirs(run_dir)
    git = GitManager(Path(manifest.repo_path), paths.logs / "git-lifecycle.jsonl")
    branch = manifest.work_branch or git.current_branch()
    if git.current_branch() != branch:
        git.checkout(branch)
    status = git.status_porcelain().strip()
    committed = False
    if status:
        git.add("-A")
        head_commit = git.commit(f"mylab: deliver {plan_id}")
        committed = True
    else:
        head_commit = git.head_commit()
    manifest.work_branch = branch
    manifest.latest_work_commit = head_commit
    save_manifest(paths, manifest)
    report_path = paths.results / f"{plan_id}.git.md"
    report_path.write_text(
        "\n".join(
            [
                "# Git Delivery",
                f"- plan_id: {plan_id}",
                f"- work_branch: {branch}",
                f"- head_commit: {head_commit}",
                f"- committed_new_changes: {'yes' if committed else 'no'}",
                "",
                "## Git Status Before Commit",
                status or "(clean)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    append_jsonl(
        paths.logs / "git-lifecycle.jsonl",
        {
            "ts": utc_now(),
            "event": "iteration_git_delivered",
            "plan_id": plan_id,
            "work_branch": branch,
            "head_commit": head_commit,
            "committed_new_changes": committed,
        },
    )
    return report_path


def restore_original_branch(run_dir: Path, manifest: RunManifest) -> str:
    paths = init_run_dirs(run_dir)
    git = GitManager(Path(manifest.repo_path), paths.logs / "git-lifecycle.jsonl")
    target = manifest.original_branch or manifest.source_branch
    current = git.current_branch()
    if current != target:
        logger.info("Restoring original branch {}", target)
        git.checkout(target)
    append_jsonl(
        paths.logs / "git-lifecycle.jsonl",
        {
            "ts": utc_now(),
            "event": "original_branch_restored",
            "target_branch": target,
            "restored_from": current,
            "saved_work_branch": manifest.work_branch,
        },
    )
    return target
