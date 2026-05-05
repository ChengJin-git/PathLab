from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pytest

from pathlab_paper_agent.pipeline import create_dev_run, run_stage
from pathlab_paper_agent.renderers.locked_block_renderer import LockedBlockRenderer, latex_cmd_key
from pathlab_paper_agent.schemas import CreatePaperRequest, SourceTaskRef, TemplateId


_LOCKED_BLOCK_NAMES = {
    "dataset_block.tex",
    "method_block.tex",
    "results_block.tex",
    "external_block.tex",
    "metrics_macros.tex",
    "evidence_gaps.tex",
}


_TABLE_NAMES = {
    "table_1_dataset.tex",
    "table_2_main_results.tex",
    "table_3_per_class.tex",
    "table_4_ablation.tex",
    "table_5_external_validation.tex",
}


def _fixture_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "fixtures" / "wsi_classification_minimal"


def _golden_locked_blocks_dir() -> Path:
    return _fixture_dir() / "golden" / "deterministic" / "locked_blocks"


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
    (raw_dir / "collector_bundle.json").write_text(json.dumps(collector_bundle), encoding="utf-8")


@pytest.mark.asyncio
async def test_fixture_locked_blocks_are_byte_identical_to_golden(tmp_path) -> None:
    request = CreatePaperRequest(
        title="Fixture Locked Blocks Paper",
        source_tasks=[SourceTaskRef(task_id="wsi_cls_fixture")],
    )
    paper_id, paths = await create_dev_run(request, paper_id="paper_m5_fixture", uploads_dir=tmp_path)
    _write_fixture_raw_collected(paths)

    run_stage(paper_id, "building_evidence", uploads_dir=tmp_path)

    actual_names = {path.name for path in paths.locked_blocks_dir.glob("*.tex")}
    assert actual_names == _LOCKED_BLOCK_NAMES
    for name in sorted(_LOCKED_BLOCK_NAMES):
        assert (paths.locked_blocks_dir / name).read_bytes() == (_golden_locked_blocks_dir() / name).read_bytes()
        assert (paths.locked_blocks_dir / "miccai" / name).is_file()
        assert (paths.locked_blocks_dir / "nature_scientific_reports" / name).is_file()
    assert "\\paragraph{Cohort.}" in (
        paths.locked_blocks_dir / "nature_scientific_reports" / "dataset_block.tex"
    ).read_text(encoding="utf-8")


def test_renderer_writes_template_specific_locked_blocks() -> None:
    payload = {
        "datasets": [{"wsi_count": 4, "case_count": 4}],
        "splits": [],
        "models": [
            {
                "model_name": "Attention MIL Fixture",
                "feature_extractor": "resnet50",
                "aggregator": "attention_mil",
            }
        ],
        "metrics": {
            "main.metrics.test_auc_1": {
                "name": "metrics.test_auc",
                "formatted": "0.9456",
                "task_id": "wsi_cls_fixture",
            }
        },
        "external_validation": [],
        "missing_evidence": [],
    }
    miccai = LockedBlockRenderer(TemplateId.miccai)
    nature = LockedBlockRenderer(TemplateId.nature_scientific_reports)

    assert miccai.template_dir.name == "miccai"
    assert nature.template_dir.name == "nature_scientific_reports"
    assert miccai.template_dir != nature.template_dir
    assert (miccai.template_dir / "dataset_block.tex.j2").is_file()
    assert (nature.template_dir / "dataset_block.tex.j2").is_file()
    miccai_blocks = miccai.render(**payload).locked_blocks
    nature_blocks = nature.render(**payload).locked_blocks
    assert "\\paragraph{Dataset.}" in miccai_blocks["dataset_block.tex"]
    assert "\\paragraph{Cohort.}" in nature_blocks["dataset_block.tex"]
    assert miccai_blocks["dataset_block.tex"] != nature_blocks["dataset_block.tex"]
    assert "No external validation evidence was available." in miccai_blocks["external_block.tex"]


