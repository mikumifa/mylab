from __future__ import annotations

import json
from pathlib import Path

from mylab.logging import logger
from mylab.storage import append_jsonl, read_text, write_text
from mylab.storage.trial_layout import trial_paths, relative_to_run
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


def _extract_stable_notes(current: str) -> str:
    if not current:
        return _default_stable_notes()
    stable_marker = "## Stable Notes"
    if stable_marker in current:
        stable_start = current.index(stable_marker) + len(stable_marker)
        tail = current[stable_start:]
        if "\n## " in tail:
            tail = tail.split("\n## ", 1)[0]
        return tail.strip() or _default_stable_notes()
    return _default_stable_notes()


def update_repo_asset(
    *,
    run_dir: Path,
    trial_id: str,
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
    stable_notes = _extract_stable_notes(current)
    content = "\n".join(
        [
            "# Repository Shared Asset",
            f"- repo_path: {manifest.repo_path}",
            f"- updated_at: {utc_now()}",
            "",
            "This file stores reusable repository-level runbook knowledge only.",
            "Keep stable operating notes, output constraints, code map hints, and recurring pitfalls here.",
            "Do not store task-specific hypotheses, experiment results, or next-step conclusions in this file.",
            "",
            "## Stable Notes",
            stable_notes.strip(),
        ]
    )
    write_text(path, content)
    append_jsonl(
        run_dir / "logs" / "iteration-agent.jsonl",
        {
            "ts": utc_now(),
            "level": "INFO",
            "event": "repo_asset_updated",
            "trial_id": trial_id,
            "asset_path": str(path),
        },
    )
    return path


def trial_index_jsonl_path(run_dir: Path) -> Path:
    return run_dir / "trials" / "index.jsonl"


def trial_index_markdown_path(run_dir: Path) -> Path:
    return run_dir / "trials" / "index.md"


def _load_trial_index_records(run_dir: Path) -> list[dict[str, str]]:
    path = trial_index_jsonl_path(run_dir)
    if not path.exists():
        return []
    records: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    return records


def _write_trial_index(run_dir: Path, records: list[dict[str, str]]) -> None:
    jsonl_path = trial_index_jsonl_path(run_dir)
    markdown_path = trial_index_markdown_path(run_dir)
    lines = [json.dumps(record, ensure_ascii=True) for record in records]
    write_text(jsonl_path, "\n".join(lines) if lines else "")
    markdown_lines = [
        "# Trial Catalog",
        f"- run_id: {run_dir.name}",
        f"- updated_at: {utc_now()}",
        "",
    ]
    for record in records:
        markdown_lines.extend(
            [
                f"## {record['trial_id']}",
                f"- trial_kind: {record.get('trial_kind', 'unknown')}",
                f"- status: {record['status']}",
                f"- goal_summary: {record.get('goal_summary', '-')}",
                f"- trial_essence: {record.get('trial_essence', '-')}",
                f"- decision_focus: {record.get('decision_focus', '-')}",
                f"- expected_signal: {record.get('expected_signal', '-')}",
                f"- code_checkpoint: {record.get('code_checkpoint', '-')}",
                f"- code_checkpoint_ref: {record.get('code_checkpoint_ref', '-')}",
                f"- trial_path: {record.get('trial_path', '-')}",
                f"- summary_path: {record.get('summary_path', '-')}",
                f"- short_summary: {record.get('short_summary', '-')}",
                "",
            ]
        )
    write_text(markdown_path, "\n".join(markdown_lines))


def upsert_trial_index_record(
    *,
    run_dir: Path,
    trial_id: str,
    parent_trial_id: str | None,
    trial_kind: str,
    status: str,
    short_summary: str,
    artifacts: list[str],
    goal_summary: str | None = None,
    trial_essence: str | None = None,
    decision_focus: str | None = None,
    expected_signal: str | None = None,
    code_checkpoint: str | None = None,
    code_checkpoint_ref: str | None = None,
) -> None:
    records = _load_trial_index_records(run_dir)
    by_plan = {record["trial_id"]: record for record in records}
    previous = by_plan.get(trial_id, {})
    paths = trial_paths(run_dir, trial_id)
    by_plan[trial_id] = {
        "trial_id": trial_id,
        "parent_trial_id": parent_trial_id or previous.get("parent_trial_id", ""),
        "trial_kind": trial_kind or previous.get("trial_kind", "unknown"),
        "status": status,
        "short_summary": " ".join(short_summary.split()),
        "goal_summary": " ".join(
            (goal_summary or previous.get("goal_summary", "")).split()
        ),
        "trial_essence": " ".join(
            (trial_essence or previous.get("trial_essence", "")).split()
        ),
        "decision_focus": " ".join(
            (decision_focus or previous.get("decision_focus", "")).split()
        ),
        "expected_signal": " ".join(
            (expected_signal or previous.get("expected_signal", "")).split()
        ),
        "code_checkpoint": " ".join(
            (code_checkpoint or previous.get("code_checkpoint", "")).split()
        ),
        "code_checkpoint_ref": " ".join(
            (code_checkpoint_ref or previous.get("code_checkpoint_ref", "")).split()
        ),
        "trial_path": relative_to_run(paths.trial, run_dir),
        "summary_path": relative_to_run(paths.summary, run_dir),
        "artifacts": ", ".join(" ".join(item.split()) for item in artifacts),
        "updated_at": utc_now(),
    }
    ordered = [by_plan[key] for key in sorted(by_plan)]
    _write_trial_index(run_dir, ordered)
    append_jsonl(
        run_dir / "logs" / "iteration-agent.jsonl",
        {
            "ts": utc_now(),
            "level": "INFO",
            "event": "trial_index_updated",
            "trial_id": trial_id,
            "status": status,
        },
    )


def render_trial_catalog(run_dir: Path) -> str:
    records = _load_trial_index_records(run_dir)
    if not records:
        return "(no prior trials yet)"
    lines = ["Available trial key info:"]
    for record in records:
        lines.extend(
            [
                f"- {record['trial_id']} [{record.get('trial_kind', 'unknown')}] status={record['status']}",
                f"  goal_summary: {record.get('goal_summary', '-') or '-'}",
                f"  trial_essence: {record.get('trial_essence', '-') or '-'}",
                f"  decision_focus: {record.get('decision_focus', '-') or '-'}",
                f"  expected_signal: {record.get('expected_signal', '-') or '-'}",
                f"  code_checkpoint: {record.get('code_checkpoint', '-') or '-'} ({record.get('code_checkpoint_ref', '-') or '-'})",
                f"  trial_path: {record.get('trial_path', '-') or '-'}",
                f"  summary_path: {record.get('summary_path', '-') or '-'}",
            ]
        )
    return "\n".join(lines)
