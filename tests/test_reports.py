from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mylab.domain import RunManifest
from mylab.services.reports import write_summary
from mylab.storage.plan_layout import plan_paths
from mylab.storage.runs import init_run_dirs, load_manifest, save_manifest


class ReportsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="mylab-reports-")
        self.root = Path(self.temp_dir.name)
        self.paths = init_run_dirs(self.root / "run")
        save_manifest(
            self.paths,
            RunManifest(
                run_id="run-001",
                repo_path=str(self.root / "repo"),
                source_branch="main",
                goal_file=str(self.paths.inputs / "goal.txt"),
                runs_env_var="MYLAB_RUNS_DIR",
            ),
        )
        (self.paths.inputs / "goal.txt").write_text(
            "reproduce the user's requested main experiment and report the conclusion\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_write_summary_uses_structured_result_report(self) -> None:
        scoped_paths = plan_paths(self.paths.root, "plan-001", ensure=True)
        scoped_paths.result.write_text(
            "\n".join(
                [
                    "# Outcome",
                    "Validation accuracy reached 91.2% after fixing the output root wiring.",
                    "",
                    "# Evidence",
                    "1. results/metrics.json",
                    "2. logs/train.stdout.log",
                    "",
                    "# Artifacts",
                    "1. plans/plan-001/executor.sh",
                    "2. plans/plan-001/result.md",
                    "",
                    "# Next Iteration",
                    "1. Compare against the lighter baseline.",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        summary_path = write_summary(
            self.paths.root,
            "plan-001",
            "completed",
            "Execution finished. Replace this placeholder with an evidence-based summary.",
            [f"plans/plan-001/codex.events.jsonl"],
            [f"plans/plan-001/executor.sh"],
            ["Inspect the result report and replace this placeholder summary."],
        )

        content = summary_path.read_text(encoding="utf-8")
        self.assertIn("Validation accuracy reached 91.2%", content)
        self.assertIn("results/metrics.json", content)
        self.assertIn("Compare against the lighter baseline.", content)
        self.assertNotIn("Replace this placeholder", content)

    def test_write_summary_falls_back_to_codex_last_message(self) -> None:
        scoped_paths = plan_paths(self.paths.root, "plan-002", ensure=True)
        scoped_paths.codex_last.write_text(
            "Implemented configurable output root and preserved stdout under the run directory.\n",
            encoding="utf-8",
        )

        summary_path = write_summary(
            self.paths.root,
            "plan-002",
            "completed",
            "Execution finished. Replace this placeholder with an evidence-based summary.",
            [f"plans/plan-002/codex.events.jsonl"],
            [f"plans/plan-002/executor.sh"],
            ["Inspect the result report and replace this placeholder summary."],
        )

        content = summary_path.read_text(encoding="utf-8")
        self.assertIn(
            "Implemented configurable output root and preserved stdout under the run directory.",
            content,
        )
        self.assertIn("plans/plan-002/codex.last.md", content)
        self.assertIn("Finish the documentation by updating result.md, summary.md, and the shared asset", content)
        self.assertNotIn("Replace this placeholder", content)

    def test_write_summary_generates_structured_next_iteration_from_result_report(self) -> None:
        scoped_paths = plan_paths(self.paths.root, "plan-005", ensure=True)
        scoped_paths.result.write_text(
            "\n".join(
                [
                    "# Outcome",
                    "MLP baseline now trains end-to-end on GPU.",
                    "",
                    "# Evidence",
                    "1. src/example_lab/models/mlp.py",
                    "2. results/train_metrics.json",
                    "",
                    "# Artifacts",
                    "1. src/example_lab/train.py",
                    "2. plans/plan-005/summary.md",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        summary_path = write_summary(
            self.paths.root,
            "plan-005",
            "completed",
            "Execution finished. Replace this placeholder with an evidence-based summary.",
            [f"plans/plan-005/codex.events.jsonl"],
            [f"plans/plan-005/executor.sh"],
            ["Inspect the result report and replace this placeholder summary."],
        )

        content = summary_path.read_text(encoding="utf-8")
        self.assertIn("focusing on src/example_lab/models/mlp.py, src/example_lab/train.py", content)
        self.assertIn("Run only the smallest experiments or checks needed", content)
        self.assertIn("Finish the documentation by updating result.md, summary.md, and the shared asset", content)

    def test_write_summary_includes_git_delivery_metadata(self) -> None:
        manifest = load_manifest(self.paths.root)
        manifest.goal_language = "zh"
        manifest.work_branch = "mylab/run-001/plan-001"
        manifest.latest_work_commit = "abc1234"
        save_manifest(self.paths, manifest)
        plan_paths(self.paths.root, "plan-003", ensure=True).git_report.write_text(
            "# Git Delivery\n- work_branch: mylab/run-001/plan-001\n- head_commit: abc1234\n",
            encoding="utf-8",
        )

        summary_path = write_summary(
            self.paths.root,
            "plan-003",
            "completed",
            "Execution finished. Replace this placeholder with an evidence-based summary.",
            [f"plans/plan-003/codex.events.jsonl"],
            [f"plans/plan-003/executor.sh"],
            ["Inspect the result report and replace this placeholder summary."],
        )

        content = summary_path.read_text(encoding="utf-8")
        self.assertIn("- goal_language: zh", content)
        self.assertIn("- work_branch: mylab/run-001/plan-001", content)
        self.assertIn("- work_commit: abc1234", content)
        self.assertIn("plans/plan-003/git.md", content)
        self.assertIn("git:mylab/run-001/plan-001@abc1234", content)

    def test_write_summary_uses_goal_language_for_missing_report(self) -> None:
        manifest = load_manifest(self.paths.root)
        manifest.goal_language = "zh"
        goal_path = Path(manifest.goal_file)
        goal_path.parent.mkdir(parents=True, exist_ok=True)
        goal_path.write_text("复现用户要求的主实验并给出结论\n", encoding="utf-8")
        save_manifest(self.paths, manifest)

        summary_path = write_summary(
            self.paths.root,
            "plan-004",
            "completed",
            "Execution finished. Replace this placeholder with an evidence-based summary.",
            [f"plans/plan-004/codex.events.jsonl"],
            [f"plans/plan-004/executor.sh"],
            ["Inspect the result report and replace this placeholder summary."],
        )

        content = summary_path.read_text(encoding="utf-8")
        self.assertIn("执行已完成，但没有找到结果报告。", content)
        self.assertIn("先打开 executor 输出并补写结构化结果报告", content)


if __name__ == "__main__":
    unittest.main()
