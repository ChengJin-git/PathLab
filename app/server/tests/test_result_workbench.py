"""Scientific semantics, input boundaries, persisted scopes and CPU execution."""

from uuid import uuid4

import numpy as np
import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from backend.auth.models import User
from backend.database.models import (
    Base,
    DataGroup,
    Dataset,
    DatasetTask,
    WSISlide,
    TrainingTask,
    TrainingTaskWSI,
    AIResult,
)
from backend.services.result_analysis.contracts import (
    AnalysisConfig,
    ChartSpec,
    IntervalSpec,
)
from backend.services.result_analysis.compute import (
    compute_source,
    compare,
    prepare_rows,
)
from backend.services.result_analysis.sources import (
    index_task,
    authorized_sources,
    public_source,
)
from backend.services.result_analysis.inputs import load_predictions


def predictions():
    return [
        {
            "result_id": i + 1,
            "wsi_id": f"w{i}",
            "sample_id": f"w{i}",
            "dataset_id": "d",
            "case_id": f"c{i}",
            "label": label,
            "pred": "positive" if score >= 0.5 else "negative",
            "probs": {"negative": 1 - score, "positive": score},
            "metadata": {},
            "gender": "F" if i % 2 else "M",
            "age": 40 + i,
            "source": "lung",
            "filename": f"{i}.png",
        }
        for i, (label, score) in enumerate(
            zip(["negative", "negative", "positive", "positive"], [0.1, 0.4, 0.35, 0.8])
        )
    ]


def source():
    return {
        "source_id": "task:t",
        "title": "Test",
        "revision": "1",
        "task_type": "patch_classification",
        "details": {"classes": ["negative", "positive"], "prediction_count": 4},
    }


def test_measured_scores_threshold_and_calibration():
    config = AnalysisConfig(
        metrics=["accuracy", "brier", "auc", "average_precision", "mcc"],
        charts=[ChartSpec(id="calibration"), ChartSpec(id="pr")],
    )
    result = compute_source(source(), predictions(), config)
    assert result["metrics"]["accuracy"]["value"] == 0.75
    assert result["metrics"]["brier"]["value"] == pytest.approx(
        (0.1**2 + 0.4**2 + 0.65**2 + 0.2**2) / 4
    )
    assert result["metrics"]["auc"]["value"] == 0.75
    assert result["metrics"]["average_precision"]["value"] == pytest.approx(5 / 6)
    assert result["metrics"]["mcc"]["value"] == pytest.approx(1 / np.sqrt(3))
    assert result["charts"]["pr"]["series"]
    changed = compute_source(
        source(), predictions(), config.model_copy(update={"threshold": 0.3})
    )
    assert changed["samples"][1]["pred"] == "positive"
    assert changed["metrics"]["brier"] == result["metrics"]["brier"]


def test_case_aggregation_and_cluster_interval_are_reproducible():
    rows = predictions()
    rows[1]["case_id"] = rows[0]["case_id"]
    config = AnalysisConfig(
        unit="case",
        metrics=["accuracy", "brier"],
        interval=IntervalSpec(enabled=True, samples=50),
    )
    prepared = prepare_rows(rows, config, source()["details"]["classes"])
    assert len(prepared) == 3
    assert prepared[0]["probs"]["positive"] == 0.25
    first = compute_source(source(), rows, config)
    second = compute_source(source(), rows, config)
    assert first["metrics"] == second["metrics"]
    assert (
        first["metrics"]["brier"]["ci_lower"] <= first["metrics"]["brier"]["ci_upper"]
    )
    rows[1]["label"] = "positive"
    with pytest.raises(ValueError, match="conflicting"):
        prepare_rows(rows, config, source()["details"]["classes"])


def test_unlabelled_is_missing_not_zero_and_comparison_uses_sample_identity():
    rows = predictions()
    for row in rows:
        row["label"] = None
    config = AnalysisConfig(
        metrics=["accuracy", "entropy", "mean_confidence"],
        charts=[ChartSpec(id="distribution")],
    )
    result = compute_source(source(), rows, config)
    assert result["metrics"]["accuracy"]["value"] is None
    assert result["metrics"]["entropy"]["value"] > 0
    assert result["charts"]["distribution"]["series"][0]["y"] == [3, 1]
    smaller = compute_source({**source(), "source_id": "task:other"}, rows[1:], config)
    comparisons = compare([result, smaller], config)
    assert comparisons[0]["same_samples"] is False
    assert comparisons[0]["overlap"] == 3
    assert comparisons[0]["disagreement"] == 0


