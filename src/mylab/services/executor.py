from __future__ import annotations

from pathlib import Path

from mylab.codex import CodexExecSpec, CodexRunner
from mylab.logging import logger
from mylab.services.assets import repo_asset_path
from mylab.services.notifications import NotificationClient, load_notification_settings
from mylab.services.trials import training_budget_rule_lines
from mylab.storage import append_jsonl, write_json, write_text
from mylab.storage.trial_layout import trial_iteration_log_path, trial_paths, relative_to_run
from mylab.storage.runs import load_manifest
from mylab.utils import describe_language, utc_now


def executor_prompt(run_dir: Path, trial_id: str) -> str:
    manifest = load_manifest(run_dir)
    paths = trial_paths(run_dir, trial_id)
    trial_path = paths.trial
    result_path = paths.result
    summary_path = paths.summary
    log_path = paths.executor_log
    command_path = paths.command
    return "\n".join(
        [
            f"You are the iteration agent executing {trial_id}.",
            "Read the current trial definition, rewrite any scaffolded trial content into an accurate trial plan if needed, then implement the required code and script changes and keep all outputs under the provided run directory.",
            f"Repository root: {manifest.repo_path}",
            f"Run directory: {run_dir}",
            f"Trial file: {trial_path}",
            f"Result report path: {result_path}",
            f"Summary path: {summary_path}",
            f"Structured log path: {log_path}",
            f"Trial index path: {run_dir / 'trials' / 'index.md'}",
            f"Repository shared asset path: {repo_asset_path(run_dir)}",
            f"Job monitor directory: {paths.jobs}",
            f"Trial log directory: {paths.logs}",
            "Rules:",
            "1. Do not hardcode experiment output paths outside the run directory.",
            "2. Preserve raw command output and intermediate artifacts.",
            "3. If execution is long-running, create or update runnable scripts before starting.",
            "4. Training, deployment, Terraform, and build tasks must default to the mylab job monitor instead of running as direct foreground shell commands, even before you know whether they will take a long time.",
            "5. The documented job-monitor CLI is the default interface. Do not inspect mylab source code or invent alternate entrypoints just to start or poll a job unless the documented CLI actually fails in this run.",
            "6. Start monitored work with `mylab tool start-job --run-dir <run_dir> --trial-id <trial_id> --name <label> --command '<command>'`.",
            "7. Wait on monitored work with `mylab tool wait-job --run-dir <run_dir> --job-id <job_id>`. This waits for up to one hour by default. If it returns status=running, call it again later instead of switching back to a long foreground shell command.",
            "8. Only inspect logs on demand with `mylab tool tail-job --run-dir <run_dir> --job-id <job_id>`. Do not print long log tails on every poll; keep polling output concise to reduce token usage.",
            "9. Keep the final report tied to concrete file paths and observed results.",
            "10. Reuse the repository shared asset when relevant, update it with durable repo knowledge, and avoid known bad paths.",
            "11. Do not silently change the training budget defined by the trial, repository, or user input.",
            "12. Early stopping, reduced search, or proxy runs are allowed only when justified by repo logic or explicit trial rationale, and the result report must state both the authoritative budget source and the actual stop point.",
            f"13. Write the result report and concise user-facing summary in {describe_language(manifest.goal_language)} to match the original goal language.",
            "14. Use the current trial's `references/` files when the trial body points to deeper context; do not wait for the prompt to enumerate every path.",
            "15. Read referenced files directly when you need them; this prompt intentionally avoids inlining large file contents.",
            "16. If goal_summary, trial_essence, decision_focus, expected_signal, or other trial sections still contain scaffold language, rewrite trial.md first so it accurately describes what this trial will actually try.",
            "17. goal_summary and trial_essence must describe this trial's actual attempted move, not merely restate the overall run goal.",
            "18. Maximize meaningful progress per trial. Prefer finishing the decisive implementation, execution, comparison, and analysis loop in one trial whenever feasible instead of splitting obvious work into many tiny rounds.",
            "",
            f"Repository shared asset reference: {repo_asset_path(run_dir)}",
            f"All-trial guidance reference: {paths.references / 'all-guidance.md'}",
            f"Next-trial guidance reference: {paths.references / 'next-guidance.md'}",
            f"Trial skill reference: {paths.references / 'trial-skill.md'}",
            "Training budget guardrails:",
            *training_budget_rule_lines(),
            "",
            "After completion, write a markdown result report and a concise summary.",
            "The result report must explicitly mention the authoritative training budget source, the actual executed budget, and any early-stopping condition when training is involved.",
            "",
            f"Also write a reusable shell entrypoint to: {command_path}",
        ]
    )


def prepare_executor(run_dir: Path, trial_id: str, model: str | None) -> Path:
    manifest = load_manifest(run_dir)
    paths = trial_paths(run_dir, trial_id, ensure=True)
    trial_path = paths.trial
    if not trial_path.exists():
        raise FileNotFoundError(f"missing trial file: {trial_path}")
    prompt_path = paths.executor_prompt
    output_path = paths.codex_last
    command_path = paths.command
    prompt = executor_prompt(run_dir, trial_id)
    write_text(prompt_path, prompt)
    spec = CodexExecSpec(
        repo_path=Path(manifest.repo_path),
        run_dir=run_dir,
        prompt_path=prompt_path,
        output_path=output_path,
        event_path=paths.codex_events,
        model=model,
    )
    logger.info("Preparing Codex executor for {} in {}", trial_id, run_dir)
    CodexRunner().prepare_shell_script(spec, command_path)
    append_jsonl(
        trial_iteration_log_path(run_dir, trial_id),
        {
            "ts": utc_now(),
            "level": "INFO",
            "event": "executor_prepared",
            "trial_id": trial_id,
            "prompt": relative_to_run(prompt_path, run_dir),
            "command": relative_to_run(command_path, run_dir),
        },
    )
    write_json(
        paths.status,
        {
            "trial_id": trial_id,
            "status": "executor_prepared",
            "prepared_at": utc_now(),
            "prompt": relative_to_run(prompt_path, run_dir),
            "command": relative_to_run(command_path, run_dir),
        },
    )
    return command_path


def run_executor(
    run_dir: Path, trial_id: str, model: str | None, full_auto: bool
) -> Path:
    manifest = load_manifest(run_dir)
    notifier = NotificationClient(run_dir, load_notification_settings(run_dir))
    paths = trial_paths(run_dir, trial_id, ensure=True)
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
    logger.info("Running Codex executor for {} on repo {}", trial_id, manifest.repo_path)
    append_jsonl(
        trial_iteration_log_path(run_dir, trial_id),
        {
            "ts": utc_now(),
            "level": "INFO",
            "event": "executor_started",
            "trial_id": trial_id,
        },
    )

    def on_event(rendered: str, event_kind: str) -> None:
        if event_kind != "agent_message":
            return
        prefix = "[codex] agent:"
        message = (
            rendered[len(prefix) :].strip() if rendered.startswith(prefix) else rendered
        )
        notifier.notify_agent_message(trial_id, message)

    CodexRunner().run(spec, on_event=on_event)
    append_jsonl(
        trial_iteration_log_path(run_dir, trial_id),
        {
            "ts": utc_now(),
            "level": "INFO",
            "event": "executor_finished",
            "trial_id": trial_id,
        },
    )
    write_json(
        paths.status,
        {
            "trial_id": trial_id,
            "status": "executor_finished",
            "finished_at": utc_now(),
            "output": relative_to_run(output_path, run_dir),
        },
    )
    return output_path
