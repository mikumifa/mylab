from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mylab.config import ROOT
from mylab.storage import read_text


@dataclass(frozen=True)
class PlanSkillProfile:
    skill_name: str
    plan_kind: str
    description: str
    flow: list[str]
    frontmatter_essence: list[str]
    plan_body_rules: list[str]
    reference_files: list[str]
    skill_path: Path


def _skill_path(skill_name: str) -> Path:
    return ROOT / ".codex" / "skills" / skill_name / "SKILL.md"


def _parse_frontmatter(content: str) -> dict[str, str]:
    if not content.startswith("---\n"):
        return {}
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}
    payload: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        payload[key.strip()] = value.strip()
    return payload


def _section_items(content: str, heading: str) -> list[str]:
    lines = content.splitlines()
    capture = False
    items: list[str] = []
    for raw_line in lines:
        line = raw_line.rstrip()
        if line.strip() == heading:
            capture = True
            continue
        if capture and line.startswith("## "):
            break
        if not capture:
            continue
        stripped = line.strip()
        if len(stripped) > 3 and stripped[0].isdigit() and stripped[1:3] == ". ":
            items.append(stripped[3:].strip())
        elif stripped.startswith("- "):
            items.append(stripped[2:].strip())
    return [item for item in items if item]


def load_plan_skill(skill_name: str) -> PlanSkillProfile:
    path = _skill_path(skill_name)
    content = read_text(path)
    meta = _parse_frontmatter(content)
    return PlanSkillProfile(
        skill_name=meta.get("name", skill_name),
        plan_kind=meta.get("plan_kind", skill_name),
        description=meta.get("description", ""),
        flow=_section_items(content, "## Flow"),
        frontmatter_essence=_section_items(content, "## Frontmatter Essence"),
        plan_body_rules=_section_items(content, "## Plan Body Rules"),
        reference_files=_section_items(content, "## Reference Files"),
        skill_path=path,
    )


def infer_plan_skill(goal_text: str, feedback: str | None = None) -> PlanSkillProfile:
    text = "\n".join(part for part in [goal_text, feedback or ""] if part).lower()
    parameter_markers = [
        "调参",
        "参数",
        "超参",
        "parameter",
        "hyperparameter",
        "sweep",
        "grid search",
        "search space",
        "batch experiment",
        "batch experiments",
    ]
    if any(marker in text for marker in parameter_markers):
        return load_plan_skill("mylab-parameter-tuning")
    return load_plan_skill("mylab-structure-tuning")
