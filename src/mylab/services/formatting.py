from __future__ import annotations

from pathlib import Path

from mylab.storage import append_jsonl, write_text
from mylab.storage.runs import load_manifest
from mylab.utils import list_tracked_files, utc_now


def format_repo_report(repo_path: Path, run_dir: Path) -> Path:
    report = run_dir / "results" / "format-audit.md"
    suspicious = [
        item
        for item in list_tracked_files(repo_path)
        if "output" in item.lower() or "result" in item.lower() or "log" in item.lower()
    ]
    content = "\n".join(
        [
            "# Repo Format Audit",
            "",
            f"- repo_path: {repo_path}",
            f"- generated_at: {utc_now()}",
            "",
            "## Findings",
            "1. Ensure code writes experiment outputs under a configurable root directory.",
            "2. Ensure scripts expose output locations through CLI args or environment variables.",
            "3. Ensure run logs preserve stdout, stderr, and executed command lines.",
            "",
            "## Files To Inspect",
            *[f"- {item}" for item in suspicious[:50]],
        ]
    )
    write_text(report, content)
    return report


def format_for_manifest(run_dir: Path) -> Path:
    manifest = load_manifest(run_dir)
    report = format_repo_report(Path(manifest.repo_path), run_dir)
    append_jsonl(
        run_dir / "logs" / "format-agent.jsonl",
        {
            "ts": utc_now(),
            "level": "INFO",
            "event": "repo_audited",
            "report": str(report),
        },
    )
    return report
