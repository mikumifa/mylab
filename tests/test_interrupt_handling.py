from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import mylab.commands.root as root_module
import mylab.flow.serial as serial_module
from mylab.domain import QueueState, RunManifest, TaskRecord
from mylab.flow.serial import SerialFlowRunner
from mylab.orchestrator.queue import save_queue
from mylab.storage.runs import init_run_dirs, save_manifest


class InterruptingSerialFlowRunner(SerialFlowRunner):
    def _log_run_overview(self, queue: QueueState) -> None:
        return None

    def _dispatch(self, task: TaskRecord) -> str:
        raise KeyboardInterrupt()

    def _enqueue_followups(self, queue: QueueState, task: TaskRecord) -> None:
        return None


class InterruptHandlingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="mylab-interrupt-")
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
                original_branch="main",
                work_branch="mylab/run-001/trial-001",
            ),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_serial_flow_restores_branch_after_ctrl_c(self) -> None:
        save_queue(
            self.paths.root,
            QueueState(
                tasks=[
                    TaskRecord(
                        task_id="task-0001",
                        kind="run_executor",
                        status="pending",
                        created_at="2026-03-17T00:00:00Z",
                        payload={"trial_id": "trial-001"},
                    )
                ]
            ),
        )
        restored: list[tuple[Path, str]] = []
        original_restore = serial_module.restore_original_branch
        try:
            serial_module.restore_original_branch = lambda run_dir, manifest: restored.append(
                (run_dir, manifest.original_branch or "")
            ) or (manifest.original_branch or "")
            outputs = InterruptingSerialFlowRunner(
                self.paths.root,
                allow_exec=True,
            ).run_until_blocked(limit=1)
        finally:
            serial_module.restore_original_branch = original_restore

        self.assertEqual(
            outputs,
            [
                {
                    "task_id": "task-0001",
                    "kind": "run_executor",
                    "output": "INTERRUPTED: user requested stop",
                }
            ],
        )
        self.assertEqual(restored, [(self.paths.root, "main")])

    def test_main_returns_130_on_keyboard_interrupt(self) -> None:
        original_cmd = root_module.cmd_bot_telegram
        try:
            root_module.cmd_bot_telegram = lambda args: (_ for _ in ()).throw(KeyboardInterrupt())
            exit_code = root_module.main(["bot", "telegram"])
        finally:
            root_module.cmd_bot_telegram = original_cmd

        self.assertEqual(exit_code, 130)


if __name__ == "__main__":
    unittest.main()
