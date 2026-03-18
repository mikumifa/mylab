from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mylab.services.git_lifecycle import commit_iteration_changes, ensure_run_branch
from mylab.services.plans import bootstrap_run
from mylab.storage.runs import init_run_dirs, load_manifest, planned_run_dirs


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

    def test_bootstrap_does_not_create_run_dir_before_preflight(self) -> None:
        (self.repo / "README.md").write_text("base\n", encoding="utf-8")
        run_git(self.repo, "add", "README.md")
        run_git(self.repo, "commit", "-m", "init")
        (self.repo / "README.md").write_text("dirty\n", encoding="utf-8")

        run_root = self.repo / ".mylab_runs" / "run-004"
        with self.assertRaisesRegex(RuntimeError, "uncommitted changes"):
            bootstrap_run(
                repo_path=self.repo,
                goal_text="goal",
                run_id="run-004",
                paths=planned_run_dirs(run_root),
                source_branch="main",
            )

        self.assertFalse(run_root.exists())

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
        skill_path = self.repo / ".codex" / "skills" / "mylab-job-monitor" / "SKILL.md"
        structure_skill_path = (
            self.repo / ".codex" / "skills" / "mylab-structure-tuning" / "SKILL.md"
        )
        structure_template_path = (
            self.repo
            / ".codex"
            / "skills"
            / "mylab-structure-tuning"
            / "templates"
            / "plan.template.md"
        )
        parameter_skill_path = (
            self.repo / ".codex" / "skills" / "mylab-parameter-tuning" / "SKILL.md"
        )
        parameter_template_path = (
            self.repo
            / ".codex"
            / "skills"
            / "mylab-parameter-tuning"
            / "templates"
            / "plan.template.md"
        )
        reference_path = (
            self.repo
            / ".codex"
            / "skills"
            / "mylab-job-monitor"
            / "references"
            / "complete-example.md"
        )
        head_after = run_git(self.repo, "rev-parse", "HEAD").stdout.strip()
        commit_subject = run_git(self.repo, "log", "-1", "--pretty=%s").stdout.strip()

        self.assertIn("/.mylab_runs/", gitignore)
        self.assertTrue(skill_path.exists())
        self.assertTrue(structure_skill_path.exists())
        self.assertTrue(structure_template_path.exists())
        self.assertTrue(parameter_skill_path.exists())
        self.assertTrue(parameter_template_path.exists())
        self.assertTrue(reference_path.exists())
        self.assertIn("mylab tool start-job", skill_path.read_text(encoding="utf-8"))
        self.assertIn("## Frontmatter Essence", structure_skill_path.read_text(encoding="utf-8"))
        self.assertIn("## Frontmatter Essence", parameter_skill_path.read_text(encoding="utf-8"))
        self.assertNotEqual(head_before, head_after)
        self.assertEqual(commit_subject, "chore: bootstrap mylab repo assets")
        self.assertEqual(manifest.original_branch, "main")
        self.assertEqual(manifest.original_head_commit, head_after)

    def test_iteration_commit_writes_delivery_report(self) -> None:
        (self.repo / "README.md").write_text("base\n", encoding="utf-8")
        run_git(self.repo, "add", "README.md")
        run_git(self.repo, "commit", "-m", "init")

        paths = init_run_dirs(self.repo / ".mylab_runs" / "run-005")
        manifest = bootstrap_run(
            repo_path=self.repo,
            goal_text="用中文复现实验",
            run_id="run-005",
            paths=paths,
            source_branch="main",
        )
        ensure_run_branch(paths.root, manifest, "plan-001")
        (self.repo / "experiment.txt").write_text("iteration 1\n", encoding="utf-8")

        report_path = commit_iteration_changes(paths.root, manifest, "plan-001")

        commit_subject = run_git(self.repo, "log", "-1", "--pretty=%s").stdout.strip()
        saved_manifest = load_manifest(paths.root)
        self.assertEqual(commit_subject, "mylab: deliver plan-001")
        self.assertEqual(saved_manifest.work_branch, "mylab/run-005/plan-001")
        self.assertTrue(saved_manifest.latest_work_commit)
        self.assertTrue(report_path.exists())
        report = report_path.read_text(encoding="utf-8")
        self.assertIn("- work_branch: mylab/run-005/plan-001", report)
        self.assertIn("- committed_new_changes: yes", report)

    def test_existing_work_branch_is_reused_instead_of_reset(self) -> None:
        (self.repo / "README.md").write_text("base\n", encoding="utf-8")
        run_git(self.repo, "add", "README.md")
        run_git(self.repo, "commit", "-m", "init")

        paths = init_run_dirs(self.repo / ".mylab_runs" / "run-006")
        manifest = bootstrap_run(
            repo_path=self.repo,
            goal_text="goal",
            run_id="run-006",
            paths=paths,
            source_branch="main",
        )
        ensure_run_branch(paths.root, manifest, "plan-001")
        (self.repo / "kept.txt").write_text("keep me\n", encoding="utf-8")
        commit_iteration_changes(paths.root, manifest, "plan-001")
        first_commit = load_manifest(paths.root).latest_work_commit

        run_git(self.repo, "checkout", "main")
        manifest = load_manifest(paths.root)
        branch = ensure_run_branch(paths.root, manifest, "plan-002")
        current_head = run_git(self.repo, "rev-parse", "HEAD").stdout.strip()

        self.assertEqual(branch, "mylab/run-006/plan-001")
        self.assertEqual(current_head, first_commit)
        self.assertTrue((self.repo / "kept.txt").exists())


if __name__ == "__main__":
    unittest.main()
