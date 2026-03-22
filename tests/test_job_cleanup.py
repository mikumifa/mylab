from __future__ import annotations

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
from mylab.storage.trial_layout import trial_paths
from mylab.storage.runs import init_run_dirs, save_manifest


class JobCleanupOnExitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="mylab-job-cleanup-")
        self.root = Path(self.temp_dir.name)
        self.paths = init_run_dirs(self.root / "run")
        goal_file = self.paths.inputs / "goal.txt"
        write_text(goal_file, "goal")
        save_manifest(
            self.paths,
            RunManifest(
                run_id="run-001",
                repo_path=str(self.root / "repo"),
                source_branch="main",
                goal_file=str(goal_file),
                runs_env_var="MYLAB_RUNS_DIR",
                original_branch="main",
            ),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_start_terminates_jobs_on_exit(self) -> None:
        original_require = root_module.require_selected_run_dir
        original_logging = root_module.configure_logging
        original_preflight = root_module.print_codex_preflight
        original_resolve = root_module.resolve_flow_control
        original_runner = root_module.SerialFlowRunner
        original_terminate = root_module.terminate_all_jobs
        calls: list[tuple[str, object]] = []

        class FakeRunner:
            def __init__(self, run_dir: Path, allow_exec: bool, *, mode: str) -> None:
                calls.append(("runner_init", run_dir))

            def run_until_blocked(self, limit: int | None) -> list[dict[str, str]]:
                calls.append(("runner_run", limit))
                return []

        try:
            root_module.require_selected_run_dir = lambda: self.paths.root
            root_module.configure_logging = lambda log_dir: calls.append(("logging", log_dir))
            root_module.print_codex_preflight = lambda model: calls.append(("preflight", model))
            root_module.resolve_flow_control = lambda **kwargs: ("unlimit", None)
            root_module.SerialFlowRunner = FakeRunner
            root_module.terminate_all_jobs = lambda run_dir: calls.append(("terminate", run_dir)) or []
            exit_code = root_module.main(["start"])
        finally:
            root_module.require_selected_run_dir = original_require
            root_module.configure_logging = original_logging
            root_module.print_codex_preflight = original_preflight
            root_module.resolve_flow_control = original_resolve
            root_module.SerialFlowRunner = original_runner
            root_module.terminate_all_jobs = original_terminate

        self.assertEqual(exit_code, 0)
        self.assertIn(("terminate", self.paths.root), calls)

    def test_start_resident_defaults_repo_to_current_directory(self) -> None:
        original_cwd = Path.cwd()
        original_logging = root_module.configure_logging
        original_preflight = root_module.print_codex_preflight
        original_resolve = root_module.resolve_flow_control
        original_bootstrap = root_module.bootstrap_run
        original_planned = root_module.planned_run_dirs
        original_notifications = root_module.resolve_notification_settings
        original_runner = root_module.SerialFlowRunner
        original_terminate = root_module.terminate_all_jobs
        original_set_current = root_module.set_current_run
        original_make_run_id = root_module.make_run_id
        captured: list[tuple[str, object]] = []

        class FakeRunner:
            def __init__(self, run_dir: Path, allow_exec: bool, *, mode: str) -> None:
                captured.append(("runner_init", run_dir))

            def run_until_blocked(self, limit: int | None) -> list[dict[str, str]]:
                captured.append(("runner_run", limit))
                return []

        try:
            os.chdir(self.root)
            root_module.configure_logging = lambda log_dir: captured.append(("logging", log_dir))
            root_module.print_codex_preflight = lambda model: captured.append(("preflight", model))
            root_module.resolve_flow_control = lambda **kwargs: ("resident", None)
            root_module.planned_run_dirs = lambda run_root: self.paths
            root_module.resolve_notification_settings = lambda: None
            root_module.make_run_id = lambda goal_text: "run-001"
            root_module.set_current_run = lambda run_id: captured.append(("current", run_id))
            root_module.bootstrap_run = lambda **kwargs: captured.append(
                ("repo_path", kwargs["repo_path"])
            )
            root_module.SerialFlowRunner = FakeRunner
            root_module.terminate_all_jobs = lambda run_dir: captured.append(("terminate", run_dir)) or []

            exit_code = root_module.main(["start", "--goal", "goal", "--mode", "resident"])
        finally:
            os.chdir(original_cwd)
            root_module.configure_logging = original_logging
            root_module.print_codex_preflight = original_preflight
            root_module.resolve_flow_control = original_resolve
            root_module.bootstrap_run = original_bootstrap
            root_module.planned_run_dirs = original_planned
            root_module.resolve_notification_settings = original_notifications
            root_module.SerialFlowRunner = original_runner
            root_module.terminate_all_jobs = original_terminate
            root_module.set_current_run = original_set_current
            root_module.make_run_id = original_make_run_id

        self.assertEqual(exit_code, 0)
        self.assertIn(("repo_path", self.root.resolve()), captured)

    def test_start_existing_run_enqueues_next_iteration_without_goal(self) -> None:
        original_require = root_module.require_selected_run_dir
        original_logging = root_module.configure_logging
        original_preflight = root_module.print_codex_preflight
        original_resolve = root_module.resolve_flow_control
        original_runner = root_module.SerialFlowRunner
        original_terminate = root_module.terminate_all_jobs
        calls: list[tuple[str, object]] = []

        self.paths.trials.mkdir(exist_ok=True)
        prior_trial = trial_paths(self.paths.root, "trial-001", ensure=True)
        write_text(prior_trial.trial, "# trial 001")
        write_text(prior_trial.summary, "# summary 001")
        manifest = root_module.load_manifest(self.paths.root)
        manifest.latest_trial_id = "trial-001"
        save_manifest(self.paths, manifest)

        class FakeRunner:
            def __init__(self, run_dir: Path, allow_exec: bool, *, mode: str) -> None:
                calls.append(("runner_init", run_dir))

            def run_until_blocked(self, limit: int | None) -> list[dict[str, str]]:
                calls.append(("runner_run", limit))
                return []

        try:
            root_module.require_selected_run_dir = lambda: self.paths.root
            root_module.configure_logging = lambda log_dir: calls.append(("logging", log_dir))
            root_module.print_codex_preflight = lambda model: calls.append(("preflight", model))
            root_module.resolve_flow_control = lambda **kwargs: ("limit", 1)
            root_module.SerialFlowRunner = FakeRunner
            root_module.terminate_all_jobs = lambda run_dir: calls.append(("terminate", run_dir)) or []

            exit_code = root_module.main(["start", "--run", "run-001"])
        finally:
            root_module.require_selected_run_dir = original_require
            root_module.configure_logging = original_logging
            root_module.print_codex_preflight = original_preflight
            root_module.resolve_flow_control = original_resolve
            root_module.SerialFlowRunner = original_runner
            root_module.terminate_all_jobs = original_terminate

        self.assertEqual(exit_code, 0)
        queue = load_queue(self.paths.root)
        self.assertEqual(len(queue.tasks), 1)
        self.assertEqual(queue.tasks[0].kind, "iterate_plan")
        self.assertEqual(queue.tasks[0].payload["parent_trial_id"], "trial-001")

    def test_start_exit_deletes_latest_unfinished_trial(self) -> None:
        original_require = root_module.require_selected_run_dir
        original_logging = root_module.configure_logging
        original_preflight = root_module.print_codex_preflight
        original_resolve = root_module.resolve_flow_control
        original_runner = root_module.SerialFlowRunner
        original_terminate = root_module.terminate_all_jobs

        unfinished = trial_paths(self.paths.root, "trial-002", ensure=True)
        write_text(unfinished.trial, "# trial 002")
        manifest = root_module.load_manifest(self.paths.root)
        manifest.latest_trial_id = "trial-002"
        save_manifest(self.paths, manifest)
        save_queue(
            self.paths.root,
            QueueState(
                tasks=[
                    TaskRecord(
                        task_id="task-0001",
                        kind="run_executor",
                        status="pending",
                        created_at="2026-03-22T00:00:00Z",
                        payload={"trial_id": "trial-002"},
                    )
                ]
            ),
        )

        class FakeRunner:
            def __init__(self, run_dir: Path, allow_exec: bool, *, mode: str) -> None:
                return None

            def run_until_blocked(self, limit: int | None) -> list[dict[str, str]]:
                return []

        try:
            root_module.require_selected_run_dir = lambda: self.paths.root
            root_module.configure_logging = lambda log_dir: None
            root_module.print_codex_preflight = lambda model: None
            root_module.resolve_flow_control = lambda **kwargs: ("unlimit", None)
            root_module.SerialFlowRunner = FakeRunner
            root_module.terminate_all_jobs = lambda run_dir: []

            exit_code = root_module.main(["start"])
        finally:
            root_module.require_selected_run_dir = original_require
            root_module.configure_logging = original_logging
            root_module.print_codex_preflight = original_preflight
            root_module.resolve_flow_control = original_resolve
            root_module.SerialFlowRunner = original_runner
            root_module.terminate_all_jobs = original_terminate

        self.assertEqual(exit_code, 0)
        self.assertFalse(unfinished.root.exists())
        self.assertEqual(load_queue(self.paths.root).tasks, [])
        self.assertIsNone(root_module.load_manifest(self.paths.root).latest_trial_id)

    def test_main_sends_notification_when_command_errors(self) -> None:
        original_require = root_module.require_selected_run_dir
        original_logging = root_module.configure_logging
        original_preflight = root_module.print_codex_preflight
        original_resolve = root_module.resolve_flow_control
        original_runner = root_module.SerialFlowRunner
        original_terminate = root_module.terminate_all_jobs
        original_notifier = root_module.NotificationClient
        original_load_settings = root_module.load_notification_settings
        sent: list[tuple[str, str, str]] = []

        class FakeNotifier:
            def __init__(self, run_dir: Path, settings) -> None:
                self.run_dir = run_dir

            def notify(self, title: str, body: str, *, notify_type: str = "info") -> bool:
                sent.append((title, body, notify_type))
                return True

        class FailingRunner:
            def __init__(self, run_dir: Path, allow_exec: bool, *, mode: str) -> None:
                return None

            def run_until_blocked(self, limit: int | None) -> list[dict[str, str]]:
                raise RuntimeError("boom")

        try:
            root_module.require_selected_run_dir = lambda: self.paths.root
            root_module.configure_logging = lambda log_dir: None
            root_module.print_codex_preflight = lambda model: None
            root_module.resolve_flow_control = lambda **kwargs: ("unlimit", None)
            root_module.SerialFlowRunner = FailingRunner
            root_module.terminate_all_jobs = lambda run_dir: []
            root_module.NotificationClient = FakeNotifier
            root_module.load_notification_settings = lambda run_dir: object()

            exit_code = root_module.main(["start"])
        finally:
            root_module.require_selected_run_dir = original_require
            root_module.configure_logging = original_logging
            root_module.print_codex_preflight = original_preflight
            root_module.resolve_flow_control = original_resolve
            root_module.SerialFlowRunner = original_runner
            root_module.terminate_all_jobs = original_terminate
            root_module.NotificationClient = original_notifier
            root_module.load_notification_settings = original_load_settings

        self.assertEqual(exit_code, 1)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], "mylab command failed: start")
        self.assertIn("run=run", sent[0][1])
        self.assertIn("error=boom", sent[0][1])
        self.assertEqual(sent[0][2], "failure")
