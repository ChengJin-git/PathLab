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

from autoresearch.domain.skills.base_skill import Skill  # noqa: E402

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
    assert "Default extractor: **Virchow2**" in out

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
    preferred list starting with Virchow2) and upstream_skill=feature_extraction.
    The rendered block must prioritize Virchow2 under preferred and point back
    at the feature_extraction skill so the agent knows to run it first.
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
    preferred_names = preferred_lines[0].split(":", 1)[1].strip()
    assert preferred_names.startswith("Virchow2"), (
        "Virchow2 must be first in the patch-level preferred extractor list; got:\n"
        + preferred_lines[0]
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


def test_system_prompt_includes_run_experiment_workflow_policy():
    """The system prompt must carry an explicit workflow-policy block telling
    the agent to execute iterations through ``run_experiment`` before
    ``ratchet_commit`` / ``ratchet_revert``. Pairs with the tool-level gate
    added in 57231463 / f5208311 — instruction-level guidance catches the
    bypass before the tool-level refusal fires (evidence store would have
    nothing to capture if the agent ran ``python script.py`` via terminal
    and then called ratchet_commit directly).
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
        skill_constraints="",
        skill_extractor_guidance="",
        environment_context="",
    )

    # Look for a workflow-policy section (heading) — distinct from the
    # incidental appearance of these tool names in the tools table. The
    # policy must call out the exact anti-pattern ("python ... ratchet_commit").
    assert "Workflow policy" in rendered, (
        "System prompt must contain a 'Workflow policy' section so the "
        "run_experiment-before-commit rule lives somewhere the agent can "
        "find it as a rule (not just a tool description)."
    )

    # The policy block must name both tools AND the ratchet_revert counterpart
    # so the agent knows the rule covers the failure branch too.
    assert "run_experiment" in rendered
    assert "ratchet_commit" in rendered
    assert "ratchet_revert" in rendered

    # Find the Workflow policy block and check all three tools live inside it
    # — guards against someone removing the policy while leaving the heading.
    policy_idx = rendered.index("Workflow policy")
    # Take the next ~600 chars as the block content (the policy is short).
    block = rendered[policy_idx : policy_idx + 600]
    assert "run_experiment" in block, (
        "run_experiment must appear inside the Workflow policy block, not "
        "only in the tools table. Got block:\n" + block
    )
    assert "ratchet_commit" in block, (
        "ratchet_commit must appear inside the Workflow policy block."
    )


def test_system_prompt_warns_against_agent_using_external_true():
    """Review Fix C (2026-04-21 post-fix code review, Finding 3, Option 3).

    ``RatchetCommitAction.external=True`` / ``RatchetRevertAction.external=True``
    is a documented escape hatch for humans committing out-of-band experiment
    runs; the reviewer pointed out that the agent can also pick it for itself,
    which would let the agent skirt the evidence gate on its own volition.

    The fix ships two defenses: the synthesis-layer gate
    (``_run_synthesis_stage`` forces ``paper_ready=False`` when
    ``external_experiment_opt_in`` appears in the skip log) and this
    prompt-level guidance. This test locks in the prompt-level piece so a
    future edit to ``system_prompt.j2`` cannot silently drop the
    "don't self-select external=true" instruction.
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
        skill_constraints="",
        skill_extractor_guidance="",
        environment_context="",
    )

    # The guidance must live inside the Workflow policy block, not stashed
    # somewhere the LLM won't find it.
    assert "Workflow policy" in rendered
    policy_idx = rendered.index("Workflow policy")
    block = rendered[policy_idx : policy_idx + 1500]

    # Two invariants: (1) the prohibition itself must be present, and (2)
    # it must explicitly carve out the user-asked escape hatch so a human
    # can still legitimately request external=true.
    assert "external=true" in block, (
        "Workflow policy must mention 'external=true' so the agent sees the "
        "rule. Got block:\n" + block
    )
    assert "Do NOT" in block or "do not" in block.lower(), (
        "Workflow policy must explicitly tell the agent NOT to use "
        "external=true on its own. Got block:\n" + block
    )
    assert "user" in block.lower(), (
        "Workflow policy must carve out the user-requested case (so humans "
        "can still commit out-of-band runs intentionally). Got block:\n"
        + block
    )


