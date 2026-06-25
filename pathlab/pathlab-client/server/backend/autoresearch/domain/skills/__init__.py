"""
Auto Research Agent — Skill Registry

Loads and manages training skills from YAML definitions.

Usage:
    from .skills import registry
    skill = registry.match("classification")
    template = skill.get_template_content()
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from .base_skill import Skill

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).parent


class SkillRegistry:
    """Registry of available training skills."""

    def __init__(self):
        self._skills: dict[str, Skill] = {}
        self._loaded = False

    def load_all(self) -> int:
        """Scan skills/ directory for YAML files and load them."""
        if self._loaded:
            return len(self._skills)

        count = 0
        for yaml_file in sorted(_SKILLS_DIR.glob("*.yaml")):
            try:
                skill = Skill.from_yaml(yaml_file)
                self._skills[skill.name] = skill
                count += 1
                logger.debug(f"[skills] Loaded: {skill.name} ({yaml_file.name})")
            except Exception as e:
                logger.warning(f"[skills] Failed to load {yaml_file.name}: {e}")

        self._loaded = True
        logger.info(f"[skills] Loaded {count} skills: {list(self._skills.keys())}")
        return count

    def get(self, name: str) -> Skill:
        """Get a skill by name."""
        self._ensure_loaded()
        if name not in self._skills:
            raise KeyError(
                f"Skill not found: {name!r}. "
                f"Available: {list(self._skills.keys())}"
            )
        return self._skills[name]

    def match(self, task_type: str, organ: Optional[str] = None) -> Skill:
        """
        Find the best matching skill for a task type.
        Returns first skill whose task_types contains the given type.
        """
        self._ensure_loaded()

        for skill in self._skills.values():
            if task_type in skill.task_types:
                return skill

        # Fallback: return first available skill
        if self._skills:
            first = next(iter(self._skills.values()))
            logger.warning(
                f"[skills] No skill matches task_type={task_type!r}, "
                f"falling back to {first.name!r}"
            )
            return first

        raise RuntimeError("No skills available. Check skills/ directory for YAML files.")

    def list_available(self) -> list[str]:
        """List all available skill names."""
        self._ensure_loaded()
        return list(self._skills.keys())

    def list_skills(self) -> list[Skill]:
        """List all available skills."""
        self._ensure_loaded()
        return list(self._skills.values())

    def _ensure_loaded(self):
        if not self._loaded:
            self.load_all()


# Global singleton
registry = SkillRegistry()
