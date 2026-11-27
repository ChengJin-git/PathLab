"""Authoritative storage roots, streamed in bounded database batches.

FeatureArtifact is an inventory entry, not a consumer: a registered cache can be
reclaimed when no experiment uses it. Results, experiments and saved analyses are
consumers even when their original image has since been removed.
"""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import sqlite3
import asyncio
from sqlalchemy.orm import noload

from sqlalchemy import select, text
from backend.database import models as m
from .inventory import IDENTITY, Inventory


@dataclass
class References:
    image_ids: set[str] = field(default_factory=set)
    owners: set[str] = field(default_factory=set)
    used_ids: set[str] = field(default_factory=set)
    paths: set[str] = field(default_factory=set)
    active: set[str] = field(default_factory=set)
    checkpoint: int | None = None

    def add(self, value, root: Path):
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(key, str) and key.startswith("/"):
                    self.add(key, root)
                self.add(item, root)
        elif isinstance(value, (list, tuple)):
            for item in value:
                self.add(item, root)
        elif isinstance(value, str):
            tokens = IDENTITY.findall(value)
            self.used_ids.update(tokens)
            self.used_ids.update(
                token.removeprefix("session_")
                for token in tokens
                if token.startswith("session_")
            )
            pattern = re.escape(str(root)) + r"/[^\s\"'<>`\[\]{}(),;]+"
            paths = re.findall(pattern, value)
            if (
                value.startswith(str(root) + os.sep)
                and "\n" not in value
                and len(value) < 4096
            ):
                paths.append(value)
            for path in paths:
                relative = os.path.relpath(os.path.normpath(path.rstrip(".:")), root)
                parts = Path(relative).parts
                if not parts or parts[0] == "..":
                    continue
                if relative in {
                    "autoresearch/autoresearch_sessions",
                    "autoresearch/autoresearch_sessions/model_artifacts",
                    "autoresearch/pathlab_datasets/session_inputs",
                    "autoresearch/runtime",
                    "logs/training",
                    "logs/analysis",
                }:
                    continue
                # Runtime base directories in configurations do not pin every
                # artifact. Specific feature directories and owned roots do.
                minimum = 3 if parts[0] == "autoresearch" else 2
                if len(parts) >= minimum:
                    self.paths.add(relative)


async def collect(db, root: Path, progress=lambda *a, **k: None) -> References:
    refs = References()
    if db.bind.dialect.name == "postgresql":
        refs.checkpoint = await db.scalar(
            text("SELECT txid_snapshot_xmin(txid_current_snapshot()) % 4294967296")
        )
    processed = 0

    async def rows(statement):
        nonlocal processed
        stream = await db.stream(statement.execution_options(yield_per=512))
        async for batch in stream.partitions(512):
            for row in batch:
                yield row
            processed += len(batch)
            progress(processed, None, "references")

    async for wsi_id, path, associated in rows(
        select(m.WSISlide.wsi_id, m.WSISlide.wsi_path, m.WSISlide.associated_files)
    ):
        refs.image_ids.add(wsi_id)
        # Source images and MRXS/TMAP companions are rooted by path. Feature
        # registrations remain rooted if explicitly supplied as dataset inputs.
        refs.add(path, root)
        refs.add(associated, root)
        refs.used_ids.discard(wsi_id)
    for model, column in (
        (m.TrainingTask, m.TrainingTask.task_id),
        (m.AITask, m.AITask.task_id),
        (m.AutoResearchSession, m.AutoResearchSession.session_id),
        (m.ResearchJob, m.ResearchJob.job_id),
        (m.TrainedModel, m.TrainedModel.model_id),
        (m.AnalysisRun, m.AnalysisRun.analysis_id),
        (m.ResultAnalysis, m.ResultAnalysis.analysis_id),
        (m.ChatConversation, m.ChatConversation.conversation_id),
        (m.Manuscript, m.Manuscript.report_id),
        (m.Dataset, m.Dataset.dataset_id),
        (m.ExportTask, m.ExportTask.task_id),
    ):
        async for row in rows(select(model).options(noload("*"))):
            entity = row[0]
            identity = str(getattr(entity, column.key))
            refs.owners.add(identity)
            data = {
                c.name: getattr(entity, c.key)
                for c in model.__table__.columns
                if c.name not in {"id", "user_id", "wsi_id", "dataset_id"}
            }
            refs.add(data, root)
            status = getattr(entity, "status", None)
            if model in (
                m.TrainingTask,
                m.AITask,
                m.ResearchJob,
                m.ResultAnalysis,
            ) and status in {
                "pending",
                "queued",
                "running",
                "processing",
                "patching",
                "extracting",
                "training",
                "resuming",
                "cancelling",
                "stopping",
            }:
                refs.active.add(identity)
            if (
                model is m.AutoResearchSession
                and status in {"queued", "running", "stopping"}
            ):
                refs.active.add(identity)
    for model in (
        m.AutoResearchExperiment,
        m.ResultSource,
        m.ResultRecipe,
        m.ResultConversation,
        m.Workspace,
        m.WorkbenchFile,
    ):
        async for row in rows(select(model).options(noload("*"))):
            entity = row[0]
            refs.add(
                {
                    c.name: getattr(entity, c.key)
                    for c in model.__table__.columns
                    if c.name not in {"id", "user_id"}
                },
                root,
            )
            if model is m.AutoResearchExperiment and entity.training_task_id:
                refs.owners.add(entity.training_task_id)
    async for metadata, content in rows(
        select(m.ChatMessage.extra_metadata, m.ChatMessage.content)
    ):
        refs.add(metadata, root)
        refs.add(content, root)
    await add_events(db, root, refs, progress)
    async for task_id, wsi_id in rows(
        select(m.TrainingTaskWSI.task_id, m.TrainingTaskWSI.wsi_id)
    ):
        if task_id in refs.owners or task_id in refs.used_ids:
            refs.used_ids.add(wsi_id)
    async for task_id, wsi_id in rows(
        select(m.AIResult.task_id, m.AIResult.wsi_id).distinct()
    ):
        # Saved inference rows are a consumer in their own right. A missing
        # orchestration task is not permission to discard the saved result.
        if task_id:
            refs.owners.add(task_id)
        refs.used_ids.add(wsi_id)
    from sqlalchemy import Text, cast

    async for (metadata,) in rows(
        select(m.AIResult.extra_metadata).where(
            cast(m.AIResult.extra_metadata, Text).contains(str(root))
        )
    ):
        refs.add(metadata, root)
    # Pending durable cleanup is not a live owner. Its saved paths are removed by
    # that queue, not pinned by a self-reference in its deletion manifest.
    async for task_id, params in rows(
        select(m.StorageTask.task_id, m.StorageTask.params).where(
            m.StorageTask.status.in_(["pending", "processing"]),
            ~m.StorageTask.task_type.in_(
                [
                    "file_cleanup",
                    "storage_cleanup",
                    "storage_scan",
                    "chat_delete",
                ]
            ),
        )
    ):
        refs.active.add(task_id)
        refs.add(params, root)
    return refs


