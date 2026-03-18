from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import mylab.flow.serial as serial_module
from mylab.domain import QueueState, RunManifest, TaskRecord
from mylab.flow.serial import SerialFlowRunner
from mylab.orchestrator.queue import save_queue
from mylab.services.run_control import (
    FLOW_MODE_LIMIT,
    FLOW_MODE_STEP,
    FLOW_MODE_UNLIMIT,
    load_run_control_settings,
)
from mylab.services.telegram_bot import TelegramSettings
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
            QueueState(tasks=[make_restore_task(1)]),
        )

        outputs = FakeSerialFlowRunner(
            self.paths.root,
            allow_exec=False,
            mode=FLOW_MODE_STEP,
            confirm_continue=lambda _completed: False,
        ).run_until_blocked(limit=None)

        self.assertEqual([item["task_id"] for item in outputs], ["task-0001"])

    def test_step_mode_auto_queues_next_iteration_before_waiting(self) -> None:
        save_manifest(
            self.paths,
            RunManifest(
                run_id="run-001",
                repo_path=str(self.root / "repo"),
                source_branch="main",
                goal_file=str(self.paths.inputs / "goal.txt"),
                runs_env_var="MYLAB_RUNS_DIR",
                latest_trial_id="trial-001",
            ),
        )
        queue = QueueState(tasks=[])
        runner = FakeSerialFlowRunner(
            self.paths.root,
            allow_exec=False,
            mode=FLOW_MODE_STEP,
        )
        original_consume = serial_module.consume_feedback_since
        try:
            serial_module.consume_feedback_since = lambda cursor: (None, cursor)
            ok = runner._maybe_chain_next_iteration(
                queue,
                completed_iterations=1,
                step_limit=2,
            )
        finally:
            serial_module.consume_feedback_since = original_consume

        self.assertTrue(ok)
        self.assertEqual(queue.tasks[0].kind, "iterate_plan")
        self.assertIn(
            "Continue to the next full iteration",
            queue.tasks[0].payload["feedback"],
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

    def test_step_mode_queues_next_iteration_after_feedback(self) -> None:
        save_manifest(
            self.paths,
            RunManifest(
                run_id="run-001",
                repo_path=str(self.root / "repo"),
                source_branch="main",
                goal_file=str(self.paths.inputs / "goal.txt"),
                runs_env_var="MYLAB_RUNS_DIR",
                latest_trial_id="trial-001",
            ),
        )
        queue = QueueState(tasks=[])
        runner = FakeSerialFlowRunner(
            self.paths.root,
            allow_exec=False,
            mode=FLOW_MODE_STEP,
        )
        runner._wait_for_step_feedback = lambda _completed: "next instruction from telegram"
        original_load = serial_module.load_telegram_settings
        serial_module.load_telegram_settings = lambda: TelegramSettings(
            bot_token=None,
            allowed_chat_ids=[],
        )

        try:
            ok = runner._maybe_chain_next_iteration(
                queue,
                completed_iterations=1,
                step_limit=1,
            )
        finally:
            serial_module.load_telegram_settings = original_load

        self.assertTrue(ok)
        self.assertEqual(queue.tasks[0].kind, "iterate_plan")
        self.assertEqual(
            queue.tasks[0].payload["feedback"], "next instruction from telegram"
        )

    def test_step_mode_does_not_block_on_stdin_when_telegram_is_enabled(self) -> None:
        save_manifest(
            self.paths,
            RunManifest(
                run_id="run-001",
                repo_path=str(self.root / "repo"),
                source_branch="main",
                goal_file=str(self.paths.inputs / "goal.txt"),
                runs_env_var="MYLAB_RUNS_DIR",
                latest_trial_id="trial-001",
            ),
        )
        runner = FakeSerialFlowRunner(
            self.paths.root,
            allow_exec=False,
            mode=FLOW_MODE_STEP,
        )
        original_load = serial_module.load_telegram_settings
        original_consume = serial_module.consume_feedback_since
        original_sleep = serial_module.time.sleep
        try:
            serial_module.load_telegram_settings = lambda: TelegramSettings(
                bot_token="123:abc",
                allowed_chat_ids=[42],
                poll_interval_seconds=1,
            )
            runner._poll_telegram_feedback = lambda _settings=None: None
            serial_module.consume_feedback_since = lambda cursor: (None, cursor)

            def stop_sleep(_seconds: int) -> None:
                raise RuntimeError("stop-loop")

            serial_module.time.sleep = stop_sleep
            with patch("builtins.input", side_effect=AssertionError("stdin should not be used")):
                with patch("sys.stdin.isatty", return_value=True):
                    with self.assertRaisesRegex(RuntimeError, "stop-loop"):
                        runner._wait_for_step_feedback(1)
        finally:
            serial_module.load_telegram_settings = original_load
            serial_module.consume_feedback_since = original_consume
            serial_module.time.sleep = original_sleep

    def test_step_mode_polls_telegram_before_consuming_feedback(self) -> None:
        save_manifest(
            self.paths,
            RunManifest(
                run_id="run-001",
                repo_path=str(self.root / "repo"),
                source_branch="main",
                goal_file=str(self.paths.inputs / "goal.txt"),
                runs_env_var="MYLAB_RUNS_DIR",
                latest_trial_id="trial-001",
            ),
        )
        queue = QueueState(tasks=[])
        runner = FakeSerialFlowRunner(
            self.paths.root,
            allow_exec=False,
            mode=FLOW_MODE_STEP,
        )
        original_load = serial_module.load_telegram_settings
        original_consume = serial_module.consume_feedback_since
        polled: list[str] = []
        try:
            serial_module.load_telegram_settings = lambda: TelegramSettings(
                bot_token="123:abc",
                allowed_chat_ids=[42],
                poll_interval_seconds=1,
            )
            runner._poll_telegram_feedback = lambda _settings=None: polled.append("yes")
            serial_module.consume_feedback_since = lambda cursor: ("from telegram", cursor + 1)
            ok = runner._maybe_chain_next_iteration(
                queue,
                completed_iterations=1,
                step_limit=1,
            )
        finally:
            serial_module.load_telegram_settings = original_load
            serial_module.consume_feedback_since = original_consume

        self.assertTrue(ok)
        self.assertGreaterEqual(len(polled), 1)
        self.assertEqual(queue.tasks[0].payload["feedback"], "from telegram")

    def test_step_mode_wait_ignores_stale_feedback_before_wait_starts(self) -> None:
        save_manifest(
            self.paths,
            RunManifest(
                run_id="run-001",
                repo_path=str(self.root / "repo"),
                source_branch="main",
                goal_file=str(self.paths.inputs / "goal.txt"),
                runs_env_var="MYLAB_RUNS_DIR",
                latest_trial_id="trial-001",
                feedback_cursor=0,
            ),
        )
        runner = FakeSerialFlowRunner(
            self.paths.root,
            allow_exec=False,
            mode=FLOW_MODE_STEP,
        )
        original_load = serial_module.load_telegram_settings
        original_count = serial_module.feedback_record_count
        original_consume = serial_module.consume_feedback_since
        try:
            serial_module.load_telegram_settings = lambda: TelegramSettings(
                bot_token="123:abc",
                allowed_chat_ids=[42],
                poll_interval_seconds=1,
            )
            runner._poll_telegram_feedback = lambda _settings=None: None
            serial_module.feedback_record_count = lambda scopes=None: 3

            calls: list[int] = []

            def fake_consume(cursor: int) -> tuple[str | None, int]:
                calls.append(cursor)
                if len(calls) == 1:
                    return None, 3
                return "fresh telegram step", 4

            serial_module.consume_feedback_since = fake_consume
            feedback = runner._wait_for_step_feedback(1)
        finally:
            serial_module.load_telegram_settings = original_load
            serial_module.feedback_record_count = original_count
            serial_module.consume_feedback_since = original_consume

        self.assertEqual(feedback, "fresh telegram step")
        self.assertEqual(calls[0], 3)

    def test_unlimit_mode_queues_next_iteration_instead_of_stopping(self) -> None:
        save_manifest(
            self.paths,
            RunManifest(
                run_id="run-001",
                repo_path=str(self.root / "repo"),
                source_branch="main",
                goal_file=str(self.paths.inputs / "goal.txt"),
                runs_env_var="MYLAB_RUNS_DIR",
                latest_trial_id="trial-001",
            ),
        )
        queue = QueueState(tasks=[])
        runner = FakeSerialFlowRunner(
            self.paths.root,
            allow_exec=False,
            mode=FLOW_MODE_UNLIMIT,
        )
        original_load = serial_module.load_telegram_settings
        original_consume = serial_module.consume_feedback_since
        try:
            serial_module.load_telegram_settings = lambda: TelegramSettings(
                bot_token=None,
                allowed_chat_ids=[],
            )
            serial_module.consume_feedback_since = lambda cursor: (None, cursor)
            ok = runner._maybe_chain_next_iteration(
                queue,
                completed_iterations=1,
                step_limit=0,
            )
        finally:
            serial_module.load_telegram_settings = original_load
            serial_module.consume_feedback_since = original_consume

        self.assertTrue(ok)
        self.assertEqual(queue.tasks[0].kind, "iterate_plan")
        self.assertIn(
            "Continue to the next full iteration",
            queue.tasks[0].payload["feedback"],
        )


if __name__ == "__main__":
    unittest.main()
