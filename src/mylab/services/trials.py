from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from mylab.config import TRIAL_HEADINGS, RUNS_ENV_VAR
from mylab.domain import RunManifest, RunPaths
from mylab.logging import logger
from mylab.services.assets import (
    load_repo_asset,
    upsert_trial_index_record,
)
from mylab.services.git_lifecycle import prepare_repo_for_run
from mylab.services.notifications import NotificationSettings
from mylab.services.trial_skills import TrialSkillProfile, infer_trial_skill
from mylab.services.telegram_bot import (
    load_all_guidance_context,
    load_feedback_context,
    load_next_guidance_context,
    load_persistent_feedback_context,
    load_telegram_settings,
)
from mylab.storage import append_jsonl, read_text, write_json, write_text
from mylab.storage.trial_layout import (
    trial_iteration_log_path,
    trial_paths,
    relative_to_run,
)
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


def next_trial_index(trials_dir: Path) -> int:
    suffixes: list[int] = []
    for path in sorted(trials_dir.glob("trial-*")):
        stem = path.stem if path.is_file() else path.name
        if not stem.startswith("trial-"):
            continue
        try:
            suffixes.append(int(stem.split("-")[-1]))
        except ValueError:
            continue
    if not suffixes:
        return 1
    return max(suffixes) + 1


_GOAL_SUMMARY_PLACEHOLDER = (
    "<Codex: rewrite after choosing this trial's actual scope; summarize what this "
    "trial will concretely try, not the overall run goal>"
)
_TRIAL_ESSENCE_PLACEHOLDER = (
    "<Codex: rewrite with the actual hypothesis / search region / design move this "
    "trial is testing>"
)
_DECISION_FOCUS_PLACEHOLDER = (
    "<Codex: rewrite with the key decision this trial should unlock>"
)
_EXPECTED_SIGNAL_PLACEHOLDER = (
    "<Codex: rewrite with the concrete evidence or comparison this trial should "
    "produce>"
)


def trial_code_checkpoint(manifest: RunManifest) -> tuple[str, str]:
    if manifest.latest_work_commit and manifest.work_branch:
        return manifest.latest_work_commit, manifest.work_branch
    if manifest.original_head_commit and manifest.source_branch:
        return manifest.original_head_commit, manifest.source_branch
    return "unknown", manifest.source_branch


def _scaffold_questions(profile: TrialSkillProfile) -> list[str]:
    if profile.trial_kind == "parameter-tuning":
        return [
            "Codex must rewrite this list after identifying the actual parameter family or search region worth testing now.",
            "Codex must state how combinations will be generated, tracked, and compared in this round.",
            "Codex must state which ranking rule or decision rule this batch should answer.",
        ]
    return [
        "Codex must rewrite this list after identifying the actual hypothesis this round is testing.",
        "Codex must state the concrete implementation delta versus the current baseline.",
        "Codex must state which train, eval, and analysis signals will decide whether this idea should continue.",
    ]


def _scaffold_steps(profile: TrialSkillProfile) -> list[str]:
    if profile.trial_kind == "parameter-tuning":
        return [
            "Codex must rewrite these steps into a concrete end-to-end batch plan for this trial instead of leaving a generic sweep outline.",
            "The rewritten steps should cover search-space definition, batch generation, execution, result aggregation, and ranking in one trial whenever feasible.",
            "If some work cannot be completed in this trial, Codex must say exactly what blocks it and still maximize completed work in the current round.",
        ]
    return [
        "Codex must rewrite these steps into the actual end-to-end plan for this structural trial instead of leaving a generic stage list.",
        "The rewritten steps should cover the concrete implementation delta, execution, evaluation, and analysis in one trial whenever feasible.",
        "If some work cannot be completed in this trial, Codex must say exactly what blocks it and still maximize completed work in the current round.",
    ]


