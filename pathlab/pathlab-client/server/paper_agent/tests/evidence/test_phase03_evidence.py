from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pytest

from pathlab_paper_agent.pipeline import create_dev_run, run_stage
from pathlab_paper_agent.schemas import CreatePaperRequest, SourceTaskRef
from pathlab_paper_agent.validators.identifier_guard import run as run_identifier_guard
from pathlab_paper_agent.validators.metric_guard import run as run_metric_guard


def _fixture_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "fixtures" / "wsi_classification_minimal"


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _slide_rows(fixture: Path) -> list[dict[str, str]]:
    with (fixture / "wsi_slides.csv").open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_fixture_raw_collected(paths) -> None:
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
    collector_bundle = {
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
                                1 for item in slides if item["split"] == split and item["label"] == row["label"]
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
    (raw_dir / "collector_bundle.json").write_text(json.dumps(collector_bundle), encoding="utf-8")


def _rewrite_fixture_as_crc_msi(paths) -> None:
    raw_path = paths.evidence_dir / "raw_collected" / "collector_bundle.json"
    bundle = _load_json(raw_path)
    bundle["task_summaries"][0]["task_name"] = "CRC MSI WSI Classification"
    bundle["task_summaries"][0]["classes"] = ["MSI", "MSS"]
    cohort = bundle["dataset_summaries"][0]["datasets"][0]
    cohort["name"] = "CRC MSI cohort"
    cohort["source_organ"] = "colorectal"
    cohort["label_distribution"] = {"MSI": 2, "MSS": 2}
    bundle["model_summaries"][0]["models"][0]["classes"] = ["MSI", "MSS"]
    raw_path.write_text(json.dumps(bundle), encoding="utf-8")


@pytest.mark.asyncio
async def test_phase03_builds_scrubbed_evidence_and_tables_from_fixture(tmp_path) -> None:
    from pathlab_paper_agent.storage import is_path_allowed_for_download

    request = CreatePaperRequest(
        title="Fixture Evidence Paper",
        source_tasks=[SourceTaskRef(task_id="wsi_cls_fixture")],
    )
    paper_id, paths = await create_dev_run(request, paper_id="paper_phase03_fixture", uploads_dir=tmp_path)
    _write_fixture_raw_collected(paths)

    manifest = run_stage(paper_id, "building_evidence", uploads_dir=tmp_path)

    private_lock = _load_json(paths.evidence_lock_private)
    public_evidence = _load_json(paths.evidence_public)
    table_2 = (paths.tables_dir / "table_2_main_results.tex").read_text(encoding="utf-8")
    experimental_log = paths.experimental_log.read_text(encoding="utf-8")

    assert private_lock["collector"]["status"] == "ready"
    assert private_lock["metrics"]["main.metrics.test_accuracy"]["formatted"] == "0.9123"
    assert "CASE-0001" in private_lock["private_identifiers"]["case_ids"]
    assert public_evidence["phi_scrubbed"] is True
    assert public_evidence["datasets"][0]["wsi_count"] == 4
    assert public_evidence["metrics"][0]["formatted"]
    assert "CASE-0001" not in json.dumps(public_evidence)
    assert "/private/pathlab" not in json.dumps(public_evidence)
    assert "Example Hospital" not in json.dumps(public_evidence)
    assert "0.9123" in table_2
    assert "0.9456" in table_2
    assert "CASE-0001" not in table_2
    assert "/private/pathlab" not in experimental_log

    assert (paths.evidence_dir / "dataset_summary.public.json").is_file()
    assert (paths.tables_dir / "table_5_external_validation.tex").is_file()
    assert (paths.locked_blocks_dir / "evidence_gaps.tex").is_file()

    # \newcommand names must be letters only — guard against regression to
    # `\metricmain.metrics.test_accuracy` which is invalid LaTeX.
    macros_text = (paths.locked_blocks_dir / "metrics_macros.tex").read_text(encoding="utf-8")
    cmd_names = re.findall(r"\\newcommand\{\\([^}]+)\}", macros_text)
    assert cmd_names, "metrics_macros.tex should define at least one macro for the fixture"
    for name in cmd_names:
        assert re.fullmatch(r"[A-Za-z]+", name), f"Illegal LaTeX command name: {name!r}"
    assert "\\metricMainMetricsTestAccuracy" in macros_text
    assert manifest.artifact_index["evidence/evidence_lock.private.json"]["downloadable"] is False
    assert manifest.artifact_index["evidence/dataset_summary.public.json"]["visibility"] == "public"

    assert run_metric_guard(paths).status == "pass"
    assert run_identifier_guard(paths).status == "pass"
    assert is_path_allowed_for_download("evidence/dataset_summary.public.json") is True
    assert is_path_allowed_for_download("evidence/evidence_lock.private.json") is False


@pytest.mark.asyncio
async def test_phase03_promotes_user_idea_topic_context_into_public_evidence(tmp_path) -> None:
    user_idea = """
# Paper Intent

[TOPIC_CONTEXT]
{
  "disease": "colorectal cancer",
  "clinical_endpoint": "microsatellite instability status",
  "prediction_target": "MSI vs MSS",
  "modality": "H&E whole-slide images",
  "task_type": "wsi_classification",
  "method_family": "multiple instance learning",
  "classes": ["MSI", "MSS"],
  "confidence": "high",
  "sources": ["pre_training_chat_summary"]
}
[/TOPIC_CONTEXT]
""".strip()
    request = CreatePaperRequest(
        title="CRC MSI Prediction from H&E Whole-Slide Images",
        source_tasks=[SourceTaskRef(task_id="wsi_cls_fixture")],
        user_idea=user_idea,
    )
    paper_id, paths = await create_dev_run(request, paper_id="paper_phase03_topic", uploads_dir=tmp_path)
    _write_fixture_raw_collected(paths)
    _rewrite_fixture_as_crc_msi(paths)

    manifest = run_stage(paper_id, "building_evidence", uploads_dir=tmp_path)

    private_lock = _load_json(paths.evidence_lock_private)
    public_evidence = _load_json(paths.evidence_public)
    topic_summary = _load_json(paths.evidence_dir / "topic_summary.public.json")
    experimental_log = paths.experimental_log.read_text(encoding="utf-8")

    assert public_evidence["topic"]["disease"] == "colorectal cancer"
    assert public_evidence["topic"]["clinical_endpoint"] == "microsatellite instability status"
    assert public_evidence["topic"]["prediction_target"] == "MSI vs MSS"
    assert public_evidence["topic"]["classes"] == ["MSI", "MSS"]
    assert public_evidence["topic"]["needs_confirmation"] is False
    assert "pre_training_chat_summary" in public_evidence["topic"]["sources"]
    assert private_lock["topic"] == public_evidence["topic"]
    assert topic_summary["topic"] == public_evidence["topic"]
    assert "Clinical endpoint: microsatellite instability status" in experimental_log
    assert "Topic confidence: high" in experimental_log
    assert manifest.artifact_index["evidence/topic_summary.public.json"]["visibility"] == "public"
