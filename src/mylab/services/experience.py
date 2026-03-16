from __future__ import annotations

from pathlib import Path

from mylab.logging import logger
from mylab.storage import append_jsonl, read_text, write_text
from mylab.storage.runs import load_manifest
from mylab.utils import slugify, utc_now


def repo_experience_path(run_dir: Path) -> Path:
    manifest = load_manifest(run_dir)
    repo_key = slugify(manifest.repo_path)
    return run_dir.parent / "experience" / f"{repo_key}.md"


def load_repo_experience(run_dir: Path) -> str:
    path = repo_experience_path(run_dir)
    if not path.exists():
        return ""
    return read_text(path).strip()


def render_experience_entry(
    *,
    run_id: str,
    plan_id: str,
    status: str,
    outcome: str,
    evidence: list[str],
    artifacts: list[str],
    next_iteration: list[str],
) -> str:
    return "\n".join(
        [
            f"## {utc_now()} | {run_id} | {plan_id}",
            f"- status: {status}",
            f"- outcome: {outcome.strip()}",
            "- evidence:",
            *[f"  - {item}" for item in evidence],
            "- artifacts:",
            *[f"  - {item}" for item in artifacts],
            "- next_iteration:",
            *[f"  - {item}" for item in next_iteration],
        ]
    )


def update_repo_experience(
    *,
    run_dir: Path,
    plan_id: str,
    status: str,
    outcome: str,
    evidence: list[str],
    artifacts: list[str],
    next_iteration: list[str],
) -> Path:
    manifest = load_manifest(run_dir)
    path = repo_experience_path(run_dir)
    logger.info("Updating repository experience memory at {}", path)
    current = load_repo_experience(run_dir)
    header = "\n".join(
        [
            "# Repository Experience Memory",
            f"- repo_path: {manifest.repo_path}",
            f"- updated_at: {utc_now()}",
            "",
            "Keep only reusable lessons, observed failures, and proven tactics from prior runs.",
            "",
        ]
    )
    entry = render_experience_entry(
        run_id=manifest.run_id,
        plan_id=plan_id,
        status=status,
        outcome=outcome,
        evidence=evidence,
        artifacts=artifacts,
        next_iteration=next_iteration,
    )
    existing_entries = ""
    if current:
        marker = "\n## "
        if current.startswith("## "):
            existing_entries = current
        elif marker in current:
            existing_entries = current[current.index(marker) + 1 :].strip()
    content_parts = [header.rstrip()]
    if existing_entries:
        content_parts.extend([existing_entries, entry])
    else:
        content_parts.append(entry)
    content = "\n\n".join(part.strip() for part in content_parts if part.strip())
    write_text(path, content)
    append_jsonl(
        run_dir / "logs" / "experience-agent.jsonl",
        {
            "ts": utc_now(),
            "level": "INFO",
            "event": "experience_updated",
            "plan_id": plan_id,
            "experience_path": str(path),
        },
    )
    return path
