"""Shared manuscript workflow for manual experiments and autonomous research.

Evidence is copied from authorized records, never accepted from the browser. Every
report retains its original evidence even if the experiment is subsequently refined.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import shutil
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, select, update

from backend.auth.dependencies import assert_research_access
from backend.autoresearch.engine import store
from backend.common.config import Config
from backend.database.database import safe_session
from backend.database.models import (
    AnalysisRun,
    AutoResearchSession,
    Manuscript,
    ManuscriptGeneration,
    ResearchJob,
    TrainedModel,
    TrainingTask,
    TrainingTaskWSI,
    WSISlide,
    utc_now,
)

TEMPLATES = {
    "conference": {
        "name": "Conference template",
        "sections": [
            "Abstract",
            "Introduction",
            "Methods",
            "Experiments and results",
            "Discussion",
            "Conclusion",
            "References",
        ],
    },
    "journal": {
        "name": "Journal template",
        "sections": [
            "Abstract",
            "Introduction",
            "Results",
            "Discussion",
            "References",
            "Methods",
            "Data availability",
            "Code availability",
            "Acknowledgements",
            "Funding",
            "Author contributions",
            "Competing interests",
        ],
    },
}


def clean_json(value):
    """Historical metrics may contain NaN/Inf; missing evidence remains missing."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    return value


def recommendation(evidence: dict) -> dict:
    completed = [r for r in evidence["runs"] if r["status"] == "completed"]
    datasets = {d for r in completed for d in r.get("dataset_ids", []) if d}
    # Product routing, not a journal acceptance criterion. Budget/effort is not evidence.
    template = "journal" if len(completed) >= 6 and len(datasets) >= 2 else "conference"
    return {
        "template": template,
        "completed_runs": len(completed),
        "dataset_count": len(datasets),
    }


async def research_evidence(session, summary: str | None = None, *, reviewed: bool = False) -> dict:
    runs = await store.experiments(session.session_id)
    root = Path(session.workspace_path).resolve()
    notes = {}
    for name in ["research-plan.md", "findings.md", "research-log.md"]:
        path = (root / name).resolve()
        if (
            path.is_relative_to(root)
            and path.is_file()
            and path.stat().st_size <= 100000
        ):
            notes[name] = await asyncio.to_thread(path.read_text, encoding="utf-8")
    from backend.autoresearch.engine.study import writing_evidence
    study = await writing_evidence(session) if reviewed else None
    if study:
        runs = [run for run in runs if run['run_id'] in study['run_ids']]
        notes = study['sources']
    papers = [
        paper
        for event in await store.events(session.session_id, limit=500, latest=True)
        if event.get("kind") == "literature"
        for paper in event.get("papers", [])
    ]
    return clean_json(
        {
            "source_type": "research",
            "source_id": session.session_id,
            "title": (session.recovery_metadata or {}).get('current_goal') or session.research_question,
            'study': {key: value for key, value in study.items() if key != 'sources'} if study else None,
            "summary": study['review']['conclusion'] if study else summary if summary is not None else session.final_report or "",
            "outcome": (session.recovery_metadata or {}).get("outcome", ""),
            "research_notes": notes,
            "literature": [] if study else papers[:30],
            "datasets": (session.recovery_metadata or {}).get("datasets", []),
            "figure_sources": [
                {"path": a["path"], "name": a.get("name", "")}
                for a in ([{'path':path} for path in study['figure_paths']] if study else (session.recovery_metadata or {}).get("artifacts", []))
                if str(a.get("path", "")).lower().endswith((".png", ".jpg", ".jpeg"))
            ],
            "runs": [
                {
                    "run_id": r["run_id"],
                    "name": r.get("experiment_name"),
                    "status": r["status"],
                    "dataset_ids": [r["dataset_id"]] if r.get("dataset_id") else [],
                    "config": r.get("config", {}),
                    "metrics": r.get("metrics") or {},
                }
                for r in runs
            ],
        }
    )


