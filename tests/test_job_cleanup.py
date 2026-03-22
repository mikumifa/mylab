from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import mylab.commands.root as root_module
from mylab.domain import RunManifest
from mylab.storage import write_text
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
