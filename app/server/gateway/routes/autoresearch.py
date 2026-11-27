"""Research workbench API. OpenCode execution belongs to Research Worker."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import sys
import shutil
import tempfile
import zipfile
import httpx
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from starlette.background import BackgroundTask

from backend.auth import (
    User,
    create_autoresearch_access_token,
    current_active_user,
    get_autoresearch_access_token_claims,
    get_autoresearch_header_or_access_token_claims,
)
from backend.auth.dependencies import assert_research_access
from backend.autoresearch.engine import datasets, jobs, store, tools
from backend.autoresearch.engine.builtin_skills import catalog
from backend.autoresearch.engine.effort import EFFORT_BUDGETS, effort_budget
from backend.autoresearch.engine.request import ResearchOptions
from backend.autoresearch.engine.skills import (ResearchSkill, SkillImportError, snapshot_skills,
    import_files, unpack_zip, MAX_IMPORT_BYTES, MAX_SKILLS, MAX_FILES)
from backend.autoresearch.engine.skill_imports import import_skill
from backend.autoresearch.engine.runtime import credentials, private_dir, workspace
from backend.autoresearch.engine.requirements import polish_requirements
from backend.autoresearch.engine.titles import placeholder as title_placeholder
from backend.services.text_editor import EditingError
from backend.autoresearch.engine.scheduler import queue_snapshot, session_queue
from backend.common.config import Config
from backend.common.model_config import resolve_model_config
from backend.database.database import safe_session
from backend.database.models import AutoResearchSession
from backend.services.workbench import ResourceReference

router = APIRouter(prefix="/research", tags=["research"])


def require_research_platform(language="en-US"):
    from backend.autoresearch.runtime.container_backend import backend, available
    if backend() == 'docker' and not available()[0]:
        messages = {
            'zh-CN': '请安装并启动 Docker Desktop，然后导入 PathLab 研究沙箱镜像。Mac 沙箱实验使用 CPU；内置模型训练可使用 MPS。',
            'zh-HK': '請安裝並啟動 Docker Desktop，再匯入 PathLab 研究沙箱映像。Mac 沙箱實驗使用 CPU；內置模型訓練可使用 MPS。',
            'en-US': 'Install/start Docker Desktop and load the PathLab research sandbox image. Mac sandbox experiments use CPU; built-in training can use MPS.',
        }
        raise HTTPException(503, messages.get(language, messages['en-US']))


class ImportResearchSkill(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    url: str = Field(min_length=1, max_length=2048)


class StartResearch(ResearchOptions):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=12000)
    language: Literal['en-US', 'zh-CN', 'zh-HK'] = 'en-US'
    dataset_ids: list[str] = Field(default_factory=list)
    workspace_id: str | None = None
    source_conversation_id: str | None = Field(None, max_length=255)
    chat_request_id: str | None = Field(None, min_length=8, max_length=64)
    references: list[ResourceReference] = Field(default_factory=list, max_length=16)
    task_kind: Literal['auto','analysis','experiment','document'] = 'auto'
    report_policy: Literal['auto','summary','manuscript'] = 'auto'
    research_standard: Literal['standard', 'scientific'] | None = None
    enabled_connectors: list[Literal['web_search', 'articles']] | None = None
    library_skill_id: str | None = Field(None,max_length=80)
    library_skill_ids: list[str] = Field(default_factory=list,max_length=8)


class ResearchMessage(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    references: list[ResourceReference] = Field(default_factory=list, max_length=16)


class PolishResearchGoal(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=12000)
    language: Literal["en-US", "zh-CN", "zh-HK"]
    source_conversation_id: str | None = Field(None, min_length=1, max_length=255)


class PolishedResearchGoal(BaseModel):
    question: str


class ResearchAnswer(BaseModel):
    form_id: str = Field(min_length=1, max_length=255)
    answer: dict[str, str | int | float | bool | list[str]]


class AccessTokenRequest(BaseModel):
    purpose: str = Field(pattern=r"^(events|session_download|run_download)$")
    run_id: str = ""


async def owned(session_id: str, user: User):
    assert_research_access(user)
    try:
        row = await store.get(session_id)
    except KeyError:
        raise HTTPException(404, "Research not found")
    if row.user_id != str(user.id) and not user.is_admin():
        raise HTTPException(403, "Research access denied")
    if (row.recovery_metadata or {}).get('delete_requested'):
        raise HTTPException(409, 'Research and its files are being deleted')
    return row


async def internal_session(
    session_id: str, authorization: Annotated[str | None, Header()] = None
):
    try:
        row = await store.get(session_id)
    except KeyError:
        raise HTTPException(404, "Research not found")
    supplied = (authorization or "").removeprefix("Bearer ")
    if not hmac.compare_digest(supplied, credentials(session_id)["tool_token"]):
        raise HTTPException(401, "Invalid research credential")
    import uuid

    async with safe_session() as db:
        user = await db.get(User, uuid.UUID(row.user_id))
        if user is None or not user.is_active or not user.can_use_gpu():
            raise HTTPException(403, "Research owner can no longer execute jobs")
        assert_research_access(user)
        from backend.services.workspaces import resolve_scope

        scope = await resolve_scope(
            db, user, (row.recovery_metadata or {}).get("workspace_id")
        )
        if (
            scope.execution_mode == "read_only"
            or "training" not in scope.enabled_skills
        ):
            raise HTTPException(403, "Research workspace no longer permits execution")
    return row


@router.get("/configuration")
async def configuration(user: User = Depends(current_active_user)):
    assert_research_access(user)
    try:
        model = (await resolve_model_config()).public()
        error = ""
    except ValueError as exc:
        model, error = {}, str(exc)
    return {
        "model": model,
        "error": error,
        "runtime": "opencode-v2",
        "builtin_skills": catalog(),
        "can_execute": user.can_use_gpu(),
        "effort_presets": {
            standard: {
                effort: {"max_experiments": attempts, "time_budget_seconds": seconds}
                for effort, (attempts, seconds) in presets.items()
            }
            for standard, presets in EFFORT_BUDGETS.items()
        },
        "capacity": {
            k: v for k, v in (await queue_snapshot()).items() if k != "positions"
        },
    }


@router.get("/datasets")
async def dataset_options(
    query: str = "",
    workspace_id: str | None = None,
    user: User = Depends(current_active_user),
):
    assert_research_access(user)
    return {"items": await datasets.list_datasets(user, workspace_id, query)}


@router.post("/polish-goal", response_model=PolishedResearchGoal)
async def polish_goal(body: PolishResearchGoal, user: User = Depends(current_active_user)):
    assert_research_access(user)
    context = ""
    if body.source_conversation_id:
        context = (await handoff_context(body.source_conversation_id, user))["context"]
    try:
        question = await polish_requirements(body.question, body.language, context)
    except EditingError:
        raise HTTPException(502, "Research request editing is temporarily unavailable.") from None
    return PolishedResearchGoal(question=question)


@router.post("/skills/import")
async def import_research_skill(body: ImportResearchSkill, user: User = Depends(current_active_user)):
    assert_research_access(user)
    try:
        return await import_skill(body.url, str(user.id))
    except SkillImportError as exc:
        raise HTTPException(422, str(exc)) from None
    except (ValueError, TimeoutError, OSError, httpx.HTTPError):
        raise HTTPException(422, 'skillDownloadFailed') from None


@router.post('/skills/upload')
async def upload_research_skills(request: Request, user: User = Depends(current_active_user)):
    assert_research_access(user)
    from starlette.datastructures import UploadFile
    from starlette.formparsers import MultiPartException
    received = 0
    async def bounded_receive():
        nonlocal received
        message = await request.receive()
        received += len(message.get('body', b''))
        if received > MAX_IMPORT_BYTES + 2 * 1024 * 1024:
            raise MultiPartException('skillTooLarge')
        return message
    bounded = Request(request.scope, receive=bounded_receive)
    form = await bounded.form(max_files=MAX_FILES, max_fields=1)
    files = [value for key, value in form.multi_items() if key == 'files' and isinstance(value, UploadFile)]
    try:
        if len(files) > MAX_FILES:
            raise SkillImportError('skillTooLarge')
        contents, total = {}, 0
        for file in files:
            data = await file.read(MAX_IMPORT_BYTES + 1)
            total += len(data)
            if total > MAX_IMPORT_BYTES:
                raise SkillImportError('skillTooLarge')
            name = file.filename or 'SKILL.md'
            if name in contents:
                raise SkillImportError('skillDuplicatePath')
            contents[name] = (data, data.startswith(b'#!'))
        if len(contents) == 1 and next(iter(contents)).lower().endswith(('.zip', '.skill')):
            contents = await asyncio.to_thread(unpack_zip, next(iter(contents.values()))[0])
        return await asyncio.to_thread(import_files, contents, str(user.id))
    except SkillImportError as exc:
        raise HTTPException(422, str(exc)) from None
    finally:
        await form.close()


@router.post("/sessions")
async def create_session(
    body: StartResearch,
    user: User = Depends(current_active_user),
    workspace_header: Annotated[str | None, Header(alias="X-Workspace-ID")] = None,
):
    assert_research_access(user)
    require_research_platform(body.language)
    if not user.can_use_gpu():
        raise HTTPException(403, "Research execution requires GPU capability")
    workspace_id = body.workspace_id or workspace_header
    if body.workspace_id and workspace_header and body.workspace_id != workspace_header:
        raise HTTPException(400, "Conflicting workspace scope")
    from backend.services.workspaces import resolve_scope

    handoff = None
    resolved_refs = []
    library_skills = []
    async with safe_session() as db:
        selected_library=list(dict.fromkeys([*body.library_skill_ids,*([body.library_skill_id] if body.library_skill_id else [])]))
        if selected_library:
            from backend.services.capability_library import selected_skill, research_skill
            for identity in selected_library:
                selected=await selected_skill(db,user,identity)
                if selected.builtin and not (selected.config or {}).get('package_file'):body.selected_skill=selected.entry_id
                else:library_skills.append(await research_skill(selected,user))
        if body.source_conversation_id:
            from backend.autoresearch.engine.handoff import conversation_context
            from gateway.chat.permissions import require_conversation_access

            conversation = await require_conversation_access(
                db, body.source_conversation_id, user
            )
            if workspace_id and workspace_id != conversation.workspace_id:
                raise HTTPException(
                    409, "Keep the Chat workspace when continuing in AutoResearch."
                )
            workspace_id = conversation.workspace_id
            handoff = conversation_context(conversation.messages)
        if body.chat_request_id:
            previous = await db.scalar(select(AutoResearchSession).where(AutoResearchSession.chat_request_id == body.chat_request_id))
            if previous:
                if previous.user_id != str(user.id) or previous.chat_conversation_id != body.source_conversation_id:
                    raise HTTPException(409, "Request identity belongs to another conversation")
                return store.summary(previous)
        if body.references:
            from backend.services.workbench import resolve_references
            resolved_refs = await resolve_references(db, user, workspace_id, body.references)
            body.dataset_ids = list(dict.fromkeys(body.dataset_ids + [r.get("dataset_id", r["id"]) for r in resolved_refs if r["kind"] in {"dataset", "slide"}]))
        scope = await resolve_scope(db, user, workspace_id)
        connectors = sorted(set(scope.enabled_connectors).intersection(
            scope.enabled_connectors if body.enabled_connectors is None else body.enabled_connectors))
        if (
            scope.execution_mode == "read_only"
            or "training" not in scope.enabled_skills
        ):
            raise HTTPException(403, "Research execution is disabled in this workspace")
        from backend.database.models import Dataset
        allowed = set((await db.scalars(scope.datasets(user).where(Dataset.dataset_id.in_(body.dataset_ids)))).all()) if body.dataset_ids else set()
        if set(body.dataset_ids) - allowed:
            raise HTTPException(403, "Dataset is outside the research scope")
    if body.selected_skill not in {entry["id"] for entry in catalog()}:
        raise HTTPException(422, "Unknown research skill")
    try:
        model = await resolve_model_config()
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    sid = uuid4().hex[:16]
    root = workspace(sid)
    root.mkdir(parents=True)
    max_experiments, time_budget_seconds = effort_budget(body.effort, body.research_standard)
    max_experiments = body.advanced.max_experiments or max_experiments
    time_budget_seconds = body.advanced.time_budget_seconds or time_budget_seconds
    try:
        custom_skills = await asyncio.to_thread(snapshot_skills, [*body.advanced.skills, *library_skills], root, str(user.id))
    except SkillImportError as exc:
        shutil.rmtree(root)
        raise HTTPException(422, str(exc)) from None
    async with safe_session() as db:
        from backend.autoresearch.engine.admission import check_capacity, lock_admission
        await lock_admission(db)
        # Recheck idempotency after acquiring the cross-process admission lock.
        if body.chat_request_id:
            previous = await db.scalar(select(AutoResearchSession).where(AutoResearchSession.chat_request_id == body.chat_request_id))
            if previous and previous.user_id == str(user.id) and previous.chat_conversation_id == body.source_conversation_id:
                shutil.rmtree(root)
                return store.summary(previous)
        try:
            await check_capacity(db, str(user.id))
        except HTTPException:
            shutil.rmtree(root)
            raise
        if body.source_conversation_id:
            from backend.database.models import ChatConversation, StorageTask
            from backend.services.chat_deletion import deletion_id
            conversation_row = await db.scalar(select(ChatConversation).where(ChatConversation.conversation_id == body.source_conversation_id).with_for_update())
            deleting = await db.scalar(select(StorageTask.task_id).where(StorageTask.task_id == deletion_id(body.source_conversation_id), StorageTask.status != 'completed'))
            if not conversation_row or deleting:
                shutil.rmtree(root)
                raise HTTPException(409, 'Conversation is being deleted')
        row = AutoResearchSession(
            session_id=sid,
            user_id=str(user.id),
            research_question=body.question.strip(),
            phase="ideation",
            status="queued",
            workspace_path=str(root),
            max_iterations=max_experiments,
            current_iteration=0,
            chat_conversation_id=body.source_conversation_id,
            chat_request_id=body.chat_request_id,
            recovery_metadata={
                "title": title_placeholder(body.language),
                "title_pending": True,
                "chat_title_placeholder": (
                    title_placeholder(body.language) if not body.source_conversation_id
                    else conversation_row.title if conversation_row.title in {
                        'New Conversation', 'New conversation', '新对话', '新對話', '自主探索', 'Autonomous research',
                    } else None
                ),
                "model": model.public(),
                "workspace_id": workspace_id,
                "allow_downloads": body.allow_downloads,
                "dataset_ids": body.dataset_ids,
                "effort": body.effort,
                "language": body.language,
                "custom_skills": custom_skills,
                "time_budget_seconds": time_budget_seconds,
                "datasets": [],
                "data_mounts": {},
                "research_phase": "ideation",
                "chat_handoff": handoff,
                "selected_skill": body.selected_skill,
                'task_kind': body.task_kind,
                'report_policy': body.report_policy,
                'research_standard': body.research_standard,
                'enabled_connectors': connectors,
                "pending_references": [r.model_dump() for r in body.references],
            },
        )
        db.add(row)
        if not body.source_conversation_id:
            from backend.database.models import ChatConversation, ChatMessage
            row.chat_conversation_id = 'research_' + sid
            db.add(ChatConversation(conversation_id=row.chat_conversation_id, user_id=str(user.id), title=title_placeholder(body.language), workspace_id=workspace_id))
            db.add(ChatMessage(conversation_id=row.chat_conversation_id, role='user', content=body.question,
                               extra_metadata={'references': [r.model_dump() for r in body.references], 'research_session_id': sid}))
        if body.source_conversation_id:
            from backend.database.models import ChatConversation, ChatMessage, WorkbenchFile, utc_now
            conversation_row = await db.scalar(select(ChatConversation).where(ChatConversation.conversation_id == body.source_conversation_id))
            if conversation_row:
                conversation_row.updated_at = utc_now()
            # Explicit skill submissions have a durable user turn; automatic
            # routing already persisted the original Chat turn before dispatch.
            if body.chat_request_id and body.chat_request_id.startswith('manual-'):
                db.add(ChatMessage(conversation_id=body.source_conversation_id, role='user', content=body.question,
                                   extra_metadata={'references': [r.model_dump() for r in body.references], 'research_session_id': sid}))
            for reference in body.references:
                if reference.kind == 'file':
                    upload = await db.get(WorkbenchFile, reference.id)
                    if upload and upload.user_id == str(user.id) and not upload.session_id and not upload.conversation_id:
                        upload.conversation_id = body.source_conversation_id
        try:
            await db.commit()
        except Exception as exc:
            from sqlalchemy.exc import IntegrityError
            await db.rollback()
            if isinstance(exc, IntegrityError) and body.chat_request_id:
                previous = await db.scalar(select(AutoResearchSession).where(AutoResearchSession.chat_request_id == body.chat_request_id))
                if previous and previous.user_id == str(user.id) and previous.chat_conversation_id == body.source_conversation_id:
                    shutil.rmtree(root)
                    return store.summary(previous)
            raise
    await store.update(sid, event={"kind": "state", "status": "queued"})
    row = await store.get(sid)
    return {
        **store.summary(row),
        "queue": session_queue(await queue_snapshot(), sid, row.status),
    }


@router.get("/handoff/{conversation_id}")
async def handoff_context(
    conversation_id: str, user: User = Depends(current_active_user)
):
    assert_research_access(user)
    from backend.autoresearch.engine.handoff import conversation_context
    from gateway.chat.permissions import require_conversation_access

    async with safe_session() as db:
        conversation = await require_conversation_access(db, conversation_id, user)
        return {
            **conversation_context(conversation.messages),
            "workspace_id": conversation.workspace_id,
        }


@router.get("/sessions")
async def list_sessions(user: User = Depends(current_active_user)):
    assert_research_access(user)
    snapshot = await queue_snapshot()
    async with safe_session() as db:
        stmt = select(AutoResearchSession).where(
            or_(AutoResearchSession.recovery_metadata['delete_requested'].as_boolean().is_(None), AutoResearchSession.recovery_metadata['delete_requested'].as_boolean().is_(False)),
        )
        if not user.is_admin():
            stmt = stmt.where(AutoResearchSession.user_id == str(user.id))
        rows = (
            await db.scalars(
                stmt.order_by(AutoResearchSession.created_at.desc()).limit(100)
            )
        ).all()
        import uuid

        owners = (
            await db.scalars(
                select(User).where(User.id.in_([uuid.UUID(r.user_id) for r in rows]))
            )
        ).all()
        names = {str(owner.id): owner.username for owner in owners}
        return {
            "items": [
                {
                    **store.summary(row),
                    "username": names.get(row.user_id),
                    "queue": session_queue(snapshot, row.session_id, row.status),
                }
                for row in rows
            ]
        }


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, user: User = Depends(current_active_user), compact: bool = False):
    from backend.autoresearch.engine.activity import project_event
    from backend.autoresearch.engine.metric_preview import preview_experiment, preview_job
    row = await owned(session_id, user)
    state = row.recovery_metadata or {}
    events = await store.events(session_id, limit=100 if compact else 300, latest=True)
    if not compact:
        seen = {event['seq'] for event in events}
        events = sorted([*events, *(event for event in await store.latest_job_progress(session_id)
                                    if event['seq'] not in seen)], key=lambda event: event['seq'])
    language = state.get('language', 'en-US')
    activity = await store.activity(session_id, limit=100, context=True)
    return {
        **store.summary(row),
        "queue": session_queue(await queue_snapshot(), session_id, row.status),
        "state": {
            "datasets": state.get("datasets", []),
            "artifacts": state.get("artifacts", [])[:40] if compact else state.get("artifacts", []),
            "plan": row.experiment_plan or [],
            "report": row.final_report or "",
            "time_budget_seconds": state.get("time_budget_seconds"),
            "forms": state.get("forms", []),
            "research_phase": state.get("research_phase", "ideation"),
            "workspace_id": state.get("workspace_id"),
            "continuation": state.get("continuation"),
            "report_history": [] if compact else state.get("report_history", []),
            "report_draft_id": state.get("report_draft_id"),
            "manuscript_id": state.get("manuscript_id"),
            "report_generation_id": state.get("report_generation_id"),
            "budget_shutdown": state.get("budget_shutdown"),
            "file_index": state.get('file_index'),
            'analysis_results': state.get('analysis_results', []),
        },
        "events": [project_event(event, language) for event in events],
        'activity': [project_event(event, language) for event in activity['items']],
        'activity_before': activity['next_before'],
        "jobs": [preview_job(job) for job in await store.jobs(session_id, compact=compact)],
        "experiments": [preview_experiment(run) for run in await store.experiments(session_id)],
    }


@router.get('/sessions/{session_id}/runs/{run_id}/metrics')
async def run_metrics(session_id: str, run_id: str, user: User = Depends(current_active_user)):
    await owned(session_id, user)
    run = await store.experiment(session_id, run_id)
    if run is None:
        raise HTTPException(404, 'Run not found')
    return {'run_id': run_id, 'metrics': run.get('metrics') or {}}


@router.get('/sessions/{session_id}/analysis/{analysis_id}')
async def read_analysis(session_id: str, analysis_id: str, user: User = Depends(current_active_user)):
    row = await owned(session_id, user)
    entry = next((item for item in (row.recovery_metadata or {}).get('analysis_results', []) if item['id'] == analysis_id), None)
    if entry is None:
        raise HTTPException(404, 'Analysis result not found')
    from backend.autoresearch.engine.analysis_results import read_result
    try:
        return await asyncio.to_thread(read_result, Path(row.workspace_path), entry['path'])
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from None


@router.post("/sessions/{session_id}/messages")
async def message(
    session_id: str, body: ResearchMessage, user: User = Depends(current_active_user)
):
    row = await owned(session_id, user)
    if row.status not in store.ACTIVE | {"paused", "blocked", "failed", "interrupted"}:
        raise HTTPException(409, "Resume this research before adding instructions")
    if body.references:
        from backend.autoresearch.engine.references import command_reference_context
        body.text += await command_reference_context(session_id, user, body.references)
    reference_options = {'references': [r.model_dump() for r in body.references]} if body.references else {}
    if row.status in {"blocked", "failed", "interrupted"}:
        return {
            "command_id": await store.continue_session(session_id, text=body.text, **reference_options),
            "status": "queued",
        }
    if row.status not in store.ACTIVE | {"paused"}:
        raise HTTPException(409, "Resume this research before adding instructions")
    return {
        "command_id": await store.command(session_id, "message", body.text, **reference_options),
        "status": "queued",
    }


@router.post("/sessions/{session_id}/answers")
async def answer(
    session_id: str, body: ResearchAnswer, user: User = Depends(current_active_user)
):
    row = await owned(session_id, user)
    if body.form_id not in {
        form["id"] for form in (row.recovery_metadata or {}).get("forms", [])
    }:
        raise HTTPException(404, "Pending research question not found")
    command_id = await store.command(session_id, "answer", body.model_dump_json())
    return {"command_id": command_id, "status": "queued"}


async def control(session_id: str, action: str, user: User):
    row = await owned(session_id, user)
    if action == "resume":
        if not user.can_use_gpu():
            raise HTTPException(403, "Research execution requires GPU capability")
        if row.status not in {"paused", "interrupted", "failed", "blocked"}:
            raise HTTPException(409, "Research cannot be resumed in this state")
        await store.continue_session(session_id)
        return store.summary(await store.get(session_id))
    elif row.status not in store.ACTIVE | {"paused", "blocked"}:
        raise HTTPException(409, "Research is not active")
    await store.command(session_id, action)
    return store.summary(await store.get(session_id))


@router.post("/sessions/{session_id}/pause")
async def pause(session_id: str, user: User = Depends(current_active_user)):
    return await control(session_id, "pause", user)


@router.post("/sessions/{session_id}/stop")
async def stop(session_id: str, user: User = Depends(current_active_user)):
    return await control(session_id, "stop", user)


@router.post("/sessions/{session_id}/resume")
async def resume(session_id: str, user: User = Depends(current_active_user)):
    require_research_platform()
    return await control(session_id, "resume", user)


class ContinueResearch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field("", max_length=12000)
    dataset_ids: list[str] = Field(default_factory=list, max_length=20)
    additional_experiments: int = Field(0, ge=0, le=20)
    additional_time_seconds: int = Field(0, ge=0, le=259200)
    replace_datasets: bool = False
    baseline_run_id: str | None = Field(None, min_length=1, max_length=255)
    references: list[ResourceReference] = Field(default_factory=list, max_length=16)


@router.post("/sessions/{session_id}/continue")
async def continue_research(
    session_id: str, body: ContinueResearch, user: User = Depends(current_active_user)
):
    row = await owned(session_id, user)
    require_research_platform()
    if not user.can_use_gpu():
        raise HTTPException(403, "Research execution requires GPU capability")
    if body.dataset_ids:
        from backend.services.workbench import resolve_references
        async with safe_session() as db:
            await resolve_references(db, user, (row.recovery_metadata or {}).get('workspace_id'),
                [ResourceReference(kind='dataset', id=identity) for identity in body.dataset_ids])
    try:
        if body.references:
            from backend.autoresearch.engine.references import command_reference_context
            body.text += await command_reference_context(session_id, user, body.references)
        command_id = await store.continue_session(
            session_id,
            text=body.text,
            dataset_ids=body.dataset_ids,
            additional_experiments=body.additional_experiments,
            replace_datasets=body.replace_datasets,
            baseline_run_id=body.baseline_run_id,
            additional_time_seconds=body.additional_time_seconds,
            **({'references': [r.model_dump() for r in body.references]} if body.references else {}),
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return {"command_id": command_id, "status": "queued"}


EDITABLE_STATES = {"blocked", "paused", "failed", "interrupted"}
EDITABLE_SUFFIXES = {
    ".py",
    ".r",
    ".sh",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".md",
    ".txt",
    ".csv",
}


def editable_source(root: Path, path: str) -> Path:
    file = jobs.contained(root, path)
    relative = file.relative_to(root)
    if (
        not relative.parts
        or relative.parts[0] in {"runs", "datasets", "downloads"}
        or any(part.startswith(".") for part in relative.parts)
        or file.name in {"opencode.json", "AGENTS.md"}
        or file.suffix.lower() not in EDITABLE_SUFFIXES
    ):
        raise HTTPException(
            403,
            "Only editable workspace source files can be changed; data and previous runs are read-only.",
        )
    return file


@router.get("/sessions/{session_id}/source-files")
async def source_files(session_id: str, user: User = Depends(current_active_user)):
    row = await owned(session_id, user)
    root = Path(row.workspace_path)

    def listing():
        items = []
        for directory, dirs, files in os.walk(root):
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".")
                and d not in {"runs", "datasets", "downloads"}
                and not (Path(directory) / d).is_symlink()
            ]
            for name in sorted(files):
                path = Path(directory) / name
                if (
                    path.is_symlink()
                    or not path.is_file()
                    or path.stat().st_size > 500_000
                ):
                    continue
                try:
                    editable_source(root, str(path.relative_to(root)))
                except (ValueError, HTTPException):
                    continue
                items.append(str(path.relative_to(root)))
                if len(items) >= 100:
                    return items
        return items

    return {
        "items": await asyncio.to_thread(listing),
        "editable": row.status in EDITABLE_STATES,
    }


class SourceEdit(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=500_000)
    revision: str = Field(min_length=1, max_length=64)


@router.put("/sessions/{session_id}/source-files")
async def edit_source(
    session_id: str, body: SourceEdit, user: User = Depends(current_active_user)
):
    await owned(session_id, user)
    async with safe_session() as db:
        row = await db.scalar(
            select(AutoResearchSession)
            .where(AutoResearchSession.session_id == session_id)
            .with_for_update()
        )
        if row.status not in EDITABLE_STATES:
            raise HTTPException(409, "Pause the session before editing source files.")
        try:
            file = editable_source(Path(row.workspace_path), body.path)
        except ValueError:
            raise HTTPException(403, "File is outside this workspace.")
        if not file.is_file():
            raise HTTPException(404, "Source file not found.")
        if hashlib.sha256(file.read_bytes()).hexdigest() != body.revision:
            raise HTTPException(
                409,
                "This file changed since you opened it. Reopen it before saving to preserve the latest changes.",
            )
        fd, temp = tempfile.mkstemp(dir=file.parent, prefix=".edit-")
        try:
            os.fchmod(fd, file.stat().st_mode & 0o777)
            with os.fdopen(fd, "w") as stream:
                stream.write(body.content)
            os.replace(temp, file)
        finally:
            Path(temp).unlink(missing_ok=True)
    await store.update(session_id, event={"kind": "source_edited", "path": body.path})
    return {"saved": True, "revision": hashlib.sha256(file.read_bytes()).hexdigest()}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, user: User = Depends(current_active_user)):
    row = await owned(session_id, user)
    from backend.services.chat_deletion import request_deletion
    async with safe_session() as db:
        await request_deletion(db, row.chat_conversation_id, user)
        return {'session_id': session_id, 'conversation_id': row.chat_conversation_id, 'status': 'deleted'}


@router.post("/sessions/{session_id}/access-token")
async def mint_token(
    session_id: str, body: AccessTokenRequest, user: User = Depends(current_active_user)
):
    await owned(session_id, user)
    token, expiry = create_autoresearch_access_token(
        user=user, session_id=session_id, purpose=body.purpose, run_id=body.run_id
    )
    return {"token": token, "expires_in": expiry}


def claims_user(claims: dict, session_id: str, purpose: str, run_id: str = "") -> User:
    if claims.get("typ") == "autoresearch_access":
        if (
            claims.get("sid") != session_id
            or claims.get("purpose") != purpose
            or (run_id and claims.get("rid") != run_id)
        ):
            raise HTTPException(403, "Research token scope mismatch")
    assert_research_access(claims["user"])
    return claims["user"]


@router.get("/sessions/{session_id}/events")
async def events(
    session_id: str,
    request: Request,
    after: int = 0,
    claims: dict = Depends(get_autoresearch_access_token_claims),
):
    from backend.autoresearch.engine.activity import project_event

    await owned(session_id, claims_user(claims, session_id, "events"))
    try:
        cursor = max(0, after, int(request.headers.get("last-event-id", "0") or 0))
    except ValueError:
        raise HTTPException(422, "Invalid event cursor")

    async def stream():
        nonlocal cursor
        while not await request.is_disconnected():
            # A connected stream must stop after token expiry or role revocation,
            # rather than retaining the permissions from its opening request.
            try:
                current_claims = await get_autoresearch_access_token_claims(
                    token=request.query_params.get("token")
                )
                current = await owned(session_id, claims_user(current_claims, session_id, "events"))
            except HTTPException:
                return
            batch = await store.events(session_id, cursor)
            for event in batch:
                cursor = event["seq"]
                public = project_event(event, (current.recovery_metadata or {}).get('language', 'en-US'))
                yield f"id: {cursor}\ndata: {json.dumps(public, ensure_ascii=False)}\n\n"
            if len(batch) == 500:
                continue
            row = await store.get(session_id)
            yield f"data: {json.dumps({'kind': 'heartbeat', 'status': row.status})}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Referrer-Policy": "no-referrer",
        },
    )


@router.get("/sessions/{session_id}/files")
async def read_file(
    session_id: str,
    path: str,
    download: bool = False,
    user: User = Depends(current_active_user),
):
    row = await owned(session_id, user)
    try:
        file = jobs.contained(Path(row.workspace_path), path)
    except ValueError:
        raise HTTPException(403, "Artifact is outside this workspace")
    if not file.is_file() or file.name == "opencode.json" or ".opencode" in file.parts:
        raise HTTPException(404, "Artifact not found")
    if download:
        return FileResponse(file, filename=file.name)
    if file.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        from backend.services.file_preview import MEDIA_LIMIT
        if file.stat().st_size > MEDIA_LIMIT:
            raise HTTPException(413, 'Download this image to inspect it')
        return FileResponse(file)
    if file.stat().st_size > 2_000_000:
        raise HTTPException(413, "Download this file to inspect it")
    data = file.read_bytes()
    return {
        "path": path,
        "content": data.decode(errors="replace"),
        "revision": hashlib.sha256(data).hexdigest(),
    }


async def archive(session_id: str, run_id: str, user: User):
    row = await owned(session_id, user)
    root = Path(row.workspace_path)
    if run_id and (Path(run_id).name != run_id or run_id in {".", ".."}):
        raise HTTPException(422, "Invalid run ID")
    source = jobs.contained(root, f"runs/{run_id}") if run_id else root
    if not source.is_dir():
        raise HTTPException(404, "Artifacts not found")
    fd, name = tempfile.mkstemp(suffix=".zip", dir=Config.get_autoresearch_dir())
    os.close(fd)

    def build():
        with zipfile.ZipFile(name, "w", zipfile.ZIP_DEFLATED) as z:
            for file in source.rglob("*"):
                if (
                    file.is_file()
                    and not file.is_symlink()
                    and file.name != "opencode.json"
                    and not any(
                        p in {".git", ".opencode"}
                        for p in file.relative_to(source).parts
                    )
                ):
                    z.write(file, file.relative_to(source))
            # Imported skill code/resources are part of reproducibility. Include
            # these session-owned trees, but not OpenCode credentials/config/cache.
            packages = root / '.opencode/packages'
            if packages.is_dir():
                for file in packages.rglob('*'):
                    if file.is_file() and not file.is_symlink():
                        z.write(file, file.relative_to(root))

    await asyncio.to_thread(build)
    return FileResponse(
        name,
        filename=f"research-{session_id}{'-' + run_id if run_id else ''}.zip",
        background=BackgroundTask(Path(name).unlink),
    )


@router.get("/sessions/{session_id}/download")
async def download_session(
    session_id: str,
    claims: dict = Depends(get_autoresearch_header_or_access_token_claims),
):
    return await archive(
        session_id, "", claims_user(claims, session_id, "session_download")
    )


@router.get("/sessions/{session_id}/runs/{run_id}/download")
async def download_run(
    session_id: str,
    run_id: str,
    claims: dict = Depends(get_autoresearch_header_or_access_token_claims),
):
    return await archive(
        session_id, run_id, claims_user(claims, session_id, "run_download", run_id)
    )


@router.get("/internal/{session_id}/tools")
async def tool_catalog(session_id: str, _session=Depends(internal_session)):
    return {"tools": tools.TOOLS}


@router.post("/internal/{session_id}/call")
async def tool_call(session_id: str, body: dict, _session=Depends(internal_session)):
    try:
        result = await tools.call(session_id, body["name"], body.get("arguments", {}))
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, default=str),
                }
            ]
        }
    except Exception as exc:
        return {"isError": True, "content": [{"type": "text", "text": str(exc)}]}
