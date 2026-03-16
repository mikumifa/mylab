from __future__ import annotations

import subprocess
from pathlib import Path


def detect_git_branch(repo_path: Path) -> str:
    cmd = ["git", "-C", str(repo_path), "rev-parse", "--abbrev-ref", "HEAD"]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def list_tracked_files(repo_path: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo_path), "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()