async def source_evidence(source_type: str, source_id: str, user, scope=None, *, for_writing: bool = False) -> dict:
    assert_research_access(user)
    async with safe_session() as db:
        if source_type == "research":
            row = await db.scalar(
                select(AutoResearchSession).where(
                    AutoResearchSession.session_id == source_id,
                )
            )
        else:
            row = await db.scalar(
                select(TrainingTask).where(TrainingTask.task_id == source_id)
            )
        if row is None:
            raise HTTPException(404, "Report source not found")
        if row.user_id != str(user.id) and not user.is_admin():
            raise HTTPException(403, "Report source access denied")
        if source_type == "research":
            if (
                scope
                and scope.workspace_id
                and (row.recovery_metadata or {}).get("workspace_id")
                != scope.workspace_id
            ):
                raise HTTPException(403, "Report source is outside this workspace")
            try:
                evidence = await research_evidence(row, reviewed=for_writing)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from None
            if not any(r["status"] == "completed" for r in evidence["runs"]):
                raise HTTPException(409, "This research has no completed results yet")
            return evidence
        if scope and scope.workspace_id:
            allowed = await db.scalar(
                select(TrainingTask.task_id).where(
                    TrainingTask.task_id == source_id,
                    scope.task_filter(TrainingTask.task_id, user),
                )
            )
            if not allowed:
                raise HTTPException(403, "Report source is outside this workspace")
        job = await db.get(ResearchJob, source_id)
        if row.status != "completed" or (job and job.kind != "experiment"):
            raise HTTPException(409, "Select a completed experiment")
        models = (
            await db.scalars(
                select(TrainedModel).where(TrainedModel.task_id == source_id)
            )
        ).all()
        dataset_ids = list(
            (
                await db.scalars(
                    select(WSISlide.dataset_id)
                    .join(TrainingTaskWSI, TrainingTaskWSI.wsi_id == WSISlide.wsi_id)
                    .where(TrainingTaskWSI.task_id == source_id)
                    .distinct()
                )
            ).all()
        )
        metrics = {
            m.model_id: {
                "train": m.train_metrics or {},
                "validation": m.val_metrics or {},
            }
            for m in models
        }
        if job and job.result.get("metrics"):
            metrics["experiment"] = job.result["metrics"]
        analyses = (
            await db.scalars(
                select(AnalysisRun)
                .where(AnalysisRun.task_id == source_id)
                .order_by(AnalysisRun.created_at.desc())
                .limit(20)
            )
        ).all()
        analysis_evidence = await asyncio.to_thread(
            read_analyses, analyses, source_id, user
        )
        for analysis in analysis_evidence:
            metrics[f"analysis.{analysis['analysis_id']}"] = analysis["metrics"]
        return clean_json(
            {
                "source_type": "experiment",
                "source_id": source_id,
                "title": row.task_name,
                "summary": row.task_description or "",
                "outcome": "completed",
                "analyses": analysis_evidence,
                "runs": [
                    {
                        "run_id": source_id,
                        "name": row.task_name,
                        "status": row.status,
                        "dataset_ids": [d for d in dataset_ids if d],
                        "config": {
                            "preprocessing": row.preprocessing_config or {},
                            "model": row.model_config or {},
                        },
                        "metrics": metrics,
                    }
                ],
            }
        )


def read_analyses(analyses, task_id: str, user) -> list[dict]:
    """Include measured analyses bound to this task, without per-patient data."""
    base = (Config.get_uploads_dir() / "logs" / "analysis").resolve()
    result = []
    for row in analyses:
        if row.user_id != str(user.id) and not user.is_admin():
            continue
        path = (base / task_id / row.analysis_id / "summary.json").resolve()
        if (
            not path.is_relative_to(base)
            or not path.is_file()
            or path.stat().st_size > 5_000_000
        ):
            continue
        try:
            summary = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(summary, dict) or summary.get("task_id") != task_id:
            continue
        result.append(
            {
                "analysis_id": row.analysis_id,
                **{
                    key: summary[key]
                    for key in [
                        "description",
                        "num_samples",
                        "task_type",
                        "bootstrap_ci",
                        "class_metrics",
                        "random_seed",
                    ]
                    if key in summary
                },
                "metrics": summary.get("metrics") or {},
                "figure_names": [
                    name
                    for name in [
                        "roc_curve.png",
                        "confusion_matrix.png",
                        "loss_curve.png",
                        "km_curve.png",
                    ]
                    if (path.parent / name).is_file()
                ],
                "chart_data": {
                    key: value
                    for key, value in (summary.get("chart_data") or {}).items()
                    if key in {"roc_curve", "confusion_matrix", "loss_curve"}
                },
            }
        )
    return result


