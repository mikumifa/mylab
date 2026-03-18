from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mylab.domain import RunManifest
from mylab.services.executor import executor_prompt
from mylab.services.plans import create_initial_plan
from mylab.services.plan_skills import infer_plan_skill
from mylab.storage import write_text
from mylab.storage.plan_layout import plan_paths
from mylab.storage.runs import init_run_dirs, save_manifest


class TrainingBudgetPromptingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="mylab-budget-")
        self.root = Path(self.temp_dir.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.paths = init_run_dirs(self.root / "run")
        goal_file = self.paths.inputs / "goal.txt"
        write_text(goal_file, "Train the model and compare with the baseline.")
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
        prompt = plan_paths(self.paths.root, "plan-001").plan_prompt.read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "Do not weaken the experiment by silently changing the training budget",
            prompt,
        )
        self.assertIn("Training budget guardrails:", prompt)
        self.assertIn("If you stop early, record the intended budget source", prompt)
        content = plan_path.read_text(encoding="utf-8")
        self.assertIn('plan_skill: mylab-structure-tuning', content)
        self.assertIn('plan_essence:', content)
        self.assertIn('decision_focus:', content)
        self.assertIn('expected_signal:', content)
        self.assertIn('next_iteration_hook:', content)
        self.assertIn('plans/plan-001/references/plan-skill.md', content)

    def test_executor_prompt_mentions_no_silent_undertraining(self) -> None:
        scoped_paths = plan_paths(self.paths.root, "plan-001", ensure=True)
        write_text(
            scoped_paths.plan,
            "\n".join(
                [
                    "---",
                    "plan_id: plan-001",
                    "run_id: run-001",
                    "parent_plan_id: none",
                    "plan_kind: idea-cycle",
                    f"repo_path: {self.repo}",
                    "source_branch: main",
                    "generated_at: 2026-03-17T00:00:00Z",
                    "goal_summary: \"Train and evaluate the model.\"",
                    "entrypoint: plans/plan-001/plan.md",
                    "references_dir: plans/plan-001/references",
                    "---",
                    "",
                    "# Plan Metadata",
                    "- plan_id: plan-001",
                    "- parent_plan_id: none",
                    "- run_id: run-001",
                    f"- repo_path: {self.repo}",
                    "- source_branch: main",
                    "- generated_at: 2026-03-17T00:00:00Z",
                    "",
                    "# Experiment Goal",
                    "Train and evaluate the model.",
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
                    "# Referenced Files",
                    "1. plans/plan-001/references/shared-asset.md",
                    "",
                    "# Result Collection Rules",
                    "1. Keep outputs under the run directory.",
                ]
            ),
        )

        prompt = executor_prompt(self.paths.root, "plan-001")

        self.assertIn(
            "do not silently change the training budget defined by the plan, repository, or user input",
            prompt.lower(),
        )
        self.assertIn(
            "training, deployment, terraform, and build tasks must default to the mylab job monitor",
            prompt.lower(),
        )
        self.assertIn("mylab tool start-job", prompt)
        self.assertIn("mylab tool wait-job", prompt)
        self.assertIn("keep polling output concise to reduce token usage", prompt)
        self.assertIn(
            "do not inspect mylab source code or invent alternate entrypoints",
            prompt.lower(),
        )
        self.assertIn(
            "authoritative budget source and the actual stop point",
            prompt,
        )
        self.assertIn(
            "authoritative training budget source, the actual executed budget",
            prompt,
        )
        self.assertIn("This waits for up to one hour by default", prompt)

    def test_parameter_goal_selects_parameter_tuning_skill(self) -> None:
        profile = infer_plan_skill("做一个参数组合 sweep，批量比较不同参数配置。")
        self.assertEqual(profile.skill_name, "mylab-parameter-tuning")
        self.assertEqual(profile.plan_kind, "parameter-tuning")


if __name__ == "__main__":
    unittest.main()
