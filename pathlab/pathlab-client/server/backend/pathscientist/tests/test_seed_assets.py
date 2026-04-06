import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def test_pathscientist_skill_registry_loads_seed_assets():
    from pathscientist.domain.skills import SkillRegistry

    registry = SkillRegistry()
    assert registry.load_all() >= 5
    assert "mil_classification" in registry.list_available()

    skill = registry.get("mil_classification")
    assert skill.get_template_path().exists()
    assert "classification_template.py" in str(skill.get_template_path())


def test_pathscientist_template_registry_resolves_common_dir():
    from pathscientist.domain.templates import get_common_dir, get_template_path

    template_path = get_template_path("classification")
    common_dir = get_common_dir()

    assert template_path.exists()
    assert common_dir.exists()
    assert (common_dir / "aggregators").exists()


def test_pathscientist_script_safety_flags_subprocess_execution():
    from pathscientist.runtime.script_safety import ScriptRisk, assess_script_risk

    risk, reasons = assess_script_risk("import subprocess\nsubprocess.run(['ls'])\n")

    assert risk == ScriptRisk.HIGH
    assert any("subprocess execution" in reason for reason in reasons)


def test_pathscientist_structured_output_extracts_json_after_thinking():
    from pathscientist.structured_output import extract_json

    payload = "<think>reasoning</think>\n```json\n{\"ok\": true, \"n\": 3}\n```"

    assert extract_json(payload) == {"ok": True, "n": 3}