def retarget(content: str, template: str) -> str:
    """Reorder named manuscript sections without dropping custom sections or prose."""
    chunks = ['']
    fence = None
    for line in content.splitlines(keepends=True):
        marker = re.match(r'^\s*(`{3,}|~{3,})', line)
        if marker:
            if fence is None:
                fence = marker[1]
            elif marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = None
        heading = re.match(r'^## ([^\r\n]+)', line) if not fence and not marker else None
        if heading:
            chunks.extend([heading[1], ''])
        else:
            chunks[-1] += line
    sections = {}
    from .manuscript_language import (
        canonical_heading,
        document_language,
        localize_headings,
    )
    language = document_language({'content': content})
    for index in range(1, len(chunks), 2):
        name = canonical_heading(chunks[index].strip())
        if name.lower() in {"results", "experiments and results"}:
            name = "Results" if template == "journal" else "Experiments and results"
        sections[name] = sections.get(name, "") + chunks[index + 1]
    ordered = [chunks[0].strip()] if chunks[0].strip() else []
    for name in TEMPLATES[template]["sections"]:
        if name in sections:
            ordered.append(f"## {name}\n\n{sections.pop(name).strip()}")
    ordered += [f"## {name}\n\n{text.strip()}" for name, text in sections.items()]
    return localize_headings("\n\n".join(ordered), language)


def serialize(row) -> dict:
    return {
        "report_id": row.report_id,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "user_id": row.user_id,
        "template": row.template,
        "title": row.title,
        "content": row.content,
        "evidence": row.evidence,
        "recommendation": recommendation(row.evidence),
        "status": row.status,
        "revision": row.revision,
        "updated_at": row.updated_at.isoformat() + "Z",
        "created_at": row.created_at.isoformat() + "Z",
    }


async def create(
    user_id: str,
    evidence: dict,
    template="auto",
    *,
    title="",
    content="",
    status="draft",
) -> dict:
    selected = recommendation(evidence)["template"] if template == "auto" else template
    if selected not in TEMPLATES:
        raise ValueError("Select a conference or journal template.")
    row = Manuscript(
        report_id=uuid4().hex,
        user_id=user_id,
        source_type=evidence["source_type"],
        source_id=evidence["source_id"],
        title=title.strip() or evidence["title"][:500],
        template=selected,
        content=content.strip(),
        evidence=deepcopy(evidence),
        revision=1,
        status=status,
    )
    async with safe_session() as db:
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return serialize(row)


async def owned(report_id: str, user, scope=None) -> dict:
    assert_research_access(user)
    async with safe_session() as db:
        row = await db.get(Manuscript, report_id)
        if row is None:
            raise HTTPException(404, "Report not found")
        if row.user_id != str(user.id) and not user.is_admin():
            raise HTTPException(403, "Report access denied")
        result = serialize(row)
        generation = await db.get(ManuscriptGeneration, report_id)
        if generation:
            result["generation"] = generation_summary(generation)
            result["references"] = (generation.progress or {}).get(
                "cited_references", (generation.progress or {}).get("references", [])
            )
            result["figures"] = (generation.progress or {}).get("figures", [])
    # Recheck source access on every read/edit/export; a snapshot is not an access grant.
    await source_evidence(result["source_type"], result["source_id"], user, scope)
    return result


def generation_summary(job) -> dict:
    progress = job.progress or {}
    from .manuscript_language import HEADINGS
    labels = HEADINGS.get((job.options or {}).get('language', 'en-US'), {})
    return {
        "status": job.status,
        "stage": job.stage,
        "error_code": job.error_code,
        "completed_sections": list(progress.get("sections", {})),
        "total_sections": progress.get("total_sections", 0),
        "current_section": labels.get(progress.get('current_section', ''), progress.get('current_section', '')),
        "reference_count": len(
            progress.get("cited_references", progress.get("references", []))
        ),
        "language": (job.options or {}).get("language", "en-US"),
        "autonomous": bool((job.options or {}).get("autonomous")),
    }


