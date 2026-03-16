from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from mylab.logging import logger
from mylab.utils import shell_join


@dataclass
class CodexExecSpec:
    repo_path: Path
    run_dir: Path
    prompt_path: Path
    output_path: Path
    event_path: Path
    model: str
    full_auto: bool = False

    def command(self) -> list[str]:
        cmd = [
            "codex",
            "exec",
            "--cd",
            str(self.repo_path),
            "--add-dir",
            str(self.run_dir),
            "--model",
            self.model,
            "--sandbox",
            "workspace-write",
            "--output-last-message",
            str(self.output_path),
            "--json",
            "-",
        ]
        if self.full_auto:
            cmd.insert(2, "--full-auto")
        return cmd

    def shell_command(self) -> str:
        return shell_join(self.command()) + f" < {self.prompt_path}"


class CodexRunner:
    def prepare_shell_script(self, spec: CodexExecSpec, script_path: Path) -> Path:
        logger.debug("Writing Codex shell script to {}", script_path)
        script_path.write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\n" + spec.shell_command() + "\n",
            encoding="utf-8",
        )
        script_path.chmod(0o755)
        return script_path

    def run(self, spec: CodexExecSpec) -> Path:
        logger.info("Executing Codex command in {}", spec.repo_path)
        with (
            spec.prompt_path.open("r", encoding="utf-8") as prompt_handle,
            spec.event_path.open("w", encoding="utf-8") as log_handle,
        ):
            subprocess.run(
                spec.command(),
                check=True,
                stdin=prompt_handle,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
            )
        return spec.output_path
