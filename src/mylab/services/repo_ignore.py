from __future__ import annotations

from pathlib import Path

from mylab.logging import logger


def _normalize_gitignore_entry(relative_path: Path) -> str:
    value = relative_path.as_posix().strip("/")
    if not value:
        return ""
    return f"/{value}/"


def ensure_run_dir_ignored(repo_path: Path, run_dir: Path) -> tuple[bool, str]:
    repo_path = repo_path.resolve()
    run_dir = run_dir.resolve()
    try:
        relative = run_dir.relative_to(repo_path)
    except ValueError:
        return False, ""

    target_relative = Path(relative.parts[0])
    entry = _normalize_gitignore_entry(target_relative)
    if not entry:
        return False, ""

    gitignore_path = repo_path / ".gitignore"
    if gitignore_path.exists():
        lines = gitignore_path.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    normalized_lines = {line.strip() for line in lines}
    if entry in normalized_lines:
        return False, entry

    logger.info("Adding {} to {}", entry, gitignore_path)
    new_lines = list(lines)
    if new_lines and new_lines[-1].strip():
        new_lines.append("")
    new_lines.append(entry)
    gitignore_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return True, entry
