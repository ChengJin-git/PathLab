"""Shared launch settings used by Chat briefs and the research creation API."""

from pydantic import BaseModel, ConfigDict, Field
from .effort import MAX_EXPERIMENTS, ResearchEffort
from .skills import MAX_SKILLS, ResearchSkill


class AdvancedResearch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    max_experiments: int | None = Field(None, ge=1, le=MAX_EXPERIMENTS)
    time_budget_seconds: int | None = Field(None, ge=360, le=259200)
    skills: list[ResearchSkill] = Field(default_factory=list, max_length=MAX_SKILLS)


class ResearchOptions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    effort: ResearchEffort = 'medium'
    advanced: AdvancedResearch = Field(default_factory=AdvancedResearch)
    allow_downloads: bool = True
    selected_skill: str = Field('pathlab-research', max_length=120)
