"""Research MCP contracts and adapters to existing PathLab services."""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import asdict
from pathlib import Path

from jsonschema import validate

from backend.auth.models import User
from backend.common.config import Config
from backend.common.gpu_resources import GpuWorkload
from backend.database.database import safe_session
from backend.services.research_prediction import PredictionSpec

from . import datasets, jobs, store
from .acquisition_contract import AcquisitionRecord
from .activity import PUBLIC_ACTIONS
from .recovery import REASONS


def tool(name: str, description: str, properties: dict, required=()) -> dict:
    # Inline nested Pydantic definitions: their $refs otherwise point at the
    # enclosing MCP schema, not the nested record/resources object.
    def inline(schema, definitions=None):
        if isinstance(schema, list):
            return [inline(value, definitions) for value in schema]
        if not isinstance(schema, dict):
            return schema
        definitions = schema.get("$defs", definitions or {})
        if "$ref" in schema:
            return inline(definitions[schema["$ref"].split("/")[-1]], definitions)
        return {
            key: inline(value, definitions)
            for key, value in schema.items()
            if key != "$defs"
        }

    properties = {key: inline(value) for key, value in properties.items()}
    if name in PUBLIC_ACTIONS:
        properties["activity"] = {
            "type": "string", "minLength": 1, "maxLength": 120,
            "description": "Brief user-facing description of this action in the session output language, e.g. 核查公开数据是否包含临床终点. Describe the scientific work, not tools, internal steps, paths or reasoning. Keep search query in the best language for retrieval; activity is separate. Use neutral wording, not a claim of success.",
        }
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": list(required),
            "additionalProperties": False,
        },
    }