async def save(
    report_id: str,
    revision: int,
    *,
    title: str,
    content: str,
    template: str,
    status: str = "draft",
) -> None:
    async with safe_session() as db:
        generation = await db.get(ManuscriptGeneration, report_id, with_for_update=True)
        if generation and generation.status in {"queued", "running"}:
            raise HTTPException(
                409, "Wait for article generation to finish before editing."
            )
        current = await db.get(Manuscript, report_id)
        if current is not None and current.template != template:
            content = retarget(content, template)
        result = await db.execute(
            update(Manuscript)
            .where(
                Manuscript.report_id == report_id,
                Manuscript.revision == revision,
            )
            .values(
                title=title,
                content=content,
                template=template,
                status=status,
                revision=revision + 1,
                updated_at=utc_now(),
            )
        )
        if result.rowcount != 1:
            raise HTTPException(
                409, "Report changed in another window. Reload before saving."
            )
        await db.commit()


async def remove(report_id: str, user, scope=None) -> None:
    """Delete a settled report and its own assets under the same job lock as resume."""
    await owned(report_id, user, scope)
    changed_session = None
    async with safe_session() as db:
        generation = await db.get(ManuscriptGeneration, report_id, with_for_update=True)
        if generation and generation.status in {"queued", "running"}:
            raise HTTPException(
                409, "Wait for article generation to stop before deleting it."
            )
        report = await db.get(Manuscript, report_id, with_for_update=True)
        if report is None:
            raise HTTPException(404, "Report not found")
        if report.user_id != str(user.id) and not user.is_admin():
            raise HTTPException(403, "Report access denied")
        roots = [(Config.get_uploads_dir().resolve(), "reports")]
        if report.source_type == "research":
            session = await db.scalar(
                select(AutoResearchSession)
                .where(AutoResearchSession.session_id == report.source_id)
                .with_for_update()
            )
            if session:
                roots.append((Path(session.workspace_path).resolve(), "reports"))
                meta = deepcopy(session.recovery_metadata or {})
                for key in [
                    "manuscript_id",
                    "report_draft_id",
                    "report_generation_id",
                    "delivered_report_id",
                ]:
                    if meta.get(key) == report_id:
                        meta.pop(key)
                if (meta.get("budget_resume") or {}).get("draft_id") == report_id:
                    meta["budget_resume"]["draft_id"] = None
                prefix = f"reports/{report_id}/"
                meta["artifacts"] = [
                    a
                    for a in meta.get("artifacts", [])
                    if not a.get("path", "").startswith(prefix)
                ]
                session.recovery_metadata = meta
                changed_session = session.session_id

        def clean_files():
            if not re.fullmatch(r"[a-f0-9]{32}", report_id):
                raise ValueError("Invalid report identifier")
            paths = []
            for root, subfolder in roots:
                parent = root / subfolder
                if not parent.resolve().is_relative_to(root):
                    raise ValueError("Report directory is outside its storage root")
                paths.append(parent / report_id)
            for path in paths:
                if path.is_symlink():
                    path.unlink()
                elif path.exists():
                    shutil.rmtree(path)

        try:
            await asyncio.to_thread(clean_files)
        except (OSError, ValueError):
            raise HTTPException(
                409, "Unable to remove report files. Please retry."
            ) from None
        await db.execute(
            delete(ManuscriptGeneration).where(
                ManuscriptGeneration.report_id == report_id
            )
        )
        await db.delete(report)
        await db.commit()
    if changed_session:
        await store.update(
            changed_session, event={"kind": "report_deleted", "report_id": report_id}
        )


