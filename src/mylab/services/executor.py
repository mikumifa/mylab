from __future__ import annotations

from pathlib import Path

from mylab.codex import CodexExecSpec, CodexRunner
from mylab.logging import logger
from mylab.services.assets import repo_asset_path
from mylab.services.notifications import NotificationClient, load_notification_settings
from mylab.services.plans import training_budget_rule_lines
from mylab.storage import append_jsonl, write_text
from mylab.storage.plan_layout import plan_paths, relative_to_run
from mylab.storage.runs import load_manifest
from mylab.utils import describe_language, utc_now


def executor_prompt(run_dir: Path, plan_id: str) -> str:
    manifest = load_manifest(run_dir)
    paths = plan_paths(run_dir, plan_id)
    plan_path = paths.plan
    result_path = paths.result
    summary_path = paths.summary
    log_path = paths.executor_log
    command_path = paths.command
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
            f"Job monitor metadata directory: {run_dir / 'jobs'}",
            "Rules:",
            "1. Do not hardcode experiment output paths outside the run directory.",
            "2. Preserve raw command output and intermediate artifacts.",
            "3. If execution is long-running, create or update runnable scripts before starting.",
            "4. Training, deployment, Terraform, and build tasks must default to the mylab job monitor instead of running as direct foreground shell commands, even before you know whether they will take a long time.",
            "5. The documented job-monitor CLI is the default interface. Do not inspect mylab source code or invent alternate entrypoints just to start or poll a job unless the documented CLI actually fails in this run.",
            "6. Start monitored work with `mylab tool start-job --run-dir <run_dir> --plan-id <plan_id> --name <label> --command '<command>'`.",
            "7. Wait on monitored work with `mylab tool wait-job --run-dir <run_dir> --job-id <job_id>`. This waits for up to one hour by default. If it returns status=running, call it again later instead of switching back to a long foreground shell command.",
            "8. Only inspect logs on demand with `mylab tool tail-job --run-dir <run_dir> --job-id <job_id>`. Do not print long log tails on every poll; keep polling output concise to reduce token usage.",
            "9. Keep the final report tied to concrete file paths and observed results.",
            "10. Reuse the repository shared asset when relevant, update it with durable repo knowledge, and avoid known bad paths.",
            "11. Do not silently change the training budget defined by the plan, repository, or user input.",
            "12. Early stopping, reduced search, or proxy runs are allowed only when justified by repo logic or explicit plan rationale, and the result report must state both the authoritative budget source and the actual stop point.",
            f"13. Write the result report and concise user-facing summary in {describe_language(manifest.goal_language)} to match the original goal language.",
            "14. Use the current plan's `references/` files when the plan body points to deeper context; do not wait for the prompt to enumerate every path.",
            "15. Read referenced files directly when you need them; this prompt intentionally avoids inlining large file contents.",
            "",
            f"Repository shared asset reference: {repo_asset_path(run_dir)}",
            f"All-plan guidance reference: {paths.references / 'all-guidance.md'}",
            f"Next-plan guidance reference: {paths.references / 'next-guidance.md'}",
            f"Plan skill reference: {paths.references / 'plan-skill.md'}",
            "Training budget guardrails:",
            *training_budget_rule_lines(),
            "",
            "After completion, write a markdown result report and a concise summary.",
            "The result report must explicitly mention the authoritative training budget source, the actual executed budget, and any early-stopping condition when training is involved.",
            "",
            f"Also write a reusable shell entrypoint to: {command_path}",
        ]
    )


def prepare_executor(run_dir: Path, plan_id: str, model: str | None) -> Path:
    manifest = load_manifest(run_dir)
    paths = plan_paths(run_dir, plan_id, ensure=True)
    plan_path = paths.plan
    if not plan_path.exists():
        raise FileNotFoundError(f"missing plan file: {plan_path}")
    prompt_path = paths.executor_prompt
    output_path = paths.codex_last
    command_path = paths.command
    prompt = executor_prompt(run_dir, plan_id)
    write_text(prompt_path, prompt)
    spec = CodexExecSpec(
        repo_path=Path(manifest.repo_path),
        run_dir=run_dir,
        prompt_path=prompt_path,
        output_path=output_path,
        event_path=paths.codex_events,
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
            "prompt": relative_to_run(prompt_path, run_dir),
            "command": relative_to_run(command_path, run_dir),
        },
    )
    return command_path


def run_executor(
    run_dir: Path, plan_id: str, model: str | None, full_auto: bool
) -> Path:
    manifest = load_manifest(run_dir)
    notifier = NotificationClient(run_dir, load_notification_settings(run_dir))
    paths = plan_paths(run_dir, plan_id, ensure=True)
    prompt_path = paths.executor_prompt
    output_path = paths.codex_last
    event_path = paths.codex_events
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

    def on_event(rendered: str, event_kind: str) -> None:
        if event_kind != "agent_message":
            return
        prefix = "[codex] agent:"
        message = (
            rendered[len(prefix) :].strip() if rendered.startswith(prefix) else rendered
        )
        notifier.notify_agent_message(plan_id, message)

    CodexRunner().run(spec, on_event=on_event)
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
