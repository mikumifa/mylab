from __future__ import annotations

from pathlib import Path

from mylab.config import SUMMARY_HEADINGS
from mylab.logging import logger
from mylab.services.assets import update_repo_asset, upsert_plan_index_record
from mylab.storage import append_jsonl, read_text, write_text
from mylab.storage.runs import load_manifest
from mylab.utils import utc_now


def should_update_repo_asset(outcome: str, next_iteration: list[str]) -> bool:
    normalized_outcome = outcome.strip().lower()
    if "placeholder" in normalized_outcome:
        return False
    return not any("placeholder" in item.strip().lower() for item in next_iteration)


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


def summarize_execution_outputs(
    run_dir: Path,
    plan_id: str,
    *,
    goal_language: str,
) -> tuple[str, list[str], list[str], list[str]]:
    if goal_language == "zh":
        missing_report = "执行已完成，但没有找到结果报告。请直接检查 executor 日志。"
        empty_report = "执行已完成，但结果报告为空。"
        write_report = "打开 executor 输出并补写结构化结果报告。"
        rerun_report = "重新执行 executor，或检查结果报告为什么为空。"
        review_next = "检查结果报告，并决定下一步最小且可辩护的改动。"
    else:
        missing_report = (
            "Execution finished, but no result report was found. Inspect the executor logs directly."
        )
        empty_report = "Execution finished, but the result report is empty."
        write_report = "Open the executor output and write a structured result report."
        rerun_report = "Re-run the executor or inspect why the result report was empty."
        review_next = (
            "Review the result report and decide the next smallest defensible change."
        )
    result_path = run_dir / "results" / f"{plan_id}.result.md"
    codex_last_path = run_dir / "results" / f"{plan_id}.codex.last.md"
    source_path = result_path if result_path.exists() else codex_last_path
    if not source_path.exists():
        return (
            missing_report,
            [f"logs/{plan_id}.codex.events.jsonl"],
            [f"commands/{plan_id}.executor.sh"],
            [write_report],
        )

    content = read_text(source_path).strip()
    if not content:
        return (
            f"{empty_report.rstrip('.')} ({source_path.name}).",
            [
                f"logs/{plan_id}.codex.events.jsonl",
                str(source_path.relative_to(run_dir)),
            ],
            [f"commands/{plan_id}.executor.sh"],
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
            str(source_path.relative_to(run_dir)),
            f"logs/{plan_id}.codex.events.jsonl",
        ]

    artifacts = _extract_list_items(_extract_markdown_section(content, "# Artifacts"))
    if not artifacts:
        artifacts = [
            f"commands/{plan_id}.executor.sh",
            str(source_path.relative_to(run_dir)),
        ]

    next_iteration = _extract_list_items(
        _extract_markdown_section(content, "# Next Iteration")
    )
    if not next_iteration:
        next_iteration = [review_next]

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
    if (
        not outcome
        or "placeholder" in outcome.strip().lower()
        or not evidence
        or not artifacts
        or not next_iteration
    ):
        outcome, evidence, artifacts, next_iteration = summarize_execution_outputs(
            run_dir, plan_id, goal_language=manifest.goal_language
        )
    git_report_path = run_dir / "results" / f"{plan_id}.git.md"
    if git_report_path.exists():
        git_artifact = str(git_report_path.relative_to(run_dir))
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
    summary_path = run_dir / "summaries" / f"{plan_id}.summary.md"
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
        status=status,
        short_summary=outcome,
        artifacts=[str(summary_path), *artifacts],
    )
    if should_update_repo_asset(outcome, next_iteration):
        update_repo_asset(
            run_dir=run_dir,
            plan_id=plan_id,
            status=status,
            outcome=outcome,
            evidence=evidence,
            artifacts=artifacts,
            next_iteration=next_iteration,
        )
    return summary_path
