from __future__ import annotations

from pathlib import Path

from mylab.config import ROOT


def skills_root() -> Path:
    source_root = ROOT / ".codex" / "skills"
    if source_root.exists():
        return source_root
    return Path(__file__).resolve().parent / "skills"


def skill_dir(skill_name: str) -> Path:
    return skills_root() / skill_name
