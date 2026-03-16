from __future__ import annotations

from pathlib import Path

from mylab.codex import CodexExecSpec, CodexRunner
from mylab.logging import logger
from mylab.storage import append_jsonl, write_text
from mylab.storage.runs import load_manifest
from mylab.utils import utc_now


def executor_prompt(run_dir: Path, plan_id: str) -> str:
    manifest = load_manifest(run_dir)
    plan_path = run_dir / "plans" / f"{plan_id}.md"
    result_path = run_dir / "results" / f"{plan_id}.result.md"
    summary_path = run_dir / "summaries" / f"{plan_id}.summary.md"
    log_path = run_dir / "logs" / f"{plan_id}.executor.jsonl"
    command_path = run_dir / "commands" / f"{plan_id}.executor.sh"
    return "\n".join(
        [
            f"You are execution agent 3 for {plan_id}.",
            "Read the plan, implement the required code and script changes, and keep all outputs under the provided run directory.",
            f"Repository root: {manifest.repo_path}",
            f"Run directory: {run_dir}",
            f"Plan file: {plan_path}",
            f"Result report path: {result_path}",
            f"Summary path: {summary_path}",
            f"Structured log path: {log_path}",
            "Rules:",
            "1. Do not hardcode experiment output paths outside the run directory.",
            "2. Preserve raw command output and intermediate artifacts.",
            "3. If execution is long-running, create or update runnable scripts before starting.",
            "4. Keep the final report tied to concrete file paths and observed results.",
            "",
            "After completion, write a markdown result report and a concise summary.",
            "",
            "Plan content:",
            "",
            plan_path.read_text(encoding="utf-8"),
            "",
            f"Also write a reusable shell entrypoint to: {command_path}",
        ]
    )


def prepare_executor(run_dir: Path, plan_id: str, model: str) -> Path:
    manifest = load_manifest(run_dir)
    plan_path = run_dir / "plans" / f"{plan_id}.md"
    if not plan_path.exists():
        raise FileNotFoundError(f"missing plan file: {plan_path}")
    prompt_path = run_dir / "prompts" / f"{plan_id}.executor.prompt.md"
    output_path = run_dir / "results" / f"{plan_id}.codex.last.md"
    command_path = run_dir / "commands" / f"{plan_id}.executor.sh"
    prompt = executor_prompt(run_dir, plan_id)
    write_text(prompt_path, prompt)
    spec = CodexExecSpec(
        repo_path=Path(manifest.repo_path),
        run_dir=run_dir,
        prompt_path=prompt_path,
        output_path=output_path,
        event_path=run_dir / "logs" / f"{plan_id}.codex.events.jsonl",
        model=model,
    )
    logger.info("Preparing Codex executor for {} in {}", plan_id, run_dir)
    CodexRunner().prepare_shell_script(spec, command_path)
    append_jsonl(
        run_dir / "logs" / "agent3-preparer.jsonl",
        {
            "ts": utc_now(),
            "level": "INFO",
            "event": "executor_prepared",
            "plan_id": plan_id,
            "prompt": str(prompt_path),
            "command": str(command_path),
        },
    )
    return command_path


def run_executor(run_dir: Path, plan_id: str, model: str, full_auto: bool) -> Path:
    manifest = load_manifest(run_dir)
    prompt_path = run_dir / "prompts" / f"{plan_id}.executor.prompt.md"
    output_path = run_dir / "results" / f"{plan_id}.codex.last.md"
    event_path = run_dir / "logs" / f"{plan_id}.codex.events.jsonl"
    spec = CodexExecSpec(
        repo_path=Path(manifest.repo_path),
        run_dir=run_dir,
        prompt_path=prompt_path,
        output_path=output_path,
        event_path=event_path,
        model=model,
        full_auto=full_auto,
    )
    logger.info("Running Codex executor for {} on repo {}", plan_id, manifest.repo_path)
    append_jsonl(
        run_dir / "logs" / "agent4-runner.jsonl",
        {
            "ts": utc_now(),
            "level": "INFO",
            "event": "executor_started",
            "plan_id": plan_id,
        },
    )
    CodexRunner().run(spec)
    append_jsonl(
        run_dir / "logs" / "agent4-runner.jsonl",
        {
            "ts": utc_now(),
            "level": "INFO",
            "event": "executor_finished",
            "plan_id": plan_id,
        },
    )
    return output_path
