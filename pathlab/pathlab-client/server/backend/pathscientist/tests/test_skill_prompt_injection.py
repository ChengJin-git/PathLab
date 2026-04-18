"""Tests for Skill.get_extractor_guidance_prompt + system_prompt.j2 injection.

Motivated by session_142a4acaed08 which selected 7 ImageNet/CLIP backbones and
zero pathology foundation models. Root cause: ``agent.py`` only injected
``skill.get_constraints_prompt()`` into the system prompt; the richer
``recommended_feature_extractors`` / ``extractors_available`` / ``default_extractor``
/ ``extractor_selection_guidance`` fields we added to the skill YAMLs were
silently loaded into a ``data`` dict and never surfaced to the LLM.

This regression suite asserts:

* ``Skill.get_extractor_guidance_prompt()`` renders the extractor tiers,
  preferred FM list, ablation-only baselines, default extractor in bold,
  selection rule, and upstream-skill pointer when the YAML data is present.
* ``Skill.get_extractor_guidance_prompt()`` returns ``""`` when the YAML
  carries none of those fields (e.g. segmentation, survival).
* ``prompts/system_prompt.j2`` renders the ``skill_extractor_guidance``
  kwarg verbatim so the block actually reaches the LLM.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pathscientist.domain.skills.base_skill import Skill  # noqa: E402

_SKILLS_DIR = Path(__file__).parent.parent / "domain" / "skills"
_PROMPT_FILE = Path(__file__).parent.parent / "prompts" / "system_prompt.j2"


def test_feature_extraction_skill_renders_tiers():
    """feature_extraction.yaml has extractors_available (4 tiers) +
    default_extractor + extractor_selection_guidance. The rendered block
    must advertise the default FM and mark ImageNet as ablation-only so
    the agent cannot silently fall back to ResNet50 / ViT-L/16.
    """
    skill = Skill.from_yaml(_SKILLS_DIR / "feature_extraction.yaml")

    out = skill.get_extractor_guidance_prompt()

    assert out, "feature_extraction skill must produce a non-empty guidance block"
    assert "Default extractor: **UNI2**" in out

    # ImageNet baselines must be called out as ablation-only. The exact tier
    # name lives in extractors_available (imagenet_baseline) — the rendered
    # block must connect ResNet50 to an "ablation" context so the LLM
    # cannot pick it as primary.
    ablation_lines = [
        line
        for line in out.splitlines()
        if "ablation" in line.lower()
    ]
    assert ablation_lines, (
        "Expected at least one line mentioning 'ablation' to cover ImageNet "
        "baselines; got:\n" + out
    )
    assert any("ResNet50" in line for line in ablation_lines), (
        "ResNet50 must appear on an 'ablation only' line; got:\n" + out
    )

    # The selection-rule prose should flow through too.
    assert "pathology" in out.lower()


def test_patch_classification_skill_renders_upstream():
    """patch_classification.yaml has recommended_feature_extractors (with
    preferred list containing CONCH) and upstream_skill=feature_extraction.
    The rendered block must list CONCH under preferred and point back at
    the feature_extraction skill so the agent knows to run it first.
    """
    skill = Skill.from_yaml(_SKILLS_DIR / "patch_classification.yaml")

    out = skill.get_extractor_guidance_prompt()

    assert out, "patch_classification skill must produce a non-empty guidance block"
    assert "CONCH" in out

    # CONCH must be on the preferred line (not just buried somewhere).
    preferred_lines = [
        line for line in out.splitlines() if "Preferred" in line
    ]
    assert preferred_lines, (
        "Expected a 'Preferred' line listing pathology FMs; got:\n" + out
    )
    assert any("CONCH" in line for line in preferred_lines), (
        "CONCH must appear on the 'Preferred' line; got:\n" + out
    )

    # Upstream-skill pointer must name feature_extraction explicitly so the
    # agent can route there rather than inventing its own extraction step.
    assert "feature_extraction" in out


def test_skill_without_extractor_fields_returns_empty(tmp_path):
    """A YAML carrying none of the new extractor fields must produce an
    empty guidance block — we must not emit a hanging 'Feature extractor
    guidance:' heading with nothing under it.
    """
    bare_yaml = tmp_path / "bare.yaml"
    bare_yaml.write_text(
        yaml.safe_dump(
            {
                "name": "bare",
                "description": "Minimal skill without extractor metadata.",
                "template": "classification_template.py",
            }
        ),
        encoding="utf-8",
    )

    skill = Skill.from_yaml(bare_yaml)

    assert skill.get_extractor_guidance_prompt() == ""


def test_system_prompt_includes_guidance():
    """The system prompt template must render the ``skill_extractor_guidance``
    kwarg. Without this the extractor guidance would never reach the LLM
    even after Skill.get_extractor_guidance_prompt() returned text.
    """
    import jinja2

    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_PROMPT_FILE.parent)),
        keep_trailing_newline=True,
    )
    template = env.get_template(_PROMPT_FILE.name)
    rendered = template.render(
        primary_metric="auc",
        max_iterations=5,
        research_question="",
        skill_constraints="Some skill constraints.",
        skill_extractor_guidance="X-Guidance",
        environment_context="",
    )

    assert "X-Guidance" in rendered