async def publish_document(session, report_id: str) -> dict:
    """Publish the shared LLM writer's completed article, without creating a copy."""
    from . import report_export
    from .manuscript_writer import WritingPaused

    async with safe_session() as db:
        row = await db.get(Manuscript, report_id)
        job = await db.get(ManuscriptGeneration, report_id)
        if row is None or job is None or row.source_id != session.session_id:
            raise ValueError("Research manuscript not found")
        report = serialize(row)
        report["references"] = job.progress.get(
            "cited_references", job.progress.get("references", [])
        )
        report["figures"] = job.progress.get("figures", [])
    export_input = {**report, "status": "ready"}
    docx, latex = await asyncio.to_thread(
        lambda: (report_export.word(export_input), report_export.latex(export_input))
    )
    from backend.autoresearch.engine.budget import expired

    current = await store.get(session.session_id)
    if (
        current.status not in {"running", "waiting"}
        or expired(current)
        or (current.recovery_metadata or {}).get("budget_shutdown")
        or (current.recovery_metadata or {}).get("budget_stop_requested")
    ):
        raise WritingPaused("budget")
    root = Path(session.workspace_path).resolve()
    folder = (root / "reports" / report["report_id"]).resolve()
    if not folder.is_relative_to(root):
        raise ValueError("Report directory must remain inside the research workspace")
    folder.mkdir(parents=True, exist_ok=True)

    def render():
        (folder / "report.md").write_text(
            f"# {report['title']}\n\n{report['content']}", encoding="utf-8"
        )
        (folder / "report.docx").write_bytes(docx)
        (folder / "latex.zip").write_bytes(latex)

    await asyncio.to_thread(render)
    artifacts = [
        {
            "path": str(path.relative_to(root)),
            "name": path.name,
            "kind": "report",
            "size": path.stat().st_size,
        }
        for path in sorted(folder.iterdir())
    ]
    await store.merge_metadata_items(session.session_id, "artifacts", artifacts, "path")
    await store.update(
        session.session_id,
        meta={"manuscript_id": report["report_id"], "research_phase": "writing"},
        phase="writing",
        event={"kind": "artifacts", "artifacts": artifacts},
    )
    return {
        "report_id": report["report_id"],
        "template": report["template"],
        "artifacts": artifacts,
    }


async def checkpoint_research(
    session, *, title: str, content: str, template: str = "auto"
) -> dict:
    """Keep complete sections editable without claiming that a final report exists."""
    evidence = await research_evidence(session)
    if not any(r["status"] == "completed" for r in evidence["runs"]):
        raise ValueError(
            "Save data-only progress in findings.md; no manuscript is needed."
        )
    selected = recommendation(evidence)["template"] if template == "auto" else template
    report = await create(
        session.user_id, evidence, selected, title=title, content=content
    )
    await store.update(
        session.session_id,
        meta={
            "report_draft_id": report["report_id"],
            "manuscript_id": None,
            "finish_requested": False,
        },
        event={"kind": "report_draft", "report_id": report["report_id"]},
    )
    return {
        "report_id": report["report_id"],
        "status": "draft",
        "instruction": "Draft checkpoint saved. Continue writing before publishing a final report.",
    }


async def require_research_report(session) -> None:
    from backend.autoresearch.engine.study import scientific
    meta = session.recovery_metadata or {}
    if meta.get('report_policy') == 'summary' or (meta.get('task_kind') in {'analysis', 'document'} and meta.get('report_policy') != 'manuscript'):
        return
    start_iteration = int(
        (session.recovery_metadata or {}).get("report_start_iteration", 0)
    )
    experiments = await store.experiments(session.session_id)
    if not scientific(session) and not any(
        r["status"] == "completed" and r.get("iteration", 0) > start_iteration
        for r in experiments
    ):
        return
    evidence = await research_evidence(session, reviewed=True)
    if not any(r["status"] == "completed" for r in evidence["runs"]):
        return
    report_id = (session.recovery_metadata or {}).get("manuscript_id")
    async with safe_session() as db:
        report = await db.get(Manuscript, report_id) if report_id else None
    if (
        report is None
        or report.status != "ready"
        or not same_research_evidence(report.evidence, evidence)
    ):
        raise ValueError(
            "Complete the LLM article with generate_article before finishing these experiments."
        )
    folder = Path(session.workspace_path) / "reports" / report.report_id
    if not all((folder / name).is_file() for name in ["report.docx", "latex.zip"]):
        raise ValueError(
            "Editable article exports are missing. Resume generate_article before finishing."
        )


def same_research_evidence(left, right):
    # Completion updates these display fields after publication; they do not change
    # the measured sources. All goal, protocol, method, figures and run changes do.
    return {k: v for k, v in left.items() if k not in {'summary', 'outcome'}} == {
        k: v for k, v in right.items() if k not in {'summary', 'outcome'}
    }
