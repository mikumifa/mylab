from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mylab.services.plans import bootstrap_run
from mylab.storage.runs import init_run_dirs


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


class GitPreflightTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="mylab-git-preflight-")
        self.repo = Path(self.temp_dir.name) / "repo"
        self.repo.mkdir()
        run_git(self.repo, "init", "-b", "main")
        run_git(self.repo, "config", "user.name", "mylab-test")
        run_git(self.repo, "config", "user.email", "mylab@example.com")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_bootstrap_requires_existing_commit(self) -> None:
        paths = init_run_dirs(self.repo / ".mylab_runs" / "run-001")
        with self.assertRaisesRegex(RuntimeError, "no commits"):
            bootstrap_run(
                repo_path=self.repo,
                goal_text="goal",
                run_id="run-001",
                paths=paths,
                source_branch="main",
            )

    def test_bootstrap_requires_clean_worktree(self) -> None:
        (self.repo / "README.md").write_text("base\n", encoding="utf-8")
        run_git(self.repo, "add", "README.md")
        run_git(self.repo, "commit", "-m", "init")
        (self.repo / "README.md").write_text("dirty\n", encoding="utf-8")

        paths = init_run_dirs(self.repo / ".mylab_runs" / "run-002")
        with self.assertRaisesRegex(RuntimeError, "uncommitted changes"):
            bootstrap_run(
                repo_path=self.repo,
                goal_text="goal",
                run_id="run-002",
                paths=paths,
                source_branch="main",
            )

    def test_bootstrap_commits_gitignore_entry_and_records_branch(self) -> None:
        (self.repo / "README.md").write_text("base\n", encoding="utf-8")
        run_git(self.repo, "add", "README.md")
        run_git(self.repo, "commit", "-m", "init")
        head_before = run_git(self.repo, "rev-parse", "HEAD").stdout.strip()

        paths = init_run_dirs(self.repo / ".mylab_runs" / "run-003")
        manifest = bootstrap_run(
            repo_path=self.repo,
            goal_text="goal",
            run_id="run-003",
            paths=paths,
            source_branch="main",
        )

        gitignore = (self.repo / ".gitignore").read_text(encoding="utf-8")
        head_after = run_git(self.repo, "rev-parse", "HEAD").stdout.strip()
        commit_subject = run_git(self.repo, "log", "-1", "--pretty=%s").stdout.strip()

        self.assertIn("/.mylab_runs/", gitignore)
        self.assertNotEqual(head_before, head_after)
        self.assertEqual(commit_subject, "chore: ignore mylab run artifacts")
        self.assertEqual(manifest.original_branch, "main")
        self.assertEqual(manifest.original_head_commit, head_after)


if __name__ == "__main__":
    unittest.main()
