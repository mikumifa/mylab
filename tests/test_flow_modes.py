from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mylab.domain import QueueState, RunManifest, TaskRecord
from mylab.flow.serial import SerialFlowRunner
from mylab.orchestrator.queue import save_queue
from mylab.services.run_control import (
    FLOW_MODE_LIMIT,
    FLOW_MODE_STEP,
    FLOW_MODE_UNLIMIT,
    load_run_control_settings,
)
from mylab.storage.runs import init_run_dirs, save_manifest


def make_restore_task(index: int) -> TaskRecord:
    return TaskRecord(
        task_id=f"task-{index:04d}",
        kind="restore_branch",
        status="pending",
        created_at="2026-03-17T00:00:00Z",
        payload={},
    )


class FakeSerialFlowRunner(SerialFlowRunner):
    def _log_run_overview(self, queue: QueueState) -> None:
        return None

    def _dispatch(self, task: TaskRecord) -> str:
        return f"done:{task.task_id}"

    def _enqueue_followups(self, queue: QueueState, task: TaskRecord) -> None:
        return None


class FlowModeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="mylab-flow-mode-")
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

    def test_limit_mode_counts_full_iterations(self) -> None:
        save_queue(
            self.paths.root,
            QueueState(
                tasks=[make_restore_task(1), make_restore_task(2), make_restore_task(3)]
            ),
        )

        outputs = FakeSerialFlowRunner(
            self.paths.root,
            allow_exec=False,
            mode=FLOW_MODE_LIMIT,
        ).run_until_blocked(limit=2)

        self.assertEqual(
            [item["task_id"] for item in outputs], ["task-0001", "task-0002"]
        )

    def test_step_mode_prompts_after_first_iteration_by_default(self) -> None:
        save_queue(
            self.paths.root,
            QueueState(tasks=[make_restore_task(1), make_restore_task(2)]),
        )

        outputs = FakeSerialFlowRunner(
            self.paths.root,
            allow_exec=False,
            mode=FLOW_MODE_STEP,
            confirm_continue=lambda _completed: False,
        ).run_until_blocked(limit=None)

        self.assertEqual([item["task_id"] for item in outputs], ["task-0001"])

    def test_step_mode_can_auto_run_limit_then_switch_to_step(self) -> None:
        save_queue(
            self.paths.root,
            QueueState(
                tasks=[
                    make_restore_task(1),
                    make_restore_task(2),
                    make_restore_task(3),
                    make_restore_task(4),
                ]
            ),
        )
        answers = iter([True, False])

        outputs = FakeSerialFlowRunner(
            self.paths.root,
            allow_exec=False,
            mode=FLOW_MODE_STEP,
            confirm_continue=lambda _completed: next(answers),
        ).run_until_blocked(limit=2)

        self.assertEqual(
            [item["task_id"] for item in outputs],
            ["task-0001", "task-0002", "task-0003"],
        )

    def test_unlimit_mode_ignores_iteration_cap(self) -> None:
        save_queue(
            self.paths.root,
            QueueState(
                tasks=[make_restore_task(1), make_restore_task(2), make_restore_task(3)]
            ),
        )

        outputs = FakeSerialFlowRunner(
            self.paths.root,
            allow_exec=False,
            mode=FLOW_MODE_UNLIMIT,
        ).run_until_blocked(limit=1)

        self.assertEqual(
            [item["task_id"] for item in outputs],
            ["task-0001", "task-0002", "task-0003"],
        )

    def test_load_run_control_settings_from_config(self) -> None:
        config_path = self.root / "config.toml"
        config_path.write_text(
            "\n".join(
                [
                    "[runner]",
                    'mode = "step"',
                    "limit = 2",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        settings = load_run_control_settings(config_path)

        self.assertEqual(settings.mode, FLOW_MODE_STEP)
        self.assertEqual(settings.limit, 2)


if __name__ == "__main__":
    unittest.main()
