from __future__ import annotations

from pathlib import Path

from mylab.codex import CodexExecSpec, CodexRunner
from mylab.logging import logger
from mylab.services.assets import load_repo_asset, repo_asset_path
from mylab.services.plans import training_budget_rule_lines
from mylab.services.telegram_bot import load_feedback_context, load_telegram_settings
from mylab.storage import append_jsonl, write_text
from mylab.storage.runs import load_manifest
from mylab.utils import utc_now


def executor_prompt(run_dir: Path, plan_id: str) -> str:
    manifest = load_manifest(run_dir)
    inherited_asset = load_repo_asset(run_dir)
    feedback_context = load_feedback_context(
        load_telegram_settings().feedback_context_limit
    )
    plan_path = run_dir / "plans" / f"{plan_id}.md"
    result_path = run_dir / "results" / f"{plan_id}.result.md"
    summary_path = run_dir / "summaries" / f"{plan_id}.summary.md"
    log_path = run_dir / "logs" / f"{plan_id}.executor.jsonl"
    command_path = run_dir / "commands" / f"{plan_id}.executor.sh"
    return "\n".join(
        [
            f"You are the iteration agent executing {plan_id}.",
            "Read the plan, implement the required code and script changes, and keep all outputs under the provided run directory.",
            f"Repository root: {manifest.repo_path}",
            f"Run directory: {run_dir}",
            f"Plan file: {plan_path}",
            f"Result report path: {result_path}",
            f"Summary path: {summary_path}",
            f"Structured log path: {log_path}",
            f"Plan index path: {run_dir / 'plans' / 'index.md'}",
            f"Repository shared asset path: {repo_asset_path(run_dir)}",
            "Rules:",
            "1. Do not hardcode experiment output paths outside the run directory.",
            "2. Preserve raw command output and intermediate artifacts.",
            "3. If execution is long-running, create or update runnable scripts before starting.",
            "4. Keep the final report tied to concrete file paths and observed results.",
            "5. Reuse the repository shared asset when relevant, update it with durable repo knowledge, and avoid known bad paths.",
            "6. Do not silently shrink the intended training budget. If the experiment is supposed to run 500 epochs/steps, do not arbitrarily run 200 instead.",
            "7. Early stopping, reduced search, or proxy runs are allowed only when justified by repo logic or explicit plan rationale, and the result report must state both the planned budget and the actual stop point.",
            "",
            "Repository shared asset:",
            inherited_asset or "(none yet)",
            "",
            "Training budget guardrails:",
            *training_budget_rule_lines(),
            "",
            "Recent user feedback from Telegram inbox:",
            feedback_context or "(none yet)",
            "",
            "After completion, write a markdown result report and a concise summary.",
            "The result report must explicitly mention the configured training budget, the actual executed budget, and any early-stopping condition when training is involved.",
            "",
            "Plan content:",
            "",
            plan_path.read_text(encoding="utf-8"),
            "",
            f"Also write a reusable shell entrypoint to: {command_path}",
        ]
    )


def prepare_executor(run_dir: Path, plan_id: str, model: str | None) -> Path:
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
        run_dir / "logs" / "iteration-agent.jsonl",
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


def run_executor(
    run_dir: Path, plan_id: str, model: str | None, full_auto: bool
) -> Path:
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
        run_dir / "logs" / "iteration-agent.jsonl",
        {
            "ts": utc_now(),
            "level": "INFO",
            "event": "executor_started",
            "plan_id": plan_id,
        },
    )
    CodexRunner().run(spec)
    append_jsonl(
        run_dir / "logs" / "iteration-agent.jsonl",
        {
            "ts": utc_now(),
            "level": "INFO",
            "event": "executor_finished",
            "plan_id": plan_id,
        },
    )
    return output_path
