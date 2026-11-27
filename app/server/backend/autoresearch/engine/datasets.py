"""Scoped Data Repo views and the existing public dataset providers."""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
import re
import threading
import time
from collections import Counter
from contextlib import suppress
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from backend.auth.models import User
from backend.common import file_lock as fcntl
from backend.common.config import Config
from backend.database.database import safe_session
from backend.database.models import Dataset, WSISlide

from ..dataset.download_progress import DownloadProgressReporter
from ..dataset.downloader import extract_archive
from ..dataset.pathlab_registration import register_manifest_with_pathlab
from ..dataset.providers.factory import build_default_providers
from ..dataset.registry import DatasetRegistry
from ..dataset.types import DatasetManifest, DatasetRecord
from . import store
from .dataset_files import DatasetFiles, DatasetPreparationTimeout
from .input_files import InputFiles
from .runtime import private_dir

log = logging.getLogger(__name__)
PREPARATION_SECONDS = 120


async def prepare_pending_datasets(session):
    """Resume frozen inputs; explicit prepare_dataset refreshes a dataset when needed."""
    meta = session.recovery_metadata or {}
    root = Path(session.workspace_path)
    prepared = {item['dataset_id']: item for item in meta.get('datasets', [])}
    mounts = meta.get('data_mounts', {})
    for dataset_id in meta.get('dataset_ids', []):
        item = prepared.get(dataset_id)
        manifest = root / 'datasets' / dataset_id / 'manifest.json'
        inputs = private_dir(session.session_id) / 'inputs' / dataset_id
        if (item and item.get('manifest_path') == str(manifest) and manifest.is_file()
                and (manifest.parent / 'labels.csv').is_file() and inputs.is_dir()
                and mounts.get(str(inputs)) == f'/research-data/{dataset_id}'):
            continue
        await prepare_dataset(session.session_id, dataset_id)


async def validate_access(session):
    """Recheck mounted datasets before a resumed session or queued job executes."""
    from uuid import UUID

    from backend.services.workspaces import resolve_scope

    meta = session.recovery_metadata or {}
    if meta.get('delete_requested'):
        raise PermissionError('Research is being deleted')
    async with safe_session() as db:
        user = await db.get(User, UUID(session.user_id))
        if user is None or not user.is_active or not user.can_use_gpu():
            raise PermissionError("Research owner no longer has execution access")
        from backend.auth.dependencies import assert_research_access

        assert_research_access(user)
        scope = await resolve_scope(db, user, meta.get("workspace_id"))
        if (
            scope.execution_mode == "read_only"
            or "training" not in scope.enabled_skills
        ):
            raise PermissionError("Research is disabled in this workspace")
        allowed = set((await db.scalars(scope.datasets(user))).all())
        acquired = set(meta.get("acquired_dataset_ids", []))
        ids = {d["dataset_id"] for d in meta.get("datasets", [])}
        if ids - allowed - acquired:
            raise PermissionError("Research dataset access has changed")
        rows = (
            await db.scalars(select(Dataset).where(Dataset.dataset_id.in_(ids)))
        ).all()
        if len(rows) != len(ids):
            raise PermissionError("A research dataset is no longer available")
        for dataset in rows:
            if (
                not user.is_admin()
                and dataset.user_id != session.user_id
                and dataset.dataset_id not in allowed
            ):
                raise PermissionError("Research dataset access is no longer available")
    if meta.get('resource_references'):
        from .references import validate_references
        await validate_references(session)


async def list_datasets(
    user: User, workspace_id: str | None = None, query: str = ""
) -> list[dict]:
    async with safe_session() as db:
        statement = select(Dataset).options(selectinload(Dataset.tasks))
        if str(user.role) != "admin":
            from backend.services.dataset_access import accessible_dataset_ids
            statement = statement.where(Dataset.dataset_id.in_(accessible_dataset_ids(user)))
        if workspace_id:
            from backend.services.workspaces import resolve_scope

            scope = await resolve_scope(db, user, workspace_id)
            statement = statement.where(Dataset.dataset_id.in_(scope.datasets(user)))
        if query:
            statement = statement.where(Dataset.name.ilike(f"%{query}%"))
        datasets = (await db.scalars(statement.order_by(Dataset.name).limit(100))).all()
        ids = [d.dataset_id for d in datasets]
        counts = dict(
            (
                await db.execute(
                    select(WSISlide.dataset_id, func.count())
                    .where(WSISlide.dataset_id.in_(ids))
                    .group_by(WSISlide.dataset_id)
                )
            ).all()
        )
        return [
            {**d.to_dict(), "file_count": counts.get(d.dataset_id, 0)} for d in datasets
        ]


