"""Bundled skills must be complete, pinned, discoverable and actually used."""

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from backend.autoresearch.engine import builtin_skills, runtime
from backend.services.text_editor import (
    EditingError,
    manuscript_editing_prompt,
    validate_manuscript_edit,
)


def test_full_upstream_packages_and_licenses_match_lock():
    root = builtin_skills.LIBRARY
    lock = json.loads((root / "sources.lock.json").read_text())
    for source in lock["sources"]:
        assert len(source["commit"]) == 40
        assert any(Path(name).name.startswith("LICENSE") for name in source["files"])
        for relative, expected in source["files"].items():
            path = root / source["directory"] / relative
            assert path.is_file(), relative
            assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, relative
    items = builtin_skills.catalog()
    ids = {item["id"] for item in items}
    assert len(ids) == 36
    assert sum(item["source"] == "bundled" for item in items) == 29
    assert {
        "nature-shared",
        "nature-writing",
        "nature-academic-search",
        "nature-data",
        "nature-figure",
        "nature-reviewer",
        "humanizer",
        "humanizer-zh",
        "pathtrove",
        "pathtrove-data",
        "pathtrove-best-data",
    } <= ids


def test_domain_skills_have_native_entries_and_do_not_overwrite_user_skill(tmp_path):
    user = tmp_path / ".opencode/skills/user-skill-1/SKILL.md"
    user.parent.mkdir(parents=True)
    user.write_text("My research rules")
    builtin_skills.install_domain_skills(tmp_path)
    entries = list((tmp_path / ".opencode/skills").glob("pathlab-*/SKILL.md"))
    assert len(entries) == 6 and user.read_text() == "My research rules"
    for path in entries:
        text = path.read_text()
        header = yaml.safe_load(text.split("---", 2)[1])
        assert header["name"] == path.parent.name
        assert "/opt/pathlab/guidance/" in text and "submit_computation" in text


@pytest.mark.parametrize(
    "stage,section",
    [
        ("plan", ""),
        ("section", "Abstract"),
        ("section", "Methods"),
        ("section", "Experiments and results"),
        ("section", "Discussion"),
        ("review", ""),
        ("polish", ""),
    ],
)
@pytest.mark.parametrize("language", ["en-US", "zh-CN", "zh-HK"])
def test_writer_loads_real_manifest_fragments_and_correct_humanizer(
    stage, section, language
):
    context = builtin_skills.writing_context(stage, language, section)
    assert 0 < len(context["text"]) < 110000
    assert len(context["sha256"]) == 64
    assert "nature-shared/core/terminology-ledger.md" in context["text"]
    for filename in context["files"]:
        assert (builtin_skills.LIBRARY / filename).is_file()
    if stage in {"review", "polish"}:
        assert (
            "humanizer-zh" if language.startswith("zh") else "humanizer"
        ) in context["skills"]
        assert "embedded workflow" in context["text"]


def test_polishing_uses_passage_language_and_explicit_translation_request():
    english = manuscript_editing_prompt(
        "Edit.", "Validation AUROC is 0.81.", "Shorten it.", "zh-CN"
    )
    chinese = manuscript_editing_prompt(
        "编辑。", "验证集 AUROC 为0.81。", "更自然", "zh-HK"
    )
    translation = manuscript_editing_prompt(
        "Edit.", "验证集 AUROC 为0.81。", "翻译为学术英文", "zh-CN"
    )
    assert (
        "editing/humanizer/SKILL.md" in english
        and "editing/humanizer-zh/SKILL.md" not in english
    )
    assert "editing/humanizer-zh/SKILL.md" in chinese
    assert "editing/humanizer/SKILL.md" in translation


def test_polish_fact_guards_keep_measurements_citations_and_links():
    validate_manuscript_edit(
        "28例验证病例的AUROC为0.81[1]。", "28 例验证病例的 AUROC 为 0.810 [1]。"
    )
    validate_manuscript_edit("The AUROC was .81.", "The AUROC was 0.810.")
    with pytest.raises(EditingError):
        validate_manuscript_edit("AUROC 0.81.", "AUROC 0.91.")
    original = "## Results\n\nValidation AUROC was 0.81 in 28 cases [1, 2]. No external validation. ![Plot](figures/figure-1.png)"
    validate_manuscript_edit(original, original.replace("was", "reached"))
    for changed in [
        original.replace("0.81", "0.91"),
        original.replace("[1, 2]", "[1]"),
        original.replace("28 cases", "cases"),
        original.replace("## Results", "## Conclusion"),
        original.replace("figure-1.png", "figure-2.png"),
    ]:
        with pytest.raises(EditingError):
            validate_manuscript_edit(original, changed)


def test_runtime_mounts_library_read_only(monkeypatch, tmp_path):
    image = tmp_path / "sandbox.sif"
    image.write_bytes(b"test")
    monkeypatch.setattr(runtime, "_resolve_default_image", lambda: str(image))
    monkeypatch.setattr(runtime, "_resolve_apptainer_bin", lambda: "apptainer")
    monkeypatch.setattr(runtime.Config, "get_autoresearch_dir", lambda: tmp_path)
    monkeypatch.setattr(runtime.Config, "get_uploads_dir", lambda: tmp_path)
    workspace = tmp_path / "session_test"
    workspace.mkdir()
    command = runtime.sandbox_command(workspace, {})
    assert f"{builtin_skills.LIBRARY}:/opt/pathlab/skill-library:ro" in command


def test_pathtrove_data_is_pinned_mounted_read_only_and_served_over_mcp(monkeypatch, tmp_path):
    import json

    from backend.autoresearch.engine import pathtrove

    image = tmp_path / "sandbox.sif"
    image.write_bytes(b"test")
    monkeypatch.setattr(runtime, "_resolve_default_image", lambda: str(image))
    monkeypatch.setattr(runtime, "_resolve_apptainer_bin", lambda: "apptainer")
    monkeypatch.setattr(runtime.Config, "get_autoresearch_dir", lambda: tmp_path)
    monkeypatch.setattr(runtime.Config, "get_uploads_dir", lambda: tmp_path)
    assert not pathtrove.ready()
    pinned = pathtrove.manifest()
    data = pathtrove.home() / "data" / pinned["data_version"]
    data.mkdir(parents=True)
    (data / pathtrove.MARKER).write_text(json.dumps({"archive_sha256": "0" * 64}))
    assert not pathtrove.ready()
    (data / pathtrove.MARKER).write_text(json.dumps({"archive_sha256": pinned["archive"]["sha256"]}))
    assert pathtrove.ready()
    workspace = tmp_path / "session_test"
    workspace.mkdir()
    command = runtime.sandbox_command(workspace, {})
    assert f"{pathtrove.home()}:{pathtrove.SANDBOX_HOME}:ro" in command
    server = pathtrove.mcp_server()
    entry = server["command"][1]
    assert entry.startswith("/opt/pathlab/skill-library/")
    assert (builtin_skills.LIBRARY / entry.removeprefix("/opt/pathlab/skill-library/")).is_file()
    assert server["environment"]["PATHTROVE_HOME"] == pathtrove.SANDBOX_HOME
