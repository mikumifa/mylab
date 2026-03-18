from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from mylab.config import PLAN_HEADINGS, RUNS_ENV_VAR
from mylab.domain import RunManifest, RunPaths
from mylab.logging import logger
from mylab.services.assets import load_repo_asset, upsert_plan_index_record
from mylab.services.git_lifecycle import prepare_repo_for_run
from mylab.services.notifications import NotificationSettings
from mylab.services.plan_skills import PlanSkillProfile, infer_plan_skill
from mylab.services.telegram_bot import (
    load_feedback_context,
    load_persistent_feedback_context,
    load_telegram_settings,
)
from mylab.storage import append_jsonl, read_text, write_text
from mylab.storage.plan_layout import plan_paths, relative_to_run
from mylab.storage.runs import init_run_dirs, save_manifest
from mylab.utils import (
    describe_language,
    detect_preferred_language,
    detect_source_branch,
    slugify,
    utc_now,
)


def make_run_id(goal_text: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_{slugify(goal_text)}"


def lab_input_text(goal: str | None, lab_md: Path | None) -> str:
    if goal:
        goal_path = Path(goal).expanduser()
        if goal_path.exists() and goal_path.is_file():
            return read_text(goal_path).strip()
        return goal.strip()
    if lab_md:
        return read_text(lab_md).strip()
    raise ValueError("either goal or lab_md must be provided")


def next_plan_index(plans_dir: Path) -> int:
    suffixes: list[int] = []
    for path in sorted(plans_dir.glob("plan-*")):
        stem = path.stem if path.is_file() else path.name
        if not stem.startswith("plan-"):
            continue
        try:
            suffixes.append(int(stem.split("-")[-1]))
        except ValueError:
            continue
    if not suffixes:
        return 1
    return max(suffixes) + 1


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


def plan_frontmatter_essence(
    *,
    profile: PlanSkillProfile,
    goal_text: str,
    feedback: str | None,
) -> dict[str, str]:
    headline = " ".join(goal_text.strip().split())
    brief_feedback = " ".join((feedback or "").strip().split())
    if profile.plan_kind == "parameter-tuning":
        return {
            "plan_essence": f"Run a comparable parameter batch for: {headline[:160]}",
            "decision_focus": brief_feedback[:160]
            or "Use batch comparison to narrow the next search region.",
            "expected_signal": "A ranked comparison over parameter combinations with a clear next search recommendation.",
            "next_iteration_hook": "Use the ranking result to design the next parameter region or combination set.",
        }
    return {
        "plan_essence": f"Test a structural idea end-to-end for: {headline[:160]}",
        "decision_focus": brief_feedback[:160]
        or "Use implementation, training, evaluation, and analysis to decide the next structural move.",
        "expected_signal": "A structural conclusion grounded in implementation delta, train behavior, eval results, and analysis.",
        "next_iteration_hook": "Use the analysis to propose the next architecture or module combination.",
    }


def profile_questions(
    profile: PlanSkillProfile, goal_text: str, feedback: str | None = None
) -> list[str]:
    if profile.plan_kind == "parameter-tuning":
        return [
            f"Which parameter family or search region matters most for: {goal_text[:80]}?",
            "How will combinations be generated so the batch is comparable and reproducible?",
            "Which metric or ranking rule will choose the next search region?",
        ]
    context = f"{goal_text} | feedback: {feedback}" if feedback else goal_text
    return heuristic_questions(context)


def profile_steps(
    profile: PlanSkillProfile, repo_path: Path, feedback: str | None = None
) -> list[str]:
    if profile.plan_kind == "parameter-tuning":
        steps = [
            f"Inspect the tracked repository at {repo_path} and identify the parameter entrypoints that control this sweep.",
            "Generate the concrete parameter combinations for this round and save them as reusable run inputs under the current plan directory.",
            "Run the batch with preserved raw logs and keep every trial output under the run directory.",
            "Collect the batch results into a comparable table or machine-readable summary.",
            "Compare and rank the combinations, then state which search region should be explored next.",
        ]
        if feedback:
            steps.insert(1, f"Apply this tuning feedback when shaping the batch: {feedback}")
        return steps
    steps = [
        f"Checkout the source branch and inspect the tracked repository at {repo_path}.",
        "Implement the current structural idea as the smallest defensible code delta for this round.",
        "Train the changed system while preserving raw logs and intermediate outputs.",
        "Run evaluation that is comparable with the current baseline or parent plan.",
        "Analyze the outcome and extract the next structural design move for the next iteration.",
    ]
    if feedback:
        steps.insert(1, f"Use this feedback to refine the current design idea before implementation: {feedback}")
    return steps


def profile_deliverables(profile: PlanSkillProfile, plan_id: str) -> list[str]:
    if profile.plan_kind == "parameter-tuning":
        return [
            f"Parameter batch specification for {plan_id}.",
            f"Collected comparison table or aggregated result artifact for {plan_id}.",
            f"Recommendation for the next parameter region based on ranked evidence.",
        ]
    return [
        f"Structural implementation delta and runnable scripts for {plan_id}.",
        f"Train plus eval evidence bundle for {plan_id}.",
        f"Design conclusion and next structural idea for {plan_id}.",
    ]


def _reference_paths_for_plan(run_root: Path, plan_id: str) -> dict[str, str]:
    paths = plan_paths(run_root, plan_id)
    return {
        "shared_asset": relative_to_run(paths.references / "shared-asset.md", run_root),
        "persistent_feedback": relative_to_run(
            paths.references / "persistent-feedback.md", run_root
        ),
        "recent_feedback": relative_to_run(
            paths.references / "recent-feedback.md", run_root
        ),
        "plan_skill": relative_to_run(paths.references / "plan-skill.md", run_root),
        "parent_plan": relative_to_run(paths.references / "parent-plan.md", run_root),
    }


def _write_plan_references(
    *,
    run_root: Path,
    plan_id: str,
    plan_skill_content: str,
    shared_asset: str,
    persistent_feedback: str,
    recent_feedback: str,
    parent_plan_content: str | None = None,
) -> dict[str, Path]:
    paths = plan_paths(run_root, plan_id, ensure=True)
    refs = {
        "plan_skill": paths.references / "plan-skill.md",
        "shared_asset": paths.references / "shared-asset.md",
        "persistent_feedback": paths.references / "persistent-feedback.md",
        "recent_feedback": paths.references / "recent-feedback.md",
    }
    write_text(refs["plan_skill"], plan_skill_content)
    write_text(refs["shared_asset"], shared_asset or "(none yet)")
    write_text(refs["persistent_feedback"], persistent_feedback or "(none yet)")
    write_text(refs["recent_feedback"], recent_feedback or "(none yet)")
    if parent_plan_content is not None:
        refs["parent_plan"] = paths.references / "parent-plan.md"
        write_text(refs["parent_plan"], parent_plan_content or "(none yet)")
    return refs


def training_budget_rule_lines() -> list[str]:
    return [
        "If the experiment specifies a training budget in the plan, repository, or user input, follow that source of truth unless the repository already enforces a different valid default.",
        "Early stopping or other speedup strategies are allowed only when they preserve the experiment's validity; do not silently change the training budget.",
        "If you stop early, record the intended budget source, the actual stop point, and the reason in the result report and logs.",
    ]


def render_plan_markdown(
    *,
    plan_id: str,
    parent_plan_id: str | None,
    run_id: str,
    repo_path: Path,
    source_branch: str,
    plan_kind: str,
    plan_skill_name: str,
    essence: dict[str, str],
    goal_text: str,
    questions: list[str],
    steps: list[str],
    deliverables: list[str],
    references: list[str],
) -> str:
    parent_value = parent_plan_id or "none"
    generated_at = utc_now()
    goal_summary = " ".join(goal_text.strip().split())[:160]
    escaped_goal_summary = goal_summary.replace('"', "'")
    references_block = (
        chr(10).join(
            f"{index}. {item}" for index, item in enumerate(references, start=1)
        )
        if references
        else "1. (none)"
    )
    return f"""---
plan_id: {plan_id}
run_id: {run_id}
parent_plan_id: {parent_value}
plan_kind: {plan_kind}
plan_skill: {plan_skill_name}
repo_path: {repo_path}
source_branch: {source_branch}
generated_at: {generated_at}
goal_summary: "{escaped_goal_summary}"
plan_essence: "{essence['plan_essence'].replace('"', "'")}"
decision_focus: "{essence['decision_focus'].replace('"', "'")}"
expected_signal: "{essence['expected_signal'].replace('"', "'")}"
next_iteration_hook: "{essence['next_iteration_hook'].replace('"', "'")}"
entrypoint: plans/{plan_id}/plan.md
references_dir: plans/{plan_id}/references
---

# Plan Metadata
- plan_id: {plan_id}
- parent_plan_id: {parent_value}
- run_id: {run_id}
- repo_path: {repo_path}
- source_branch: {source_branch}
- plan_kind: {plan_kind}
- plan_skill: {plan_skill_name}
- plan_essence: {essence['plan_essence']}
- decision_focus: {essence['decision_focus']}
- expected_signal: {essence['expected_signal']}
- next_iteration_hook: {essence['next_iteration_hook']}
- generated_at: {generated_at}

# Experiment Goal
{goal_text.strip()}

# Investigation Questions
{chr(10).join(f"{index}. {item}" for index, item in enumerate(questions, start=1))}

# Execution Plan
{chr(10).join(f"{index}. {item}" for index, item in enumerate(steps, start=1))}

# Deliverables
{chr(10).join(f"{index}. {item}" for index, item in enumerate(deliverables, start=1))}

# Referenced Files
{references_block}

# Result Collection Rules
1. All intermediate artifacts must be written under the run directory only.
2. Every code change must be tied to this plan ID in logs or commit notes.
3. Raw execution logs must be preserved without truncation.
4. Final summaries must reference concrete artifact paths.
5. Preserve the intended training budget unless an explicit early-stop rule or repo default justifies stopping earlier.
6. If training stops early, record the authoritative budget source, actual stop point, and stopping reason.
"""


def validate_plan_markdown(content: str) -> list[str]:
    missing = [heading for heading in PLAN_HEADINGS if heading not in content]
    errors = [f"missing required heading: {heading}" for heading in missing]
    if not content.startswith("---\n"):
        errors.append("missing yaml frontmatter")
    frontmatter = ""
    if content.startswith("---\n"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            frontmatter = parts[1]
    for needle in ("- plan_id:", "- run_id:", "- repo_path:", "- source_branch:"):
        if needle not in content:
            errors.append(f"missing metadata field: {needle}")
    for field in (
        "plan_id:",
        "run_id:",
        "plan_kind:",
        "plan_skill:",
        "plan_essence:",
        "decision_focus:",
        "expected_signal:",
        "next_iteration_hook:",
        "entrypoint:",
        "references_dir:",
    ):
        if field not in frontmatter:
            errors.append(f"missing frontmatter field: {field}")
    return errors


def bootstrap_run(
    *,
    repo_path: Path,
    goal_text: str,
    run_id: str,
    paths: RunPaths,
    source_branch: str | None = None,
    input_file_name: str = "goal.txt",
    notifications: NotificationSettings | None = None,
) -> RunManifest:
    original_branch, original_head_commit = prepare_repo_for_run(
        repo_path, paths.root, paths.logs / "git-lifecycle.jsonl"
    )
    paths = init_run_dirs(paths.root)
    resolved_branch = source_branch or detect_source_branch(repo_path)
    logger.info("Bootstrapping run {} for repo {}", run_id, repo_path)
    goal_file = paths.inputs / input_file_name
    write_text(goal_file, goal_text)
    manifest = RunManifest(
        run_id=run_id,
        repo_path=str(repo_path),
        source_branch=resolved_branch,
        goal_file=str(goal_file),
        runs_env_var=RUNS_ENV_VAR,
        goal_language=detect_preferred_language(goal_text),
        original_branch=original_branch,
        original_head_commit=original_head_commit,
        notify_urls=list((notifications or NotificationSettings(urls=[])).urls),
        notify_config_path=(notifications.config_path if notifications else None),
        notify_tag=(notifications.tag if notifications else None),
    )
    save_manifest(paths, manifest)
    append_jsonl(
        paths.logs / "run-lifecycle.jsonl",
        {
            "ts": utc_now(),
            "event": "run_bootstrapped",
            "run_id": run_id,
            "repo_path": str(repo_path),
            "run_dir": str(paths.root),
            "original_branch": original_branch,
            "original_head_commit": original_head_commit,
        },
    )
    return manifest


def create_initial_plan(paths: RunPaths, manifest: RunManifest) -> Path:
    goal_text = read_text(Path(manifest.goal_file)).strip()
    inherited_asset = load_repo_asset(paths.root)
    persistent_feedback = load_persistent_feedback_context(
        load_telegram_settings().feedback_context_limit
    )
    feedback_context = load_feedback_context(
        load_telegram_settings().feedback_context_limit
    )
    output_language = describe_language(manifest.goal_language)
    plan_id = f"plan-{next_plan_index(paths.plans):03d}"
    profile = infer_plan_skill(goal_text)
    plan_kind = profile.plan_kind
    logger.info("Creating initial plan {}", plan_id)
    scoped_paths = plan_paths(paths.root, plan_id, ensure=True)
    refs = _write_plan_references(
        run_root=paths.root,
        plan_id=plan_id,
        plan_skill_content=read_text(profile.skill_path),
        shared_asset=inherited_asset,
        persistent_feedback=persistent_feedback,
        recent_feedback=feedback_context,
    )
    reference_labels = _reference_paths_for_plan(paths.root, plan_id)
    plan_path = scoped_paths.plan
    prompt_path = scoped_paths.plan_prompt
    content = render_plan_markdown(
        plan_id=plan_id,
        parent_plan_id=None,
        run_id=manifest.run_id,
        repo_path=Path(manifest.repo_path),
        source_branch=manifest.source_branch,
        plan_kind=plan_kind,
        plan_skill_name=profile.skill_name,
        essence=plan_frontmatter_essence(
            profile=profile,
            goal_text=goal_text,
            feedback=None,
        ),
        goal_text=goal_text,
        questions=profile_questions(profile, goal_text),
        steps=profile_steps(profile, Path(manifest.repo_path)),
        deliverables=profile_deliverables(profile, plan_id),
        references=[
            reference_labels["plan_skill"],
            reference_labels["shared_asset"],
            reference_labels["persistent_feedback"],
            reference_labels["recent_feedback"],
        ],
    )
    errors = validate_plan_markdown(content)
    if errors:
        raise ValueError("; ".join(errors))
    write_text(plan_path, content)
    write_text(
        prompt_path,
        "\n".join(
            [
                f"You are the iteration agent for run {manifest.run_id}.",
                "Draft the first plan without changing the required markdown headings.",
                f"Repository: {manifest.repo_path}",
                f"Source branch: {manifest.source_branch}",
                f"Write the final result back to: {plan_path}",
                f"Plan kind: {plan_kind}",
                f"Plan skill: {profile.skill_name}",
                "If a repository shared asset is present, inherit its stable notes and avoid repeating known failures.",
                "Do not weaken the experiment by silently changing the training budget defined by the plan, repository, or user input.",
                "If you propose early stopping or a faster proxy, make sure the plan says how comparability is preserved and which budget source remains authoritative.",
                f"Write user-facing planning text in {output_language} to match the original goal language.",
                "The plan file uses a three-layer layout: YAML frontmatter first, markdown body second, referenced files third.",
                "Keep the frontmatter focused on the reusable essence of this plan, not only identifiers.",
                "Follow the selected skill's flow, frontmatter emphasis, body rules, and reference-file contract.",
                f"Referenced file for plan skill: {refs['plan_skill']}",
                f"Referenced file for shared asset: {refs['shared_asset']}",
                f"Referenced file for persistent feedback: {refs['persistent_feedback']}",
                f"Referenced file for recent feedback: {refs['recent_feedback']}",
                "",
                "Repository shared asset:",
                inherited_asset or "(none yet)",
                "",
                "Persistent run guidance from Telegram:",
                persistent_feedback or "(none yet)",
                "",
                "Training budget guardrails:",
                *training_budget_rule_lines(),
                "",
                "Recent user feedback from Telegram inbox:",
                feedback_context or "(none yet)",
                "",
                content,
            ]
        ),
    )
    manifest.latest_plan_id = plan_id
    save_manifest(paths, manifest)
    upsert_plan_index_record(
        run_dir=paths.root,
        plan_id=plan_id,
        parent_plan_id=None,
        plan_kind=plan_kind,
        status="planned",
        short_summary=goal_text.splitlines()[0],
        artifacts=[relative_to_run(plan_path, paths.root)],
    )
    append_jsonl(
        paths.logs / "iteration-agent.jsonl",
        {"ts": utc_now(), "level": "INFO", "event": "plan_created", "plan_id": plan_id},
    )
    return plan_path


def create_iterated_plan(
    paths: RunPaths, manifest: RunManifest, parent_plan_id: str, feedback: str
) -> Path:
    goal_text = read_text(Path(manifest.goal_file)).strip()
    inherited_asset = load_repo_asset(paths.root)
    persistent_feedback = load_persistent_feedback_context(
        load_telegram_settings().feedback_context_limit
    )
    feedback_context = load_feedback_context(
        load_telegram_settings().feedback_context_limit
    )
    output_language = describe_language(manifest.goal_language)
    plan_id = f"plan-{next_plan_index(paths.plans):03d}"
    profile = infer_plan_skill(goal_text, feedback)
    plan_kind = profile.plan_kind
    logger.info("Creating iterated plan {} from {}", plan_id, parent_plan_id)
    scoped_paths = plan_paths(paths.root, plan_id, ensure=True)
    parent_paths = plan_paths(paths.root, parent_plan_id)
    plan_path = scoped_paths.plan
    parent_plan_path = parent_paths.plan
    if not parent_plan_path.exists():
        raise FileNotFoundError(f"missing parent plan: {parent_plan_path}")
    refs = _write_plan_references(
        run_root=paths.root,
        plan_id=plan_id,
        plan_skill_content=read_text(profile.skill_path),
        shared_asset=inherited_asset,
        persistent_feedback=persistent_feedback,
        recent_feedback=feedback_context,
        parent_plan_content=read_text(parent_plan_path),
    )
    reference_labels = _reference_paths_for_plan(paths.root, plan_id)
    content = render_plan_markdown(
        plan_id=plan_id,
        parent_plan_id=parent_plan_id,
        run_id=manifest.run_id,
        repo_path=Path(manifest.repo_path),
        source_branch=manifest.source_branch,
        plan_kind=plan_kind,
        plan_skill_name=profile.skill_name,
        essence=plan_frontmatter_essence(
            profile=profile,
            goal_text=goal_text,
            feedback=feedback,
        ),
        goal_text=goal_text,
        questions=profile_questions(profile, goal_text, feedback),
        steps=profile_steps(profile, Path(manifest.repo_path), feedback),
        deliverables=profile_deliverables(profile, plan_id),
        references=[
            reference_labels["plan_skill"],
            reference_labels["shared_asset"],
            reference_labels["persistent_feedback"],
            reference_labels["recent_feedback"],
            reference_labels["parent_plan"],
        ],
    )
    errors = validate_plan_markdown(content)
    if errors:
        raise ValueError("; ".join(errors))
    write_text(plan_path, content)
    write_text(
        scoped_paths.plan_prompt,
        "\n".join(
            [
                f"You are the iteration agent for run {manifest.run_id}.",
                "Create the next plan without changing the required markdown headings.",
                f"Repository: {manifest.repo_path}",
                f"Source branch: {manifest.source_branch}",
                f"Parent plan: {parent_plan_path}",
                f"Write the final result back to: {plan_path}",
                f"Feedback: {feedback}",
                f"Plan kind: {plan_kind}",
                f"Plan skill: {profile.skill_name}",
                "Do not weaken the experiment by silently changing the training budget defined by the plan, repository, or user input.",
                "If you propose early stopping or a faster proxy, make sure the plan says how comparability is preserved and which budget source remains authoritative.",
                f"Write user-facing planning text in {output_language} to match the original goal language.",
                "The plan file uses a three-layer layout: YAML frontmatter first, markdown body second, referenced files third.",
                "Keep the frontmatter focused on the reusable essence of this plan, not only identifiers.",
                "Follow the selected skill's flow, frontmatter emphasis, body rules, and reference-file contract.",
                f"Referenced file for plan skill: {refs['plan_skill']}",
                f"Referenced file for shared asset: {refs['shared_asset']}",
                f"Referenced file for persistent feedback: {refs['persistent_feedback']}",
                f"Referenced file for recent feedback: {refs['recent_feedback']}",
                f"Referenced file for parent plan: {refs['parent_plan']}",
                "",
                "Repository shared asset:",
                inherited_asset or "(none yet)",
                "",
                "Persistent run guidance from Telegram:",
                persistent_feedback or "(none yet)",
                "",
                "Training budget guardrails:",
                *training_budget_rule_lines(),
                "",
                "Recent user feedback from Telegram inbox:",
                feedback_context or "(none yet)",
                "",
                "Parent plan content:",
                "",
                read_text(parent_plan_path),
                "",
                "Draft plan content:",
                "",
                content,
            ]
        ),
    )
    manifest.latest_plan_id = plan_id
    manifest.current_iteration += 1
    save_manifest(paths, manifest)
    upsert_plan_index_record(
        run_dir=paths.root,
        plan_id=plan_id,
        parent_plan_id=parent_plan_id,
        plan_kind=plan_kind,
        status="planned",
        short_summary=feedback.splitlines()[0],
        artifacts=[
            relative_to_run(parent_plan_path, paths.root),
            relative_to_run(plan_path, paths.root),
        ],
    )
    append_jsonl(
        paths.logs / "iteration-agent.jsonl",
        {
            "ts": utc_now(),
            "level": "INFO",
            "event": "plan_iterated",
            "plan_id": plan_id,
            "parent_plan_id": parent_plan_id,
        },
    )
    return plan_path
