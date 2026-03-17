from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from mylab.logging import colorize, emit_progress, logger
from mylab.utils import shell_join


@dataclass
class CodexExecSpec:
    repo_path: Path
    run_dir: Path
    prompt_path: Path
    output_path: Path
    event_path: Path
    model: str | None
    full_auto: bool = False

    def command(self) -> list[str]:
        cmd = ["codex", "exec"]
        if self.model:
            cmd.extend(["--model", self.model])
        if self.full_auto:
            cmd.append("--full-auto")
        cmd.extend(
            [
                "--dangerously-bypass-approvals-and-sandbox",
                "--cd",
                str(self.repo_path),
                "--add-dir",
                str(self.run_dir),
                "--output-last-message",
                str(self.output_path),
                "--json",
                "-",
            ]
        )
        return cmd

    def shell_command(self) -> str:
        return shell_join(self.command()) + f" < {self.prompt_path}"


class CodexRunner:
    def _render_event(self, line: str) -> tuple[str | None, str | None]:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return f"[codex] {line}", "raw"

        event_type = event.get("type")
        if not isinstance(event_type, str):
            return f"[codex] {line}", "raw"

        if event_type in {"thread.started", "turn.started"}:
            return f"[codex] {event_type}", event_type
        if event_type == "turn.completed":
            return "[codex] turn.completed", event_type
        if event_type == "turn.failed":
            error = event.get("error", {})
            if isinstance(error, dict):
                return (
                    f"[codex] turn.failed: {error.get('message', 'unknown error')}",
                    event_type,
                )
            return "[codex] turn.failed", event_type
        if event_type == "error":
            return f"[codex] error: {event.get('message', 'unknown error')}", event_type

        item = event.get("item")
        if isinstance(item, dict):
            item_type = item.get("type")
            if item_type == "agent_message":
                text = str(item.get("text", "")).strip().replace("\n", " ")
                return f"[codex] agent: {text[:240]}", item_type
            if item_type == "command_execution":
                command = str(item.get("command", "")).strip()
                status = str(item.get("status", "")).strip()
                if command:
                    return f"[codex] command ({status or 'event'}): {command}", item_type
            if item_type == "todo_list":
                return "[codex] todo_list updated", item_type

        return None, None

    def _emit_rendered_event(self, rendered: str) -> None:
        if not rendered.startswith("[codex] "):
            emit_progress("[codex]", rendered, color="cyan")
            return
        body = rendered[len("[codex] ") :]
        if body.startswith("error:") or body.startswith("turn.failed:"):
            emit_progress("[codex]", body, color="red")
            return
        if body.startswith("turn.completed"):
            emit_progress("[codex]", body, color="green")
            return
        if body.startswith("agent:"):
            emit_progress("[codex]", body, color="green")
            return
        if body.startswith("command"):
            return
        if body.startswith("todo_list"):
            return
        emit_progress("[codex]", body, color="cyan")

    def prepare_shell_script(self, spec: CodexExecSpec, script_path: Path) -> Path:
        logger.debug("Writing Codex shell script to {}", script_path)
        script_path.write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\n" + spec.shell_command() + "\n",
            encoding="utf-8",
        )
        script_path.chmod(0o755)
        return script_path

    def run(
        self,
        spec: CodexExecSpec,
        on_event: Callable[[str, str], None] | None = None,
    ) -> Path:
        logger.info("Executing Codex command in {}", spec.repo_path)
        with spec.prompt_path.open("r", encoding="utf-8") as prompt_handle:
            process = subprocess.Popen(
                spec.command(),
                stdin=prompt_handle,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            assert process.stdout is not None
            with spec.event_path.open("w", encoding="utf-8") as log_handle:
                for line in process.stdout:
                    log_handle.write(line)
                    log_handle.flush()
                    rendered, event_kind = self._render_event(line.rstrip("\n"))
                    if rendered:
                        self._emit_rendered_event(rendered)
                        if on_event and event_kind:
                            on_event(rendered, event_kind)
            return_code = process.wait()
            if return_code != 0:
                raise subprocess.CalledProcessError(return_code, process.args)
        return spec.output_path
