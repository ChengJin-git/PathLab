"""Dev-only FastAPI service for standalone paper-agent testing."""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .bootstrap import configure_uploads_dir
from .pipeline import (
    create_dev_run,
    load_manifest,
    manifest_artifacts,
    run_stage,
    save_manifest,
    summarize_manifest,
)
from .regenerate import MissingSectionDraftError, UnknownSectionError, latest_regenerate_log_summary, regenerate_section
from .schemas import (
    CreatePaperRequest,
    PaperRunCreateResponse,
    PaperRunDetail,
    PaperRunListResponse,
    PaperRunStage,
    RegenerateSectionRequest,
)
from .storage import PaperRunPaths, is_path_allowed_for_download, papers_root, safe_resolve, validate_paper_id

logger = logging.getLogger(__name__)

_STAGES_FULL: tuple[PaperRunStage, ...] = (
    PaperRunStage.collecting,
    PaperRunStage.building_evidence,
    PaperRunStage.outlining,
    PaperRunStage.plotting,
    PaperRunStage.literature_review,
    PaperRunStage.section_writing,
    PaperRunStage.validating,
    PaperRunStage.refining,
    PaperRunStage.rendering,
    PaperRunStage.exporting,
)
_CRC_MSI_TASK_ID = "crc_msi_abmil_fixture"


def _is_registered_public_artifact(manifest, rel_path: str) -> bool:
    raw = manifest.artifact_index.get(rel_path)
    if not isinstance(raw, dict):
        return False
    return (
        raw.get("visibility") == "public"
        and bool(raw.get("downloadable", True))
        and raw.get("status", "ready") in {"ready", "generated", "completed"}
    )


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def _fixture_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "crc_msi_classification"


def _read_fixture_json(name: str) -> dict:
    path = _fixture_dir() / name
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _crc_msi_task() -> dict:
    task = _read_fixture_json("task_record.json")
    return {
        "task_id": task.get("task_id", _CRC_MSI_TASK_ID),
        "task_name": task.get("task_name", "CRC MSI WSI Classification"),
        "task_type": task.get("task_type", "wsi_classification"),
        "data_type": task.get("data_type", "wsi"),
        "task_description": task.get("task_description"),
        "status": task.get("status", "completed"),
        "progress": 100,
        "error_message": None,
        "preprocessing_config": task.get("preprocessing_config"),
        "model_config": task.get("model_config"),
        "classes": task.get("classes", ["MSI", "MSS"]),
        "source_dataset_id": "crc_msi_dataset_fixture",
        "created_at": "2026-05-05T09:30:00+00:00",
        "updated_at": "2026-05-05T11:20:00+00:00",
        "started_at": "2026-05-05T09:35:00+00:00",
        "finished_at": "2026-05-05T11:20:00+00:00",
        "user_id": "00000000-0000-0000-0000-000000000000",
        "username": "demo",
    }


def _task_matches(task: dict, search: str | None) -> bool:
    if not search:
        return True
    needle = search.casefold()
    return any(
        needle in str(task.get(key) or "").casefold()
        for key in ("task_id", "task_name", "task_type", "task_description")
    )


def _with_crc_msi_defaults(body: CreatePaperRequest | None) -> CreatePaperRequest:
    request = body or CreatePaperRequest()
    if not any(task.task_id == _CRC_MSI_TASK_ID for task in request.source_tasks):
        return request

    fixture_request = _read_fixture_json("paper_request.json")
    updates = {}
    if not request.title:
        updates["title"] = fixture_request.get("title") or "CRC MSI Prediction from H&E Whole-Slide Images"
    if not request.user_idea:
        updates["user_idea"] = fixture_request.get("user_idea")
    return request.model_copy(update=updates) if updates else request


