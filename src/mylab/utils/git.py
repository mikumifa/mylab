from __future__ import annotations

import subprocess
from pathlib import Path


def detect_git_branch(repo_path: Path) -> str:
    cmd = ["git", "-C", str(repo_path), "rev-parse", "--abbrev-ref", "HEAD"]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def has_commits(repo_path: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "--verify", "HEAD"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def working_tree_is_clean(repo_path: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo_path), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    )
    return not result.stdout.strip()


def branch_exists(repo_path: Path, branch: str) -> bool:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_path),
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{branch}",
        ],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def detect_source_branch(repo_path: Path) -> str:
    current = detect_git_branch(repo_path)
    if not current.startswith("mylab/"):
        return current
    for candidate in ("main", "master"):
        if branch_exists(repo_path, candidate):
            return candidate
    return current


def list_tracked_files(repo_path: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo_path), "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()
