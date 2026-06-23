"""End-to-end smoke for the v1 paper-generation pipeline using fixture data.

Drives all nine stages (`building_evidence` → `exporting`) against the
``wsi_classification_minimal`` fixture without reaching any real LLM or
external API: the agents pick up their `_NoNetworkXxxLLMClient` fallbacks
because pytest sets ``PYTEST_CURRENT_TEST``, and M8b's
``_NoNetworkCitationSearchProvider`` answers Semantic Scholar / PubMed
lookups deterministically.

The test asserts the pipeline contract end-to-end: every stage advances
through ``run_stage`` without raising, the locked blocks / sections /
bundle ZIPs land where downstream stages expect them, and all six M10
guards plus the M11 refinement loop accept the candidate.

To inspect the rendered outputs (sections, main.pdf when Docker is
available, bundle ZIPs, etc.), point pytest's basetemp at a stable
location, e.g.::

    uv run pytest tests/integration --basetemp=tests/integration/.smoke_runs

The `.smoke_runs` directory under ``tests/integration/`` is gitignored.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from pathlab_paper_agent.pipeline import create_dev_run, run_stage
from pathlab_paper_agent.schemas import CreatePaperRequest, SourceTaskRef, TemplateId

_STAGES = (
    "building_evidence",
    "outlining",
    "plotting",
    "literature_review",
    "section_writing",
    "validating",
    "refining",
    "rendering",
    "exporting",
)
_REQUIRED_SECTION_SLUGS = (
    "abstract",
    "introduction",
    "related_work",
    "methods",
    "experiments",
    "results",
    "discussion",
    "conclusion",
)


def _fixture_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "fixtures" / "wsi_classification_minimal"


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _slide_rows(fixture: Path) -> list[dict[str, str]]:
    with (fixture / "wsi_slides.csv").open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _seed_collector_bundle(paths) -> None:
    """Replicate the collector bundle the M3/M5 fixture tests use, so the smoke
    can skip the M2 collecting stage that would otherwise hit a real database."""
    fixture = _fixture_dir()
    task = _load_json(fixture / "task_record.json")
    model = _load_json(fixture / "trained_model.json")
    summary = _load_json(fixture / "analysis" / "summary.json")
    slides = _slide_rows(fixture)

    label_distribution: dict[str, int] = {}
    split_distribution: dict[str, int] = {}
    source_distribution: dict[str, int] = {}
    for row in slides:
        label_distribution[row["label"]] = label_distribution.get(row["label"], 0) + 1
        split_distribution[row["split"]] = split_distribution.get(row["split"], 0) + 1
        source_distribution[row["source"]] = source_distribution.get(row["source"], 0) + 1

    raw_dir = paths.evidence_dir / "raw_collected"
    raw_dir.mkdir(parents=True, exist_ok=True)
    bundle = {
        "paper_id": paths.paper_id,
        "mode": "fixture",
        "status": "ready",
        "collected_at": "2026-05-04T00:00:00Z",
        "source_tasks": [{"task_id": task["task_id"], "role": "main", "label": None}],
        "task_summaries": [
            {
                "task_id": task["task_id"],
                "role": "main",
                "exists": True,
                "status": "ready",
                "task_name": task["task_name"],
                "task_type": task["task_type"],
                "data_type": task["data_type"],
                "aggregation_level": task["aggregation_level"],
                "classes": task["classes"],
            }
        ],
        "dataset_summaries": [
            {
                "task_id": task["task_id"],
                "role": "main",
                "status": "ready",
                "datasets": [
                    {
                        "dataset_id": "fixture_ds",
                        "name": "Synthetic WSI Fixture",
                        "task_type": task["task_type"],
                        "data_type": task["data_type"],
                        "aggregation_level": task["aggregation_level"],
                        "wsi_count": len(slides),
                        "case_count": len({row["case_id"] for row in slides}),
                        "label_distribution": label_distribution,
                        "split_distribution": split_distribution,
                        "source_distribution": source_distribution,
                    }
                ],
            }
        ],
        "split_summaries": [
            {
                "task_id": task["task_id"],
                "role": "main",
                "status": "ready",
                "buckets": [
                    {
                        "split": split,
                        "wsi_count": count,
                        "case_count": count,
                        "label_distribution": {
                            row["label"]: sum(
                                1
                                for item in slides
                                if item["split"] == split and item["label"] == row["label"]
                            )
                            for row in slides
                            if row["split"] == split
                        },
                    }
                    for split, count in sorted(split_distribution.items())
                ],
            }
        ],
        "model_summaries": [
            {
                "task_id": task["task_id"],
                "role": "main",
                "status": "ready",
                "models": [model],
            }
        ],
        "analysis_summaries": [
            {
                "task_id": task["task_id"],
                "role": "main",
                "status": "ready",
                "selected_analysis_id": "20260504_010101",
                "analyses": [
                    {
                        "analysis_id": "20260504_010101",
                        "analysis_dir": "/private/pathlab/logs/analysis/wsi_cls_fixture/20260504_010101",
                        "summary_path": "/private/pathlab/logs/analysis/wsi_cls_fixture/20260504_010101/summary.json",
                        "results_path": "/private/pathlab/logs/analysis/wsi_cls_fixture/20260504_010101/results.json",
                        "summary": summary,
                        "results_count": len(_load_json(fixture / "analysis" / "results.json")),
                        "chart_paths": summary["chart_paths"],
                    }
                ],
            }
        ],
        "external_validation_summary": {"status": "missing", "items": [], "missing_evidence": []},
        "qualitative_summaries": [],
        "missing_evidence": [],
    }
    (raw_dir / "collector_bundle.json").write_text(json.dumps(bundle, indent=2), encoding="utf-8")


def _seed_user_inputs(paths) -> None:
    paths.idea.write_text(
        "# Idea\n\n"
        "Develop an attention-based MIL classifier for WSI tumor vs normal "
        "with PathLab evidence-locked reporting.\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_pipeline_runs_end_to_end_with_no_network_fixtures(tmp_path: Path) -> None:
    request = CreatePaperRequest(
        title="Synthetic WSI Tumor Classifier: A PathLab Smoke",
        source_tasks=[SourceTaskRef(task_id="wsi_cls_fixture")],
        selected_templates=[TemplateId.miccai, TemplateId.nature_scientific_reports],
    )
    paper_id, paths = await create_dev_run(request, paper_id="smoke_v1", uploads_dir=tmp_path)
    _seed_user_inputs(paths)
    _seed_collector_bundle(paths)

    final_manifest = None
    for stage in _STAGES:
        final_manifest = run_stage(paper_id, stage, uploads_dir=tmp_path)

    assert final_manifest is not None
    print(f"\n[smoke] paper run root: {paths.root}")

    # Sections written by the section-writing + refining stages.
    section_files = {p.stem for p in paths.sections_dir.glob("*.tex")}
    assert set(_REQUIRED_SECTION_SLUGS).issubset(section_files), section_files

    # Locked blocks landed for both selected templates.
    for template in ("miccai", "nature_scientific_reports"):
        template_blocks_dir = paths.locked_blocks_dir / template
        assert template_blocks_dir.is_dir(), template_blocks_dir
        assert (template_blocks_dir / "dataset_block.tex").is_file()
        assert (template_blocks_dir / "method_block.tex").is_file()

    # Citations chain produced bib + selected refs + coverage report.
    assert paths.refs_bib.is_file()
    assert (paths.citations_dir / "selected_refs.json").is_file()
    coverage = _load_json(paths.citations_dir / "coverage_report.json")
    assert coverage["status"] == "pass"

    # All six M10 guards reported pass on the final, refined sections.
    expected_guards = {
        "metric_guard",
        "identifier_guard",
        "latex_guard",
        "citation_guard",
        "claim_guard",
        "consistency_guard",
    }
    for guard in expected_guards:
        report = _load_json(paths.validation_dir / f"{guard}.json")
        assert report["status"] == "pass", report

    # Refinement loop accepted at least one iteration with the no-network critic.
    refinement_log = _load_json(paths.validation_dir / "refinement_log.json")
    assert refinement_log["accepted_iterations"], refinement_log

    # Export stage produced bundle ZIPs for both templates.
    for template in ("miccai", "nature_scientific_reports"):
        bundle = paths.exports_dir / f"{template}_bundle.zip"
        assert bundle.is_file(), bundle
        artifact = final_manifest.artifact_index[f"exports/{template}_bundle.zip"]
        # downloadable hinges on Docker availability + dry-run latexmk; we only
        # assert the bundle was registered in the manifest with the expected
        # private/public visibility.
        assert artifact["visibility"] == "public"

    # Manifest reflects the refining stage advancing the run; status remains
    # `running` here because we drove stages manually without a final
    # ``complete`` call, but the pipeline did not crash on any contract.
    assert final_manifest.current_stage.value == "exporting"
