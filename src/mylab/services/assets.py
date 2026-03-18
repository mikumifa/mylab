from __future__ import annotations

import json
from pathlib import Path

from mylab.logging import logger
from mylab.storage import append_jsonl, read_text, write_text
from mylab.storage.plan_layout import plan_paths, relative_to_run
from mylab.storage.runs import load_manifest
from mylab.utils import slugify, utc_now


def legacy_repo_experience_path(run_dir: Path) -> Path:
    manifest = load_manifest(run_dir)
    repo_key = slugify(manifest.repo_path)
    return run_dir.parent / "experience" / f"{repo_key}.md"


def repo_asset_path(run_dir: Path) -> Path:
    return run_dir / "assets" / "repo.md"


def load_repo_asset(run_dir: Path) -> str:
    asset_path = repo_asset_path(run_dir)
    if asset_path.exists():
        return read_text(asset_path).strip()
    manifest = load_manifest(run_dir)
    repo_key = slugify(manifest.repo_path)
    legacy_run_asset = run_dir / "assets" / f"{repo_key}.md"
    if legacy_run_asset.exists():
        return read_text(legacy_run_asset).strip()
    legacy_shared_asset = run_dir.parent / "assets" / f"{repo_key}.md"
    if legacy_shared_asset.exists():
        return read_text(legacy_shared_asset).strip()
    legacy_path = legacy_repo_experience_path(run_dir)
    if legacy_path.exists():
        return read_text(legacy_path).strip()
    return ""


def _default_stable_notes() -> str:
    return "\n".join(
        [
            "- How to run the repository: unknown",
            "- Configurable output root: unknown",
            "- Important code locations: unknown",
            "- Repeated pitfalls: unknown",
            "- Reusable commands or scripts: unknown",
        ]
    )


def _split_asset_sections(current: str) -> tuple[str, str]:
    if not current:
        return _default_stable_notes(), ""
    stable_marker = "## Stable Notes"
    iteration_marker = "## Iteration Notes"
    if stable_marker in current and iteration_marker in current:
        stable_start = current.index(stable_marker) + len(stable_marker)
        iteration_start = current.index(iteration_marker)
        stable = (
            current[stable_start:iteration_start].strip() or _default_stable_notes()
        )
        iterations = current[iteration_start + len(iteration_marker) :].strip()
        return stable, iterations
    if current.startswith("# Repository Experience Memory"):
        marker = "\n## "
        if marker in current:
            iterations = current[current.index(marker) + 1 :].strip()
            return _default_stable_notes(), iterations
    return _default_stable_notes(), current.strip()


def render_asset_entry(
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
            f"### {utc_now()} | {run_id} | {plan_id}",
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


def update_repo_asset(
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
    path = repo_asset_path(run_dir)
    logger.info("Updating repository shared asset at {}", path)
    current = load_repo_asset(run_dir)
    stable_notes, iteration_notes = _split_asset_sections(current)
    entry = render_asset_entry(
        run_id=manifest.run_id,
        plan_id=plan_id,
        status=status,
        outcome=outcome,
        evidence=evidence,
        artifacts=artifacts,
        next_iteration=next_iteration,
    )
    iterations = [part.strip() for part in (iteration_notes, entry) if part.strip()]
    content = "\n".join(
        [
            "# Repository Shared Asset",
            f"- repo_path: {manifest.repo_path}",
            f"- updated_at: {utc_now()}",
            "",
            "This file stores reusable repository knowledge across all iterations.",
            "Keep operational notes, code map hints, pitfalls, and the shortest durable result memory here.",
            "",
            "## Stable Notes",
            stable_notes.strip(),
            "",
            "## Iteration Notes",
            "",
            "\n\n".join(iterations).strip() or "(none yet)",
        ]
    )
    write_text(path, content)
    append_jsonl(
        run_dir / "logs" / "iteration-agent.jsonl",
        {
            "ts": utc_now(),
            "level": "INFO",
            "event": "repo_asset_updated",
            "plan_id": plan_id,
            "asset_path": str(path),
        },
    )
    return path


def plan_index_jsonl_path(run_dir: Path) -> Path:
    return run_dir / "plans" / "index.jsonl"


def plan_index_markdown_path(run_dir: Path) -> Path:
    return run_dir / "plans" / "index.md"


def _load_plan_index_records(run_dir: Path) -> list[dict[str, str]]:
    path = plan_index_jsonl_path(run_dir)
    if not path.exists():
        return []
    records: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    return records


def _write_plan_index(run_dir: Path, records: list[dict[str, str]]) -> None:
    jsonl_path = plan_index_jsonl_path(run_dir)
    markdown_path = plan_index_markdown_path(run_dir)
    lines = [json.dumps(record, ensure_ascii=True) for record in records]
    write_text(jsonl_path, "\n".join(lines) if lines else "")
    markdown_lines = [
        "# Plan Index",
        f"- run_id: {run_dir.name}",
        f"- updated_at: {utc_now()}",
        "",
        "| plan_id | kind | parent | status | plan_path | summary_path | short_summary |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for record in records:
        short_summary = " ".join(record["short_summary"].split()).replace("|", "/")
        markdown_lines.append(
            "| {plan_id} | {plan_kind} | {parent_plan_id} | {status} | {plan_path} | {summary_path} | {short_summary} |".format(
                plan_id=record["plan_id"],
                plan_kind=record.get("plan_kind", "unknown"),
                parent_plan_id=record["parent_plan_id"] or "-",
                status=record["status"],
                plan_path=record.get("plan_path", "-").replace("|", "/"),
                summary_path=record.get("summary_path", "-").replace("|", "/"),
                short_summary=short_summary,
            )
        )
    write_text(markdown_path, "\n".join(markdown_lines))


def upsert_plan_index_record(
    *,
    run_dir: Path,
    plan_id: str,
    parent_plan_id: str | None,
    plan_kind: str,
    status: str,
    short_summary: str,
    artifacts: list[str],
) -> None:
    records = _load_plan_index_records(run_dir)
    by_plan = {record["plan_id"]: record for record in records}
    previous = by_plan.get(plan_id, {})
    paths = plan_paths(run_dir, plan_id)
    by_plan[plan_id] = {
        "plan_id": plan_id,
        "parent_plan_id": parent_plan_id or previous.get("parent_plan_id", ""),
        "plan_kind": plan_kind or previous.get("plan_kind", "unknown"),
        "status": status,
        "short_summary": " ".join(short_summary.split()),
        "plan_path": relative_to_run(paths.plan, run_dir),
        "summary_path": relative_to_run(paths.summary, run_dir),
        "artifacts": ", ".join(" ".join(item.split()) for item in artifacts),
        "updated_at": utc_now(),
    }
    ordered = [by_plan[key] for key in sorted(by_plan)]
    _write_plan_index(run_dir, ordered)
    append_jsonl(
        run_dir / "logs" / "iteration-agent.jsonl",
        {
            "ts": utc_now(),
            "level": "INFO",
            "event": "plan_index_updated",
            "plan_id": plan_id,
            "status": status,
        },
    )
