from __future__ import annotations

import tempfile
from pathlib import Path

from mylab.codex import CodexExecSpec, CodexRunner
from mylab.logging import logger
from mylab.services.formatting import format_repo_report
from mylab.services.repo_skills import ensure_repo_skills_installed
from mylab.storage import write_text
from mylab.utils import has_commits, working_tree_is_clean


def adapter_prompt(repo_path: Path, audit_path: Path, goal_text: str | None) -> str:
    goal_block = (
        f"User goal or adaptation target:\n{goal_text.strip()}\n"
        if goal_text and goal_text.strip()
        else "User goal or adaptation target:\n(no explicit goal provided; adapt the repo for direct single-trial execution)\n"
    )
    return "\n".join(
        [
            "You are adapting the current repository so it can directly run one mylab-style trial.",
            f"Repository root: {repo_path}",
            goal_block.rstrip(),
            "Hard constraints:",
            "1. Do not create a mylab run.",
            "2. Do not create trial/trials/summaries/results/commands run artifacts.",
            "3. Do not switch Git branches.",
            "4. Edit the current repository directly so it becomes runnable for a single trial.",
            "5. Prioritize configurable output roots, reusable run scripts, and preserved stdout/stderr.",
            "6. Do not hardcode output, log, or intermediate-result directories inside the repo when they should be configurable.",
            "7. If repo adaptation requires a small wrapper script or config entrypoint, add it directly to the repo.",
            "8. If the repo is already close to runnable, finish the missing last-mile changes instead of rewriting unrelated code.",
            "9. Keep changes minimal but sufficient to make one direct trial executable.",
            "",
            f"Format audit reference: {audit_path}",
            "Read the repository and the audit, then make the needed code changes directly in place.",
        ]
    )


def run_adapter(repo_path: Path, goal_text: str | None, model: str | None) -> Path:
    repo_path = repo_path.expanduser().resolve()
    if not has_commits(repo_path):
        raise RuntimeError(
            "repository has no commits; commit the current branch before running mylab adapter"
        )
    if not working_tree_is_clean(repo_path):
        raise RuntimeError(
            "repository has uncommitted changes; commit or stash them before running mylab adapter"
        )

    installed_skill_files = ensure_repo_skills_installed(repo_path)
    if installed_skill_files:
        logger.info("Installed repository skill files for adapter at {}", repo_path)

    with tempfile.TemporaryDirectory(prefix="mylab-adapter-") as temp_dir:
        temp_root = Path(temp_dir)
        audit_path = format_repo_report(repo_path, temp_root)
        prompt_path = temp_root / "adapter.prompt.md"
        output_path = temp_root / "adapter.last.md"
        event_path = temp_root / "adapter.events.jsonl"
        write_text(prompt_path, adapter_prompt(repo_path, audit_path, goal_text))
        spec = CodexExecSpec(
            repo_path=repo_path,
            run_dir=temp_root,
            prompt_path=prompt_path,
            output_path=output_path,
            event_path=event_path,
            model=model,
        )
        CodexRunner().run(spec)
    return repo_path
