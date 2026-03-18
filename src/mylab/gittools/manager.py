from __future__ import annotations

import subprocess
from pathlib import Path

from mylab.logging import logger
from mylab.storage import append_jsonl
from mylab.utils import utc_now


class GitManager:
    def __init__(self, repo_path: Path, log_path: Path) -> None:
        self.repo_path = repo_path
        self.log_path = log_path

    def _run(self, args: list[str]) -> str:
        logger.debug("Running git command in {}: {}", self.repo_path, " ".join(args))
        result = subprocess.run(
            ["git", "-C", str(self.repo_path), *args],
            check=True,
            capture_output=True,
            text=True,
        )
        append_jsonl(
            self.log_path,
            {
                "ts": utc_now(),
                "event": "git_command",
                "args": args,
                "stdout": result.stdout.strip(),
            },
        )
        return result.stdout.strip()

    def current_branch(self) -> str:
        return self._run(["rev-parse", "--abbrev-ref", "HEAD"])

    def head_commit(self) -> str:
        return self._run(["rev-parse", "HEAD"])

    def checkout(self, branch: str) -> None:
        logger.info("Checking out git branch {}", branch)
        self._run(["checkout", branch])

    def branch_exists(self, branch: str) -> bool:
        result = subprocess.run(
            ["git", "-C", str(self.repo_path), "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    def delete_branch(self, branch: str, *, force: bool = True) -> None:
        flag = "-D" if force else "-d"
        logger.info("Deleting git branch {}", branch)
        self._run(["branch", flag, branch])

    def add(self, *paths: str) -> None:
        if not paths:
            return
        self._run(["add", *paths])

    def commit(self, message: str) -> str:
        logger.info("Creating git commit in {}", self.repo_path)
        self._run(["commit", "-m", message])
        return self.head_commit()

    def create_and_checkout_branch(self, branch: str, source_branch: str) -> None:
        logger.info("Creating work branch {} from {}", branch, source_branch)
        self._run(["checkout", source_branch])
        self._run(["checkout", "-B", branch, source_branch])

    def status_porcelain(self) -> str:
        return self._run(["status", "--short"])
