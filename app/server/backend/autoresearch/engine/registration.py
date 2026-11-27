"""Publish research features and models to the existing PathLab catalogs."""

from __future__ import annotations

import json
import asyncio
import shutil
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from backend.common.config import Config
from backend.database.database import safe_session
from backend.database.models import (
    Dataset,
    TrainedModel,
    TrainingTask,
    TrainingTaskWSI,
    ResearchJob,
    WSISlide,
)

from . import store
from .jobs import contained


async def register_model(
    session_id: str,
    *,
    run_id: str,
    path: str,
    dataset_id: str,
    name: str,
    feature_extractor: str = "",
    aggregator: str,
    config_path: str = "",
    prediction: dict | None = None,
    adapter_dir: str = "",
) -> dict:
    feature_extractor, aggregator = feature_extractor.strip(), aggregator.strip()
    if not aggregator or (
        not feature_extractor and (prediction or {}).get("input_kind") != "image"
    ):
        raise ValueError(
            "Provide the model architecture and the feature extractor for feature-based prediction."
        )
    session = await store.get(session_id)
    root = Path(session.workspace_path)
    model_path = contained(root, path)
    if not model_path.is_file():
        raise ValueError("Model file does not exist")
    run = next(
        (
            r
            for r in await store.experiments(session_id)
            if r["run_id"] == run_id and r["status"] == "completed"
        ),
        None,
    )
    if run is None:
        raise ValueError("Model must reference a completed experiment")
    async with safe_session() as db:
        job = await db.get(ResearchJob, run_id)
        if (
            job is None
            or job.session_id != session_id
            or job.kind != "experiment"
            or job.status != "completed"
        ):
            raise ValueError("Only a completed experiment can publish a model record")
    finished_at = (
        datetime.fromtimestamp(job.result["finished_at"], timezone.utc).replace(
            tzinfo=None
        )
        if job.result.get("finished_at")
        else job.updated_at
    )
    started_at = finished_at - timedelta(
        seconds=float(job.result.get("duration_seconds", 0))
    )
    if dataset_id not in {
        d["dataset_id"] for d in (session.recovery_metadata or {}).get("datasets", [])
    }:
        raise ValueError("Prepare the source dataset before registering a model")
    config = contained(root, config_path) if config_path else None
    if config is not None and not config.is_file():
        raise ValueError("Model configuration does not exist")
    # A research checkpoint is an artifact until its loader/preprocessing/label
    # contract has been validated for the platform predictor. Filename matching
    # cannot establish that contract (e.g. joblib or a custom torch state dict).
    from backend.services.model_catalog import validate_research_checkpoint

    native_config = (
        None
        if prediction
        else await asyncio.to_thread(
            validate_research_checkpoint,
            model_path,
            config,
            aggregator,
            feature_extractor,
        )
    )
    inference_ready = native_config is not None
    task_id, model_id = run_id, f"{run_id}_model"
    durable = Config.get_uploads_dir() / "models" / model_id
    published_model = durable / (
        "aggregator.pth" if inference_ready else model_path.name
    )
    published_config = None
    if config:
        published_config = durable / ("config.json" if inference_ready else config.name)
    adapter = None
    if adapter_dir:
        source_adapter = contained(root, adapter_dir)
        if not source_adapter.is_dir():
            raise ValueError("Prediction adapter directory does not exist")
        files = list(source_adapter.rglob("*"))
        if (
            any(p.is_symlink() for p in files)
            or sum(p.stat().st_size for p in files if p.is_file()) > 32 * 1024**2
        ):
            raise ValueError(
                "Adapter directory must be regular source files, up to 32 MiB"
            )
        adapter = source_adapter
    async with safe_session() as db:
        dataset = await db.scalar(
            select(Dataset).where(Dataset.dataset_id == dataset_id)
        )
        if dataset is None:
            raise ValueError("Source dataset no longer exists")
        from backend.services.dataset_catalog import require_dataset_task
        from backend.database.repositories import DataGroupRepository

        selected_task_type = (
            prediction.get("task_type") if prediction else "wsi_classification"
        )
        require_dataset_task(dataset, selected_task_type)
        group = await DataGroupRepository.get_or_create(
            db,
            data_type=dataset.data_type,
            aggregation_level=dataset.aggregation_level,
            task_type=selected_task_type,
        )
        if native_config and group.task_type != "wsi_classification":
            raise ValueError(
                "This native classifier checkpoint cannot represent a different task; provide a task-aware prediction adapter"
            )
        slides = list(
            (
                await db.scalars(
                    select(WSISlide).where(WSISlide.dataset_id == dataset_id)
                )
            ).all()
        )
        classes = (
            native_config["classes"]
            if inference_ready
            else sorted({s.label for s in slides if s.label})
        )
        predictor = None
        if not inference_ready:
            from backend.services.research_prediction import (
                prepare_predictor,
                save_manifest,
            )

            if not prediction:
                raise ValueError(
                    "Provide prediction runtime, classes in output order, pooling and score_method; custom models also provide adapter_dir and entrypoint."
                )
            if prediction.get("task_type") != group.task_type:
                raise ValueError(
                    "Prediction task_type must match the source dataset task"
                )
            predictor = await asyncio.to_thread(
                prepare_predictor, model_path, feature_extractor, prediction, adapter
            )
            if (
                group.task_type.endswith("classification")
                and classes
                and set(predictor["classes"]) != set(classes)
            ):
                raise ValueError("Prediction labels do not match the dataset labels")
            classes = predictor["classes"]
            inference_ready = True

        def publish():
            durable.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix=f".{model_id}-", dir=durable.parent
            ) as temporary:
                staging = Path(temporary)
                shutil.copy2(model_path, staging / published_model.name)
                if config:
                    shutil.copy2(config, staging / published_config.name)
                if adapter:
                    shutil.copytree(
                        adapter,
                        staging / "adapter",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                    )
                if predictor:
                    save_manifest(
                        staging, {**predictor, "model_file": published_model.name}
                    )
                # Validation finished before any existing published artifact changes.
                durable.mkdir(exist_ok=True)
                for item in staging.iterdir():
                    if item.is_dir():
                        target = durable / item.name
                        if target.exists():
                            shutil.rmtree(target)
                        shutil.move(str(item), target)
                    elif item.name != "predictor.json":
                        os.replace(item, durable / item.name)
                if predictor:
                    os.replace(staging / "predictor.json", durable / "predictor.json")
                else:
                    (durable / "predictor.json").unlink(missing_ok=True)

        await asyncio.to_thread(publish)
        task = await db.scalar(
            select(TrainingTask).where(TrainingTask.task_id == task_id)
        )
        if task is None:
            task = TrainingTask(
                task_id=task_id,
                task_name=name,
                group_id=group.group_id,
                user_id=session.user_id,
                status="completed",
                progress=100,
                classes=classes,
                started_at=started_at,
                finished_at=finished_at,
                created_at=started_at,
                preprocessing_config={"feature_extractor": feature_extractor},
                model_config={
                    "source": "autoresearch",
                    "session_id": session_id,
                    "run_id": run_id,
                    "feature_extractor": feature_extractor,
                    "aggregator": aggregator,
                    "config": run["config"],
                },
            )
            db.add(task)
            await db.flush()
            db.add_all(
                [
                    TrainingTaskWSI(task_id=task_id, wsi_id=s.wsi_id, split=s.split)
                    for s in slides
                ]
            )
        task.preprocessing_config = {
            **(task.preprocessing_config or {}),
            **(predictor.get("preprocessing", {}) if predictor else {}),
            "feature_extractor": feature_extractor,
        }
        task.classes = classes
        task.model_config = {
            **(task.model_config or {}),
            "feature_extractor": feature_extractor,
            "aggregator": aggregator,
            "source": "autoresearch",
            "run_id": run_id,
            "session_id": session_id,
        }
        task.model_config = {
            **task.model_config,
            "inference_contract": predictor["contract"]
            if predictor
            else "pathlab-native-v1",
        }
        task.started_at, task.finished_at = started_at, finished_at
        model = await db.scalar(
            select(TrainedModel).where(TrainedModel.model_id == model_id)
        )
        if model is None:
            model = TrainedModel(
                model_id=model_id,
                task_id=task_id,
                model_name=name,
                user_id=session.user_id,
                model_path=str(published_model),
                config_path=str(published_config) if published_config else None,
                classes=classes,
                feature_extractor=feature_extractor or None,
                aggregator=aggregator or None,
                val_metrics=run["metrics"],
                is_default=False,
                is_active=inference_ready,
            )
            db.add(model)
        else:
            model.is_active = inference_ready
            model.model_path = str(published_model)
            model.config_path = str(published_config) if published_config else None
            model.feature_extractor = feature_extractor
            model.aggregator = aggregator
            model.val_metrics = run["metrics"]
            model.model_name = name
            model.classes = classes
        await db.flush()
        from backend.services.result_analysis.sources import index_task

        await index_task(db, task_id)
        await db.commit()
    result = {
        "model_id": model_id,
        "training_task_id": task_id,
        "run_id": run_id,
        "inference_ready": inference_ready,
        "inference_reason": None
        if inference_ready
        else "research_artifact_requires_predictor_contract",
    }
    await store.update(session_id, event={"kind": "model", **result})
    return result