async def prepare_dataset(session_id: str, dataset_id: str) -> dict:
    started = time.monotonic()
    session = await store.get(session_id)
    meta = session.recovery_metadata or {}
    async with safe_session() as db:
        import uuid

        user = await db.get(User, uuid.UUID(session.user_id))
    async with safe_session() as db:
        from backend.auth.dependencies import get_dataset_with_access
        from backend.services.workspaces import resolve_scope

        row = await get_dataset_with_access(dataset_id, user, db)
        scope = await resolve_scope(db, user, meta.get("workspace_id"))
        acquired = (
            dataset_id in meta.get("acquired_dataset_ids", [])
            and row.user_id == session.user_id
        )
        if not acquired and dataset_id not in set(
            (await db.scalars(scope.datasets(user))).all()
        ):
            raise PermissionError("Dataset is outside the authorized research scope")
        row = await db.scalar(
            select(Dataset)
            .options(selectinload(Dataset.tasks))
            .where(Dataset.dataset_id == dataset_id)
        )
        dataset = row.to_dict()
        annotations = {}
        if set(dataset["task_types"]) & {"patch_segmentation", "patch_detection"}:
            from backend.services.dataset_catalog import load_task_annotations
            for task_type in set(dataset['task_types']) & {'patch_segmentation','patch_detection'}:
                annotations[task_type] = await load_task_annotations(db, dataset_id, task_type)
        slides = list(
            (
                await db.scalars(
                    select(WSISlide)
                    .where(WSISlide.dataset_id == dataset_id)
                    .order_by(WSISlide.wsi_id)
                )
            ).all()
        )
        from backend.database.models import FeatureArtifact
        registered=(await db.scalars(select(FeatureArtifact).join(WSISlide,WSISlide.wsi_id==FeatureArtifact.wsi_id).where(WSISlide.dataset_id==dataset_id,FeatureArtifact.status=='ready'))).all()
        feature_map={}
        for artifact in registered:feature_map.setdefault(artifact.wsi_id,{})[artifact.model_id]=artifact.feature_path
    target = Path(session.workspace_path) / "datasets" / dataset_id
    target.mkdir(parents=True, exist_ok=True)
    input_root = private_dir(session_id) / "inputs" / dataset_id
    input_root.mkdir(parents=True, exist_ok=True)
    cancelled = threading.Event()
    progress = {'stage': 'resolve_sources', 'completed': 0}

    def check():
        if cancelled.is_set():
            raise RuntimeError('Dataset preparation was cancelled')
        if time.monotonic() - started >= PREPARATION_SECONDS:
            raise DatasetPreparationTimeout(dataset['name'], progress['stage'], progress['completed'], len(slides))

    def build():
        inventory = DatasetFiles(check)
        sources = {}
        for slide in slides:
            check()
            sources[slide.wsi_id] = inventory.resolve_source(Path(slide.wsi_path))
            progress['completed'] += 1
        roots = [Config.get_uploads_dir() / "features"]
        for slide in slides[:5]:
            source = sources[slide.wsi_id]
            for parent in [source.parent, source.parent.parent]:
                for sub in ["features", "pt_files"]:
                    if parent / sub not in roots:
                        roots.append(parent / sub)
        items = []
        inputs = InputFiles(private_dir(session_id), dataset_id)
        # Retain task-specific labels shipped alongside registered source slides.
        from ..dataset.normalizers.mil_classification import (
            _SLIDE_ID_COLUMNS,
            _first_value,
            _first_value_with_column,
            _label_columns_for_profile,
            _read_table,
        )

        label_columns = _label_columns_for_profile(
            {"question": session.research_question}
        )
        source_labels = {}
        label_sources = set()
        progress.update(stage='label_inventory', completed=0)
        directories = {directory for source in sources.values() for directory in (source.parent, source.parent.parent)}
        for directory in sorted(directories):
            label_sources.update(inventory.label_tables(directory))
        log.info('Dataset preparation %s/%s: %s slides, %s label directories, %.2fs to inventory', session_id, dataset_id, len(slides), len(directories), time.monotonic() - started)
        for label_source in sorted(label_sources):
            check()
            try:
                for row in _read_table(label_source):
                    check()
                    key = Path(_first_value(row, _SLIDE_ID_COLUMNS)).stem
                    label, column = _first_value_with_column(row, label_columns)
                    if key and label:
                        source_labels[key] = (label, column)
            except TimeoutError:
                raise
            except OSError:
                continue

        progress.update(stage='input_views', completed=0)
        for slide in slides:
            check()
            source = sources[slide.wsi_id]
            features = inventory.features(slide, source, roots)
            features.update({model:path for model,path in feature_map.get(slide.wsi_id,{}).items() if Path(path).is_file()})
            input_path = (
                f"/research-data/{dataset_id}/images/{slide.wsi_id}{source.suffix}"
            )
            if source.is_file():
                inputs.add(source, input_path)
            feature_paths = {}
            for extractor, feature in features.items():
                destination = f"/research-data/{dataset_id}/features/{extractor}/{slide.wsi_id}{Path(feature).suffix}"
                inputs.add(inventory.resolve_source(Path(feature)), destination)
                feature_paths[extractor] = destination
            label, label_source = slide.label, "data_repo"
            task_specific = label_columns[0].startswith("Task")
            if task_specific or not label:
                for stem in [
                    Path(slide.original_filename or "").stem,
                    source.stem,
                    slide.wsi_id,
                ]:
                    if stem in source_labels:
                        label, label_source = source_labels[stem]
                        break
            items.append(
                {
                    "wsi_id": slide.wsi_id,
                    "case_id": slide.case_id
                    or (
                        slide.wsi_id if dataset["aggregation_level"] == "file" else None
                    ),
                    "path": input_path,
                    "label": label,
                    "label_source": label_source,
                    "split": slide.split,
                    "event_time": slide.event_time,
                    "event_status": slide.event_status,
                    "features": feature_paths,
                }
            )
            progress['completed'] += 1
        manifest = {
            "dataset_id": dataset_id,
            "name": dataset["name"],
            "data_type": dataset["data_type"],
            "task_types": dataset["task_types"],
            "aggregation_level": dataset["aggregation_level"],
            "source_organ": dataset["source_organ"],
            "is_public": dataset["is_public"],
            "acquisition_metadata": dataset.get("acquisition_metadata"),
            "items": items,
            "label_counts": dict(Counter(x["label"] for x in items if x["label"])),
            "feature_extractors": sorted({k for x in items for k in x["features"]}),
        }
        manifest['annotation_files'] = {}
        for task_type, payload in annotations.items():
            annotation_file = input_root / f'{task_type}-annotations.json'
            annotation_file.write_text(json.dumps(payload, ensure_ascii=False))
            manifest['annotation_files'][task_type] = f'/research-data/{dataset_id}/{annotation_file.name}'
        check()
        manifest_tmp = target / '.manifest.json.tmp'
        labels_tmp = target / '.labels.csv.tmp'
        manifest_tmp.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2)
        )
        with labels_tmp.open("w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "wsi_id",
                    "case_id",
                    "label",
                    "split",
                    "path",
                    "event_time",
                    "event_status",
                ],
            )
            writer.writeheader()
            writer.writerows({k: x[k] for k in writer.fieldnames} for x in items)
        check()
        labels_tmp.replace(target / 'labels.csv')
        manifest_tmp.replace(target / 'manifest.json')
        return manifest, inputs.mounts

    def locked_build():
        with (input_root / '.prepare.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('This dataset is already being prepared for this session. Wait for the current operation instead of submitting a duplicate.') from None
            try:
                return build()
            finally:
                for name in ('.manifest.json.tmp', '.labels.csv.tmp'):
                    (target / name).unlink(missing_ok=True)

    build_task = asyncio.create_task(asyncio.to_thread(locked_build))
    try:
        manifest, mounts = await asyncio.shield(build_task)
    except asyncio.CancelledError:
        cancelled.set()
        with suppress(Exception):
            await build_task
        raise
    info = {k: v for k, v in manifest.items() if k != "items"}
    info.update(
        {
            "manifest_path": str(target / "manifest.json"),
            "file_count": len(slides),
            "mount_note": "If a newly attached external file is not visible yet, end this turn; PathLab will refresh the input mounts.",
        }
    )
    from ..runtime.container_backend import backend, container_path, map_tree
    if backend() == 'docker' and os.name == 'nt':
        # Manifests read inside the Linux container must never expose drive-letter paths.
        manifest_path = target / 'manifest.json'
        translated = map_tree(json.loads(manifest_path.read_text()), {
            str(Path(session.workspace_path)): container_path(str(Path(session.workspace_path)))
        })
        manifest_path.write_text(json.dumps(translated, ensure_ascii=False), encoding='utf8')
    await store.attach_dataset(session_id, info, mounts)
    log.info('Dataset preparation %s/%s completed: %s slides in %.2fs', session_id, dataset_id, len(slides), time.monotonic() - started)
    return info


async def mount_download(session_id: str, record: DatasetRecord, root: Path) -> str:
    target = "/research-data/downloads/" + re.sub(r"[^A-Za-z0-9._-]", "_", record.dataset_id)
    latest = await store.get(session_id)
    meta = latest.recovery_metadata or {}
    mounts = {source: path for source, path in meta.get("data_mounts", {}).items() if path != target}
    sources = [item for item in meta.get("downloaded_sources", []) if item["mounted_at"] != target]
    sources.append({"dataset_id": record.dataset_id, "name": record.name, "provider": record.provider,
                    "source_url": record.source_url, "mounted_at": target})
    await store.update(
        session_id,
        meta={"data_mounts": {**mounts, str(root): target}, "mounts_changed": True,
              "downloaded_sources": sources},
        expected_metadata={"data_mounts": meta.get("data_mounts"),
                           "downloaded_sources": meta.get("downloaded_sources")},
        event={"kind": "dataset", "dataset": {"dataset_id": record.dataset_id, "name": record.name,
                                              "mounted_at": target, "registered": False}},
    )
    return target


def public_datasets(query: str = "") -> list[dict]:
    seed = Path(__file__).parents[1] / "dataset" / "seed_data"
    records = [r for p in seed.glob("*.json") for r in DatasetRegistry(p).load()]
    return [
        r.to_dict()
        for r in records
        if not query or query.lower() in json.dumps(r.to_dict()).lower()
    ][:30]


async def acquire(session_id: str, record_data: dict, job_id: str) -> dict:
    from .acquisition_contract import AcquisitionRecord

    record_data = AcquisitionRecord.model_validate(record_data).model_dump()
    session = await store.get(session_id)
    if not (session.recovery_metadata or {}).get("allow_downloads", True):
        raise PermissionError("Public downloads are disabled for this research")
    record = DatasetRecord.from_dict(record_data)
    providers = build_default_providers()
    if record.provider not in providers:
        raise ValueError(f"Unknown provider: {record.provider}")
    from hashlib import sha256

    identity = {"provider": record.provider, "dataset_id": record.dataset_id}
    if record.download.include:
        # Different file selections from one repository are different cached datasets.
        identity["include"] = sorted(record.download.include)
    source_identity = sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    root = (
        Config.get_autoresearch_dir()
        / "dataset_cache"
        / session.user_id
        / source_identity
    )
    cache_owner_root = Config.get_autoresearch_dir() / "dataset_cache" / session.user_id
    if (
        root.resolve() == cache_owner_root.resolve()
        or not root.resolve().is_relative_to(cache_owner_root.resolve())
    ):
        raise ValueError("Dataset cache name must identify a child directory")
    root.mkdir(parents=True, exist_ok=True)
    marker = root / "research-download.json"
    inventory_file = root / "download-inventory.json"
    progress = DownloadProgressReporter(
        Path(session.workspace_path) / "downloads" / f"{job_id}.json",
        dataset_id=record.dataset_id,
        provider=record.provider,
        raw_root=root,
    )

    def download():
        with (root / ".download.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if marker.exists():
                previous = DatasetRecord.from_dict(json.loads(marker.read_text()))
                if (
                    previous.dataset_id != record.dataset_id
                    or previous.download != record.download
                ):
                    raise ValueError(
                        "This cache name belongs to a different dataset source; use a distinct dataset name"
                    )
                if record.license.lower() == "unknown":
                    record.license = previous.license
                if not record.description:
                    record.description = previous.description
                if inventory_file.is_file():
                    inventory = json.loads(inventory_file.read_text())
                    if any(
                        not (root / item["path"]).is_file()
                        or (root / item["path"]).stat().st_size != item["size"]
                        for item in inventory
                    ):
                        raise ValueError(
                            "Cached dataset files are missing or truncated; repair the download before registration"
                        )
                marker.write_text(json.dumps(record.to_dict(), ensure_ascii=False))
                return True
            result = providers[record.provider].download(record, root, progress)
            if result.status not in {"downloaded", "cached", "prepared"}:
                raise RuntimeError(result.reason or result.status)
            for path in result.files:
                if str(path).endswith((".zip", ".tar", ".tar.gz", ".tgz")):
                    extract_archive(Path(path), root / "extracted")
            inventory_file.write_text(
                json.dumps(
                    [
                        {
                            "path": str(Path(path).relative_to(root)),
                            "size": Path(path).stat().st_size,
                        }
                        for path in result.files
                    ]
                )
            )
            marker.write_text(json.dumps(record.to_dict()))
            return False

    cache_hit = await asyncio.to_thread(download)
    from ..dataset.normalizers import (
        MILClassificationNormalizer,
        NormalizerError,
        PatchClassificationNormalizer,
    )

    raw_root = root / "extracted" if (root / "extracted").is_dir() else root
    task_type = (record.task_types or ["wsi_classification"])[0]
    normalizer = (
        PatchClassificationNormalizer()
        if "patch" in task_type
        else MILClassificationNormalizer()
    )
    if task_type in {"wsi_survival", "patch_segmentation", "patch_detection"}:
        contract = {"task_type": task_type}
    else:
        try:
            contract = await asyncio.to_thread(
                normalizer.prepare, raw_root, root / "prepared"
            )
        except NormalizerError as exc:
            contract = {"preparation_note": str(exc)}
    contract["task_type"] = task_type
    if record.annotations_file:
        annotations = (root / record.annotations_file).resolve()
        if not annotations.is_file():
            annotations = (raw_root / record.annotations_file).resolve()
        if not annotations.is_relative_to(root.resolve()) or not annotations.is_file():
            raise ValueError(
                "annotations_file must identify a downloaded file inside the dataset"
            )
        contract[
            "annotations_file" if task_type in {"patch_segmentation", "patch_detection"} else "labels_file"
        ] = str(annotations)
    if record.aggregation_level == "case":
        # A file-wise random split must not be silently applied to patient bags.
        contract.pop("splits_file", None)
    if record.splits_file:
        splits = (root / record.splits_file).resolve()
        if not splits.is_file():
            splits = (raw_root / record.splits_file).resolve()
        if not splits.is_relative_to(root.resolve()) or not splits.is_file():
            raise ValueError(
                "splits_file must identify a downloaded file inside the dataset"
            )
        contract["splits_file"] = str(splits)
    manifest = DatasetManifest(
        dataset_id=record.dataset_id,
        provider=record.provider,
        selected_for_task=(record.task_types or ["classification"])[0],
        raw_root=str(root),
        prepared_root=str(root / "prepared"),
        data_mounts={str(root): str(root)},
        prepared_contract=contract,
        access=record.access,
        metadata=record.to_dict(),
        status="prepared",
    )
    async with safe_session() as db:
        registration = await register_manifest_with_pathlab(
            db=db, manifest=manifest, session_id=session_id, user_id=session.user_id
        )
        await db.commit()
    (root / "registration.json").write_text(
        json.dumps(registration, ensure_ascii=False, indent=2)
    )
    if registration.get("reason") == "no_wsi_files":
        # Pre-extracted features and tables are usable as they are; only slides enter the Data Repo.
        mounted = await mount_download(session_id, record, root)
        return {
            "root": str(root),
            "registration": registration,
            "mounted_at": mounted,
            "source": record.to_dict(),
            "cache_hit": cache_hit,
            "note": f"No whole-slide images, so nothing was registered in the Data Repo. The downloaded files are "
                    f"mounted read-only at {mounted} for direct use; prepare_dataset does not apply. Mounts "
                    "refresh when this turn ends.",
        }
    if registration["status"] != "registered":
        raise ValueError(
            f"Dataset downloaded but registration is incomplete: {registration}"
        )
    if registration.get("dataset_id"):
        latest = await store.get(session_id)
        acquired = set((latest.recovery_metadata or {}).get("acquired_dataset_ids", []))
        acquired.add(registration["dataset_id"])
        await store.update(session_id, meta={"acquired_dataset_ids": sorted(acquired)})
        await prepare_dataset(session_id, registration["dataset_id"])
    return {
        "root": str(root),
        "registration": registration,
        "source": record.to_dict(),
        "cache_hit": cache_hit,
    }
