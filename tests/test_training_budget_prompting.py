from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mylab.domain import RunManifest
from mylab.services.executor import executor_prompt
from mylab.services.trials import create_initial_trial, create_iterated_trial
from mylab.services.trial_skills import infer_trial_skill
from mylab.storage import write_text
from mylab.storage.trial_layout import trial_paths
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

    def test_initial_trial_prompt_mentions_training_budget_guardrails(self) -> None:
        trial_path = create_initial_trial(self.paths, self.manifest)

        self.assertTrue(trial_path.exists())
        prompt = trial_paths(self.paths.root, "trial-001").trial_prompt.read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "Do not weaken the experiment by silently changing the training budget",
            prompt,
        )
        self.assertIn("Training budget guardrails:", prompt)
        self.assertIn("If you stop early, record the intended budget source", prompt)
        self.assertIn("Trial file reference:", prompt)
        self.assertIn("All-trial guidance reference:", prompt)
        self.assertNotIn("Draft trial content:", prompt)
        content = trial_path.read_text(encoding="utf-8")
        self.assertIn("trial_skill: mylab-structure-tuning", content)
        self.assertIn("trial_essence:", content)
        self.assertIn("decision_focus:", content)
        self.assertIn("expected_signal:", content)
        self.assertIn("code_checkpoint:", content)
        self.assertIn("code_checkpoint_ref:", content)
        self.assertIn("all_guidance_ref:", content)
        self.assertIn("next_guidance_ref:", content)
        self.assertNotIn("next_iteration_hook:", content)
        self.assertNotIn("# Referenced Files", content)
        self.assertIn("Put full design rationale in `references/design.md`", content)
        self.assertIn("# Human Review", content)

    def test_executor_prompt_mentions_no_silent_undertraining(self) -> None:
        scoped_paths = trial_paths(self.paths.root, "trial-001", ensure=True)
        write_text(
            scoped_paths.trial,
            "\n".join(
                [
                    "---",
                    "trial_id: trial-001",
                    "run_id: run-001",
                    "trial_kind: idea-cycle",
                    "trial_skill: mylab-structure-tuning",
                    f"repo_path: {self.repo}",
                    "source_branch: main",
                    "code_checkpoint: abc1234",
                    "code_checkpoint_ref: main",
                    "generated_at: 2026-03-17T00:00:00Z",
                    'goal_summary: "Train and evaluate the model."',
                    'trial_essence: "Train and evaluate the model."',
                    'decision_focus: "Check convergence and compare against baseline."',
                    'expected_signal: "A comparable train/eval result."',
                    "entrypoint: trials/trial-001/trial.md",
                    "references_dir: trials/trial-001/references",
                    "---",
                    "",
                    "# Trial Metadata",
                    "- trial_id: trial-001",
                    "- run_id: run-001",
                    f"- repo_path: {self.repo}",
                    "- source_branch: main",
                    "- code_checkpoint: abc1234",
                    "- code_checkpoint_ref: main",
                    "- trial_kind: idea-cycle",
                    "- trial_skill: mylab-structure-tuning",
                    "- trial_essence: Train and evaluate the model.",
                    "- decision_focus: Check convergence and compare against baseline.",
                    "- expected_signal: A comparable train/eval result.",
                    "- generated_at: 2026-03-17T00:00:00Z",
                    "",
                    "# Experiment Goal",
                    "Train and evaluate the model.",
                    "",
                    "# Investigation Questions",
                    "1. Does it converge?",
                    "",
                    "# Execution Steps",
                    "1. Train the model.",
                    "",
                    "# Deliverables",
                    "1. Metrics.",
                    "",
                    "# Human Review",
                    "- Status: Pending human comment.",
                    "- Human Comment: Fill in concise feedback, objections, or approval notes here.",
                    "",
                    "# Result Collection Rules",
                    "1. Keep outputs under the run directory.",
                ]
            ),
        )

        prompt = executor_prompt(self.paths.root, "trial-001")

        self.assertIn(
            "do not silently change the training budget defined by the trial, repository, or user input",
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
        self.assertIn("Repository shared asset reference:", prompt)
        self.assertIn("Trial skill reference:", prompt)
        self.assertNotIn("Trial content:", prompt)
        self.assertNotIn("Train and evaluate the model.", prompt)

    def test_parameter_goal_selects_parameter_tuning_skill(self) -> None:
        profile = infer_trial_skill("做一个参数组合 sweep，批量比较不同参数配置。")
        self.assertEqual(profile.skill_name, "mylab-parameter-tuning")
        self.assertEqual(profile.trial_kind, "parameter-tuning")

    def test_iterated_trial_prompt_uses_trial_catalog_instead_of_parent_content(
        self,
    ) -> None:
        create_initial_trial(self.paths, self.manifest)

        trial_path = create_iterated_trial(
            self.paths,
            self.manifest,
            parent_trial_id="trial-001",
            feedback="Try a tighter comparison around the current best setting.",
        )

        self.assertTrue(trial_path.exists())
        prompt = trial_paths(self.paths.root, "trial-002").trial_prompt.read_text(
            encoding="utf-8"
        )
        self.assertIn("Trial catalog reference:", prompt)
        self.assertIn("Trial file reference:", prompt)
        self.assertNotIn("Existing trial catalog:", prompt)
        self.assertNotIn("Parent trial content:", prompt)
        self.assertNotIn("Parent trial: ", prompt)


if __name__ == "__main__":
    unittest.main()
