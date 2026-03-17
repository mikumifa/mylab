from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mylab.domain import RunManifest
from mylab.services.reports import write_summary
from mylab.storage.runs import init_run_dirs, save_manifest


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

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_write_summary_uses_structured_result_report(self) -> None:
        (self.paths.results / "plan-001.result.md").write_text(
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
                    "1. commands/plan-001.executor.sh",
                    "2. results/plan-001.result.md",
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
            [f"logs/plan-001.codex.events.jsonl"],
            [f"commands/plan-001.executor.sh"],
            ["Inspect the result report and replace this placeholder summary."],
        )

        content = summary_path.read_text(encoding="utf-8")
        self.assertIn("Validation accuracy reached 91.2%", content)
        self.assertIn("results/metrics.json", content)
        self.assertIn("Compare against the lighter baseline.", content)
        self.assertNotIn("Replace this placeholder", content)

    def test_write_summary_falls_back_to_codex_last_message(self) -> None:
        (self.paths.results / "plan-002.codex.last.md").write_text(
            "Implemented configurable output root and preserved stdout under the run directory.\n",
            encoding="utf-8",
        )

        summary_path = write_summary(
            self.paths.root,
            "plan-002",
            "completed",
            "Execution finished. Replace this placeholder with an evidence-based summary.",
            [f"logs/plan-002.codex.events.jsonl"],
            [f"commands/plan-002.executor.sh"],
            ["Inspect the result report and replace this placeholder summary."],
        )

        content = summary_path.read_text(encoding="utf-8")
        self.assertIn(
            "Implemented configurable output root and preserved stdout under the run directory.",
            content,
        )
        self.assertIn("results/plan-002.codex.last.md", content)
        self.assertNotIn("Replace this placeholder", content)


if __name__ == "__main__":
    unittest.main()