@pytest.mark.parametrize(
    "skill_yaml",
    ["patch_classification.yaml", "mil_classification.yaml", "feature_extraction.yaml"],
)
def test_skill_has_run_experiment_constraint(skill_yaml):
    """Each of the three training-capable skills must carry a constraint
    line reminding the agent to execute training through ``run_experiment``
    (so evidence is captured) rather than calling ``python`` directly via
    terminal and then ratchet_commit-ing a run that left no evidence.
    """
    skill = Skill.from_yaml(_SKILLS_DIR / skill_yaml)

    out = skill.get_constraints_prompt()

    assert "run_experiment" in out, (
        f"{skill_yaml} constraints must mention run_experiment so the agent "
        f"sees the workflow rule from the skill-specific constraints block "
        f"in addition to the global system-prompt policy. Got:\n{out}"
    )
    assert "ratchet_commit" in out, (
        f"{skill_yaml} constraints must mention ratchet_commit so the skill "
        f"block names the same two tools as the system-prompt policy. "
        f"Got:\n{out}"
    )


def test_preload_all_extractor_guidance_covers_pathology_fms():
    """Research mode (no ``config.skill_name`` set) can't know which skill the
    orchestrator's grounding stage will pick, so ``agent.preload_all_extractor_guidance``
    must concatenate extractor guidance from every registered skill — the
    LLM needs to see ``UNI2`` / ``CONCH`` / ablation markers *before* it
    writes ``train.py``, not after.

    Motivated by session_f5a4c0d2a560 (2026-04-21) which selected
    ``ViT-Large-CLIP`` / ``ViT-L-14 datacomp_xl`` — zero pathology FMs —
    because ``skill_extractor_guidance`` landed in the prompt as ``""``
    (config.skill_name was empty and no fallback preloaded anything).
    """
    from autoresearch.agent import preload_all_extractor_guidance

    out = preload_all_extractor_guidance()

    assert out, "preload must produce a non-empty guidance block for research mode"
    # The preamble must state the default policy explicitly so the agent does
    # not have to parse individual skill tiers to get the message.
    assert "pathology foundation models" in out.lower()
    # All three canonical pathology FMs from the feature_extraction /
    # patch_classification skill YAMLs must surface.
    for fm in ("UNI2", "CONCH", "Virchow2"):
        assert fm in out, f"{fm} must appear in the preloaded guidance; got:\n{out}"
    # ImageNet baselines must appear on an ablation-only line so the LLM
    # cannot read the block as a list of equally-valid options.
    ablation_lines = [
        line for line in out.splitlines() if "ablation" in line.lower()
    ]
    assert ablation_lines, "Preloaded guidance must carry ablation markers"
    assert any("ResNet50" in line for line in ablation_lines), (
        "ResNet50 must appear on an 'ablation only' line in preloaded output"
    )


def test_system_prompt_renders_extractor_guidance_when_constraints_empty():
    """Review follow-up (2026-04-21): the previous ``{% if skill_constraints %}``
    gate in ``system_prompt.j2`` swallowed ``skill_extractor_guidance`` whenever
    ``skill_constraints`` was empty, which is exactly the case in research
    mode when the orchestrator picks the skill at runtime (agent is created
    with ``config.skill_name=""`` → ``skill_constraints=""``). The gate must
    render the extractor guidance independently so the preloaded
    pathology-FM preferences actually reach the LLM.
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
        skill_constraints="",                       # empty — research mode
        skill_extractor_guidance="FIND-THIS-TOKEN", # must still surface
        environment_context="",
    )

    assert "FIND-THIS-TOKEN" in rendered, (
        "Extractor guidance must render even when skill_constraints is empty. "
        "The pre-fix j2 template had '{% if skill_constraints %}' wrapping both, "
        "so research-mode sessions lost the pathology-FM preferences entirely. "
        "Got rendered output (first 800 chars):\n" + rendered[:800]
    )
    # There must be a dedicated heading for the guidance block so the LLM
    # can key on it, not just raw text dropped at an arbitrary point.
    assert "Feature Extractor Guidance" in rendered
