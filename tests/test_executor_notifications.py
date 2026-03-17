from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import mylab.services.executor as executor_module
from mylab.domain import RunManifest
from mylab.storage import write_text
from mylab.storage.runs import init_run_dirs, save_manifest


class FakeNotifier:
    def __init__(self, run_dir: Path, settings: object) -> None:
        self.run_dir = run_dir
        self.settings = settings
        self.agent_messages: list[tuple[str, str]] = []

    def notify_agent_message(self, plan_id: str, text: str) -> bool:
        self.agent_messages.append((plan_id, text))
        return True


class FakeCodexRunner:
    def run(self, spec: object, on_event=None) -> Path:
        if on_event is not None:
            on_event("[codex] agent: first update", "agent_message")
            on_event("[codex] command (completed): python train.py", "command_execution")
            on_event("[codex] agent: second update", "agent_message")
        return spec.output_path


class ExecutorNotificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="mylab-executor-notify-")
        self.root = Path(self.temp_dir.name)
        self.paths = init_run_dirs(self.root / "run")
        write_text(self.paths.prompts / "plan-001.executor.prompt.md", "prompt")
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

    def test_run_executor_forwards_agent_messages_to_notifier(self) -> None:
        original_runner = executor_module.CodexRunner
        original_notifier = executor_module.NotificationClient
        original_load_settings = executor_module.load_notification_settings
        fake_notifier = FakeNotifier(self.paths.root, object())
        try:
            executor_module.CodexRunner = lambda: FakeCodexRunner()
            executor_module.NotificationClient = lambda run_dir, settings: fake_notifier
            executor_module.load_notification_settings = lambda run_dir: object()

            output = executor_module.run_executor(
                self.paths.root,
                "plan-001",
                model=None,
                full_auto=False,
            )
        finally:
            executor_module.CodexRunner = original_runner
            executor_module.NotificationClient = original_notifier
            executor_module.load_notification_settings = original_load_settings

        self.assertEqual(output, self.paths.results / "plan-001.codex.last.md")
        self.assertEqual(
            fake_notifier.agent_messages,
            [
                ("plan-001", "first update"),
                ("plan-001", "second update"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
