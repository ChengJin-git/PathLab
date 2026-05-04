from __future__ import annotations

import json

import pytest

from pathlab_paper_agent.pipeline import create_dev_run, run_stage
from pathlab_paper_agent.validators.citation_guard import run as run_citation_guard
from pathlab_paper_agent.validators.identifier_guard import run as run_identifier_guard
from pathlab_paper_agent.validators.latex_guard import run as run_latex_guard
from pathlab_paper_agent.validators.metric_guard import (
    render_metric_placeholders,
    run as run_metric_guard,
)


@pytest.mark.asyncio
async def test_metric_guard_renders_placeholders_and_flags_unlocked_number(tmp_path):
    _paper_id, paths = await create_dev_run(paper_id="paper_metric", uploads_dir=tmp_path)
    paths.ensure_dirs()
    paths.evidence_lock_private.write_text(
        json.dumps({"metrics": {"test_accuracy": {"value": 0.892, "formatted": "89.2%"}}}),
        encoding="utf-8",
    )
    section = paths.sections_dir / "results.tex"
    section.write_text(
        "Accuracy was {{m:test_accuracy}}. The unsupported AUC was 0.777.\n",
        encoding="utf-8",
    )

    rendered = render_metric_placeholders(section.read_text(encoding="utf-8"), json.loads(paths.evidence_lock_private.read_text()))
    assert "89.2%" in rendered

    report = run_metric_guard(paths)
    assert report.status == "fail"
    assert any(issue.code == "unlocked_numeric_value" and issue.context == "0.777" for issue in report.issues)
    assert any(issue.code == "unrendered_metric_placeholder" for issue in report.issues)


@pytest.mark.asyncio
async def test_metric_guard_flags_unknown_placeholder(tmp_path):
    _paper_id, paths = await create_dev_run(paper_id="paper_metric_unknown", uploads_dir=tmp_path)
    paths.ensure_dirs()
    paths.evidence_lock_private.write_text(json.dumps({"metrics": {}}), encoding="utf-8")
    (paths.sections_dir / "results.tex").write_text("Metric {{m:missing_auc}}.\n", encoding="utf-8")

    report = run_metric_guard(paths)
    assert report.status == "fail"
    assert any(issue.code == "unknown_metric_placeholder" for issue in report.issues)


@pytest.mark.asyncio
async def test_metric_guard_allows_rendered_evidence_locked_metric(tmp_path):
    _paper_id, paths = await create_dev_run(paper_id="paper_metric_rendered", uploads_dir=tmp_path)
    paths.ensure_dirs()
    paths.evidence_lock_private.write_text(
        json.dumps({"metrics": {"test_accuracy": {"value": 0.892, "formatted": "89.2%"}}}),
        encoding="utf-8",
    )
    (paths.sections_dir / "results.tex").write_text("Accuracy was 89.2%.\n", encoding="utf-8")

    report = run_metric_guard(paths)
    assert report.status == "pass"


@pytest.mark.asyncio
async def test_identifier_guard_flags_private_mapping_and_raw_paths(tmp_path):
    _paper_id, paths = await create_dev_run(paper_id="paper_identifier", uploads_dir=tmp_path)
    paths.ensure_dirs()
    paths.evidence_lock_private.write_text(
        json.dumps({"phi_mapping": {"case_ids": {"CASE-12345": "case_001"}, "institution_names": {"Example Hospital": "Site_A"}}}),
        encoding="utf-8",
    )
    (paths.sections_dir / "discussion.tex").write_text(
        "CASE-12345 came from /Users/private/raw.svs at Example Hospital.\n",
        encoding="utf-8",
    )

    report = run_identifier_guard(paths)
    assert report.status == "fail"
    codes = {issue.code for issue in report.issues}
    assert "private_identifier_leak" in codes
    assert "raw_path_leak" in codes


@pytest.mark.asyncio
async def test_latex_guard_flags_unbalanced_braces_and_missing_inputs(tmp_path):
    _paper_id, paths = await create_dev_run(paper_id="paper_latex", uploads_dir=tmp_path)
    paths.ensure_dirs()
    (paths.sections_dir / "methods.tex").write_text(
        "\\section{Methods\n\\input{locked_blocks/missing_block.tex}\n",
        encoding="utf-8",
    )

    report = run_latex_guard(paths)
    assert report.status == "fail"
    codes = {issue.code for issue in report.issues}
    assert "unbalanced_braces" in codes
    assert "missing_input" in codes


@pytest.mark.asyncio
async def test_latex_guard_rejects_input_and_graphic_path_escapes(tmp_path):
    _paper_id, paths = await create_dev_run(paper_id="paper_latex_escape", uploads_dir=tmp_path)
    paths.ensure_dirs()
    outside_tex = tmp_path / "outside.tex"
    outside_tex.write_text("outside\n", encoding="utf-8")
    outside_png = tmp_path / "outside.png"
    outside_png.write_bytes(b"not really a png")
    (paths.sections_dir / "methods.tex").write_text(
        f"\\input{{../outside.tex}}\n\\input{{{outside_tex}}}\n"
        f"\\includegraphics{{../outside.png}}\n\\includegraphics{{{outside_png}}}\n",
        encoding="utf-8",
    )

    report = run_latex_guard(paths)
    assert report.status == "fail"
    codes = {issue.code for issue in report.issues}
    assert "unsafe_input_path" in codes
    assert "unsafe_graphic_path" in codes


@pytest.mark.asyncio
async def test_citation_guard_flags_orphan_and_low_coverage(tmp_path):
    _paper_id, paths = await create_dev_run(paper_id="paper_cite", uploads_dir=tmp_path)
    paths.ensure_dirs()
    (paths.sections_dir / "intro.tex").write_text(
        "Prior work exists \\cite{Good2024,Missing2025}.\n",
        encoding="utf-8",
    )
    paths.refs_bib.write_text("@article{Good2024, title={Good}}\n", encoding="utf-8")
    (paths.citations_dir / "selected_refs.json").write_text(
        json.dumps({"items": [{"bib_key": "Good2024"}, {"bib_key": "Unused2023"}]}),
        encoding="utf-8",
    )
    (paths.citations_dir / "required_cites.json").write_text(
        json.dumps({"items": [{"bib_key": "Unused2023"}]}), encoding="utf-8"
    )

    report = run_citation_guard(paths)
    assert report.status == "fail"
    codes = {issue.code for issue in report.issues}
    assert "orphan_cite" in codes
    assert "missing_required_cite" in codes
    assert "citation_coverage_low" in codes


@pytest.mark.asyncio
async def test_validating_stage_writes_m10a_reports(tmp_path):
    paper_id, paths = await create_dev_run(paper_id="paper_validate", uploads_dir=tmp_path)
    for stage in [
        "collecting",
        "building_evidence",
        "outlining",
        "plotting",
        "literature_review",
        "section_writing",
    ]:
        run_stage(paper_id, stage, uploads_dir=tmp_path)

    manifest = run_stage(paper_id, "validating", uploads_dir=tmp_path)
    assert manifest.current_stage.value == "validating"
    for name in ["metric_guard", "identifier_guard", "latex_guard", "citation_guard"]:
        report_path = paths.validation_dir / f"{name}.json"
        assert report_path.is_file()
        assert json.loads(report_path.read_text(encoding="utf-8"))["status"] == "pass"
    assert (paths.validation_dir / "warnings.md").is_file()