def _scaffold_deliverables(profile: TrialSkillProfile, trial_id: str) -> list[str]:
    if profile.trial_kind == "parameter-tuning":
        return [
            f"Codex must replace this with the actual parameter batch artifacts for {trial_id}.",
            f"Codex must replace this with the actual aggregated comparison artifacts for {trial_id}.",
            f"Codex must replace this with the actual ranking conclusion or blocking reason for {trial_id}.",
        ]
    return [
        f"Codex must replace this with the actual implementation delta and runnable entrypoints for {trial_id}.",
        f"Codex must replace this with the actual train/eval evidence for {trial_id}.",
        f"Codex must replace this with the actual design conclusion or blocking reason for {trial_id}.",
    ]


def _write_trial_references(
    *,
    run_root: Path,
    trial_id: str,
    trial_skill_content: str,
    shared_asset: str,
    all_guidance: str,
    next_guidance: str,
) -> dict[str, Path]:
    paths = trial_paths(run_root, trial_id, ensure=True)
    refs = {
        "design": paths.references / "design.md",
        "experiment": paths.references / "experiment.md",
        "analysis": paths.references / "analysis.md",
        "conclusion": paths.references / "conclusion.md",
        "trial_skill": paths.references / "trial-skill.md",
        "shared_asset": paths.references / "shared-asset.md",
        "all_guidance": paths.references / "all-guidance.md",
        "next_guidance": paths.references / "next-guidance.md",
    }
    write_text(
        refs["design"],
        "\n".join(
            [
                "# Design Detail",
                "",
                "## Hypothesis",
                "(fill in)",
                "",
                "## Architecture",
                "(fill in)",
                "",
                "## Parameters",
                "(fill in as a dict-like block)",
            ]
        ),
    )
    write_text(
        refs["experiment"],
        "\n".join(
            [
                "# Experiment Detail",
                "",
                "## Dataset",
                "(fill in)",
                "",
                "## Environment",
                "(fill in)",
                "",
                "## Artifacts Path",
                "(fill in concrete paths)",
            ]
        ),
    )
    write_text(
        refs["analysis"],
        "\n".join(
            [
                "# Analysis Detail",
                "",
                "## Metrics",
                "(fill in)",
                "",
                "## Observations",
                "(fill in)",
                "",
                "## Deep Dive",
                "Put detailed anomaly or success-cause analysis here.",
            ]
        ),
    )
    write_text(
        refs["conclusion"],
        "\n".join(
            [
                "# Conclusion Detail",
                "",
                "## Hypothesis Verdict",
                "(True / False / Partial)",
                "",
                "## Summary",
                "(fill in)",
                "",
                "## Limitations And Future Directions",
                "(fill in)",
            ]
        ),
    )
    write_text(refs["trial_skill"], trial_skill_content)
    write_text(refs["shared_asset"], shared_asset or "(none yet)")
    write_text(refs["all_guidance"], all_guidance or "(none yet)")
    write_text(refs["next_guidance"], next_guidance or "(none yet)")
    return refs


def training_budget_rule_lines() -> list[str]:
    return [
        "If the experiment specifies a training budget in the trial, repository, or user input, follow that source of truth unless the repository already enforces a different valid default.",
        "Early stopping or other speedup strategies are allowed only when they preserve the experiment's validity; do not silently change the training budget.",
        "If you stop early, record the intended budget source, the actual stop point, and the reason in the result report and logs.",
    ]