def _uses_crc_msi_fixture(paths: PaperRunPaths) -> bool:
    if not paths.config.exists():
        return False
    try:
        config = json.loads(paths.config.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    tasks = config.get("source_tasks") or []
    return any(isinstance(task, dict) and task.get("task_id") == _CRC_MSI_TASK_ID for task in tasks)


def _seed_crc_msi_fixture(paths: PaperRunPaths) -> None:
    """Replace DB-missing dev collection with the synthetic CRC MSI fixture."""
    fixture_raw = _fixture_dir() / "raw_collected"
    if not fixture_raw.is_dir() or not _uses_crc_msi_fixture(paths):
        return
    target = paths.evidence_dir / "raw_collected"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(fixture_raw, target)
    logger.info("paper_agent dev_server: seeded CRC MSI fixture for %s", paths.paper_id)


def _run_full_pipeline_for_dev(paper_id: str, uploads_dir: Optional[str | Path]) -> None:
    configure_uploads_dir(uploads_dir)
    paths = PaperRunPaths.for_paper(paper_id)
    try:
        for stage in _STAGES_FULL:
            run_stage(paper_id, stage, uploads_dir=uploads_dir)
            if stage == PaperRunStage.collecting:
                _seed_crc_msi_fixture(paths)
        run_stage(
            paper_id,
            PaperRunStage.completed,
            uploads_dir=uploads_dir,
            message="Standalone paper-agent dev run completed.",
        )
    except Exception:
        logger.exception("paper_agent dev_server: background run failed for %s", paper_id)


def _list_papers(*, uploads_dir: Optional[str | Path], limit: int, offset: int) -> PaperRunListResponse:
    configure_uploads_dir(uploads_dir)
    root = papers_root()
    if not root.is_dir():
        return PaperRunListResponse(items=[], total=0)

    items = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or not (child / "manifest.json").is_file():
            continue
        try:
            items.append(summarize_manifest(child.name, uploads_dir=uploads_dir))
        except Exception as exc:
            logger.warning("paper_agent dev_server: skipping invalid run %s: %s", child.name, exc)
    items.sort(key=lambda item: item.created_at, reverse=True)
    total = len(items)
    return PaperRunListResponse(items=items[offset : offset + limit], total=total)


def create_app(*, uploads_dir: Optional[str | Path] = None, auto_run: bool | None = None) -> FastAPI:
    configure_uploads_dir(uploads_dir)
    if auto_run is None:
        auto_run = os.getenv("PATHLAB_PAPER_AGENT_DEV_AUTO_RUN") == "1"

    app = FastAPI(title="PathLab Paper Agent Dev Service", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "pathlab-paper-agent",
            "uploads": str(papers_root().parent),
            "auto_run": str(bool(auto_run)).lower(),
        }

    @app.get("/auth/me")
    async def auth_me() -> dict:
        return {
            "id": "00000000-0000-0000-0000-000000000000",
            "email": "demo@pathlab.local",
            "username": "demo",
            "is_active": True,
            "is_superuser": True,
            "is_verified": True,
            "role": "admin",
            "nickname": "Demo Admin",
        }

    @app.get("/tasks/training")
    async def list_training_tasks(
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=200),
        search: str | None = None,
        status_filter: str | None = None,
        sort_by: str | None = None,
    ) -> dict:
        del sort_by
        task = _crc_msi_task()
        tasks = [task] if _task_matches(task, search) else []
        if status_filter and status_filter != "all":
            tasks = [item for item in tasks if item.get("status") == status_filter]
        total = len(tasks)
        start = (page - 1) * page_size
        items = tasks[start : start + page_size]
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "stats": {
                "total": total,
                "running": sum(1 for item in tasks if item.get("status") == "running"),
                "completed": sum(1 for item in tasks if item.get("status") == "completed"),
                "failed": sum(1 for item in tasks if item.get("status") == "failed"),
                "cancelled": sum(1 for item in tasks if item.get("status") == "cancelled"),
            },
        }

    @app.get("/tasks/training/{task_id}")
    async def get_training_task(task_id: str) -> dict:
        task = _crc_msi_task()
        if task_id != task["task_id"]:
            raise HTTPException(status_code=404, detail=f"Training task {task_id} not found")
        return {**task, "wsi_count": 312, "wsi_ids": []}

    @app.post("/papers", response_model=PaperRunCreateResponse)
    async def create_paper(
        background_tasks: BackgroundTasks,
        body: Optional[CreatePaperRequest] = None,
    ) -> PaperRunCreateResponse:
        request = _with_crc_msi_defaults(body)
        paper_id, _paths = await create_dev_run(request, uploads_dir=uploads_dir)
        if auto_run:
            background_tasks.add_task(_run_full_pipeline_for_dev, paper_id, uploads_dir)
        return PaperRunCreateResponse(
            paper_id=paper_id,
            message=(
                "Paper run accepted; standalone dev pipeline is running in background."
                if auto_run
                else "Paper run scaffold created by standalone dev service."
            ),
        )

    @app.get("/papers", response_model=PaperRunListResponse)
    async def list_paper_runs(
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> PaperRunListResponse:
        return _list_papers(uploads_dir=uploads_dir, limit=limit, offset=offset)

    @app.get("/papers/{paper_id}", response_model=PaperRunDetail)
    async def get_paper(paper_id: str) -> PaperRunDetail:
        try:
            summary = summarize_manifest(paper_id, uploads_dir=uploads_dir)
            manifest = load_manifest(paper_id, uploads_dir=uploads_dir)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return PaperRunDetail(
            **summary.model_dump(),
            artifacts=manifest_artifacts(manifest),
            stage_log=manifest.stage_log,
        )

    @app.delete("/papers/{paper_id}")
    async def delete_paper(paper_id: str) -> dict:
        try:
            validate_paper_id(paper_id)
            paths = PaperRunPaths.for_paper(paper_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not paths.root.exists():
            raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
        shutil.rmtree(paths.root)
        return {"paper_id": paper_id, "deleted": True, "deleted_at": _utc_iso()}

    @app.post("/papers/{paper_id}/stages/{stage}:run")
    async def run_paper_stage(paper_id: str, stage: str) -> dict:
        try:
            manifest = run_stage(paper_id, stage, uploads_dir=uploads_dir)
            if PaperRunStage(stage) == PaperRunStage.collecting:
                _seed_crc_msi_fixture(PaperRunPaths.for_paper(paper_id))
                save_manifest(manifest, uploads_dir=uploads_dir)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {
            "paper_id": paper_id,
            "status": manifest.status.value,
            "current_stage": manifest.current_stage.value,
        }

    @app.post("/papers/{paper_id}/sections/{section_name}/regenerate")
    async def regenerate_paper_section(
        paper_id: str,
        section_name: str,
        body: RegenerateSectionRequest | None = None,
    ) -> dict:
        request = body or RegenerateSectionRequest()
        try:
            manifest = regenerate_section(
                paper_id,
                section_name,
                uploads_dir=uploads_dir,
                mode=request.mode,
                target_section=request.target_section,
                target_paragraph=request.target_paragraph,
                target_sentence=request.target_sentence,
                selected_text=request.selected_text,
                source_hash=request.source_hash,
                char_start=request.char_start,
                char_end=request.char_end,
                user_note=request.user_note,
                template_id=request.template_id,
            )
            summary = latest_regenerate_log_summary(paper_id, uploads_dir=uploads_dir)
        except MissingSectionDraftError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
        except UnknownSectionError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {
            "paper_id": paper_id,
            "status": manifest.status.value,
            "current_stage": manifest.current_stage.value,
            "regenerated_sections": summary.get("regenerated_sections", []),
            "refinement_log_summary": summary.get("refinement_log_summary", {}),
        }

    @app.get("/papers/{paper_id}/files")
    async def get_file_by_query(paper_id: str, path: str = Query(...)):
        return _file_response(paper_id, path)

    @app.get("/papers/{paper_id}/files/{path:path}")
    async def get_file_by_path(paper_id: str, path: str):
        return _file_response(paper_id, path)

    def _file_response(paper_id: str, rel_path: str):
        try:
            validate_paper_id(paper_id)
            paths = PaperRunPaths.for_paper(paper_id)
            if not paths.manifest.exists():
                raise HTTPException(status_code=404, detail=f"Paper {paper_id} not found")
            if not is_path_allowed_for_download(rel_path):
                raise HTTPException(status_code=403, detail="Path not in download allowlist.")
            manifest = load_manifest(paper_id, uploads_dir=uploads_dir)
            if not _is_registered_public_artifact(manifest, rel_path):
                raise HTTPException(status_code=403, detail="Artifact is not registered public.")
            target = safe_resolve(paths, rel_path)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not target.exists():
            raise HTTPException(status_code=404, detail="File not found.")
        if target.is_dir():
            raise HTTPException(status_code=400, detail="Path is a directory.")
        return FileResponse(target)

    return app
