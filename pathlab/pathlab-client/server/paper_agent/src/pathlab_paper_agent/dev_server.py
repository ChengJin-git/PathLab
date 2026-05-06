"""Dev-only FastAPI service for standalone paper-agent testing."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from .bootstrap import configure_uploads_dir
from .pipeline import create_dev_run, load_manifest, manifest_artifacts, run_stage, summarize_manifest
from .regenerate import MissingSectionDraftError, UnknownSectionError, latest_regenerate_log_summary, regenerate_section
from .schemas import CreatePaperRequest, PaperRunCreateResponse, PaperRunDetail, RegenerateSectionRequest
from .storage import PaperRunPaths, is_path_allowed_for_download, safe_resolve, validate_paper_id


def _is_registered_public_artifact(manifest, rel_path: str) -> bool:
    raw = manifest.artifact_index.get(rel_path)
    if not isinstance(raw, dict):
        return False
    return (
        raw.get("visibility") == "public"
        and bool(raw.get("downloadable", True))
        and raw.get("status", "ready") in {"ready", "generated", "completed"}
    )


def create_app(*, uploads_dir: Optional[str | Path] = None) -> FastAPI:
    configure_uploads_dir(uploads_dir)
    app = FastAPI(title="PathLab Paper Agent Dev Service", version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "pathlab-paper-agent"}

    @app.post("/papers", response_model=PaperRunCreateResponse)
    async def create_paper(body: Optional[CreatePaperRequest] = None) -> PaperRunCreateResponse:
        paper_id, _paths = await create_dev_run(body, uploads_dir=uploads_dir)
        return PaperRunCreateResponse(
            paper_id=paper_id,
            message="Paper run scaffold created by standalone dev service.",
        )

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
            validation_summary=None,
        )

    @app.post("/papers/{paper_id}/stages/{stage}:run")
    async def run_paper_stage(paper_id: str, stage: str) -> dict:
        try:
            manifest = run_stage(paper_id, stage, uploads_dir=uploads_dir)
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
