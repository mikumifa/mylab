from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import mylab.commands.root as root_module


def run_git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


class AdapterCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="mylab-adapter-cmd-")
        self.root = Path(self.temp_dir.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        run_git(self.repo, "init", "-b", "main")
        run_git(self.repo, "config", "user.name", "mylab-test")
        run_git(self.repo, "config", "user.email", "mylab@example.com")
        (self.repo / "README.md").write_text("base\n", encoding="utf-8")
        run_git(self.repo, "add", "README.md")
        run_git(self.repo, "commit", "-m", "init")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_adapter_runs_without_run_dir_or_branch_switch(self) -> None:
        original_run_adapter = root_module.run_adapter
        original_preflight = root_module.print_codex_preflight
        original_logging = root_module.configure_logging
        calls: list[tuple[Path, str | None, str | None]] = []
        preflight_models: list[str | None] = []
        logging_calls: list[object] = []
        try:
            root_module.run_adapter = (
                lambda repo_path, goal_text, model: calls.append((repo_path, goal_text, model)) or repo_path
            )
            root_module.print_codex_preflight = lambda model: preflight_models.append(model)
            root_module.configure_logging = lambda log_dir=None: logging_calls.append(log_dir)
            with io.StringIO() as buffer:
                original_stdout = sys.stdout
                try:
                    sys.stdout = buffer
                    exit_code = root_module.main(
                        ["adapter", "--repo", str(self.repo), "--goal", "make this repo runnable"]
                    )
                finally:
                    sys.stdout = original_stdout
                output = buffer.getvalue()
        finally:
            root_module.run_adapter = original_run_adapter
            root_module.print_codex_preflight = original_preflight
            root_module.configure_logging = original_logging

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, [(self.repo.resolve(), "make this repo runnable", None)])
        self.assertEqual(preflight_models, [None])
        self.assertEqual(logging_calls, [None])
        self.assertEqual(output.strip(), str(self.repo.resolve()))


if __name__ == "__main__":
    unittest.main()
