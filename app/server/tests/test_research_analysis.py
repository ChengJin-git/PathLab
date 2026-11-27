"""Custom results are measured artifacts; invalid charts cannot reach renderers."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.autoresearch.engine import analysis_results, jobs, tools


def result_file(root, **changes):
    (root / "analyze.py").write_text("print(0.125)")
    data = {
        "schema_version": "pathlab-analysis-v1",
        "title": "Calibration",
        "code_path": "analyze.py",
        "metrics": {
            "test.patient.custom_bias": {
                "value": -0.125,
                "unit": "mm",
                "ci_lower": -0.2,
                "ci_upper": 0.1,
            }
        },
        **changes,
    }
    (root / "result.json").write_text(json.dumps(data))
    return analysis_results.read_result(root, "result.json")


def test_custom_metric_units_and_tables_are_preserved(tmp_path):
    data = result_file(
        tmp_path, tables=[{"columns": ["Group", "n"], "rows": [["A", 4], ["B", None]]}]
    )
    assert data["metrics"]["test.patient.custom_bias"]["value"] == -0.125
    assert data["metrics"]["test.patient.custom_bias"]["unit"] == "mm"
    assert data["tables"][0]["rows"][1] == ["B", None]


@pytest.mark.parametrize(
    "charts",
    [
        {"roc_curve": {"classes": [["invalid"]], "data": {}}},
        {
            "roc_curve": {
                "classes": ["A"],
                "data": {
                    "A": {
                        "fpr": [0, 1],
                        "tpr": [0, 1],
                        "auc": 1,
                        "fpr_grid": [0, 1],
                        "tpr_lower": [0],
                    }
                },
            }
        },
        {
            "km_curve": {
                "high_risk": {"times": [0, 1], "probs": [1, 0.5]},
                "low_risk": {"times": [0], "probs": [1]},
                "cutoff": 0,
                "c_index": "bad",
            }
        },
        {"loss_curve": {"epochs": [0, 1], "loss": [1, float("nan")]}},
        {"confusion_matrix": {"classes": ["A"], "data": [[0, 3, 1]]}},
        {"options": {"formatter": "arbitrary options"}},
    ],
)
def test_malformed_charts_fail_before_preview(tmp_path, charts):
    with pytest.raises(ValueError):
        result_file(tmp_path, chart_data=charts)


def test_chart_contract_accepts_real_roc_and_intervals(tmp_path):
    charts = {
        "roc_curve": {
            "classes": ["Positive"],
            "data": {
                "Positive": {
                    "fpr": [0, 0, 1],
                    "tpr": [0, 1, 1],
                    "auc": 1,
                    "fpr_grid": [0, 1],
                    "tpr_lower": [0, 0.5],
                    "tpr_upper": [0.2, 1],
                }
            },
        }
    }
    assert result_file(tmp_path, chart_data=charts)["chart_data"] == charts


def test_figures_cannot_escape_workspace(tmp_path):
    outside = tmp_path.parent / "outside-analysis.png"
    outside.write_bytes(b"image")
    try:
        (tmp_path / "figure.png").symlink_to(outside)
        with pytest.raises(ValueError, match="inside"):
            result_file(tmp_path, figures=[{"path": "figure.png"}])
    finally:
        outside.unlink()


@pytest.mark.asyncio
async def test_analysis_cannot_consume_training_attempts(monkeypatch):
    monkeypatch.setattr(
        jobs.store,
        "get",
        AsyncMock(
            return_value=SimpleNamespace(
                status="running", recovery_metadata={"task_kind": "analysis"}
            )
        ),
    )
    with pytest.raises(ValueError, match="submit_computation"):
        await jobs.submit(
            "session", "experiment", {"name": "test", "command": ["python", "a.py"]}
        )


@pytest.mark.asyncio
async def test_analysis_summary_does_not_require_manuscript(monkeypatch):
    from backend.services import manuscripts

    experiments = AsyncMock(
        side_effect=AssertionError("No experiment/report lookup for analysis")
    )
    monkeypatch.setattr(manuscripts.store, "experiments", experiments)
    await manuscripts.require_research_report(
        SimpleNamespace(
            recovery_metadata={"task_kind": "analysis", "report_policy": "summary"}
        )
    )
    experiments.assert_not_called()


@pytest.mark.asyncio
async def test_publish_indexes_figures_in_other_directories(tmp_path, monkeypatch):
    from backend.autoresearch.engine import file_catalog

    (tmp_path / "figures").mkdir()
    (tmp_path / "figures/chart.png").write_bytes(b"image")
    result_file(tmp_path, figures=[{"path": "figures/chart.png"}])
    index = AsyncMock()
    monkeypatch.setattr(file_catalog, "index_tree", index)
    monkeypatch.setattr(tools.store, "merge_metadata_items", AsyncMock())
    monkeypatch.setattr(tools.store, "update", AsyncMock())
    from backend.services.result_analysis import sources
    monkeypatch.setattr(sources, 'index_research', AsyncMock())
    published = await analysis_results.publish(
        SimpleNamespace(session_id="s", workspace_path=str(tmp_path)), "./result.json"
    )
    assert published["published"]
    assert {call.args[1] for call in index.call_args_list} == {
        tmp_path,
        tmp_path / "figures",
    }


def test_prediction_export_preserves_splits_and_missing_values(tmp_path):
    from backend.autoresearch.engine.analysis_inputs import append_batch

    path = tmp_path / "predictions.jsonl"
    append_batch(
        path,
        [
            {
                "result_id": 2,
                "split": "test",
                "case_id": "patient-1",
                "age": None,
                "probs": {"A": 0.4},
                "result_metadata": {"risk_score": 1.3, "secret_path": "/host/private"},
            }
        ],
    )
    row = json.loads(path.read_text())
    assert (
        row["split"] == "test" and row["case_id"] == "patient-1" and row["age"] is None
    )
    assert row["result_metadata"] == {"risk_score": 1.3}


@pytest.mark.asyncio
async def test_prediction_export_pages_and_filters_dataset_scope(tmp_path, monkeypatch):
    from contextlib import asynccontextmanager
    from sqlalchemy import MetaData
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from backend.database.models import AIResult, WSISlide, TrainingTaskWSI
    from backend.autoresearch.engine import analysis_inputs, runtime

    engine = create_async_engine("sqlite+aiosqlite://")
    metadata = MetaData()
    # Copy FK targets for SQLite DDL; foreign-key enforcement is not needed by this fixture.
    from backend.database.models import Base

    for name in [
        "datasets",
        "data_groups",
        "training_tasks",
        "wsi_slides",
        "training_task_wsi",
        "ai_results",
    ]:
        Base.metadata.tables[name].to_metadata(metadata)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def db_session():
        async with sessions() as db:
            yield db

    monkeypatch.setattr(analysis_inputs, "safe_session", db_session)
    monkeypatch.setattr(analysis_inputs, "PAGE_SIZE", 1)
    monkeypatch.setattr(runtime, "private_dir", lambda _: tmp_path)
    async with sessions() as db:
        for i, dataset in enumerate(["visible", "hidden", "visible"]):
            db.add(
                WSISlide(
                    wsi_id=f"w{i}",
                    dataset_id=dataset,
                    wsi_path="unused",
                    case_id=f"patient{i}",
                )
            )
            db.add(AIResult(wsi_id=f"w{i}", task_id="task", pred="A", probs={"A": 0.7}))
            db.add(
                TrainingTaskWSI(
                    wsi_id=f"w{i}", task_id="task", split="test" if i == 0 else "train"
                )
            )
        await db.commit()
    try:
        exported = await analysis_inputs.export_task("s", "task", ["visible"])
        rows = [
            json.loads(line)
            for line in (
                tmp_path / "inputs/references" / Path(exported["predictions_path"]).name
            )
            .read_text()
            .splitlines()
        ]
        assert exported["prediction_rows"] == 2
        assert [row["wsi_id"] for row in rows] == ["w0", "w2"]
        assert [row["split"] for row in rows] == ["test", "train"]
    finally:
        await engine.dispose()