async def add_events(db, root, refs, progress):
    """Append-only research history is indexed once, then refreshed by ID cursor."""
    sessions = set((await db.scalars(select(m.AutoResearchSession.session_id))).all())
    inventory = Inventory(root)
    with inventory.connect() as local:
        row = local.execute(
            "SELECT value FROM meta WHERE key='event_cursor'"
        ).fetchone()
        cursor = int(row[0]) if row else 0
        stream = await db.stream(
            select(
                m.AutoResearchEvent.id,
                m.AutoResearchEvent.session_id,
                m.AutoResearchEvent.event_data,
            )
            .where(m.AutoResearchEvent.id > cursor)
            .order_by(m.AutoResearchEvent.id)
            .execution_options(yield_per=256)
        )
        async for batch in stream.partitions(256):

            def extract():
                found = set()
                for _, session_id, data in batch:
                    if session_id not in sessions:
                        continue
                    extracted = References()
                    extracted.add(data, root)
                    found.update(
                        (session_id, "id", value) for value in extracted.used_ids
                    )
                    for value in extracted.paths:
                        parts = Path(value).parts
                        if (
                            parts[0] in {"features", "coordinates"}
                            and not Path(value).suffix
                            and len(parts) <= (3 if parts[0] == "features" else 2)
                        ):
                            continue
                        found.add((session_id, "path", value))
                return found

            found = await asyncio.to_thread(extract)
            cursor = batch[-1][0]
            local.executemany(
                "INSERT OR IGNORE INTO event_references VALUES(?,?,?)", found
            )
            local.execute(
                "INSERT OR REPLACE INTO meta VALUES('event_cursor',?)", (str(cursor),)
            )
            local.commit()
            progress(cursor, None, "references")
        for (session_id,) in local.execute(
            "SELECT DISTINCT session_id FROM event_references"
        ):
            if session_id not in sessions:
                local.execute(
                    "DELETE FROM event_references WHERE session_id=?", (session_id,)
                )
        for kind, target in local.execute(
            "SELECT DISTINCT kind,target FROM event_references"
        ):
            if kind == "path":
                parts = Path(target).parts
                if (
                    parts[0] in {"features", "coordinates"}
                    and not Path(target).suffix
                    and len(parts) <= (3 if parts[0] == "features" else 2)
                ):
                    continue
            (refs.used_ids if kind == "id" else refs.paths).add(target)


def add_result_catalog(refs: References, root: Path):
    path = root / "ai_results_bundles/catalog.sqlite3"
    if path.exists():
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
            for task_id, wsi_id in db.execute(
                "SELECT DISTINCT task_id,wsi_id FROM artifacts"
            ):
                if task_id in refs.owners or task_id in refs.used_ids:
                    refs.used_ids.add(wsi_id)
    staging = root / "ai_results_bundles/.staging"
    if staging.exists():
        for attrs in staging.glob("*.zarr/.zattrs"):
            if attrs.parent.name[:-5] in refs.owners | refs.used_ids:
                refs.used_ids.update(json.loads(attrs.read_text()).get("wsi_ids", []))


async def add_runtime(refs: References, root: Path):
    from backend.common.redis_client import get_redis

    redis = get_redis()
    snapshot = await redis.get("pathlab:task_worker:runtime_status")
    if snapshot:
        value = json.loads(snapshot)
        for key in ("running_task_ids", "pending_task_ids", "patching_task_ids"):
            refs.active.update(value.get(key, []))
    for queue in ("queue", "processing", "dlq"):
        # The pending queues are small; read in bounded ranges regardless.
        offset = 0
        while batch := await redis.lrange(
            "pathlab:task_worker:" + queue, offset, offset + 255
        ):
            for raw in batch:
                try:
                    value = json.loads(raw)
                except ValueError:
                    value = raw
                refs.add(value, root)
                if queue != "dlq" and isinstance(value, dict):
                    refs.active.add(
                        value.get("job_id") or value.get("task_id") or "queued"
                    )
            offset += len(batch)
    return refs