def test_dataset_block_total_wsi_is_not_overwritten_by_external_validation() -> None:
    # Regression: dataset_block.tex must report the dataset cohort total, not the
    # last external_validation row's total_wsi (those numbers describe different cohorts).
    payload = {
        "datasets": [
            {"wsi_count": 30, "case_count": 25},
            {"wsi_count": 20, "case_count": 18},
        ],
        "splits": [],
        "models": [],
        "metrics": {},
        "external_validation": [
            {"task_id": "extval_a", "status": "ready", "total_wsi": 999},
            {"task_id": "extval_b", "status": "ready", "total_wsi": 7},
        ],
        "missing_evidence": [],
    }
    blocks = LockedBlockRenderer(TemplateId.miccai).render(**payload).locked_blocks

    assert "50 whole-slide image(s) from 43 case(s)" in blocks["dataset_block.tex"]
    assert "999" not in blocks["dataset_block.tex"]
    assert "999 WSI" in blocks["external_block.tex"]
    assert "7 WSI" in blocks["external_block.tex"]


def test_metric_macro_command_names_are_letters_only() -> None:
    metrics = {
        "main.metrics.test_auc_1": {"formatted": "0.9456"},
        "main.metrics.test_auc.1": {"formatted": "0.9555"},
    }
    macros = LockedBlockRenderer().render_metrics_macros(metrics)
    command_names = re.findall(r"\\newcommand\{\\([^}]+)\}", macros)

    assert latex_cmd_key("main.metrics.test_auc_1") == "MainMetricsTestAucOne"
    assert command_names == ["metricMainMetricsTestAucOne", "metricMainMetricsTestAucOneA"]
    for name in command_names:
        assert re.fullmatch(r"[A-Za-z]+", name), f"Illegal LaTeX command name: {name!r}"


def test_metric_macro_collision_suffixes_do_not_loop_after_z() -> None:
    separators = [
        ".",
        "_",
        "-",
        ":",
        "/",
        " ",
        "+",
        "*",
        "&",
        "%",
        "$",
        "#",
        "@",
        "!",
        "?",
        "~",
        "`",
        "|",
        "\\",
        ";",
        ",",
        "<",
        ">",
        "=",
        "[",
        "]",
        "(",
        ")",
        "{",
        "}",
    ]
    metrics = {f"metric{separator}1": {"formatted": "0.1"} for separator in separators}
    macros = LockedBlockRenderer().render_metrics_macros(metrics)
    command_names = re.findall(r"\\newcommand\{\\([^}]+)\}", macros)

    assert len(command_names) == len(separators)
    assert len(set(command_names)) == len(separators)
    assert "metricMetricOneAA" in command_names
    for name in command_names:
        assert re.fullmatch(r"[A-Za-z]+", name), f"Illegal LaTeX command name: {name!r}"


@pytest.mark.asyncio
async def test_rendering_stage_copies_template_specific_locked_blocks(tmp_path) -> None:
    request = CreatePaperRequest(
        title="Fixture Template Specific Blocks Paper",
        source_tasks=[SourceTaskRef(task_id="wsi_cls_fixture")],
    )
    paper_id, paths = await create_dev_run(request, paper_id="paper_m5_rendering", uploads_dir=tmp_path)
    _write_fixture_raw_collected(paths)

    run_stage(paper_id, "building_evidence", uploads_dir=tmp_path)
    run_stage(paper_id, "section_writing", uploads_dir=tmp_path)
    run_stage(paper_id, "rendering", uploads_dir=tmp_path)

    assert (paths.final_for_template("miccai") / "locked_blocks" / "dataset_block.tex").read_text(
        encoding="utf-8"
    ) == (paths.locked_blocks_dir / "miccai" / "dataset_block.tex").read_text(encoding="utf-8")
    assert (
        paths.final_for_template("nature_scientific_reports") / "locked_blocks" / "dataset_block.tex"
    ).read_text(encoding="utf-8") == (
        paths.locked_blocks_dir / "nature_scientific_reports" / "dataset_block.tex"
    ).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_locked_blocks_and_tables_do_not_leak_private_fixture_identifiers(tmp_path) -> None:
    request = CreatePaperRequest(
        title="Fixture PHI Boundary Paper",
        source_tasks=[SourceTaskRef(task_id="wsi_cls_fixture")],
    )
    paper_id, paths = await create_dev_run(request, paper_id="paper_m5_phi", uploads_dir=tmp_path)
    _write_fixture_raw_collected(paths)

    run_stage(paper_id, "building_evidence", uploads_dir=tmp_path)

    public_tex = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [*paths.locked_blocks_dir.rglob("*.tex"), *paths.tables_dir.glob("*.tex")]
    )
    for private_term in ["CASE-0001", "/private/pathlab", "Example Hospital"]:
        assert private_term not in public_tex
    for name in _TABLE_NAMES:
        assert (paths.tables_dir / name).is_file()
