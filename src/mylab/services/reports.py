from __future__ import annotations

from pathlib import Path

from mylab.config import SUMMARY_HEADINGS
from mylab.logging import logger
from mylab.services.assets import update_repo_asset, upsert_plan_index_record
from mylab.storage import append_jsonl, write_text
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
) -> str:
    return f"""# Summary Metadata
- run_id: {run_id}
- plan_id: {plan_id}
- status: {status}
- generated_at: {utc_now()}

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


def write_summary(
    run_dir: Path,
    plan_id: str,
    status: str,
    outcome: str,
    evidence: list[str],
    artifacts: list[str],
    next_iteration: list[str],
) -> Path:
    logger.info("Writing summary for {}", plan_id)
    summary = render_summary_markdown(
        run_id=run_dir.name,
        plan_id=plan_id,
        status=status,
        outcome=outcome,
        evidence=evidence,
        artifacts=artifacts,
        next_iteration=next_iteration,
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
