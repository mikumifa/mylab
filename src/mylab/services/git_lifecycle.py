from __future__ import annotations

from pathlib import Path

from mylab.domain import RunManifest
from mylab.gittools import GitManager
from mylab.storage import append_jsonl
from mylab.storage.runs import init_run_dirs, save_manifest
from mylab.utils import slugify, utc_now


def ensure_run_branch(run_dir: Path, manifest: RunManifest, plan_id: str) -> str:
    paths = init_run_dirs(run_dir)
    git = GitManager(Path(manifest.repo_path), paths.logs / "git-lifecycle.jsonl")
    current = git.current_branch()
    if not manifest.original_branch:
        manifest.original_branch = current
    work_branch = manifest.work_branch or f"mylab/{slugify(manifest.run_id, max_length=24)}/{plan_id}"
    git.create_and_checkout_branch(work_branch, manifest.source_branch)
    manifest.work_branch = work_branch
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


def restore_original_branch(run_dir: Path, manifest: RunManifest) -> str:
    paths = init_run_dirs(run_dir)
    git = GitManager(Path(manifest.repo_path), paths.logs / "git-lifecycle.jsonl")
    target = manifest.original_branch or manifest.source_branch
    git.checkout(target)
    append_jsonl(
        paths.logs / "git-lifecycle.jsonl",
        {
            "ts": utc_now(),
            "event": "original_branch_restored",
            "target_branch": target,
            "saved_work_branch": manifest.work_branch,
        },
    )
    return target