STRING = {"type": "string"}
TOOLS = [
    tool(
        "get_research_context",
        "Read the original request, subsequent command instructions, agent-authored working goal, remaining budget, jobs, protocol and research decisions. A working-goal summary does not create user requirements. Use on start, after steering/restart and before waiting, training or requesting resources.",
        {},
        [],
    ),
    tool(
        "record_research_decision",
        "Record measured evidence from workspace JSON: id, direction_id, action=keep|discard|repair|pivot, assessment=supported|contradicted|inconclusive|invalid, scope=candidate|direction, next_operation=draft|improve|debug|scale|replicate|analyze|finish, run_ids, observation, interpretation, next_action, evidence_files. Failed execution is invalid, not a negative finding. Direction conclusions need measured target-scale evidence. Execute the next operation within budget.",
        {"path": STRING},
        ["path"],
    ),
    tool(
        "list_connectors",
        "List enabled personal connectors. Definitions do not grant access; each call rechecks the owner and credentials.",
        {},
        [],
    ),
    tool(
        "connector_tools",
        "Load the tool catalog for one enabled connected personal MCP service.",
        {"id": STRING},
        ["id"],
    ),
    tool(
        "connector_call",
        "Call a verified tool from an enabled personal connector, using this account credentials. Do not infer success without its result.",
        {"id": STRING, "tool": STRING, "arguments": {"type": "object"}},
        ["id", "tool", "arguments"],
    ),
    tool(
        "set_task_scope",
        "Record your working interpretation of the user's current goal; this does not replace original instructions or turn experimental choices into user requirements. research_standard=scientific for original methodological/discovery research; standard for analysis, reproduction or document work. Scientific research needs a protocol, executed closest baselines and evidence review before final writing. Scope changes do not increase budget. Analysis means existing-data computation; experiment means new training/method trials. Infer semantics in context. A scientific study stays scientific while you work on sub-steps (data screening, scripts, analysis): change task_kind and current_goal, not research_standard. Lowering it to standard needs the user's own words asking for that, quoted in user_request.",
        {
            "task_kind": {
                "type": "string",
                "enum": ["analysis", "experiment", "document"],
            },
            "report_policy": {
                "type": "string",
                "enum": ["summary", "manuscript", "auto"],
            },
            "research_standard": {"type": "string", "enum": ["standard", "scientific"]},
            "current_goal": {"type": "string", "minLength": 1, "maxLength": 12000},
            "user_request": {"type": "string", "maxLength": 2000},
        },
        ["task_kind", "report_policy", "research_standard", "current_goal"],
    ),
    tool(
        "record_study_protocol",
        "Record a workspace JSON study protocol: at least three paper-level pitches as directions, verified full data sizes, the closest published baseline on full data with its published reference result, a structured evaluation with minimum_gain (the publication bar) no smaller than the metric's resolution, stages and steps. Validation steps must use the full declared data, and method and closest-baseline validation steps need at least 3 independent repeats. Changing selected_direction or budget alone preserves unchanged evidence. Read get_study_schema for exact fields. Plans never grant extra budget.",
        {"path": STRING},
        ["path"],
    ),
    tool(
        "record_replication_group",
        "Link completed repeats of the same comparison when their candidate IDs differ. Read get_study_schema; supply JSON id, step_id, run_ids, rationale and evidence_files demonstrating the same method/configuration apart from independent repetition or recovery. Appends immutable links without changing historical runs. Every run must meet the per-run sample target and current comparison fingerprint; replicate_ids are deduplicated, sample counts are never summed.",
        {"path": STRING},
        ["path"],
    ),
    tool(
        "get_study_schema",
        "Read the exact JSON schemas for a scientific protocol, decision, replication group, experiment design and measured study-result.json. Use when creating or revising these records; no model training or extra approval is required.",
        {}, [],
    ),
    tool(
        "record_study_review",
        "Record a workspace JSON evidence review: decision=iterate|pivot|write|blocked, rationale, goal_met, conclusion, unresolved, completed_steps (step ID to completed run IDs), evidence_files, figure_paths, reviewer. Returns publication_gain, the measured full-scale gain of the selected pitch over the strongest closest baseline across independent repeats. write requires completed required steps, at least 3 repeats per arm, and a gain of at least minimum_gain that also exceeds twice its standard error.",
        {"path": STRING},
        ["path"],
    ),
    tool(
        "publish_analysis",
        "Publish measured analysis results from an existing JSON file using pathlab-analysis-v1. The workbench renders arbitrary metric names, tables, figures, and reusable chart_data (confusion_matrix, roc_curve, km_curve, loss_curve). Include actual executed code_path and tasks: [{id,title,task_type,metric_keys,chart_keys}] to identify classification, survival, segmentation or custom subtasks and their recorded metric/chart keys, especially for multi-task analyses. This is not an experiment and requires no manuscript. Read the analysis contract in the research skill.",
        {"path": STRING},
        ["path"],
    ),
    tool(
        "search_web",
        "Search the web for public datasets, code repositories and research resources using PathLab's configured search connector.",
        {"query": STRING},
        ["query"],
    ),
    tool(
        "search_datasets",
        "Search authorized Data Repo and public dataset catalog. Prefer existing data.",
        {"query": STRING},
    ),
    tool(
        "prepare_dataset",
        "Create a manifest with real labels, splits, source paths and existing features.",
        {"dataset_id": STRING},
        ["dataset_id"],
    ),
    tool(
        "acquire_dataset",
        "Download and register a dataset with full source metadata. Supply verified organs, license, source URL, access, task type and aggregation level. For a Hugging Face repository that holds more than the study needs (feature hubs with many cohorts or encoders), set download.include to the needed paths; large repositories are refused without it and the error lists the layout. Downloads without whole-slide images (features, tables) are mounted read-only for direct use instead of registered. Public sources default to public Data Repo visibility; an explicit private choice is respected. Unknown metadata is reported, never silently omitted. Returns a job ID.",
        {"record": AcquisitionRecord.model_json_schema()},
        ["record"],
    ),
    tool(
        "search_papers",
        "Search local and online literature (OpenAlex, EuropePMC, Semantic Scholar, PubMed).",
        {"query": STRING},
        ["query"],
    ),
    tool(
        "read_paper",
        "Retrieve an article via the shared CPU reader. Supports original PDF URLs, landing pages and accessible HTML. action=download saves original PDF without parsing; read_download does both. Returns actual scope (PDF, webpage or abstract); never treat an abstract as full text.",
        {
            "paper_id": STRING,
            "url": STRING,
            "action": {"type": "string", "enum": ["read", "download", "read_download"]},
            "query": STRING,
        },
        ["paper_id", "url"],
    ),
    tool(
        "find_baselines",
        "Retrieve known baselines from PathLab literature.",
        {"query": STRING},
        ["query"],
    ),
    tool(
        "search_passages",
        "Search the retained local sparse/dense literature corpus.",
        {"query": STRING},
        ["query"],
    ),
    tool(
        "find_sota",
        "Look up published benchmark evidence using the retained SOTA cache and providers.",
        {"dataset": STRING, "task_type": STRING, "metric": STRING},
        ["dataset", "task_type", "metric"],
    ),
    tool(
        "submit_experiment",
        "Snapshot code and enqueue a model-training or method-comparison experiment. For metrics-only calculations, data preparation or reports use submit_computation. Write metrics.json/progress.json to OUTPUT_DIR. End your turn while waiting.",
        {
            "name": STRING,
            "command": {"type": "array", "items": STRING},
            "device": {"type": "string", "enum": ["gpu", "cpu"], "default": "gpu"},
            "resources": GpuWorkload.model_json_schema(),
            "timeout": {"type": "integer", "minimum": 10, "maximum": 259200},
            "dataset_id": STRING,
            "config": {"type": "object"},
        },
        ["name", "command"],
    ),
    tool(
        "install_dependencies",
        "Install missing Python packages in this session's sandbox .venv and verify imports. Use after ModuleNotFoundError/optional dependency errors instead of dropping requested functionality. Does not modify the host/shared image or consume experiment attempts. Python jobs automatically use this environment.",
        {
            "packages": {
                "type": "array",
                "items": STRING,
                "minItems": 1,
                "maxItems": 10,
            },
            "imports": {
                "type": "array",
                "items": STRING,
                "minItems": 1,
                "maxItems": 10,
            },
        },
        ["packages", "imports"],
    ),
    tool(
        "submit_computation",
        "Run background metrics-only calculations, data preparation, inspection or report generation. Does not create an experiment or consume experiment attempts. CWD is a frozen source snapshot; use PATHLAB_WORKSPACE for existing run inputs. Only OUTPUT_DIR is writable. Copy completed summaries into findings.md from the agent afterwards. End your turn while waiting.",
        {
            "name": STRING,
            "command": {"type": "array", "items": STRING},
            "device": {"type": "string", "enum": ["gpu", "cpu"], "default": "cpu"},
            "resources": GpuWorkload.model_json_schema(),
            "timeout": {"type": "integer", "minimum": 10, "maximum": 259200},
            "dataset_id": STRING,
            "config": {"type": "object"},
        },
        ["name", "command"],
    ),
    tool(
        "get_job",
        "Read job status, real experiment metrics and recent log output.",
        {"job_id": STRING},
        ["job_id"],
    ),
    tool(
        "cancel_job",
        "Cancel one job belonging to this research.",
        {"job_id": STRING},
        ["job_id"],
    ),
    tool(
        "update_plan",
        "Publish a concise dynamic research plan to the workbench.",
        {
            "phase": {
                "type": "string",
                "enum": ["ideation", "planning", "experiment", "writing"],
            },
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": STRING,
                        "id": STRING,
                        "phase": {
                            "type": "string",
                            "enum": ["ideation", "planning", "experiment", "writing"],
                        },
                        "summary": STRING,
                        "children": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "title": STRING,
                                    "status": {
                                        "type": "string",
                                        "enum": [
                                            "pending",
                                            "running",
                                            "completed",
                                            "failed",
                                        ],
                                    },
                                },
                                "required": ["title", "status"],
                            },
                        },
                        "status": {
                            "type": "string",
                            "enum": ["pending", "running", "completed", "failed"],
                        },
                    },
                    "required": ["title", "status"],
                },
            },
        },
        ["steps"],
    ),
    tool(
        "register_artifact",
        "Register an existing workspace file as a research deliverable.",
        {"path": STRING, "name": STRING, "kind": STRING},
        ["path"],
    ),
    tool(
        "register_model",
        "Register a completed experiment's model in PathLab's model catalog.",
        {
            "run_id": STRING,
            "path": STRING,
            "dataset_id": STRING,
            "name": STRING,
            "feature_extractor": STRING,
            "aggregator": STRING,
            "config_path": STRING,
            "prediction": PredictionSpec.model_json_schema(),
            "adapter_dir": STRING,
        },
        ["run_id", "path", "dataset_id", "name", "aggregator"],
    ),
    tool(
        "register_features",
        "Register extracted UUID-named feature files. For viewer retrieval provide coordinates_dir with matching UUID_coords.h5 files and an explicit feature_contract (model_id, model_revision, embedding_space, dimensions, preprocessing, optional text_encoder). Never infer text alignment from a model name or feature dimensions. Missing viewer features should be prepared through an agreed analysis plan.",
        {
            "dataset_id": STRING,
            "features_dir": STRING,
            "extractor": STRING,
            "coordinates_dir": STRING,
            "feature_contract": {
                "type": "object",
                "properties": {
                    "model_id": STRING,
                    "model_revision": STRING,
                    "embedding_space": STRING,
                    "dimensions": {"type": "integer"},
                    "preprocessing": STRING,
                    "text_encoder": {
                        "type": ["object", "null"],
                        "properties": {
                            "provider": STRING,
                            "checkpoint": STRING,
                            "revision": STRING,
                            "architecture": STRING,
                            "tokenizer": STRING,
                            "aligned_space": STRING,
                            "image_projection": {
                                "type": "string",
                                "enum": ["identity", "provider"],
                            },
                        },
                    },
                },
                "required": [
                    "model_id",
                    "model_revision",
                    "embedding_space",
                    "dimensions",
                    "preprocessing",
                ],
            },
        },
        ["dataset_id", "features_dir", "extractor"],
    ),
    tool(
        "request_help",
        "Last resort: pause only for a verified external dependency or exhausted evidence-based repairs. Fix ordinary code, paths, imports, tool arguments, memory settings and transient failures yourself, then rerun and verify. Continue independent useful work first. Supply actual attempts/results and why only user action can unblock the task; never ask permission to repair code. Old failed jobs are not current blockers after continuation. End your turn only when saved=true.",
        {
            "reason": {"type": "string", "enum": REASONS},
            "summary": STRING,
            "blocker": {"type": "string", "enum": ["external_dependency", "repair_exhausted"]},
            "attempts": {
                "type": "array", "minItems": 1, "maxItems": 6,
                "description": "Actual diagnostics and repairs with observed verification results, not plans or repeated requests. Exhausted repairs require at least two distinct approaches. For external access/data/budget decisions, record the check establishing the dependency; do not attempt unauthorized work.",
                "items": {"type": "object", "additionalProperties": False,
                    "properties": {"action": {"type": "string", "minLength": 1, "maxLength": 1000},
                                   "result": {"type": "string", "minLength": 1, "maxLength": 1500}},
                    "required": ["action", "result"]},
            },
            "why_user": {"type": "string", "minLength": 1, "maxLength": 2000,
                "description": "What specific input/access/decision or unavailable capability requires intervention, and why no useful authorized next action remains. Code the agent can edit is not a user dependency."},
            "alternatives": {"type": "array", "maxItems": 8,
                "description": "For scientific missing_data/data_access/needs_input blockers, assess every current research direction and state why it cannot advance the user's goal with available inputs. Optional for other tasks/blockers.",
                "items": {"type": "object", "additionalProperties": False,
                    "properties": {"direction_id": STRING, "reason": {"type": "string", "minLength": 1, "maxLength": 1500}},
                    "required": ["direction_id", "reason"]}},
            "job_ids": {"type": "array", "items": STRING, "maxItems": 6, "uniqueItems": True,
                "description": "Current failed job IDs supporting job-related code/service blockers. Failures before the latest continuation must be rechecked, not reused as proof."},
            "next_steps": {
                "type": "array",
                "items": STRING,
                "minItems": 1,
                "maxItems": 5,
            },
        },
        ["reason", "summary", "next_steps", "blocker", "attempts", "why_user"],
    ),
    tool(
        "save_report_draft",
        "Checkpoint completed manuscript sections during writing or budget shutdown. Saves an editable INCOMPLETE draft, not final Word/LaTeX artifacts. Call regularly after each section. Preserve unknowns; describe remaining work in findings.md.",
        {
            "title": {"type": "string", "minLength": 1, "maxLength": 500},
            "content": {"type": "string", "minLength": 1, "maxLength": 200000},
            "template": {
                "type": "string",
                "enum": ["auto", "conference", "journal"],
                "default": "auto",
            },
        },
        ["title", "content"],
    ),
    tool(
        "generate_article",
        "Start or resume the scientific article writer when a manuscript is in scope. It retrieves verified citations and writes an editable article. Pure analysis and document-only tasks do not require this tool. End your turn; PathLab wakes you when writing finishes.",
        {
            "instruction": {"type": "string", "maxLength": 8000},
            "language": {
                "type": "string",
                "enum": ["en-US", "zh-CN", "zh-HK"],
                "description": "Defaults to the session output language; override only when requested.",
            },
            "template": {
                "type": "string",
                "enum": ["auto", "conference", "journal"],
                "default": "auto",
            },
        },
    ),
    tool(
        "search_verified_citations",
        "Retrieve real citation metadata and abstracts from Europe PMC/PubMed and Crossref, optionally Google Scholar via a configured SerpApi key. Results include DOI/PMID, source URL and verification timestamp. Never invent references.",
        {"query": STRING},
        ["query"],
    ),
    tool(
        "finish_research",
        "Complete the user's actual task after jobs end. Downloads and metric-only tasks need no training. Report findings honestly; use request_help when waiting for user input or budget. A scientific task finishes completed after a write review. partial/no_result only when the user asked to stop (quote them in user_stop); when pitches run out, change the frame (data, endpoint, evaluation) within the user's question; request_help(reason='direction') only after two frames fail.",
        {
            "summary": STRING,
            "outcome": {
                "type": "string",
                "enum": ["completed", "partial", "no_result"],
            },
            "user_stop": {
                "type": "string", "maxLength": 2000,
                "description": "The user's own words asking to stop or wrap up, quoted verbatim from recent_instructions.",
            },
        },
        ["summary"],
    ),
]


