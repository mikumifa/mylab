from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from mylab.config import PLAN_HEADINGS, RUNS_ENV_VAR
from mylab.domain import RunManifest, RunPaths
from mylab.storage import append_jsonl, read_text, write_text
from mylab.storage.runs import save_manifest
from mylab.utils import detect_git_branch, slugify, utc_now


def make_run_id(goal_text: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_{slugify(goal_text)}"


def lab_input_text(goal: str | None, lab_md: Path | None) -> str:
    if goal:
        return goal.strip()
    if lab_md:
        return read_text(lab_md).strip()
    raise ValueError("either goal or lab_md must be provided")


def next_plan_index(plans_dir: Path) -> int:
    existing = sorted(plans_dir.glob("plan-*.md"))
    if not existing:
        return 1
    last = existing[-1].stem.split("-")[-1]
    return int(last) + 1


def heuristic_questions(goal_text: str) -> list[str]:
    return [
        f"What exact hypothesis or claim is this experiment testing: {goal_text[:80]}?",
        "What baseline, branch, or prior implementation should be compared?",
        "Which metrics and saved artifacts are required to judge success or failure?",
    ]


def heuristic_steps(repo_path: Path) -> list[str]:
    return [
        f"Checkout the source branch and inspect the tracked repository at {repo_path}.",
        "Implement code and script changes needed for the experiment without hardcoding output paths.",
        "Run the experiment, preserve raw logs, and collect all intermediate outputs.",
        "Write a structured summary that states observed results, failures, and next actions.",
    ]


def default_deliverables(plan_id: str) -> list[str]:
    return [
        f"Structured execution log for {plan_id}.",
        f"Result summary for {plan_id}.",
        f"Patched code and runnable scripts for {plan_id}.",
    ]


def render_plan_markdown(
    *,
    plan_id: str,
    parent_plan_id: str | None,
    run_id: str,
    repo_path: Path,
    source_branch: str,
    goal_text: str,
    questions: list[str],
    steps: list[str],
    deliverables: list[str],
) -> str:
    parent_value = parent_plan_id or "none"
    return f"""# Plan Metadata
- plan_id: {plan_id}
- parent_plan_id: {parent_value}
- run_id: {run_id}
- repo_path: {repo_path}
- source_branch: {source_branch}
- generated_at: {utc_now()}

# Experiment Goal
{goal_text.strip()}

# Investigation Questions
{chr(10).join(f"{index}. {item}" for index, item in enumerate(questions, start=1))}

# Execution Plan
{chr(10).join(f"{index}. {item}" for index, item in enumerate(steps, start=1))}

# Deliverables
{chr(10).join(f"{index}. {item}" for index, item in enumerate(deliverables, start=1))}

# Result Collection Rules
1. All intermediate artifacts must be written under the run directory only.
2. Every code change must be tied to this plan ID in logs or commit notes.
3. Raw execution logs must be preserved without truncation.
4. Final summaries must reference concrete artifact paths.
"""


def validate_plan_markdown(content: str) -> list[str]:
    missing = [heading for heading in PLAN_HEADINGS if heading not in content]
    errors = [f"missing required heading: {heading}" for heading in missing]
    for needle in ("- plan_id:", "- run_id:", "- repo_path:", "- source_branch:"):
        if needle not in content:
            errors.append(f"missing metadata field: {needle}")
    return errors


def bootstrap_run(
    *,
    repo_path: Path,
    goal_text: str,
    run_id: str,
    paths: RunPaths,
    source_branch: str | None = None,
    input_file_name: str = "goal.txt",
) -> RunManifest:
    resolved_branch = source_branch or detect_git_branch(repo_path)
    goal_file = paths.inputs / input_file_name
    write_text(goal_file, goal_text)
    manifest = RunManifest(
        run_id=run_id,
        repo_path=str(repo_path),
        source_branch=resolved_branch,
        goal_file=str(goal_file),
        runs_env_var=RUNS_ENV_VAR,
        original_branch=resolved_branch,
    )
    save_manifest(paths, manifest)
    append_jsonl(
        paths.logs / "run-lifecycle.jsonl",
        {"ts": utc_now(), "event": "run_bootstrapped", "run_id": run_id, "repo_path": str(repo_path)},
    )
    return manifest


def create_initial_plan(paths: RunPaths, manifest: RunManifest) -> Path:
    goal_text = read_text(Path(manifest.goal_file)).strip()
    plan_id = f"plan-{next_plan_index(paths.plans):03d}"
    plan_path = paths.plans / f"{plan_id}.md"
    prompt_path = paths.prompts / f"{plan_id}.planner.prompt.md"
    content = render_plan_markdown(
        plan_id=plan_id,
        parent_plan_id=None,
        run_id=manifest.run_id,
        repo_path=Path(manifest.repo_path),
        source_branch=manifest.source_branch,
        goal_text=goal_text,
        questions=heuristic_questions(goal_text),
        steps=heuristic_steps(Path(manifest.repo_path)),
        deliverables=default_deliverables(plan_id),
    )
    errors = validate_plan_markdown(content)
    if errors:
        raise ValueError("; ".join(errors))
    write_text(plan_path, content)
    write_text(
        prompt_path,
        "\n".join(
            [
                f"You are planner agent 1 for run {manifest.run_id}.",
                "Refine the plan without changing the required markdown headings.",
                f"Repository: {manifest.repo_path}",
                f"Source branch: {manifest.source_branch}",
                f"Write the final result back to: {plan_path}",
                "",
                content,
            ]
        ),
    )
    manifest.latest_plan_id = plan_id
    save_manifest(paths, manifest)
    append_jsonl(
        paths.logs / "agent1-planner.jsonl",
        {"ts": utc_now(), "level": "INFO", "event": "plan_created", "plan_id": plan_id},
    )
    return plan_path


def create_iterated_plan(paths: RunPaths, manifest: RunManifest, parent_plan_id: str, feedback: str) -> Path:
    goal_text = read_text(Path(manifest.goal_file)).strip()
    plan_id = f"plan-{next_plan_index(paths.plans):03d}"
    plan_path = paths.plans / f"{plan_id}.md"
    parent_plan_path = paths.plans / f"{parent_plan_id}.md"
    if not parent_plan_path.exists():
        raise FileNotFoundError(f"missing parent plan: {parent_plan_path}")
    content = render_plan_markdown(
        plan_id=plan_id,
        parent_plan_id=parent_plan_id,
        run_id=manifest.run_id,
        repo_path=Path(manifest.repo_path),
        source_branch=manifest.source_branch,
        goal_text=goal_text,
        questions=heuristic_questions(f"{goal_text} | feedback: {feedback}"),
        steps=[
            "Review the previous plan, execution logs, and preserved artifacts.",
            f"Use this feedback to update priorities: {feedback}",
            "Define the next smallest defensible code or experiment change.",
            "Preserve comparability with the parent plan and summarize deltas clearly.",
        ],
        deliverables=default_deliverables(plan_id),
    )
    errors = validate_plan_markdown(content)
    if errors:
        raise ValueError("; ".join(errors))
    write_text(plan_path, content)
    manifest.latest_plan_id = plan_id
    manifest.current_iteration += 1
    save_manifest(paths, manifest)
    append_jsonl(
        paths.logs / "agent2-iterator.jsonl",
        {
            "ts": utc_now(),
            "level": "INFO",
            "event": "plan_iterated",
            "plan_id": plan_id,
            "parent_plan_id": parent_plan_id,
        },
    )
    return plan_path
