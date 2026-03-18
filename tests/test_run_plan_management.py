from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import mylab.commands.root as root_module
from mylab.domain import QueueState, RunManifest, TaskRecord
from mylab.orchestrator.queue import load_queue, save_queue
from mylab.storage import write_text
from mylab.storage.plan_layout import plan_paths
from mylab.storage.runs import init_run_dirs, load_manifest, save_manifest


class RunPlanManagementTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="mylab-run-manage-")
        self.root = Path(self.temp_dir.name)
        self.runs_root = self.root / "runs"
        self.original_runs_env = os.environ.get("MYLAB_RUNS_DIR")
        os.environ["MYLAB_RUNS_DIR"] = str(self.runs_root)
        self.original_current = root_module.CURRENT_RUN_FILE
        root_module.CURRENT_RUN_FILE = self.root / "current_run.json"

    def tearDown(self) -> None:
        if self.original_runs_env is None:
            os.environ.pop("MYLAB_RUNS_DIR", None)
        else:
            os.environ["MYLAB_RUNS_DIR"] = self.original_runs_env
        root_module.CURRENT_RUN_FILE = self.original_current
        self.temp_dir.cleanup()

    def _create_run(self, name: str) -> Path:
        paths = init_run_dirs(self.runs_root / name)
        goal_file = paths.inputs / "goal.txt"
        write_text(goal_file, "goal")
        save_manifest(
            paths,
            RunManifest(
                run_id=name,
                repo_path=str(self.root / "repo"),
                source_branch="main",
                goal_file=str(goal_file),
                runs_env_var="MYLAB_RUNS_DIR",
                latest_plan_id=None,
            ),
        )
        return paths.root

    def test_plan_commands_require_active_run(self) -> None:
        exit_code = root_module.main(["plan", "ls"])
        self.assertEqual(exit_code, 1)

    def test_run_use_and_ls(self) -> None:
        self._create_run("run-001")
        self._create_run("run-002")

        self.assertEqual(root_module.main(["run", "use", "run-001"]), 0)

        with io.StringIO() as buffer:
            original_stdout = sys.stdout
            try:
                sys.stdout = buffer
                exit_code = root_module.main(["run", "ls"])
            finally:
                sys.stdout = original_stdout
            output = buffer.getvalue()

        self.assertEqual(exit_code, 0)
        self.assertIn("* run-001", output)
        self.assertIn("run-002", output)

    def test_plan_cat_and_rm(self) -> None:
        run_dir = self._create_run("run-001")
        paths = init_run_dirs(run_dir)
        manifest = load_manifest(run_dir)
        manifest.latest_plan_id = "plan-001"
        save_manifest(paths, manifest)
        scoped_paths = plan_paths(run_dir, "plan-001", ensure=True)
        write_text(scoped_paths.plan, "# test plan")
        save_queue(
            run_dir,
            QueueState(
                tasks=[
                    TaskRecord(
                        task_id="task-0001",
                        kind="run_executor",
                        status="pending",
                        created_at="2026-03-18T00:00:00Z",
                        payload={"plan_id": "plan-001"},
                    )
                ]
            ),
        )
        original_delete = root_module._delete_plan_branch_if_present
        try:
            root_module._delete_plan_branch_if_present = lambda _run_dir, _plan_id: None
            root_module.main(["run", "use", "run-001"])
            with io.StringIO() as buffer:
                original_stdout = sys.stdout
                try:
                    sys.stdout = buffer
                    exit_code = root_module.main(["plan", "cat", "plan-001"])
                finally:
                    sys.stdout = original_stdout
                output = buffer.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertIn("# test plan", output)

            self.assertEqual(root_module.main(["plan", "rm", "plan-001"]), 0)
        finally:
            root_module._delete_plan_branch_if_present = original_delete

        self.assertFalse(scoped_paths.root.exists())
        self.assertEqual(load_queue(run_dir).tasks, [])
        self.assertIsNone(load_manifest(run_dir).latest_plan_id)


if __name__ == "__main__":
    unittest.main()
