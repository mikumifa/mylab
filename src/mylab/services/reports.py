from __future__ import annotations

from pathlib import Path
import re

from mylab.config import SUMMARY_HEADINGS
from mylab.logging import logger
from mylab.services.assets import update_repo_asset, upsert_plan_index_record
from mylab.storage import append_jsonl, read_text, write_text
from mylab.storage.plan_layout import plan_paths, relative_to_run
from mylab.storage.runs import load_manifest
from mylab.utils import utc_now


def render_summary_markdown(
    *,
    run_id: str,
    plan_id: str,
    status: str,
    outcome: str,
    evidence: list[str],
    artifacts: list[str],
    next_iteration: list[str],
    goal_language: str | None = None,
    work_branch: str | None = None,
    work_commit: str | None = None,
) -> str:
    metadata_lines = [
        f"- run_id: {run_id}",
        f"- plan_id: {plan_id}",
        f"- status: {status}",
        f"- generated_at: {utc_now()}",
    ]
    if goal_language:
        metadata_lines.append(f"- goal_language: {goal_language}")
    if work_branch:
        metadata_lines.append(f"- work_branch: {work_branch}")
    if work_commit:
        metadata_lines.append(f"- work_commit: {work_commit}")
    return f"""# Summary Metadata
{chr(10).join(metadata_lines)}

# Outcome
{outcome.strip()}

# Evidence
{chr(10).join(f"{index}. {item}" for index, item in enumerate(evidence, start=1))}

# Artifacts
{chr(10).join(f"{index}. {item}" for index, item in enumerate(artifacts, start=1))}

# Next Iteration
{chr(10).join(f"{index}. {item}" for index, item in enumerate(next_iteration, start=1))}
"""


def validate_summary_markdown(content: str) -> list[str]:
    missing = [heading for heading in SUMMARY_HEADINGS if heading not in content]
    return [f"missing required heading: {heading}" for heading in missing]


def _extract_markdown_section(content: str, heading: str) -> str:
    lines = content.splitlines()
    capture = False
    collected: list[str] = []
    for line in lines:
        if line.strip() == heading:
            capture = True
            continue
        if capture and line.startswith("# "):
            break
        if capture:
            collected.append(line)
    return "\n".join(collected).strip()


def _extract_list_items(section: str) -> list[str]:
    items: list[str] = []
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if len(line) > 2 and line[0].isdigit() and line[1:3] == ". ":
            items.append(line[3:].strip())
            continue
        if line.startswith(("- ", "* ")):
            items.append(line[2:].strip())
    return [item for item in items if item]


def _extract_file_targets(*sections: str) -> list[str]:
    pattern = re.compile(
        r"(?<![\w/.-])(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.(?:py|md|sh|json|jsonl|yaml|yml|toml|txt)"
    )
    code_targets: list[str] = []
    other_targets: list[str] = []
    for section in sections:
        for match in pattern.findall(section):
            candidate = match.strip().lstrip("./")
            if (
                not candidate
                or candidate.startswith(("logs/", "results/", "summaries/", "commands/"))
            ):
                continue
            suffix = Path(candidate).suffix.lower()
            bucket = (
                code_targets
                if suffix in {".py", ".sh", ".toml", ".yaml", ".yml"}
                else other_targets
            )
            if candidate not in bucket:
                bucket.append(candidate)
    merged = code_targets if code_targets else other_targets
    return merged[:3]


def _fallback_next_iteration(
    *,
    goal_language: str,
    source_content: str,
    evidence: list[str],
    artifacts: list[str],
) -> list[str]:
    targets = _extract_file_targets(source_content, "\n".join(evidence), "\n".join(artifacts))
    target_text = ", ".join(targets) if targets else "当前结果直接涉及的实现代码"
    if goal_language == "zh":
        return [
            f"基于 {target_text} 补充或调整与当前结论直接相关的代码；如果上一轮 work branch 仍然适合继续，可直接从该分支推进，不必强制从 main 重新切出。",
            "对这些代码改动运行最小必要的实验或验证；只有在确实能推进用户原始目标时才增加新的实验。",
            "补全文档，更新 result.md、summary.md 和共享资产，记录改了哪些代码、跑了哪些实验、结论如何支撑当前任务。",
        ]
    fallback_target_text = (
        target_text if targets else "the implementation directly tied to the current result"
    )
    return [
        f"Update the code directly tied to the current result, focusing on {fallback_target_text}; if the previous work branch is still the right base, continue from it instead of forcing a fresh branch from main.",
        "Run only the smallest experiments or checks needed for those code changes, and add new experiments only when they materially advance the user's goal.",
        "Finish the documentation by updating result.md, summary.md, and the shared asset with the code changes, validation steps, and the conclusion they support.",
    ]


