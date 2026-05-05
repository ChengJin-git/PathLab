from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from pathlab_paper_agent.pipeline import create_dev_run, run_stage
from pathlab_paper_agent.renderers.bundle_validator import BundleValidationResult
from pathlab_paper_agent.renderers.latex_compiler import CompileResult
from pathlab_paper_agent.schemas import CreatePaperRequest, SourceTaskRef
from pathlab_paper_agent.stages import exporting as exporting_stage

_SECTION_NAMES = (
    "abstract",
    "introduction",
    "related_work",
    "methods",
    "experiments",
    "results",
    "discussion",
    "conclusion",
)
_TEMPLATE_IDS = ("miccai", "nature_scientific_reports")
_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
    b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _fixture_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "fixtures" / "wsi_classification_minimal"


def _seed_fixture_inputs(paths) -> None:
    golden_blocks = _fixture_dir() / "golden" / "deterministic" / "locked_blocks"
    for target_dir in (
        paths.locked_blocks_dir,
        paths.locked_blocks_dir / "miccai",
        paths.locked_blocks_dir / "nature_scientific_reports",
    ):
        target_dir.mkdir(parents=True, exist_ok=True)
        for block in golden_blocks.glob("*.tex"):
            shutil.copy2(block, target_dir / block.name)

    paths.tables_dir.mkdir(parents=True, exist_ok=True)
    (paths.tables_dir / "table_1_dataset.tex").write_text(
        "\\begin{tabular}{lr}\\toprule Item & Value \\\\ \\midrule WSIs & 4 \\\\ \\bottomrule\\end{tabular}\n",
        encoding="utf-8",
    )
    for section in _SECTION_NAMES:
        (paths.sections_dir / f"{section}.tex").write_text(
            f"\\section{{{section.replace('_', ' ').title()}}}\n"
            "Fixture text for export hardening.\n",
            encoding="utf-8",
        )
    paths.refs_bib.write_text(
        "@article{Fixture2026,\n"
        "  title={Fixture reference},\n"
        "  author={PathLab},\n"
        "  journal={Synthetic},\n"
        "  year={2026}\n"
        "}\n",
        encoding="utf-8",
    )

    (paths.figures_dir / "fig_ready.png").write_bytes(_PNG_BYTES)
    (paths.figures_dir / "fig_pending.png").write_bytes(_PNG_BYTES)
    (paths.figures_dir / "manifest.json").write_text(
        json.dumps(
            {
                "figures": [
                    {
                        "figure_id": "fig:ready",
                        "status": "ready",
                        "path": "figures/fig_ready.png",
                    },
                    {
                        "figure_id": "fig:pending",
                        "status": "pending_generation",
                        "path": "figures/fig_pending.png",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    private_dir = paths.evidence_dir / "raw_collected"
    private_dir.mkdir(parents=True, exist_ok=True)
    (private_dir / "collector_bundle.json").write_text('{"raw": true}', encoding="utf-8")
    paths.evidence_lock_private.write_text('{"case_id": "CASE-0001"}', encoding="utf-8")
    paths.intro_rw_draft_dir.mkdir(parents=True, exist_ok=True)
    (paths.intro_rw_draft_dir / "introduction.tex").write_text("private draft", encoding="utf-8")


def _add_private_files_to_final(paths) -> None:
    for template_id in _TEMPLATE_IDS:
        final_dir = paths.final_for_template(template_id)
        (final_dir / "source_mappings.json").write_text('{"case": "private"}', encoding="utf-8")
        (final_dir / "figures" / "phi_mapping.json").write_text('{"case": "private"}', encoding="utf-8")
        (final_dir / "raw_collected").mkdir()
        (final_dir / "raw_collected" / "private.json").write_text("{}", encoding="utf-8")
        (final_dir / "evidence").mkdir()
        (final_dir / "evidence" / "evidence_lock.private.json").write_text("{}", encoding="utf-8")
        (final_dir / "drafts" / "intro_rw_draft").mkdir(parents=True)
        (final_dir / "drafts" / "intro_rw_draft" / "introduction.tex").write_text(
            "private draft",
            encoding="utf-8",
        )


def _mock_successful_compile(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_compile(root: Path, template_id: str) -> CompileResult:
        final_dir = root / "final" / template_id
        pdf_path = final_dir / "main.pdf"
        summary_path = final_dir / "main.compile_summary.txt"
        pdf_path.write_bytes(b"%PDF-1.4\n% mock\n")
        summary_path.write_text("compile_summary\n  status=compiled\n", encoding="utf-8")
        return CompileResult("compiled", 0, pdf_path, summary_path, stdout="ok")

    monkeypatch.setattr(exporting_stage, "docker_available", lambda: True)
    monkeypatch.setattr(exporting_stage, "compile_with_docker", fake_compile)


def _mock_validation(
    monkeypatch: pytest.MonkeyPatch,
    result: BundleValidationResult,
) -> list[Path]:
    calls: list[Path] = []

    def fake_validate(bundle_path: Path) -> BundleValidationResult:
        calls.append(bundle_path)
        return result

    monkeypatch.setattr(exporting_stage, "validate_bundle", fake_validate)
    return calls


@pytest.mark.asyncio
async def test_export_stage_builds_downloadable_closed_bundles_from_fixture(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = CreatePaperRequest(
        title="Fixture M12a Export Paper",
        source_tasks=[SourceTaskRef(task_id="wsi_cls_fixture")],
    )
    paper_id, paths = await create_dev_run(request, paper_id="paper_m12a_export", uploads_dir=tmp_path)
    _seed_fixture_inputs(paths)
    run_stage(paper_id, "rendering", uploads_dir=tmp_path)
    _add_private_files_to_final(paths)
    _mock_successful_compile(monkeypatch)
    validation_calls = _mock_validation(
        monkeypatch,
        BundleValidationResult(
            status="passed",
            returncode=0,
            downloadable=True,
            summary="mock latexmk passed",
        ),
    )

    manifest = run_stage(paper_id, "exporting", uploads_dir=tmp_path)

    assert len(validation_calls) == 2
    for template_id in _TEMPLATE_IDS:
        bundle_path = paths.exports_dir / f"{template_id}_bundle.zip"
        assert bundle_path.is_file()
        assert (paths.final_for_template(template_id) / "main.pdf").is_file()
        assert manifest.artifact_index[f"exports/{template_id}_bundle.zip"]["downloadable"] is True
        assert f"final/{template_id}/main.pdf" in manifest.artifact_index

        with zipfile.ZipFile(bundle_path) as archive:
            names = set(archive.namelist())
            readme = archive.read("README.md").decode("utf-8")
        assert {"main.tex", "refs.bib", "README.md", "figures/fig_ready.png"} <= names
        assert "locked_blocks/method_block.tex" in names
        assert "tables/table_1_dataset.tex" in names
        assert "sections/abstract.tex" in names
        assert "figures/fig_pending.png" not in names
        assert "figures/manifest.json" not in names
        assert "source_mappings.json" not in names
        assert "figures/phi_mapping.json" not in names
        assert not any(name.startswith("raw_collected/") for name in names)
        assert not any(name.startswith("drafts/intro_rw_draft/") for name in names)
        assert "evidence/evidence_lock.private.json" not in names
        assert "Source tasks: `wsi_cls_fixture:main`" in readme
        assert "Agent versions:" in readme

    with zipfile.ZipFile(paths.exports_dir / "miccai_bundle.zip") as archive:
        miccai_names = set(archive.namelist())
    assert "llncs.cls" in miccai_names
    assert "splncs04.bst" in miccai_names

    with zipfile.ZipFile(paths.exports_dir / "nature_scientific_reports_bundle.zip") as archive:
        nature_names = set(archive.namelist())
    assert "sn-jnl.cls" in nature_names
    assert "sn-nature.bst" in nature_names


@pytest.mark.asyncio
async def test_export_stage_marks_bundle_not_downloadable_when_dry_run_fails(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper_id, paths = await create_dev_run(paper_id="paper_m12a_export_fail", uploads_dir=tmp_path)
    _seed_fixture_inputs(paths)
    run_stage(paper_id, "rendering", uploads_dir=tmp_path)
    _mock_successful_compile(monkeypatch)
    _mock_validation(
        monkeypatch,
        BundleValidationResult(
            status="failed",
            returncode=12,
            downloadable=False,
            summary="Undefined control sequence near line 7.",
        ),
    )

    manifest = run_stage(paper_id, "exporting", uploads_dir=tmp_path)

    for template_id in _TEMPLATE_IDS:
        artifact = manifest.artifact_index[f"exports/{template_id}_bundle.zip"]
        assert artifact["downloadable"] is False
    warnings = (paths.validation_dir / "warnings.md").read_text(encoding="utf-8")
    assert "M12a Export Hardening" in warnings
    assert "Undefined control sequence" in warnings


def test_bundle_validator_runs_latexmk_inside_extracted_zip(tmp_path, monkeypatch) -> None:
    from pathlab_paper_agent.renderers import bundle_validator

    bundle = tmp_path / "bundle.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("main.tex", "\\documentclass{article}\\begin{document}ok\\end{document}")
        archive.writestr("main.pdf", b"stale pdf")
        archive.writestr("main.aux", "stale aux")
        archive.writestr("refs.bib", "")

    def fake_run(cmd, **kwargs):
        assert "--entrypoint" in cmd
        assert "latexmk" in cmd
        assert "-dvi=0" in cmd
        assert "-ps=0" in cmd
        assert "-pdf" in cmd
        assert "-interaction=nonstopmode" in cmd
        assert kwargs["check"] is False
        assert kwargs["capture_output"] is True
        mount = cmd[cmd.index("-v") + 1]
        host_dir = Path(mount.split(":", 1)[0])
        assert (host_dir / "main.tex").is_file()
        assert not (host_dir / "main.pdf").exists()
        assert not (host_dir / "main.aux").exists()
        (host_dir / "main.pdf").write_bytes(b"%PDF-1.4\n")
        return subprocess.CompletedProcess(cmd, 0, stdout="latexmk ok", stderr="")

    monkeypatch.setattr(bundle_validator, "docker_available", lambda: True)
    monkeypatch.setattr(bundle_validator.subprocess, "run", fake_run)

    result = bundle_validator.validate_bundle(bundle)

    assert result.status == "passed"
    assert result.returncode == 0
    assert result.downloadable is True


@pytest.mark.asyncio
async def test_export_stage_clears_stale_m12a_warnings_after_success(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper_id, paths = await create_dev_run(paper_id="paper_m12a_warning_clear", uploads_dir=tmp_path)
    _seed_fixture_inputs(paths)
    run_stage(paper_id, "rendering", uploads_dir=tmp_path)
    _mock_successful_compile(monkeypatch)
    _mock_validation(
        monkeypatch,
        BundleValidationResult(
            status="failed",
            returncode=12,
            downloadable=False,
            summary="first run failed",
        ),
    )
    run_stage(paper_id, "exporting", uploads_dir=tmp_path)
    assert "M12a Export Hardening" in (paths.validation_dir / "warnings.md").read_text(encoding="utf-8")

    _mock_validation(
        monkeypatch,
        BundleValidationResult(
            status="passed",
            returncode=0,
            downloadable=True,
            summary="second run passed",
        ),
    )
    manifest = run_stage(paper_id, "exporting", uploads_dir=tmp_path)

    assert "M12a Export Hardening" not in (paths.validation_dir / "warnings.md").read_text(encoding="utf-8")
    for template_id in _TEMPLATE_IDS:
        assert manifest.artifact_index[f"exports/{template_id}_bundle.zip"]["downloadable"] is True


@pytest.mark.asyncio
async def test_export_excludes_figures_when_manifest_is_missing(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper_id, paths = await create_dev_run(paper_id="paper_m12a_missing_fig_manifest", uploads_dir=tmp_path)
    _seed_fixture_inputs(paths)
    paths.figures_manifest.unlink()
    run_stage(paper_id, "rendering", uploads_dir=tmp_path)
    _mock_successful_compile(monkeypatch)
    _mock_validation(
        monkeypatch,
        BundleValidationResult(
            status="passed",
            returncode=0,
            downloadable=True,
            summary="mock latexmk passed",
        ),
    )

    run_stage(paper_id, "exporting", uploads_dir=tmp_path)

    with zipfile.ZipFile(paths.exports_dir / "miccai_bundle.zip") as archive:
        names = set(archive.namelist())
    assert "figures/fig_ready.png" not in names
    assert "figures/fig_pending.png" not in names


@pytest.mark.asyncio
async def test_export_reports_missing_dependencies_when_section_inputs_missing_locked_block(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pathlab_paper_agent.renderers.zip_exporter import export_bundle

    paper_id, paths = await create_dev_run(paper_id="paper_m12a_missing_dep", uploads_dir=tmp_path)
    _seed_fixture_inputs(paths)
    # Section references a locked block that does not exist in final/
    (paths.sections_dir / "results.tex").write_text(
        "\\section{Results}\n\\input{locked_blocks/missing_results_block.tex}\n",
        encoding="utf-8",
    )
    run_stage(paper_id, "rendering", uploads_dir=tmp_path)
    config = paths.config
    config_payload = json.loads(config.read_text(encoding="utf-8"))
    from pathlab_paper_agent.schemas import PaperConfig

    paper_config = PaperConfig.model_validate(config_payload)

    bundle_path = paths.exports_dir / "miccai_bundle_dep.zip"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    result = export_bundle(
        paths.final_for_template("miccai"),
        bundle_path,
        paper_config,
        "miccai",
    )

    assert result.dependency_closed is False
    assert "locked_blocks/missing_results_block.tex" in result.missing_dependencies


def test_bundle_validator_rejects_zip_with_path_traversal_member(tmp_path) -> None:
    from pathlab_paper_agent.renderers.bundle_validator import validate_bundle

    bundle = tmp_path / "evil.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("main.tex", "\\documentclass{article}\\begin{document}ok\\end{document}")
        archive.writestr("../escape.tex", "private")

    result = validate_bundle(bundle)

    assert result.status == "failed"
    assert result.downloadable is False
    assert "Unsafe ZIP member path" in result.summary or "escapes extraction root" in result.summary
