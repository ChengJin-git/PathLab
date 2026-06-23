from __future__ import annotations

import json
import zipfile

import pytest

from pathlab_paper_agent.collector.analysis import discover_analysis_runs
from pathlab_paper_agent.collector.dataset import SlideRecord, build_dataset_summary
from pathlab_paper_agent.collector.role_dispatcher import group_by_role
from pathlab_paper_agent.collector.schemas import CollectorStatus, SourceTaskDescriptor
from pathlab_paper_agent.pipeline import create_dev_run, run_stage
from pathlab_paper_agent.schemas import CreatePaperRequest, SourceTaskRef, TaskRole


def test_role_dispatcher_groups_roles():
    descriptors = [
        SourceTaskDescriptor(task_id="main", role="main"),
        SourceTaskDescriptor(task_id="base", role="baseline"),
        SourceTaskDescriptor(task_id="abl", role="ablation", label="no-attn"),
        SourceTaskDescriptor(task_id="ext", role="external_validation"),
    ]

    grouped = group_by_role(descriptors)

    assert [item.task_id for item in grouped["main"]] == ["main"]
    assert [item.task_id for item in grouped["baseline"]] == ["base"]
    assert grouped["ablation"][0].label == "no-attn"
    assert grouped["external_validation"][0].task_id == "ext"


def test_dataset_summary_counts_labels_splits_and_survival():
    descriptor = SourceTaskDescriptor(task_id="task_1", role="main")
    slides = [
        SlideRecord(
            wsi_id="wsi_1",
            split="train",
            dataset_id="ds_1",
            dataset_name="Dataset A",
            case_id="case_1",
            label="tumor",
            age=60,
            gender="F",
            event_status=1,
            mpp=0.25,
            vendor="Aperio",
            magnification=40,
            file_size=10,
            feature_extracted=True,
        ),
        SlideRecord(
            wsi_id="wsi_2",
            split="test",
            dataset_id="ds_1",
            dataset_name="Dataset A",
            case_id="case_2",
            label="normal",
            age=70,
            gender="M",
            event_status=0,
            mpp=0.5,
            vendor="Aperio",
            magnification=20,
            file_size=20,
        ),
    ]

    summary = build_dataset_summary(descriptor, slides)

    assert summary.status == CollectorStatus.ready
    cohort = summary.datasets[0]
    assert cohort.wsi_count == 2
    assert cohort.case_count == 2
    assert cohort.label_distribution == {"normal": 1, "tumor": 1}
    assert cohort.split_distribution == {"test": 1, "train": 1}
    assert cohort.survival_event_distribution == {"0": 1, "1": 1}
    assert cohort.age.median == 65.0
    assert cohort.file_size_bytes_total == 30
    assert cohort.feature_extracted_count == 1


def test_analysis_discovery_selects_latest_complete_run(tmp_path):
    base = tmp_path / "logs" / "analysis" / "task_1"
    old = base / "20260101_010101"
    new = base / "20260102_010101"
    old.mkdir(parents=True)
    new.mkdir(parents=True)
    (old / "summary.json").write_text('{"metric": 1, "chart_paths": {}}', encoding="utf-8")
    (old / "results.json").write_text('[{"id": 1}]', encoding="utf-8")
    chart = new / "roc_curve.png"
    chart.write_bytes(b"png")
    (new / "summary.json").write_text(
        json.dumps({"metric": 2, "chart_paths": {"roc": str(chart)}}),
        encoding="utf-8",
    )
    (new / "results.json").write_text('[{"id": 1}, {"id": 2}]', encoding="utf-8")

    summary = discover_analysis_runs(
        tmp_path,
        SourceTaskDescriptor(task_id="task_1", role="main"),
    )

    assert summary.status == CollectorStatus.ready
    assert summary.selected_analysis_id == "20260102_010101"
    assert summary.analyses[0].results_count == 2
    assert summary.analyses[0].chart_paths == {"roc": str(chart)}


@pytest.mark.asyncio
async def test_collecting_stage_writes_private_raw_collected_outputs(tmp_path, monkeypatch):
    monkeypatch.setenv("PATHLAB_PAPER_AGENT_COLLECTOR_MODE", "filesystem")
    request = CreatePaperRequest(
        title="Collector Test",
        source_tasks=[
            SourceTaskRef(task_id="task_missing", role=TaskRole.main),
            SourceTaskRef(
                task_id="extval_missing",
                role=TaskRole.external_validation,
                label="external cohort",
            ),
        ],
    )
    _paper_id, paths = await create_dev_run(
        request,
        paper_id="paper_collector",
        uploads_dir=tmp_path,
    )

    manifest = run_stage("paper_collector", "collecting", uploads_dir=tmp_path)

    raw_dir = paths.evidence_dir / "raw_collected"
    assert (raw_dir / "collector_bundle.json").is_file()
    assert (raw_dir / "task_summary.json").is_file()
    assert (raw_dir / "dataset_summary.json").is_file()
    assert (raw_dir / "analysis_summary.json").is_file()
    assert (raw_dir / "external_validation_summary.json").is_file()
    assert (raw_dir / "qualitative_summary.json").is_file()

    bundle = json.loads((raw_dir / "collector_bundle.json").read_text(encoding="utf-8"))
    assert bundle["mode"] == "filesystem"
    assert bundle["status"] == "missing"
    assert bundle["source_tasks"][1]["role"] == "external_validation"
    assert bundle["missing_evidence"]

    source_analyses = json.loads(paths.source_analyses.read_text(encoding="utf-8"))
    assert source_analyses["collector_mode"] == "filesystem"
    assert source_analyses["items"][0]["status"] == "missing"

    artifact_index = manifest.artifact_index
    rel_path = "evidence/raw_collected/collector_bundle.json"
    assert artifact_index[rel_path]["visibility"] == "private_backend_only"
    assert artifact_index[rel_path]["downloadable"] is False


def test_qualitative_bundle_scan_is_lightweight(tmp_path):
    from pathlab_paper_agent.collector.qualitative import build_qualitative_summary

    bundle_dir = tmp_path / "ai_results_bundles"
    bundle_dir.mkdir()
    bundle = bundle_dir / "task_1.zarr.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("results/wsi_1/.zattrs", "{}")
        archive.writestr("cam/wsi_1/.zarray", "{}")
        archive.writestr("pred_mask/wsi_1/.zarray", "{}")

    summary = build_qualitative_summary(
        tmp_path,
        SourceTaskDescriptor(task_id="task_1", role="main"),
    )

    assert summary.status == CollectorStatus.ready
    assert summary.result_count == 1
    assert summary.available_artifacts == ["cam", "pred_mask"]
