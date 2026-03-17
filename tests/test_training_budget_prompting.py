from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mylab.domain import RunManifest
from mylab.services.executor import executor_prompt
from mylab.services.plans import create_initial_plan
from mylab.storage import write_text
from mylab.storage.runs import init_run_dirs, save_manifest


class TrainingBudgetPromptingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="mylab-budget-")
        self.root = Path(self.temp_dir.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.paths = init_run_dirs(self.root / "run")
        goal_file = self.paths.inputs / "goal.txt"
        write_text(
            goal_file, "Train the model for 500 epochs and compare with the baseline."
        )
        self.manifest = RunManifest(
            run_id="run-001",
            repo_path=str(self.repo),
            source_branch="main",
            goal_file=str(goal_file),
            runs_env_var="MYLAB_RUNS_DIR",
        )
        save_manifest(self.paths, self.manifest)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_initial_plan_prompt_mentions_training_budget_guardrails(self) -> None:
        plan_path = create_initial_plan(self.paths, self.manifest)

        self.assertTrue(plan_path.exists())
        prompt = (self.paths.prompts / "plan-001.plan.prompt.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "Do not weaken the experiment by silently shrinking epoch/step counts",
            prompt,
        )
        self.assertIn("Training budget guardrails:", prompt)
        self.assertIn("If you stop early, record the configured budget", prompt)

    def test_executor_prompt_mentions_no_silent_undertraining(self) -> None:
        write_text(
            self.paths.plans / "plan-001.md",
            "\n".join(
                [
                    "# Plan Metadata",
                    "- plan_id: plan-001",
                    "- parent_plan_id: none",
                    "- run_id: run-001",
                    f"- repo_path: {self.repo}",
                    "- source_branch: main",
                    "- generated_at: 2026-03-17T00:00:00Z",
                    "",
                    "# Experiment Goal",
                    "Train for 500 epochs.",
                    "",
                    "# Investigation Questions",
                    "1. Does it converge?",
                    "",
                    "# Execution Plan",
                    "1. Train the model.",
                    "",
                    "# Deliverables",
                    "1. Metrics.",
                    "",
                    "# Result Collection Rules",
                    "1. Keep outputs under the run directory.",
                ]
            ),
        )

        prompt = executor_prompt(self.paths.root, "plan-001")

        self.assertIn("do not arbitrarily run 200 instead", prompt.lower())
        self.assertIn("planned budget and the actual stop point", prompt)
        self.assertIn("configured training budget, the actual executed budget", prompt)


if __name__ == "__main__":
    unittest.main()