def test_metric_units_and_grouping_and_invalid_probabilities():
    config = AnalysisConfig(metrics=["brier", "accuracy"], group_by="gender")
    result = compute_source(source(), predictions(), config)
    assert result["metrics"]["brier"]["unit"] == ""
    assert result["metrics"]["accuracy"]["unit"] == "ratio"
    assert sum(row["count"] for row in result["groups"]) == 4
    rows = predictions()
    rows[0]["probs"]["negative"] = 9
    with pytest.raises(ValueError, match="probabilities"):
        compute_source(source(), rows, config)


@pytest.fixture
async def database():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda c: Base.metadata.create_all(
                c,
                tables=[
                    table
                    for table in Base.metadata.sorted_tables
                    if table.name != "knowhow_entries"
                ],
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        owner = User(
            id=uuid4(),
            username="owner",
            hashed_password="x",
            role="pathologist",
            is_active=True,
        )
        other = User(
            id=uuid4(),
            username="other",
            hashed_password="x",
            role="pathologist",
            is_active=True,
        )
        db.add_all(
            [
                owner,
                other,
                DataGroup(
                    group_id="g",
                    name="Group",
                    data_type="patch",
                    task_type="patch_classification",
                    aggregation_level="file",
                ),
            ]
        )
        db.add(
            Dataset(
                dataset_id="d",
                data_type="patch", aggregation_level="file", tasks=[DatasetTask(task_type="patch_classification")],
                name="Dataset",
                user_id=str(owner.id),
                is_public=False,
            )
        )
        db.add(
            TrainingTask(
                task_id="t",
                task_name="Task",
                group_id="g",
                user_id=str(owner.id),
                status="completed",
                classes=["negative", "positive"],
            )
        )
        await db.flush()
        for row in predictions():
            db.add(
                WSISlide(
                    wsi_id=row["wsi_id"],
                    dataset_id="d",
                    wsi_path="/unused",
                    label=row["label"],
                    case_id=row["case_id"],
                )
            )
            db.add(
                TrainingTaskWSI(
                    task_id="t",
                    wsi_id=row["wsi_id"],
                    split="test" if row["result_id"] < 4 else "train",
                )
            )
            db.add(
                AIResult(
                    task_id="t",
                    wsi_id=row["wsi_id"],
                    pred=row["pred"],
                    probs=row["probs"],
                )
            )
        await db.commit()
        yield db, owner, other
    await engine.dispose()


async def test_catalog_preserves_split_and_does_not_require_checkpoint(database):
    db, owner, other = database
    await index_task(db, "t")
    await db.commit()
    sources = await authorized_sources(db, owner, ["task:t"])
    item = public_source(sources[0])
    assert item["prediction_count"] == 4
    assert item["split_counts"] == {"test": 3, "train": 1}
    assert item["model_id"] is None
    rows = await load_predictions(db, sources[0], AnalysisConfig(split="test"))
    assert len(rows) == 3
    with pytest.raises(HTTPException) as denied:
        await authorized_sources(db, other, ["task:t"])
    assert denied.value.status_code == 404


async def test_background_run_survives_request_and_reuses_exact_results(database, monkeypatch, tmp_path):
    from unittest.mock import AsyncMock
    from contextlib import asynccontextmanager
    from backend.services.result_analysis import runs
    from backend.database.models import ResultAnalysis
    db, owner, _ = database
    await index_task(db, 't')
    await db.commit()
    monkeypatch.setattr(runs, 'is_worker_healthy', AsyncMock(return_value=True))
    enqueue = AsyncMock()
    monkeypatch.setattr(runs, 'enqueue_task_descriptor', enqueue)
    monkeypatch.setattr(runs, 'run_directory', lambda identity: tmp_path / identity)
    @asynccontextmanager
    async def session():
        yield db
    monkeypatch.setattr(runs, 'safe_session', session)
    config = AnalysisConfig(source_ids=['task:t'], metrics=['accuracy'], charts=[ChartSpec(id='confusion')])
    queued = await runs.submit(db, owner, config)
    assert queued.status == 'queued'
    assert (await runs.submit(db, owner, config)).analysis_id == queued.analysis_id
    assert enqueue.await_count == 1
    await runs.execute_run(queued.analysis_id)
    await db.refresh(queued)
    assert queued.status == 'completed', queued.error
    assert queued.progress == 100
    assert queued.result['results'][0]['metrics']['accuracy']['value'] == pytest.approx(2/3)
    assert (await runs.submit(db, owner, config)).analysis_id == queued.analysis_id
    changed = await runs.submit(db, owner, config.model_copy(update={'threshold': .3}))
    assert changed.analysis_id != queued.analysis_id
    assert (tmp_path / queued.analysis_id / 'sample-index.json').is_file()


async def test_native_detection_inference_persists_boxes_and_indexes_results(database, monkeypatch, tmp_path):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock
    import torch
    from PIL import Image
    from sqlalchemy import update
    from backend.ai.detectors.models import build_detector
    from backend.ai.detectors.specs import DetectionConfig
    from backend.ai.result_store import AIResultStore
    from backend.database.models import TrainedModel
    from backend.database.repositories import SegmentationAnnotationRepository
    from backend.common.config import Config
    from backend.common import task_dispatch
    from gateway.routes import inference_patch_detection as inference
    db, owner, _ = database
    await db.execute(update(DataGroup).values(task_type='patch_detection'))
    await db.execute(update(TrainingTask).values(classes=['cell']))
    images = []
    for i in range(4):
        path = tmp_path / f'{i}.png'
        Image.new('RGB', (80, 64), 'white').save(path)
        await db.execute(update(WSISlide).where(WSISlide.wsi_id == f'w{i}').values(wsi_path=str(path), original_filename=path.name, data_type='patch'))
        images.append({'id': i, 'file_name': path.name, 'width': 80, 'height': 64})
    await SegmentationAnnotationRepository.upsert(db, annotation_id='patch_detection_d', task_type='patch_detection', user_id=str(owner.id), source_dataset_id='d',
        annotations={'images': images, 'categories': [{'id': 8, 'name': 'cell'}], 'annotations': [{'id': 1, 'image_id': 0, 'category_id': 8, 'bbox': [4, 4, 16, 16]}]}, status='finalized', source='import')
    config = DetectionConfig(backbone='resnet18', pretrained=False, image_size=64)
    model = build_detector(config, ['cell'])
    checkpoint = tmp_path / 'model.pth'
    torch.save({'config': config.model_dump(), 'classes': ['cell'], 'model_state_dict': model.state_dict()}, checkpoint)
    db.add(TrainedModel(model_id='det_t', task_id='t', user_id=str(owner.id), model_name='test', model_path=str(checkpoint), classes=['cell']))
    await db.commit()
    @asynccontextmanager
    async def session():
        yield db
    monkeypatch.setattr(inference, 'safe_session', session)
    monkeypatch.setattr(Config, 'get_uploads_dir', lambda: tmp_path)
    monkeypatch.setattr(task_dispatch, 'is_task_cancelled', AsyncMock(return_value=False))
    await inference.run_detection_inference('t', 'det_t', ['w0', 'w1'], assigned_device='cpu')
    saved = AIResultStore(tmp_path).read_result('t', 'w1')
    assert saved['detection']['target']['boxes'] == []
    assert saved['has_ground_truth'] is True
    source_row = (await authorized_sources(db, owner, ['task:t']))[0]
    assert source_row.task_type == 'patch_detection'
    assert source_row.details['gt_count'] == 2
    rows = await load_predictions(db, source_row, AnalysisConfig())
    assert len(rows) == 2 and all('detection' in row['metadata'] for row in rows)


async def test_recipe_updates_use_revision_and_remain_owner_scoped(database):
    from gateway.routes.result_workbench import (
        create_recipe,
        update_recipe,
        RecipeRequest,
    )

    db, owner, other = database
    created = await create_recipe(
        RecipeRequest(name="Calibration", config=AnalysisConfig(source_ids=["task:t"])),
        owner,
        db,
    )
    assert created["config"]["source_ids"] == []
    with pytest.raises(HTTPException) as stale:
        await update_recipe(
            created["recipe_id"],
            RecipeRequest(name="Changed", config=AnalysisConfig(), version=0),
            owner,
            db,
        )
    assert stale.value.status_code == 409
    with pytest.raises(HTTPException) as denied:
        await update_recipe(
            created["recipe_id"],
            RecipeRequest(name="Changed", config=AnalysisConfig(), version=1),
            other,
            db,
        )
    assert denied.value.status_code == 404


def test_survival_segmentation_and_multitask_contracts():
    from backend.autoresearch.engine.analysis_results import AnalysisResult
    from backend.services.result_analysis.contracts import family

    rows = predictions()
    for i, row in enumerate(rows):
        row["probs"] = None
        row["event_time"], row["event_status"] = i + 1, 1
        row["metadata"] = {"risk_score": 4 - i}
    measured = compute_source(
        {**source(), "task_type": "wsi_survival"},
        rows,
        AnalysisConfig(metrics=["c_index"], charts=[ChartSpec(id="km")]),
    )
    assert measured["metrics"]["c_index"]["value"] == 1
    assert len(measured["charts"]["km"]["series"]) == 2
    for i, row in enumerate(rows):
        row["metadata"] = {"metrics": {"dice": i / 4, "miou": i / 5}}
    measured = compute_source(
        {**source(), "task_type": "patch_segmentation"},
        rows,
        AnalysisConfig(metrics=["dice", "miou"], charts=[ChartSpec(id="segmentation")]),
    )
    assert measured["metrics"]["dice"]["value"] == 0.375
    assert measured["metrics"]["miou"]["value"] == pytest.approx(0.3)
    assert family("custom") == "custom"
    payload = {
        "schema_version": "pathlab-analysis-v1",
        "title": "Two tasks",
        "code_path": "analysis.py",
        "metrics": {"diagnosis.auc": 0.8, "survival.c_index": 0.7},
        "tasks": [
            {
                "id": "diagnosis",
                "title": "Diagnosis",
                "task_type": "patch_classification",
                "metric_keys": ["diagnosis.auc"],
            },
            {
                "id": "prognosis",
                "title": "Prognosis",
                "task_type": "wsi_survival",
                "metric_keys": ["survival.c_index"],
            },
        ],
    }
    assert len(AnalysisResult.model_validate(payload).tasks) == 2
    payload["tasks"][1]["metric_keys"] = ["invented"]
    with pytest.raises(ValueError, match="missing metrics"):
        AnalysisResult.model_validate(payload)


def test_research_prediction_artifact_preserves_splits_and_rejects_invalid_data(
    tmp_path,
):
    import json
    from backend.services.result_analysis.artifacts import read_predictions

    spec = {
        "path": "predictions.jsonl",
        "task_type": "patch_classification",
        "classes": ["negative", "positive"],
        "unit": "file",
    }
    data = [
        {
            "sample_id": f"s{i}",
            "split": "test" if i < 3 else "train",
            "label": row["label"],
            "probs": row["probs"],
        }
        for i, row in enumerate(predictions())
    ]
    path = tmp_path / "predictions.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in data))
    result = read_predictions(tmp_path, spec, config=AnalysisConfig(split="test"))
    assert len(result["rows"]) == 3
    assert result["split_counts"] == {"test": 3, "train": 1}
    assert len(result["prediction_sha256"]) == 64
    measured = compute_source(
        source(), result["rows"], AnalysisConfig(metrics=["brier"])
    )
    assert measured["count"] == 3
    path.write_text(
        json.dumps({**data[0], "probs": {"negative": 1.2, "positive": -0.2}})
    )
    with pytest.raises(ValueError, match="probabilities"):
        read_predictions(tmp_path, spec)
    with pytest.raises(ValueError):
        read_predictions(tmp_path, {**spec, "path": "../private.jsonl"})


async def test_assistant_configuration_does_not_execute_and_rejects_source_substitution(
    database, monkeypatch
):
    from unittest.mock import AsyncMock
    from starlette.requests import Request
    from backend.services.result_analysis import assistant as assistant_service
    from backend.services.result_analysis.assistant import AssistantDecision
    from gateway.routes import result_workbench as routes

    db, owner, other = database
    await index_task(db, "t")
    await db.commit()
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/results/workbench/assistant",
            "headers": [],
        }
    )
    monkeypatch.setattr(request, "is_disconnected", AsyncMock(return_value=False))
    config = AnalysisConfig(source_ids=["task:t"])
    monkeypatch.setattr(
        assistant_service,
        "decide",
        AsyncMock(
            return_value=AssistantDecision(
                message="Updated", action="configure", config=config
            )
        ),
    )
    submit = AsyncMock()
    monkeypatch.setattr(routes, "submit", submit)
    response = await routes.assistant(
        routes.AssistantRequest(message="Show ROC settings", config=config),
        request,
        None,
        owner,
        db,
    )
    assert response["action"] == "configure"
    submit.assert_not_called()
    monkeypatch.setattr(
        assistant_service,
        "decide",
        AsyncMock(
            return_value=AssistantDecision(
                message="Updated",
                action="run",
                config=config.model_copy(update={"source_ids": ["private"]}),
            )
        ),
    )
    with pytest.raises(HTTPException) as error:
        await routes.assistant(
            routes.AssistantRequest(message="Compute", config=config),
            request,
            None,
            owner,
            db,
        )
    assert error.value.status_code == 422
    submit.assert_not_called()
