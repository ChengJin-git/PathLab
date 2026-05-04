"""Async DB-backed collector implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..schemas import PaperConfig
from ._clock import utc_now
from .analysis import discover_analysis_runs
from .dataset import SlideRecord, build_dataset_summary
from .external_validation import build_external_validation_summary
from .model import build_model_summary
from .qualitative import build_qualitative_summary
from .role_dispatcher import descriptors_from_config, is_external_validation
from .schemas import CollectorBundle, CollectorStatus, MissingEvidence, SourceTaskDescriptor
from .split import build_split_summary
from .task import missing_task_summary, summarize_training_task


def _task_model_config(task: Any) -> dict[str, Any]:
    value = getattr(task, "model_config", None)
    return value if isinstance(value, dict) else {}


async def _get_task(db: AsyncSession, task_id: str) -> Any | None:
    from backend.database.models import TrainingTask

    result = await db.execute(
        select(TrainingTask)
        .options(selectinload(TrainingTask.data_group))
        .where(TrainingTask.task_id == task_id)
    )
    return result.scalar_one_or_none()


async def _get_models(db: AsyncSession, task_id: str) -> list[Any]:
    from backend.database.models import TrainedModel

    result = await db.execute(
        select(TrainedModel)
        .where(TrainedModel.task_id == task_id)
        .order_by(desc(TrainedModel.created_at))
    )
    return list(result.scalars().all())


async def _get_model_by_id(db: AsyncSession, model_id: str | None) -> Any | None:
    if not model_id:
        return None
    from backend.database.models import TrainedModel

    result = await db.execute(select(TrainedModel).where(TrainedModel.model_id == model_id))
    return result.scalar_one_or_none()


async def _db_analysis_records(db: AsyncSession, task_id: str) -> list[dict[str, Any]]:
    from backend.database.models import AnalysisRun

    result = await db.execute(
        select(AnalysisRun)
        .where(AnalysisRun.task_id == task_id)
        .order_by(desc(AnalysisRun.created_at))
    )
    return [row.to_dict() for row in result.scalars().all()]


def _slide_record(slide: Any, split: str | None, dataset: Any, group: Any) -> SlideRecord:
    return SlideRecord(
        wsi_id=getattr(slide, "wsi_id", ""),
        split=split,
        dataset_id=getattr(slide, "dataset_id", None),
        dataset_name=getattr(dataset, "name", None),
        group_id=getattr(dataset, "group_id", None),
        data_type=getattr(group, "data_type", None),
        aggregation_level=getattr(group, "aggregation_level", None),
        task_type=getattr(group, "task_type", None),
        source_organ=getattr(dataset, "source_organ", None),
        is_public=getattr(dataset, "is_public", None),
        case_id=getattr(slide, "case_id", None),
        label=getattr(slide, "label", None),
        age=getattr(slide, "age", None),
        gender=getattr(slide, "gender", None),
        source=getattr(slide, "source", None),
        event_time=getattr(slide, "event_time", None),
        event_status=getattr(slide, "event_status", None),
        mpp=getattr(slide, "mpp", None),
        vendor=getattr(slide, "vendor", None),
        magnification=getattr(slide, "magnification", None),
        file_size=getattr(slide, "file_size", None),
        feature_extracted=bool(getattr(slide, "feature_extracted", False)),
    )


async def _load_regular_slides(db: AsyncSession, task_id: str) -> list[SlideRecord]:
    from backend.database.models import DataGroup, Dataset, TrainingTaskWSI, WSISlide

    result = await db.execute(
        select(WSISlide, TrainingTaskWSI.split, Dataset, DataGroup)
        .join(TrainingTaskWSI, TrainingTaskWSI.wsi_id == WSISlide.wsi_id)
        .join(Dataset, Dataset.dataset_id == WSISlide.dataset_id, isouter=True)
        .join(DataGroup, DataGroup.group_id == Dataset.group_id, isouter=True)
        .where(TrainingTaskWSI.task_id == task_id)
    )
    return [_slide_record(slide, split, dataset, group) for slide, split, dataset, group in result.all()]


async def _load_external_validation_slides(db: AsyncSession, task: Any) -> list[SlideRecord]:
    from backend.database.models import DataGroup, Dataset, WSISlide

    dataset_id = _task_model_config(task).get("dataset_id")
    if not dataset_id:
        return []
    result = await db.execute(
        select(WSISlide, Dataset, DataGroup)
        .join(Dataset, Dataset.dataset_id == WSISlide.dataset_id, isouter=True)
        .join(DataGroup, DataGroup.group_id == Dataset.group_id, isouter=True)
        .where(WSISlide.dataset_id == dataset_id)
    )
    return [
        _slide_record(slide, "external_validation", dataset, group)
        for slide, dataset, group in result.all()
    ]


async def _slides_for_task(
    db: AsyncSession,
    task: Any,
    descriptor: SourceTaskDescriptor,
) -> list[SlideRecord]:
    if is_external_validation(descriptor):
        slides = await _load_external_validation_slides(db, task)
        if slides:
            return slides
    return await _load_regular_slides(db, descriptor.task_id)


async def collect_from_session(
    db: AsyncSession,
    config: PaperConfig,
    uploads_dir: Path,
) -> CollectorBundle:
    descriptors = descriptors_from_config(config)
    task_summaries = []
    dataset_summaries = []
    split_summaries = []
    model_summaries = []
    analysis_summaries = []
    qualitative_summaries = []

    for descriptor in descriptors:
        task = await _get_task(db, descriptor.task_id)
        if task is None:
            task_summary = missing_task_summary(descriptor)
            task_summaries.append(task_summary)
            dataset_summaries.append(build_dataset_summary(descriptor, []))
            split_summaries.append(build_split_summary(descriptor, []))
            model_summaries.append(build_model_summary(descriptor, []))
            analysis = discover_analysis_runs(uploads_dir, descriptor)
            analysis_summaries.append(analysis)
            qualitative_summaries.append(build_qualitative_summary(uploads_dir, descriptor, analysis))
            continue

        task_summary = summarize_training_task(task, descriptor)
        task_summaries.append(task_summary)
        slides = await _slides_for_task(db, task, descriptor)
        dataset_summaries.append(build_dataset_summary(descriptor, slides))
        split_summaries.append(build_split_summary(descriptor, slides))

        models = await _get_models(db, descriptor.task_id)
        source_model = None
        if is_external_validation(descriptor):
            source_model = await _get_model_by_id(db, _task_model_config(task).get("model_id"))
        model_summaries.append(build_model_summary(descriptor, models, source_model))

        analysis = discover_analysis_runs(
            uploads_dir,
            descriptor,
            db_analysis_runs=await _db_analysis_records(db, descriptor.task_id),
        )
        analysis_summaries.append(analysis)
        qualitative_summaries.append(build_qualitative_summary(uploads_dir, descriptor, analysis))

    analysis_status_by_task = {item.task_id: item.status for item in analysis_summaries}
    external_validation = build_external_validation_summary(
        descriptors,
        task_summaries,
        analysis_status_by_task,
    )
    missing = _bundle_missing(
        task_summaries,
        dataset_summaries,
        split_summaries,
        model_summaries,
        analysis_summaries,
        qualitative_summaries,
        external_validation.missing_evidence,
    )
    return CollectorBundle(
        paper_id=config.paper_id,
        mode="db",
        status=_bundle_status(task_summaries, missing),
        collected_at=utc_now(),
        source_tasks=descriptors,
        task_summaries=task_summaries,
        dataset_summaries=dataset_summaries,
        split_summaries=split_summaries,
        model_summaries=model_summaries,
        analysis_summaries=analysis_summaries,
        external_validation_summary=external_validation,
        qualitative_summaries=qualitative_summaries,
        missing_evidence=missing,
    )


async def collect_from_db(config: PaperConfig, uploads_dir: Path) -> CollectorBundle:
    from backend.database import async_session

    async with async_session() as db:
        return await collect_from_session(db, config, uploads_dir)


def _bundle_missing(*groups: Any) -> list[MissingEvidence]:
    missing: list[MissingEvidence] = []
    for group in groups:
        if isinstance(group, list):
            for item in group:
                missing.extend(getattr(item, "missing_evidence", []) or [])
        else:
            missing.extend(group or [])
    return missing


def _bundle_status(
    task_summaries: list[Any],
    missing: list[MissingEvidence],
) -> CollectorStatus:
    if not task_summaries or all(not item.exists for item in task_summaries):
        return CollectorStatus.missing
    if missing:
        return CollectorStatus.partial
    return CollectorStatus.ready
