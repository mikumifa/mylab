from __future__ import annotations

import json
from argparse import Namespace
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mylab.commands.root import build_parser, cmd_start_job
from mylab.domain import RunManifest
from mylab.services.job_monitor import start_job, tail_job, wait_for_job
from mylab.storage import write_text
from mylab.storage.trial_layout import trial_paths
from mylab.storage.runs import init_run_dirs, save_manifest


class JobMonitorTest(unittest.TestCase):
    def test_start_job_cli_keeps_tool_route_and_job_command_separate(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "tool",
                "start-job",
                "--run-dir",
                "/tmp/run",
                "--trial-id",
                "trial-001",
                "--command",
                "echo hi",
            ]
        )

        self.assertEqual(args.command, "tool")
        self.assertEqual(args.tool_command, "start-job")
        self.assertEqual(args.job_command, "echo hi")

    def test_cmd_start_job_accepts_legacy_programmatic_command_field(self) -> None:
        args = Namespace(
            run_dir=self.paths.root,
            trial_id="trial-001",
            name="direct",
            cwd=str(self.root),
            command="echo direct",
        )
        with tempfile.TemporaryFile(mode="w+") as stdout:
            original_stdout = sys.stdout
            try:
                sys.stdout = stdout
                exit_code = cmd_start_job(args)
            finally:
                sys.stdout = original_stdout
            stdout.seek(0)
            started = json.loads(stdout.read())

        self.assertEqual(exit_code, 0)
        finished = wait_for_job(
            self.paths.root,
            started["job_id"],
            wait_seconds=5,
            poll_seconds=1,
        )
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["exit_code"], 0)

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="mylab-job-monitor-")
        self.root = Path(self.temp_dir.name)
        self.paths = init_run_dirs(self.root / "run")
        goal_file = self.paths.inputs / "goal.txt"
        write_text(goal_file, "Run a monitored command.")
        save_manifest(
            self.paths,
            RunManifest(
                run_id="run-001",
                repo_path=str(self.root),
                source_branch="main",
                goal_file=str(goal_file),
                runs_env_var="MYLAB_RUNS_DIR",
            ),
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_start_wait_and_tail_job(self) -> None:
        started = start_job(
            self.paths.root,
            "trial-001",
            "sleep 1; echo done",
            name="train",
            cwd=str(self.root),
        )
        self.assertEqual(started["status"], "running")
        waited = wait_for_job(
            self.paths.root,
            started["job_id"],
            wait_seconds=5,
            poll_seconds=1,
        )
        self.assertEqual(waited["status"], "completed")
        self.assertEqual(waited["exit_code"], 0)
        scoped_paths = trial_paths(self.paths.root, "trial-001")
        self.assertTrue(str(scoped_paths.logs) in waited["stdout_path"])
        self.assertTrue((scoped_paths.jobs / f"{started['job_id']}.json").exists())
        self.assertTrue((scoped_paths.jobs / f"{started['job_id']}.runner.sh").exists())
        tailed = tail_job(self.paths.root, started["job_id"], lines=5)
        self.assertEqual(tailed["stdout_tail"], "done")

    def test_wait_job_returns_running_when_window_expires(self) -> None:
        started = start_job(
            self.paths.root,
            "trial-001",
            "sleep 3; echo later",
            name="slow",
            cwd=str(self.root),
        )
        waited = wait_for_job(
            self.paths.root,
            started["job_id"],
            wait_seconds=1,
            poll_seconds=1,
        )
        self.assertEqual(waited["status"], "running")
        time.sleep(3)
        finished = wait_for_job(
            self.paths.root,
            started["job_id"],
            wait_seconds=1,
            poll_seconds=1,
        )
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["exit_code"], 0)


if __name__ == "__main__":
    unittest.main()