def summarize_execution_outputs(
    run_dir: Path,
    plan_id: str,
    *,
    goal_language: str,
    goal_text: str | None = None,
) -> tuple[str, list[str], list[str], list[str]]:
    if goal_language == "zh":
        missing_report = "执行已完成，但没有找到结果报告。请直接检查 executor 日志。"
        empty_report = "执行已完成，但结果报告为空。"
        write_report = "先打开 executor 输出并补写结构化结果报告，再据此决定代码、实验和文档上的下一步。"
        rerun_report = "重新执行 executor，或检查结果报告为什么为空，然后补出下一步需要改的代码、实验和文档。"
    else:
        missing_report = (
            "Execution finished, but no result report was found. Inspect the executor logs directly."
        )
        empty_report = "Execution finished, but the result report is empty."
        write_report = "Open the executor output and write a structured result report first, then derive the next code, experiment, and documentation steps from it."
        rerun_report = "Re-run the executor or inspect why the result report was empty, then spell out the next code, experiment, and documentation steps."
    paths = plan_paths(run_dir, plan_id)
    result_path = paths.result
    codex_last_path = paths.codex_last
    source_path = result_path if result_path.exists() else codex_last_path
    if not source_path.exists():
        return (
            missing_report,
            [relative_to_run(paths.codex_events, run_dir)],
            [relative_to_run(paths.command, run_dir)],
            [write_report],
        )

    content = read_text(source_path).strip()
    if not content:
        return (
            f"{empty_report.rstrip('.')} ({source_path.name}).",
            [
                relative_to_run(paths.codex_events, run_dir),
                relative_to_run(source_path, run_dir),
            ],
            [relative_to_run(paths.command, run_dir)],
            [rerun_report],
        )

    outcome = _extract_markdown_section(content, "# Outcome")
    if not outcome:
        paragraphs = [block.strip() for block in content.split("\n\n") if block.strip()]
        outcome = (
            paragraphs[0]
            if paragraphs
            else "Execution finished. Inspect the attached report for details."
        )
    outcome = " ".join(outcome.split())

    evidence = _extract_list_items(_extract_markdown_section(content, "# Evidence"))
    if not evidence:
        evidence = [
            relative_to_run(source_path, run_dir),
            relative_to_run(paths.codex_events, run_dir),
        ]

    artifacts = _extract_list_items(_extract_markdown_section(content, "# Artifacts"))
    if not artifacts:
        artifacts = [
            relative_to_run(paths.command, run_dir),
            relative_to_run(source_path, run_dir),
        ]

    next_iteration = _extract_list_items(
        _extract_markdown_section(content, "# Next Iteration")
    )
    if not next_iteration:
        next_iteration = _fallback_next_iteration(
            goal_language=goal_language,
            source_content=content,
            evidence=evidence,
            artifacts=artifacts,
        )

    return outcome, evidence, artifacts, next_iteration


def write_summary(
    run_dir: Path,
    plan_id: str,
    status: str,
    outcome: str | None = None,
    evidence: list[str] | None = None,
    artifacts: list[str] | None = None,
    next_iteration: list[str] | None = None,
) -> Path:
    logger.info("Writing summary for {}", plan_id)
    manifest = load_manifest(run_dir)
    goal_text: str | None = None
    if manifest.goal_file:
        goal_path = Path(manifest.goal_file)
        if goal_path.exists():
            goal_text = read_text(goal_path)
    if (
        not outcome
        or "placeholder" in outcome.strip().lower()
        or not evidence
        or not artifacts
        or not next_iteration
    ):
        outcome, evidence, artifacts, next_iteration = summarize_execution_outputs(
            run_dir,
            plan_id,
            goal_language=manifest.goal_language,
            goal_text=goal_text,
        )
    paths = plan_paths(run_dir, plan_id, ensure=True)
    git_report_path = paths.git_report
    if git_report_path.exists():
        git_artifact = relative_to_run(git_report_path, run_dir)
        if git_artifact not in artifacts:
            artifacts = [*artifacts, git_artifact]
        git_evidence = (
            f"git:{manifest.work_branch}@{manifest.latest_work_commit}"
            if manifest.work_branch and manifest.latest_work_commit
            else None
        )
        if git_evidence and git_evidence not in evidence:
            evidence = [*evidence, git_evidence]
    summary = render_summary_markdown(
        run_id=run_dir.name,
        plan_id=plan_id,
        status=status,
        outcome=outcome,
        evidence=evidence,
        artifacts=artifacts,
        next_iteration=next_iteration,
        goal_language=manifest.goal_language,
        work_branch=manifest.work_branch,
        work_commit=manifest.latest_work_commit,
    )
    errors = validate_summary_markdown(summary)
    if errors:
        raise ValueError("; ".join(errors))
    summary_path = paths.summary
    write_text(summary_path, summary)
    append_jsonl(
        run_dir / "logs" / "iteration-agent.jsonl",
        {
            "ts": utc_now(),
            "level": "INFO",
            "event": "summary_written",
            "plan_id": plan_id,
        },
    )
    upsert_plan_index_record(
        run_dir=run_dir,
        plan_id=plan_id,
        parent_plan_id=None,
        plan_kind="",
        status=status,
        short_summary=outcome,
        artifacts=[relative_to_run(summary_path, run_dir), *artifacts],
    )
    update_repo_asset(
        run_dir=run_dir,
        plan_id=plan_id,
        status=status,
        outcome=outcome,
        evidence=evidence,
        artifacts=artifacts,
        next_iteration=next_iteration,
    )
    try:
        from mylab.services.telegram_bot import push_summary_to_telegram

        push_summary_to_telegram(
            run_dir,
            plan_id,
            summary_path,
            summary_content=summary,
        )
    except Exception:
        logger.exception("Failed to push summary to Telegram for {}", plan_id)
    return summary_path