def render_trial_markdown(
    *,
    trial_id: str,
    run_id: str,
    repo_path: Path,
    source_branch: str,
    trial_kind: str,
    trial_skill_name: str,
    code_checkpoint: str,
    code_checkpoint_ref: str,
    goal_text: str,
    questions: list[str],
    steps: list[str],
    deliverables: list[str],
) -> str:
    generated_at = utc_now()
    return f"""---
trial_id: {trial_id}
run_id: {run_id}
trial_kind: {trial_kind}
trial_skill: {trial_skill_name}
repo_path: {repo_path}
source_branch: {source_branch}
code_checkpoint: {code_checkpoint}
code_checkpoint_ref: {code_checkpoint_ref}
generated_at: {generated_at}
goal_summary: "{_GOAL_SUMMARY_PLACEHOLDER}"
trial_essence: "{_TRIAL_ESSENCE_PLACEHOLDER}"
decision_focus: "{_DECISION_FOCUS_PLACEHOLDER}"
expected_signal: "{_EXPECTED_SIGNAL_PLACEHOLDER}"
all_guidance_ref: "trials/{trial_id}/references/all-guidance.md"
next_guidance_ref: "trials/{trial_id}/references/next-guidance.md"
entrypoint: trials/{trial_id}/trial.md
references_dir: trials/{trial_id}/references
---

# Trial Metadata
- trial_id: {trial_id}
- run_id: {run_id}
- repo_path: {repo_path}
- source_branch: {source_branch}
- code_checkpoint: {code_checkpoint}
- code_checkpoint_ref: {code_checkpoint_ref}
- trial_kind: {trial_kind}
- trial_skill: {trial_skill_name}
- trial_essence: {_TRIAL_ESSENCE_PLACEHOLDER}
- decision_focus: {_DECISION_FOCUS_PLACEHOLDER}
- expected_signal: {_EXPECTED_SIGNAL_PLACEHOLDER}
- generated_at: {generated_at}

# Experiment Goal
{goal_text.strip()}

This is the run-level goal context, not the finalized summary of this trial. Codex must rewrite the frontmatter and trial body so they describe what this specific trial will actually try.

# Investigation Questions
{chr(10).join(f"{index}. {item}" for index, item in enumerate(questions, start=1))}

# Execution Steps
{chr(10).join(f"{index}. {item}" for index, item in enumerate(steps, start=1))}

Keep only the decisive execution outline here. Put detailed code-change logic and execution specifics in the reference markdown files.

# Deliverables
{chr(10).join(f"{index}. {item}" for index, item in enumerate(deliverables, start=1))}

# Human Review
- Status: Pending human comment.
- Human Comment: Fill in concise feedback, objections, or approval notes here.

# Result Collection Rules
1. All intermediate artifacts must be written under the run directory only.
2. Every code change must be tied to this trial ID in logs or commit notes.
3. Raw execution logs must be preserved without truncation.
4. Final summaries must reference concrete artifact paths.
5. Preserve the intended training budget unless an explicit early-stop rule or repo default justifies stopping earlier.
6. If training stops early, record the authoritative budget source, actual stop point, and stopping reason.
7. Keep `trial.md` concise: only key facts belong here. Put deep reasoning, detailed code logic, and in-depth anomaly analysis into the referenced markdown files under `references/`.
"""


