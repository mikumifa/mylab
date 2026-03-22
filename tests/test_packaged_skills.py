from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mylab.services.repo_skills import ensure_repo_skills_installed
from mylab.services.trial_skills import load_trial_skill


class PackagedSkillsTest(unittest.TestCase):
    def test_load_trial_skill_works_without_source_codex_dir(self) -> None:
        package_root = Path(__file__).resolve().parents[1] / "src" / "mylab" / "skills"
        with patch("mylab.skill_assets.ROOT", Path("/nonexistent-mylab-root")):
            skill = load_trial_skill("mylab-parameter-tuning")
        self.assertEqual(skill.trial_kind, "parameter-tuning")
        self.assertEqual(skill.skill_path, package_root / "mylab-parameter-tuning" / "SKILL.md")

    def test_repo_bootstrap_copies_packaged_skill_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mylab-packaged-skills-") as temp_dir:
            repo = Path(temp_dir) / "repo"
            repo.mkdir()
            with patch("mylab.skill_assets.ROOT", Path("/nonexistent-mylab-root")):
                created = ensure_repo_skills_installed(repo)
        self.assertIn(
            ".codex/skills/mylab-parameter-tuning/SKILL.md",
            created,
        )
        self.assertIn(
            ".codex/skills/mylab-structure-tuning/templates/trial.template.md",
            created,
        )