async def register_features(
    session_id: str,
    *,
    dataset_id: str,
    features_dir: str,
    extractor: str,
    coordinates_dir: str | None = None,
    feature_contract: dict | None = None,
) -> dict:
    from ..dataset.feature_registration import register_extracted_features_with_pathlab

    session = await store.get(session_id)
    root = Path(session.workspace_path)
    features = contained(root, features_dir)
    coordinates = contained(root, coordinates_dir) if coordinates_dir else None
    from backend.ai.feature_contracts import FeatureContract

    contract = (
        FeatureContract.model_validate(feature_contract).model_dump()
        if feature_contract
        else None
    )
    if contract and contract["model_id"] != extractor:
        raise ValueError("Feature contract model does not match the declared extractor")
    manifest = root / "datasets" / dataset_id / "manifest.json"
    if not manifest.is_file():
        raise ValueError("Prepare the dataset before registering features")
    if not extractor or Path(extractor).name != extractor or extractor in {".", ".."}:
        raise ValueError("Invalid extractor name")
    async with safe_session() as db:
        dataset = await db.scalar(
            select(Dataset).where(Dataset.dataset_id == dataset_id)
        )
        if not dataset or dataset.user_id != session.user_id:
            raise PermissionError("Feature registration requires dataset ownership")
        slides = list(
            (
                await db.scalars(
                    select(WSISlide).where(WSISlide.dataset_id == dataset_id)
                )
            ).all()
        )
    durable = (
        Config.get_uploads_dir()
        / "features"
        / extractor
        / f"research_{session_id}_{dataset_id}"
    )
    durable.mkdir(parents=True, exist_ok=True)
    durable_coords = (
        Config.get_uploads_dir() / "coordinates" / f"research_{session_id}_{dataset_id}"
    )
    if coordinates:
        durable_coords.mkdir(parents=True, exist_ok=True)
    for feature in features.glob("*.pt"):
        if feature.is_file() and not feature.is_symlink():
            shutil.copy2(feature, durable / feature.name)
            if coordinates:
                coordinate = contained(coordinates, f"{feature.stem}_coords.h5")
                if not coordinate.is_file():
                    raise ValueError(f"Missing coordinates for {feature.stem}")
                target_coords = durable_coords / coordinate.name
                shutil.copy2(coordinate, target_coords)
                if contract:
                    from backend.services.viewer_features import validate_registration

                    slide = next(
                        (slide for slide in slides if slide.wsi_id == feature.stem),
                        None,
                    )
                    if slide is None:
                        raise ValueError(
                            "Feature image does not belong to the selected dataset"
                        )
                    await asyncio.to_thread(
                        validate_registration,
                        durable / feature.name,
                        target_coords,
                        contract,
                        slide,
                    )
    features = durable
    # Existing registration resolves UUID features using this dataset-view contract.
    (features / "dataset_manifest.json").write_text(
        json.dumps(
            {
                "layout": "pathlab_dataset_view",
                "pathlab_slide_map": [
                    {
                        "slide_id": slide.wsi_id,
                        "wsi_id": slide.wsi_id,
                        "wsi_path": slide.wsi_path,
                    }
                    for slide in slides
                ],
            }
        )
    )
    async with safe_session() as db:
        result = await register_extracted_features_with_pathlab(
            db=db,
            features_dir=str(features),
            extractor_name=extractor,
            dataset_id=dataset_id,
        )
        await db.commit()
        if contract and coordinates:
            for slide in (
                await db.scalars(
                    select(WSISlide).where(WSISlide.dataset_id == dataset_id)
                )
            ).all():
                path = durable / f"{slide.wsi_id}.pt"
                if path.with_suffix(".feature.json").is_file():
                    from backend.services.feature_inventory import register_manifest

                    await register_manifest(db, slide, path)
                    associated = dict(slide.associated_files or {})
                    associated["viewer_features"] = [
                        item
                        for item in associated.get("viewer_features", [])
                        if item.get("feature_path") != str(path)
                    ] + [{"feature_path": str(path)}]
                    slide.associated_files = associated
            await db.commit()
    await store.update(
        session_id,
        event={"kind": "features", "dataset_id": dataset_id, "result": result},
    )
    return result
