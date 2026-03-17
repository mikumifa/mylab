from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mylab.domain import RunManifest
from mylab.services.job_monitor import start_job, tail_job, wait_for_job
from mylab.storage import write_text
from mylab.storage.runs import init_run_dirs, save_manifest


class JobMonitorTest(unittest.TestCase):
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
            "plan-001",
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
        tailed = tail_job(self.paths.root, started["job_id"], lines=5)
        self.assertEqual(tailed["stdout_tail"], "done")

    def test_wait_job_returns_running_when_window_expires(self) -> None:
        started = start_job(
            self.paths.root,
            "plan-001",
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