def literature_service():
    from ..literature.embeddings import EmbeddingIndex
    from ..literature.hybrid_retriever import HybridLiteratureRetriever
    from ..literature.online_clients import (
        EuropePMCClient,
        OpenAlexClient,
        PubMedClient,
        SemanticScholarClient,
    )
    from ..literature.paper_cache import PaperCache
    from ..literature.pwc_client import PapersWithCodeClient
    from ..literature.retriever import LiteratureRetriever
    from ..literature.seed import seed_literature
    from ..literature.service import LiteratureService
    from ..literature.sota_cache import SotaCache
    from ..literature.sota_lookup import SotaLookup
    from ..literature.sparse_index import SparseChunkIndex
    from ..literature.store import LiteratureStore
    from ..runtime.network_policy import NetworkPolicy

    base = Config.get_autoresearch_dir() / "literature"
    index = LiteratureStore(base)
    if not index.list_papers():
        seed_literature(index)
    retriever = LiteratureRetriever(
        index,
        api_clients=[
            OpenAlexClient(),
            EuropePMCClient(),
            SemanticScholarClient(),
            PubMedClient(),
        ],
        paper_cache=PaperCache(base / "paper-cache.json"),
    )
    sparse = SparseChunkIndex(base / "corpus/sparse/fts.db")
    dense = EmbeddingIndex(
        base / "corpus/dense",
        model_name=os.getenv(
            "AUTORESEARCH_RAG_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-8B"
        ),
        base_url=os.getenv("AUTORESEARCH_RAG_EMBEDDING_BASE_URL", ""),
        api_key=os.getenv("AUTORESEARCH_RAG_EMBEDDING_API_KEY", ""),
    )
    passages = HybridLiteratureRetriever(
        sparse,
        dense,
        policy=NetworkPolicy(
            stage="auto",
            allow_rag_dense=bool(os.getenv("AUTORESEARCH_RAG_EMBEDDING_BASE_URL")),
        ),
    )
    sota = SotaLookup(
        index,
        SotaCache(base / "sota-cache.json"),
        pwc_client=PapersWithCodeClient(),
        online_client=OpenAlexClient(),
    )
    return LiteratureService(
        literature_retriever=retriever, passage_retriever=passages, sota_lookup=sota
    )