def validate_trial_markdown(content: str) -> list[str]:
    missing = [heading for heading in TRIAL_HEADINGS if heading not in content]
    errors = [f"missing required heading: {heading}" for heading in missing]
    if not content.startswith("---\n"):
        errors.append("missing yaml frontmatter")
    frontmatter = ""
    if content.startswith("---\n"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            frontmatter = parts[1]
    for needle in (
        "- trial_id:",
        "- run_id:",
        "- repo_path:",
        "- source_branch:",
        "- code_checkpoint:",
        "- code_checkpoint_ref:",
    ):
        if needle not in content:
            errors.append(f"missing metadata field: {needle}")
    for field in (
        "trial_id:",
        "run_id:",
        "trial_kind:",
        "trial_skill:",
        "trial_essence:",
        "decision_focus:",
        "expected_signal:",
        "all_guidance_ref:",
        "next_guidance_ref:",
        "code_checkpoint:",
        "code_checkpoint_ref:",
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


def create_initial_trial(paths: RunPaths, manifest: RunManifest) -> Path:
    goal_text = read_text(Path(manifest.goal_file)).strip()
    inherited_asset = load_repo_asset(paths.root)
    persistent_feedback = load_persistent_feedback_context(
        load_telegram_settings().feedback_context_limit
    )
    feedback_context = load_feedback_context(
        load_telegram_settings().feedback_context_limit
    )
    all_guidance = load_all_guidance_context(
        load_telegram_settings().feedback_context_limit
    )
    next_guidance = load_next_guidance_context(
        load_telegram_settings().feedback_context_limit
    )
    output_language = describe_language(manifest.goal_language)
    trial_id = f"trial-{next_trial_index(paths.trials):03d}"
    profile = infer_trial_skill(goal_text)
    trial_kind = profile.trial_kind
    code_checkpoint, code_checkpoint_ref = trial_code_checkpoint(manifest)
    logger.info("Creating initial trial {}", trial_id)
    scoped_paths = trial_paths(paths.root, trial_id, ensure=True)
    _write_trial_references(
        run_root=paths.root,
        trial_id=trial_id,
        trial_skill_content=read_text(profile.skill_path),
        shared_asset=inherited_asset,
        all_guidance=all_guidance or persistent_feedback,
        next_guidance=next_guidance or feedback_context,
    )
    trial_path = scoped_paths.trial
    prompt_path = scoped_paths.trial_prompt
    content = render_trial_markdown(
        trial_id=trial_id,
        run_id=manifest.run_id,
        repo_path=Path(manifest.repo_path),
        source_branch=manifest.source_branch,
        trial_kind=trial_kind,
        trial_skill_name=profile.skill_name,
        code_checkpoint=code_checkpoint,
        code_checkpoint_ref=code_checkpoint_ref,
        goal_text=goal_text,
        questions=_scaffold_questions(profile),
        steps=_scaffold_steps(profile),
        deliverables=_scaffold_deliverables(profile, trial_id),
    )
    errors = validate_trial_markdown(content)
    if errors:
        raise ValueError("; ".join(errors))
    write_text(trial_path, content)
    write_json(
        scoped_paths.card,
        {
            "trial_id": trial_id,
            "trial_kind": trial_kind,
            "trial_skill": profile.skill_name,
            "goal_summary": "",
            "trial_essence": "",
            "decision_focus": "",
            "expected_signal": "",
            "code_checkpoint": code_checkpoint,
            "code_checkpoint_ref": code_checkpoint_ref,
        },
    )
    write_json(
        scoped_paths.status,
        {
            "trial_id": trial_id,
            "status": "planned",
            "generated_at": utc_now(),
        },
    )
    write_text(
        prompt_path,
        "\n".join(
            [
                f"You are the iteration agent for run {manifest.run_id}.",
                "Draft the first trial without changing the required markdown headings.",
                f"Repository: {manifest.repo_path}",
                f"Source branch: {manifest.source_branch}",
                f"Write the final result back to: {trial_path}",
                f"Trial kind: {trial_kind}",
                f"Trial skill: {profile.skill_name}",
                f"Code checkpoint: {code_checkpoint} ({code_checkpoint_ref})",
                "Rewrite goal_summary, trial_essence, decision_focus, and expected_signal yourself based on what this trial will actually do after reading the repo, prior trial catalog, shared asset, and current guidance.",
                "Do not mechanically restate the overall run goal in goal_summary or trial_essence. Those fields must describe this trial's actual attempted move.",
                "Replace any scaffold bullets that say Codex must rewrite them. Do not leave generic stage language behind.",
                "If a repository shared asset is present, inherit its stable notes and avoid repeating known failures.",
                "Do not weaken the experiment by silently changing the training budget defined by the trial, repository, or user input.",
                "If you propose early stopping or a faster proxy, make sure the trial says how comparability is preserved and which budget source remains authoritative.",
                f"Write user-facing planning text in {output_language} to match the original goal language.",
                "The trial file uses a three-layer layout: YAML frontmatter first, markdown body second, referenced files third.",
                "Keep the frontmatter focused on the reusable essence of this trial, not only identifiers.",
                "Maximize the amount of meaningful work one trial can complete. Prefer an end-to-end trial that finishes the decisive implementation, execution, comparison, and analysis loop whenever feasible instead of splitting obvious work into tiny rounds.",
                "Follow the selected skill's flow, frontmatter emphasis, body rules, and reference-file contract.",
                "Use the trial directory's `references/` files when you need the deeper context.",
                "Read referenced files directly when you need them; do not wait for this prompt to inline their contents.",
                "",
                f"Trial file reference: {trial_path}",
                f"Repository shared asset reference: {paths.root / 'assets' / 'repo.md'}",
                f"All-trial guidance reference: {scoped_paths.references / 'all-guidance.md'}",
                f"Next-trial guidance reference: {scoped_paths.references / 'next-guidance.md'}",
                f"Trial skill reference: {scoped_paths.references / 'trial-skill.md'}",
                "Training budget guardrails:",
                *training_budget_rule_lines(),
            ]
        ),
    )
    manifest.latest_trial_id = trial_id
    save_manifest(paths, manifest)
    upsert_trial_index_record(
        run_dir=paths.root,
        trial_id=trial_id,
        parent_trial_id=None,
        trial_kind=trial_kind,
        status="planned",
        short_summary=goal_text.splitlines()[0],
        artifacts=[relative_to_run(trial_path, paths.root)],
        goal_summary="",
        trial_essence="",
        decision_focus="",
        expected_signal="",
        code_checkpoint=code_checkpoint,
        code_checkpoint_ref=code_checkpoint_ref,
    )
    append_jsonl(
        trial_iteration_log_path(paths.root, trial_id),
        {"ts": utc_now(), "level": "INFO", "event": "trial_created", "trial_id": trial_id},
    )
    return trial_path


def create_iterated_trial(
    paths: RunPaths, manifest: RunManifest, parent_trial_id: str, feedback: str
) -> Path:
    goal_text = read_text(Path(manifest.goal_file)).strip()
    inherited_asset = load_repo_asset(paths.root)
    persistent_feedback = load_persistent_feedback_context(
        load_telegram_settings().feedback_context_limit
    )
    feedback_context = load_feedback_context(
        load_telegram_settings().feedback_context_limit
    )
    all_guidance = load_all_guidance_context(
        load_telegram_settings().feedback_context_limit
    )
    next_guidance = load_next_guidance_context(
        load_telegram_settings().feedback_context_limit
    )
    output_language = describe_language(manifest.goal_language)
    trial_id = f"trial-{next_trial_index(paths.trials):03d}"
    profile = infer_trial_skill(goal_text, feedback)
    trial_kind = profile.trial_kind
    code_checkpoint, code_checkpoint_ref = trial_code_checkpoint(manifest)
    logger.info("Creating iterated trial {} from {}", trial_id, parent_trial_id)
    scoped_paths = trial_paths(paths.root, trial_id, ensure=True)
    parent_paths = trial_paths(paths.root, parent_trial_id)
    trial_path = scoped_paths.trial
    parent_trial_path = parent_paths.trial
    if not parent_trial_path.exists():
        raise FileNotFoundError(f"missing parent trial: {parent_trial_path}")
    _write_trial_references(
        run_root=paths.root,
        trial_id=trial_id,
        trial_skill_content=read_text(profile.skill_path),
        shared_asset=inherited_asset,
        all_guidance=all_guidance or persistent_feedback,
        next_guidance=next_guidance or feedback_context,
    )
    content = render_trial_markdown(
        trial_id=trial_id,
        run_id=manifest.run_id,
        repo_path=Path(manifest.repo_path),
        source_branch=manifest.source_branch,
        trial_kind=trial_kind,
        trial_skill_name=profile.skill_name,
        code_checkpoint=code_checkpoint,
        code_checkpoint_ref=code_checkpoint_ref,
        goal_text=goal_text,
        questions=_scaffold_questions(profile),
        steps=_scaffold_steps(profile),
        deliverables=_scaffold_deliverables(profile, trial_id),
    )
    errors = validate_trial_markdown(content)
    if errors:
        raise ValueError("; ".join(errors))
    write_text(trial_path, content)
    write_json(
        scoped_paths.card,
        {
            "trial_id": trial_id,
            "trial_kind": trial_kind,
            "trial_skill": profile.skill_name,
            "goal_summary": "",
            "trial_essence": "",
            "decision_focus": "",
            "expected_signal": "",
            "code_checkpoint": code_checkpoint,
            "code_checkpoint_ref": code_checkpoint_ref,
        },
    )
    write_json(
        scoped_paths.status,
        {
            "trial_id": trial_id,
            "status": "planned",
            "generated_at": utc_now(),
            "parent_trial_id": parent_trial_id,
        },
    )
    write_text(
        scoped_paths.trial_prompt,
        "\n".join(
            [
                f"You are the iteration agent for run {manifest.run_id}.",
                "Create the next trial without changing the required markdown headings.",
                f"Repository: {manifest.repo_path}",
                f"Source branch: {manifest.source_branch}",
                f"Write the final result back to: {trial_path}",
                f"Feedback: {feedback}",
                f"Trial kind: {trial_kind}",
                f"Trial skill: {profile.skill_name}",
                f"Code checkpoint: {code_checkpoint} ({code_checkpoint_ref})",
                "Rewrite goal_summary, trial_essence, decision_focus, and expected_signal yourself based on what this trial will actually do after reading the repo, trial catalog, shared asset, and current guidance.",
                "Do not mechanically restate the overall run goal or feedback. Those fields must describe this trial's actual attempted move and decision target.",
                "Replace any scaffold bullets that say Codex must rewrite them. Do not leave generic stage language behind.",
                "Do not weaken the experiment by silently changing the training budget defined by the trial, repository, or user input.",
                "If you propose early stopping or a faster proxy, make sure the trial says how comparability is preserved and which budget source remains authoritative.",
                f"Write user-facing planning text in {output_language} to match the original goal language.",
                "The trial file uses a three-layer layout: YAML frontmatter first, markdown body second, referenced files third.",
                "Keep the frontmatter focused on the reusable essence of this trial, not only identifiers.",
                "Maximize the amount of meaningful work one trial can complete. Prefer an end-to-end trial that finishes the decisive implementation, execution, comparison, and analysis loop whenever feasible instead of splitting obvious work into tiny rounds.",
                "Follow the selected skill's flow, frontmatter emphasis, body rules, and reference-file contract.",
                "Use the trial directory's `references/` files when you need the deeper context.",
                "Read referenced files directly when you need them; do not wait for this prompt to inline their contents.",
                "Do not treat the next trial as a rewrite of one single parent trial.",
                "Use the trial catalog to choose whichever prior trials are relevant for forming the current idea.",
                "",
                f"Trial file reference: {trial_path}",
                f"Trial catalog reference: {paths.root / 'trials' / 'index.md'}",
                f"Repository shared asset reference: {paths.root / 'assets' / 'repo.md'}",
                f"All-trial guidance reference: {scoped_paths.references / 'all-guidance.md'}",
                f"Next-trial guidance reference: {scoped_paths.references / 'next-guidance.md'}",
                f"Trial skill reference: {scoped_paths.references / 'trial-skill.md'}",
                "Training budget guardrails:",
                *training_budget_rule_lines(),
            ]
        ),
    )
    manifest.latest_trial_id = trial_id
    manifest.current_iteration += 1
    save_manifest(paths, manifest)
    upsert_trial_index_record(
        run_dir=paths.root,
        trial_id=trial_id,
        parent_trial_id=parent_trial_id,
        trial_kind=trial_kind,
        status="planned",
        short_summary=feedback.splitlines()[0],
        artifacts=[
            relative_to_run(parent_trial_path, paths.root),
            relative_to_run(trial_path, paths.root),
        ],
        goal_summary="",
        trial_essence="",
        decision_focus="",
        expected_signal="",
        code_checkpoint=code_checkpoint,
        code_checkpoint_ref=code_checkpoint_ref,
    )
    append_jsonl(
        trial_iteration_log_path(paths.root, trial_id),
        {
            "ts": utc_now(),
            "level": "INFO",
            "event": "trial_iterated",
            "trial_id": trial_id,
            "parent_trial_id": parent_trial_id,
        },
    )
    return trial_path