async def user_asked(session_id, quote) -> bool:
    """Whether quote appears verbatim in the user's own recent instructions."""
    quote = " ".join((quote or "").split())
    instructions = await store.recent_instructions(session_id, limit=50)
    return len(quote) >= 4 and any(quote in " ".join((item.get("text") or "").split()) for item in instructions)


async def call(session_id: str, name: str, arguments: dict):
    if name not in {t["name"] for t in TOOLS}:
        raise ValueError("Unknown research tool")
    validate(arguments, next(t["inputSchema"] for t in TOOLS if t["name"] == name))
    # Display metadata is consumed by the event projector, never service adapters.
    arguments = {key: value for key, value in arguments.items() if key != "activity"}
    session = await store.get(session_id)
    if (session.recovery_metadata or {}).get("delete_requested"):
        raise ValueError("Research was deleted; no further actions are accepted")
    if session.status not in {"running", "waiting"}:
        raise ValueError("Research is paused or stopped")
    connector = {
        "search_web": "web_search",
        "search_papers": "web_search",
        "find_baselines": "web_search",
        "find_sota": "web_search",
        "search_verified_citations": "web_search",
        "read_paper": "articles",
    }.get(name)
    if connector:
        from .connector_scope import require_connector

        await require_connector(session, connector)
    if name in {"list_connectors", "connector_tools", "connector_call"}:
        from backend.services.capability_library import installed_entries
        from backend.services.personal_connectors import call as connector_call
        from backend.services.personal_connectors import catalog

        async with safe_session() as db:
            user = await db.get(User, uuid.UUID(session.user_id))
            if name == "list_connectors":
                return [
                    {
                        "id": row.entry_id,
                        "name": row.name,
                        "description": row.description,
                    }
                    for row, installed in await installed_entries(db, user, "connector")
                    if not row.builtin
                    and installed
                    and installed.connected_revision == row.revision
                ]
            if name == "connector_tools":
                row, installed = await catalog(db, user, arguments["id"])
                return {"id": row.entry_id, "tools": installed.tool_catalog}
            return await connector_call(
                db, user, arguments["id"], arguments["tool"], arguments["arguments"]
            )
    if name == "set_task_scope":
        if ((session.recovery_metadata or {}).get("research_standard") == "scientific"
                and arguments["research_standard"] != "scientific"
                and not await user_asked(session_id, arguments.get("user_request"))):
            raise ValueError(
                "This is a scientific study: keep research_standard=scientific for every sub-step. Set task_kind "
                "(analysis/document/experiment) and current_goal for the step instead. Only the user can lower the "
                "standard: quote their words asking for it in user_request.")
        meta = {
            key: arguments[key]
            for key in [
                "task_kind",
                "report_policy",
                "research_standard",
                "current_goal",
            ]
        }
        if any(
            (session.recovery_metadata or {}).get(key) != meta[key]
            for key in ["research_standard", "current_goal"]
        ) and (session.recovery_metadata or {}).get('study'):
            meta['study'] = {**session.recovery_metadata['study'], 'review': None}
        await store.update(session_id, meta=meta, event={"kind": "scope", **arguments})
        from .harness import context

        return {
            "updated": True,
            **arguments,
            "context": await context(await store.get(session_id)),
        }
    if name == "get_research_context":
        from .harness import context

        return await context(session)
    if name == "record_research_decision":
        from .study import record_decision

        return await record_decision(session, arguments["path"])
    if name == 'get_study_schema':
        from .study import ResearchDecision, StudyProtocol, ReplicationGroup
        from .study_contract import ExperimentDesign, StudyMeasurement
        return {key: model.model_json_schema() for key, model in {
            'protocol': StudyProtocol, 'decision': ResearchDecision,
            'experiment_design': ExperimentDesign, 'study_result': StudyMeasurement,
            'replication_group': ReplicationGroup,
        }.items()}
    if name == 'record_replication_group':
        from .study import record_replication_group
        return await record_replication_group(session, arguments['path'])
    if name in {"record_study_protocol", "record_study_review"}:
        from .study import record_protocol, record_review

        return await (
            record_protocol if name == "record_study_protocol" else record_review
        )(session, arguments["path"])
    if name == "publish_analysis":
        from .analysis_results import publish

        return await publish(session, arguments["path"])
    root = Path(session.workspace_path)
    from .budget import expired

    budget_reached = (
        expired(session)
        or (session.recovery_metadata or {}).get("budget_shutdown")
        or (session.recovery_metadata or {}).get("budget_stop_requested")
    )
    if budget_reached and name in {
        "generate_article",
        "finish_research",
        "submit_experiment",
        "submit_computation",
        "acquire_dataset",
        "install_dependencies",
    }:
        raise ValueError(
            "Budget reached. Save complete sections with save_report_draft and request_help(reason='budget'); resume this session with added budget. Do not publish an unfinished report."
        )
    if name == "save_report_draft":
        from backend.services.manuscripts import checkpoint_research

        return await checkpoint_research(session, **arguments)
    if name == "install_dependencies":
        from .dependencies import install

        return await install(
            root,
            (session.recovery_metadata or {}).get("data_mounts", {}),
            arguments["packages"],
            arguments["imports"],
        )
    if name == "search_verified_citations":
        from backend.services.citations import search_verified

        return await search_verified(arguments["query"])
    if name == "search_web":
        from backend.services.web_search import execute_exa_search

        key = Config.get_global_settings().get("exa_api_key", "")
        if not key:
            return {
                "status": "unconfigured",
                "message": "Configure the search connector in Settings, or use search_papers and the public dataset catalog.",
            }
        return await execute_exa_search(arguments["query"], key, num_results=6)
    if name == "search_datasets":
        async with safe_session() as db:
            user = await db.get(User, uuid.UUID(session.user_id))
        query = arguments.get("query", "")
        return {
            "local": await datasets.list_datasets(
                user, (session.recovery_metadata or {}).get("workspace_id"), query
            ),
            "public": datasets.public_datasets(query),
        }
    if name == "prepare_dataset":
        return await datasets.prepare_dataset(session_id, arguments["dataset_id"])
    if name == "acquire_dataset":
        return await jobs.submit(session_id, "download", arguments)
    if name in {"search_papers", "find_baselines"}:

        def search():
            service = literature_service()
            result = (
                service.find_papers(arguments["query"], top_k=8)
                if name == "search_papers"
                else service.find_baselines(query=arguments["query"])
            )
            return [asdict(item) for item in result]

        result = await asyncio.to_thread(search)
        await store.update(
            session_id,
            event={"kind": "literature", "query": arguments["query"], "papers": result},
        )
        return result
    if name == "search_passages":
        result = await asyncio.to_thread(
            lambda: literature_service().find_passages(arguments["query"])
        )
        return [asdict(item) for item in result]
    if name == "find_sota":
        result = await asyncio.to_thread(
            lambda: literature_service().find_sota(**arguments)
        )
        return asdict(result) if result is not None else {"status": "no_evidence"}
    if name == "read_paper":
        from backend.services.articles.document import select_article_context
        from backend.services.articles.reader import process_pdf_url

        result = await process_pdf_url(
            arguments["url"],
            arguments["paper_id"],
            action=arguments.get("action", "read"),
        )
        if result.get("download_path"):
            import hashlib
            import shutil

            target = (
                root
                / "articles"
                / (
                    "paper-"
                    + hashlib.sha256(arguments["url"].encode()).hexdigest()[:16]
                    + ".pdf"
                )
            )
            target.parent.mkdir(exist_ok=True)
            await asyncio.to_thread(
                shutil.copyfile, result.pop("download_path"), target
            )
            result["saved_path"] = str(target.relative_to(root))
            await store.merge_metadata_items(
                session_id,
                "artifacts",
                [{"path": result["saved_path"], "name": target.name, "kind": "file"}],
                "path",
            )
            from .file_catalog import index_tree

            await index_tree(session, target.parent)
        result["pdf_content"] = select_article_context(
            result.get("pdf_content", ""), arguments.get("query", ""), 30000
        )
        return result
    if name == "submit_experiment":
        return await jobs.submit(session_id, "experiment", arguments)
    if name == "submit_computation":
        return await jobs.submit(session_id, "computation", arguments)
    if name in {"register_model", "register_features"}:
        from .registration import register_features, register_model

        function = register_model if name == "register_model" else register_features
        return await function(session_id, **arguments)
    if name in {"get_job", "cancel_job"}:
        job = next(
            (
                j
                for j in await store.jobs(session_id)
                if j["job_id"] == arguments["job_id"]
            ),
            None,
        )
        if job is None:
            raise ValueError("Job does not belong to this research")
        if name == "cancel_job":
            await jobs.cancel(job["job_id"])
            return next(
                j for j in await store.jobs(session_id) if j["job_id"] == job["job_id"]
            )
        log = root / "runs" / job["job_id"] / "run.log"
        if log.exists():
            with log.open("rb") as f:
                f.seek(max(0, log.stat().st_size - 12000))
                job["log_tail"] = f.read().decode(errors="replace")
        return job
    if name == "update_plan":
        phase = arguments.get("phase") or (session.recovery_metadata or {}).get(
            "research_phase", "planning"
        )
        await store.update(
            session_id,
            phase=phase,
            meta={"research_phase": phase},
            experiment_plan=arguments["steps"],
            event={"kind": "plan", "steps": arguments["steps"], "phase": phase},
        )
        return {"updated": True}
    if name == "register_artifact":
        path = jobs.contained(root, arguments["path"])
        if not path.is_file() or path.name == "opencode.json":
            raise ValueError("Artifact must be an existing research file")
        artifact = {
            "path": str(path.relative_to(root)),
            "name": arguments.get("name") or path.name,
            "kind": arguments.get("kind", "file"),
            "size": path.stat().st_size,
        }
        await store.merge_metadata_items(session_id, "artifacts", [artifact], "path")
        from .file_catalog import index_tree

        await index_tree(session, path.parent)
        await store.update(
            session_id,
            event={"kind": "artifacts", "artifacts": [artifact]},
        )
        return artifact
    if name == "finish_research":
        session_jobs = await store.jobs(session_id)
        if any(j["status"] in store.ACTIVE_JOBS for j in session_jobs):
            raise ValueError("Wait for pending jobs before finishing research")
        registrations = {}
        for job in session_jobs:
            if job["kind"] == "download" and job["status"] == "completed":
                receipt = (job.get("result") or {}).get("registration", {})
                registrations[receipt.get("dataset_id", job["job_id"])] = receipt
        incomplete = [
            receipt
            for receipt in registrations.values()
            if receipt.get("metadata_complete") is False
        ]
        if incomplete and arguments.get("outcome", "completed") == "completed":
            raise ValueError(
                "Downloaded data has incomplete registration metadata. Re-run acquire_dataset with verified missing fields (cached bytes are reused), or finish with outcome=partial and explain the gaps."
            )
        from backend.services.manuscripts import require_research_report

        from .study import scientific, untested_pitches, writing_evidence

        outcome = arguments.get("outcome", "completed")
        if scientific(session) and outcome != "completed":
            # Only the user ends a study short of its bar: exhausted pitches call for a new frame or more budget.
            if not await user_asked(session_id, arguments.get("user_stop")):
                remaining = untested_pitches(session)
                raise ValueError(
                    "The study has not reached its publication bar. "
                    + (f"Untested pitches: {remaining}. Improve the selected pitch or pivot. " if remaining else
                       "Every pitch is ruled out: revisit the frame (baseline reproduction, metric resolution versus seed "
                       "noise, headroom above the baseline, input fidelity), change it within the user's question and write new pitches. ")
                    + "If time or attempts are short, request_help(reason='budget'); to let the user choose the next route, "
                    "request_help(reason='direction') with the measured results and two or three concrete options once two frames have failed. "
                    "Finish partial/no_result only when the user asked to stop (quote them in user_stop).")
        if not scientific(session) or outcome == "completed":
            await writing_evidence(session)
            await require_research_report(session)
        await store.update(
            session_id,
            final_report=arguments["summary"],
            meta={
                "finish_requested": True,
                "outcome": outcome,
                "recovery": None,
            },
            event={"kind": "report", "text": arguments["summary"]},
        )
        return {"finished": True}
    if name == "generate_article":
        from backend.services.manuscript_writer import generate_research

        meta = session.recovery_metadata or {}
        if meta.get("report_policy") == "summary" or (
            meta.get("task_kind") in {"analysis", "document"}
            and meta.get("report_policy") != "manuscript"
        ):
            raise ValueError(
                "This task calls for analysis findings/requested files. Generate a manuscript only after the user requests one and set_task_scope records report_policy=manuscript."
            )
        if any(j["status"] in store.ACTIVE_JOBS for j in await store.jobs(session_id)):
            raise ValueError("Wait for pending jobs before publishing the final report")
        return await generate_research(
            session,
            **{
                "language": (session.recovery_metadata or {}).get("language", "en-US"),
                **arguments,
            },
        )
    if name == "request_help":
        from .recovery import assess_help

        issue = assess_help(session, arguments, await store.jobs(session_id))
        await store.update(
            session_id,
            meta={"recovery_requested": issue, "finish_requested": False},
            event={"kind": "help_requested", "recovery": issue},
        )
        return {
            "saved": True,
            "instruction": "The evidenced blocker is saved. End your turn; the user can supply the specific missing input, access or decision, or resume after the external service is repaired.",
        }
