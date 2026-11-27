"""Bounded context prefetch hints, not decisions about the user's intended action."""

from __future__ import annotations

import json
import re
from dataclasses import replace

from fastapi import HTTPException
from sqlalchemy import case, func, or_, select

from backend.database import safe_session
from backend.database.models import (
    Dataset,
    DatasetStats,
    DataGroup,
    TrainedModel,
    TrainingTask,
    TrainingTaskWSI,
    WSISlide,
    SegmentationAnnotation,
)
from backend.services.workspaces import (
    CONNECTORS,
    EXPERT_SKILLS,
    SKILLS,
    WorkspaceScope,
)
from .turn_intent import dataset_overview_kind, is_assistant_introduction

CONTEXT_SCHEMA_VERSION = 6

SKILL_TERMS = {
    "data": r"数据|資料|dataset|\bdata\b|upload|上传|上傳|注册|註冊|切片|slide|浏览|瀏覽|metadata|元数据|元資料|\bcsv\b",
    "training": r"训练|訓練|train|模型推荐|模型推薦|架构|架構|特征|特徵|features?|embedding|encoder|extractor|aggregator|mil|gpfm|uni|virchow",
    "inference": r"推理|预测|預測|验证|驗證|inferen|predict|validat|test.model|测试|測試",
    "analysis": r"分析|结果|結果|指标|指標|图表|圖表|analys|result|metric|chart|auc|accuracy|准确率|準確率|置信区间|信賴區間|confidence interval|\bdice\b|\biou\b",
    "annotation": r"标注|標註|annotation|roi|勾|圈|heatmap|热图|熱圖|mask|掩膜|蒙版",
    "literature": r"文献|文獻|论文|論文|paper|literature|article|\bpdf\b|https?://|搜索|搜尋|search",
    "tasks": r"任务|任務|进度|進度|task|progress|日志|日誌|取消|cancel|history|历史|歷史|rename|重命名|改名|重新命名",
}
BLOCK_SKILLS = {
    "OPTIONS": (),
    "TASK_CONFIG": ("training", "data"),
    "ANALYSIS_CONFIG": ("inference", "analysis", "data"),
    "DATASET_REGISTRATION": ("data",),
    "DATASET_EDIT": ("data",),
    "TASK_HISTORY_CONFIG": ("tasks",),
    "CANCEL_TASK": ("tasks",),
    "RENAME_TASK": ("tasks",),
    "PATCH_INFERENCE": ("inference",),
    "BATCH_INFERENCE_CONFIG": ("inference", "data"),
    "METADATA_UPLOAD": ("data",),
    "CSV_ACTION": ("data",),
    "IMAGE_RECOMMENDATION": ("data", "annotation"),
    "QUICK_ANALYSIS_CONFIG": ("analysis",),
    "MODEL_LIST": ("inference",),
    "METRIC_CONFIG": ("analysis",),
    "CHART_CONFIG": ("analysis",),
    "BATCH_INFERENCE_SUMMARY": ("inference", "tasks"),
}


def text_content(message):
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    return "\n".join(
        str(part.get("text", ""))
        for part in content or []
        if isinstance(part, dict) and part.get("type") == "text"
    )


def context_view(messages) -> str:
    """Attachments select a cheaper projection, without interpreting user intent."""
    latest = next((m for m in reversed(messages) if m.get("role") == "user"), {})
    content = latest.get("content")
    if isinstance(content, list) and any(
        isinstance(part, dict) and part.get("type") == "image_url" for part in content
    ):
        return "image"
    return "default"


def needs_result_evidence(query: str) -> bool:
    return bool(
        re.search(
            r"heatmap|attention.?map|prediction.?mask|predicted|热图|熱圖|注意力|预测|預測|掩膜|mask|模型输出|模型輸出",
            query,
            re.I,
        )
    )


def _text_skills(text):
    selected = {
        key for key, pattern in SKILL_TERMS.items() if re.search(pattern, text, re.I)
    }
    if re.search(r"模型|model", text, re.I):
        selected.add("inference")
    return selected


def select_skills(
    messages, scope: WorkspaceScope, expert_id: str | None
) -> tuple[str, ...]:
    if expert_id and expert_id not in EXPERT_SKILLS:
        raise HTTPException(422, "Unknown expert")
    latest = next(
        (text_content(m) for m in reversed(messages) if m.get("role") == "user"), ""
    )
    has_image = context_view(messages) == "image"
    # Standalone questions must not inherit the previous card's action workflow.
    if not has_image and is_assistant_introduction(latest):
        return ()
    if not has_image and dataset_overview_kind(latest):
        return ("data",) if "data" in scope.enabled_skills else ()
    selected = _text_skills(latest)
    # Conceptual questions do not need the user's inventory.
    conceptual = bool(
        re.search(r"是什么|是什麼|what is|explain|解释|解釋|原理", latest, re.I)
    )
    if (
        not has_image
        and conceptual
        and not re.search(
            r"我的|这个|這個|当前|當前|\b(my|this|our)\b|dataset_|train_", latest, re.I
        )
    ):
        return tuple(
            key
            for key in ("literature",)
            if key in selected and key in scope.enabled_skills
        )
    # Short follow-ups retain the workflow's output protocol, not the entire manual.
    if len(latest) < 160:
        previous = next(
            (
                text_content(m)
                for m in reversed(messages)
                if m.get("role") == "assistant"
            ),
            "",
        )
        for block, skills in BLOCK_SKILLS.items():
            if f"[{block}]" in previous:
                selected.update(skills)
        if "[NAVIGATE]" in previous:
            # API success messages carry the newly created task in navigation state.
            match = re.search(r"\[NAVIGATE\]([\s\S]*?)\[/NAVIGATE\]", previous)
            try:
                navigation = json.loads(match[1]) if match else {}
                if isinstance(navigation, dict) and (
                    navigation.get("taskId")
                    or navigation.get("state", {}).get("selectedTaskId")
                ):
                    selected.add("tasks")
            except (ValueError, AttributeError):
                pass
        if "[OPTIONS]" in previous or not any(
            f"[{block}]" in previous for block in BLOCK_SKILLS
        ):
            # Prefetch the preceding workflow even if the assistant asked a plain
            # question instead of a card. The model still decides if this is a topic change.
            prior_users = [text_content(m) for m in messages if m.get("role") == "user"]
            selected.update(_text_skills(previous))
            if len(prior_users) > 1:
                selected.update(_text_skills(prior_users[-2]))
    if expert_id:
        selected.update(EXPERT_SKILLS[expert_id])
    if has_image:
        selected.add("inference")
    if selected & {"training", "inference", "annotation"}:
        selected.add("data")
    return tuple(
        key for key in SKILLS if key in selected and key in scope.enabled_skills
    )


def request_scope(scope, req):
    if req.execution_mode not in {"standard", "read_only"}:
        raise HTTPException(422, "Invalid execution mode")
    for values, catalog in (
        (req.enabled_skills, SKILLS),
        (req.enabled_connectors, CONNECTORS),
    ):
        if values is not None and set(values) - catalog.keys():
            raise HTTPException(422, "Unknown skill or connector")
    return replace(
        scope,
        enabled_skills=tuple(
            key
            for key in scope.enabled_skills
            if req.enabled_skills is None or key in req.enabled_skills
        ),
        enabled_connectors=tuple(
            key
            for key in scope.enabled_connectors
            if req.enabled_connectors is None or key in req.enabled_connectors
        ),
        execution_mode=(
            "read_only"
            if "read_only" in (scope.execution_mode, req.execution_mode)
            else "standard"
        ),
    )


def resource_query(messages, skills: tuple[str, ...]) -> str:
    """Keep the selected resource in a short follow-up's retrieval without replaying all history."""
    latest = next(
        (text_content(m) for m in reversed(messages) if m.get("role") == "user"), ""
    )
    if (
        len(latest) >= 160
        or is_assistant_introduction(latest)
        or dataset_overview_kind(latest)
    ):
        return latest
    previous = next(
        (text_content(m) for m in reversed(messages) if m.get("role") == "assistant"),
        "",
    )
    references = []
    for block, payload in re.findall(r"\[(\w+)\]([\s\S]*?)\[/\1\]", previous):
        if not set(BLOCK_SKILLS.get(block, ())) & set(skills) and not (
            block == "NAVIGATE" and set(skills) & {"tasks", "analysis"}
        ):
            continue
        try:
            config = json.loads(payload)
        except ValueError:
            continue
        if not isinstance(config, dict):
            continue
        entries = [config, config.get("filters", {}), config.get("state", {})]
        for key in ("models", "classification_models", "segmentation_models"):
            if isinstance(config.get(key), list):
                entries.extend(config[key])
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for key in (
                "dataset_id",
                "task_id",
                "model_id",
                "data_task_id",
                "model_task_id",
                "id",
                "taskId",
                "selectedTaskId",
            ):
                value = entry.get(key)
                if isinstance(value, str) and re.fullmatch(
                    r"[A-Za-z0-9_-]{1,128}", value
                ):
                    references.append(value)
    return " ".join([latest, *dict.fromkeys(references)])


def budget_history(messages, max_chars=24000, recent=12):
    """Keep recent turns and exact latest workflow state; preserve stored history separately."""
    clean = [dict(m) for m in messages if m.get("role") in {"user", "assistant"}]
    if len(clean) <= recent and sum(len(text_content(m)) for m in clean) <= max_chars:
        return clean
    kept = []
    used = 0
    for message in reversed(clean[-recent:]):
        text = text_content(message)
        allowance = max_chars - used
        if allowance <= 0:
            break
        if len(text) > allowance:
            # Never cut JSON workflow blocks; retain their most recent complete form.
            blocks = re.findall(r"\[(\w+)\]([\s\S]*?)\[/\1\]", text)
            state = "\n".join(
                f"[{key}]{body}[/{key}]" for key, body in blocks if key in BLOCK_SKILLS
            )
            if state and len(state) <= allowance:
                message["content"] = state
            else:
                shortened = (
                    text[: max(0, allowance - 80)]
                    + "\n[Earlier content omitted; ask for specifics if needed.]"
                )
                if isinstance(message.get("content"), list):
                    message["content"] = [
                        {"type": "text", "text": shortened},
                        *[
                            part
                            for part in message["content"]
                            if isinstance(part, dict)
                            and part.get("type") == "image_url"
                        ],
                    ]
                else:
                    message["content"] = shortened
        used += len(text_content(message))
        kept.append(message)
    kept.reverse()
    return [
        {
            "role": "user",
            "content": "[History is bounded. Use retained explicit IDs/configuration; do not invent omitted details.]",
        },
        *kept,
    ]


def _ranking(query_text, *columns):
    tokens = re.findall(r"[A-Za-z0-9_-]{3,}|[\u4e00-\u9fff]{2,}", query_text)[:16]
    aliases = {
        "胃": "gastric",
        "肺": "lung",
        "乳腺": "breast",
        "结直肠": "colorectal",
        "宫颈": "cervical",
    }
    tokens.extend(value for key, value in aliases.items() if key in query_text)
    if not tokens:
        return None
    return sum(
        case(
            (or_(*(column.icontains(token, autoescape=True) for column in columns)), 1),
            else_=0,
        )
        for token in tokens
    )


async def build_context(
    user, scope: WorkspaceScope, skills, query_text: str, *, view="default"
):
    from backend.common.chat_context_cache import (
        scoped_context_key,
        read_scoped_context,
        write_scoped_context,
    )

    # General conversation needs no database or Redis. Live task progress bypasses
    # caching; inventory cache access is revalidated before every read.
    cacheable = bool(
        set(skills) & {"data", "training", "inference", "annotation"}
    ) and not set(skills) & {"tasks", "analysis"}
    if not cacheable:
        return await _query_context(user, scope, skills, query_text, view=view)
    async with safe_session() as db:
        accessible_ids = sorted(
            (await db.execute(scope.datasets(user))).scalars().all()
        )
    key = await scoped_context_key(
        {
            "schema": CONTEXT_SCHEMA_VERSION,
            "user": str(user.id),
            "role": user.role,
            "workspace": scope.workspace_id,
            "version": scope.version,
            "datasets": accessible_ids,
            "mode": scope.execution_mode,
            "skills": list(skills),
            "enabled_skills": list(scope.enabled_skills),
            "connectors": list(scope.enabled_connectors),
            "query": query_text,
            "view": view,
        }
    )
    cached = await read_scoped_context(key)
    if cached is not None:
        return cached
    context = await _query_context(user, scope, skills, query_text, view=view)
    await write_scoped_context(key, context)
    return context


async def _query_context(
    user, scope: WorkspaceScope, skills, query_text: str, *, view="default"
):
    result = {
        "scope": scope.name,
        "workspace_id": scope.workspace_id,
        "execution_mode": scope.execution_mode,
        "role": user.role,
        "gpu_base_capability": user.can_use_gpu(),
        "enabled_skills": list(scope.enabled_skills),
        "connectors": list(scope.enabled_connectors),
    }
    if not set(skills) & {
        "data",
        "training",
        "inference",
        "analysis",
        "annotation",
        "tasks",
    }:
        return _serialize_context(result)
    async with safe_session() as db:
        if "data" in skills and view != "image":
            overview = dataset_overview_kind(query_text)
            base = (
                select(
                    Dataset.dataset_id,
                    Dataset.name,
                    Dataset.source_organ,
                    Dataset.data_type,
                    Dataset.aggregation_level,
                    Dataset.description,
                    Dataset.metadata_fields,
                    Dataset.revision,
                    Dataset.is_public,
                    Dataset.parent_dataset_id,
                    Dataset.acquisition_metadata,
                    Dataset.user_id,
                    func.coalesce(DatasetStats.file_count, 0).label("file_count"),
                    DatasetStats.split_train_count,
                    DatasetStats.split_val_count,
                    DatasetStats.split_test_count,
                )
                .outerjoin(DatasetStats, DatasetStats.dataset_id == Dataset.dataset_id)
                .where(Dataset.dataset_id.in_(scope.datasets(user)))
            )
            summary = base.subquery()
            counts = (
                await db.execute(
                    select(
                        func.count(), func.coalesce(func.sum(summary.c.file_count), 0)
                    )
                )
            ).one()
            result["dataset_count"], result["image_count"] = counts
            if overview:
                result["inventory_question"] = overview
            if overview == "count" and set(skills) == {"data"}:
                return _serialize_context(result)
            if overview == "list":
                # Inventory browsing needs names/types, not IDs or split details.
                base = base.with_only_columns(
                    Dataset.name,
                    Dataset.source_organ,
                    Dataset.data_type,
                    func.coalesce(DatasetStats.file_count, 0).label("file_count"),
                )
            rank = _ranking(
                query_text, Dataset.name, Dataset.dataset_id, Dataset.source_organ
            )
            ordered = (
                base.order_by(rank.desc(), Dataset.name)
                if rank is not None
                else base.order_by(Dataset.name)
            )
            rows = (
                await db.execute(ordered.limit(5 if overview == "list" else 12))
            ).all()
            result["datasets"] = [dict(row._mapping) for row in rows]
            if not overview:
                from backend.services.dataset_catalog import task_summaries
                summaries = await task_summaries(db, [row.dataset_id for row in rows])
                for item in result['datasets']:
                    item['can_edit'] = scope.execution_mode != 'read_only' and (user.is_admin() or item.get('user_id') == str(user.id))
                    item['metadata'] = item.pop('metadata_fields', {})
                    item['tasks'] = summaries.get(item['dataset_id'], [])
                    item['task_types'] = [task['task_type'] for task in item['tasks']]
            result["datasets_complete"] = len(rows) >= result["dataset_count"]
            selected_ids = [row.dataset_id for row in rows] if not overview else []
            # Query detailed labels only for the bounded candidate set, never all WSI rows.
            if selected_ids:
                labels = (
                    await db.execute(
                        select(WSISlide.dataset_id, WSISlide.label, func.count())
                        .where(
                            WSISlide.dataset_id.in_(selected_ids),
                            WSISlide.label.isnot(None),
                        )
                        .group_by(WSISlide.dataset_id, WSISlide.label)
                    )
                ).all()
                label_map = {}
                for did, label, count in labels:
                    label_map.setdefault(did, {})[label] = count
                for item in result["datasets"]:
                    item["labels"] = label_map.get(item["dataset_id"], {})
            if (
                selected_ids
                and "annotation" in skills
                and (view == "results" or needs_result_evidence(query_text))
            ):
                from .visualization import browsing_evidence

                evidence = await browsing_evidence(db, user, selected_ids)
                for item in result["datasets"]:
                    item["result_evidence"] = evidence.get(item["dataset_id"], [])
                result["result_evidence_scope"] = (
                    "Recent verified examples only; an empty list does not prove no results exist."
                )
            if selected_ids and set(skills) & {"training", "inference", "annotation", "analysis"}:
                from backend.services.feature_inventory import dataset_feature_summary
                feature_summary=await dataset_feature_summary(db,selected_ids)
                for item in result['datasets']:
                    item['available_features']=feature_summary.get(item['dataset_id'],[])
                result['feature_evidence_scope']='Verified visual feature files can be reused for compatible analysis and image similarity. Missing text alignment does NOT mean visual features are absent. Coverage is per model and image; an empty result/model list does not prove no features exist.'
                survival = (
                    await db.execute(
                        select(WSISlide.dataset_id, WSISlide.event_status, func.count())
                        .where(
                            WSISlide.dataset_id.in_(selected_ids),
                            WSISlide.event_time.isnot(None),
                            WSISlide.event_status.isnot(None),
                        )
                        .group_by(WSISlide.dataset_id, WSISlide.event_status)
                    )
                ).all()
                survival_map = {}
                for did, status, count in survival:
                    survival_map.setdefault(did, {})[
                        "event" if status == 1 else "censored"
                    ] = count
                annotation_rows = (
                    await db.execute(
                        select(SegmentationAnnotation.source_dataset_id, func.count())
                        .where(
                            SegmentationAnnotation.source_dataset_id.in_(selected_ids),
                            SegmentationAnnotation.source != "viewer",
                        )
                        .group_by(SegmentationAnnotation.source_dataset_id)
                    )
                ).all()
                annotation_map = dict(annotation_rows)
                for item in result["datasets"]:
                    item["survival"] = {
                        "event": 0,
                        "censored": 0,
                        **survival_map.get(item["dataset_id"], {}),
                    }
                    item["annotation_count"] = annotation_map.get(item["dataset_id"], 0)
                    item["can_run_gpu"] = user.can_use_gpu()
                    item["has_predefined_splits"] = bool(
                        item["split_val_count"] or item["split_test_count"]
                    )
        if set(skills) & {"training", "inference", "analysis"}:
            models = (
                select(
                    TrainedModel.model_id,
                    TrainedModel.model_name,
                    TrainedModel.task_id,
                    TrainedModel.classes,
                    TrainedModel.feature_extractor,
                    TrainedModel.aggregator,
                    DataGroup.data_type,
                    DataGroup.task_type,
                    DataGroup.aggregation_level,
                    TrainingTask.model_config["architecture"]
                    .as_string()
                    .label("seg_architecture"),
                    TrainingTask.model_config["backbone"]
                    .as_string()
                    .label("seg_backbone"),
                )
                .join(TrainingTask, TrainingTask.task_id == TrainedModel.task_id)
                .join(DataGroup, DataGroup.group_id == TrainingTask.group_id)
            )
            if not user.is_admin():
                models = models.where(TrainedModel.user_id == str(user.id), TrainingTask.user_id == str(user.id))
            if view == "image":
                models = models.where(DataGroup.data_type == "patch")
                result["model_scope"] = "Patch models for the attached image"
            if scope.workspace_id:
                models = models.where(scope.task_filter(TrainedModel.task_id, user))
            result["model_count"] = (
                await db.execute(select(func.count()).select_from(models.subquery()))
            ).scalar()
            rank = _ranking(query_text, TrainedModel.model_name, TrainedModel.model_id)
            ordered = (
                models.order_by(rank.desc(), TrainedModel.created_at.desc())
                if rank is not None
                else models.order_by(TrainedModel.created_at.desc())
            )
            result["models"] = [
                dict(row._mapping) for row in (await db.execute(ordered.limit(5))).all()
            ]
            result["models_complete"] = len(result["models"]) >= result["model_count"]
            task_ids = [item["task_id"] for item in result["models"]]
            sources = (
                (
                    await db.execute(
                        select(
                            TrainingTaskWSI.task_id, Dataset.dataset_id, Dataset.name
                        )
                        .join(WSISlide, WSISlide.wsi_id == TrainingTaskWSI.wsi_id)
                        .join(Dataset, Dataset.dataset_id == WSISlide.dataset_id)
                        .where(
                            TrainingTaskWSI.task_id.in_(task_ids),
                            Dataset.dataset_id.in_(scope.datasets(user)),
                        )
                        .distinct()
                    )
                ).all()
                if task_ids and view != "image"
                else []
            )
            for model in result["models"]:
                model["training_datasets"] = [
                    {"dataset_id": did, "name": name}
                    for tid, did, name in sources
                    if tid == model["task_id"]
                ]
        if set(skills) & {"tasks", "analysis"} and view != "image":
            tasks = select(
                TrainingTask.task_id,
                TrainingTask.task_name,
                TrainingTask.status,
                TrainingTask.progress,
                TrainingTask.error_message,
                DataGroup.task_type,
                DataGroup.data_type,
            ).join(DataGroup, DataGroup.group_id == TrainingTask.group_id)
            if not user.is_admin():
                tasks = tasks.where(TrainingTask.user_id == str(user.id))
            if scope.workspace_id:
                tasks = tasks.where(scope.task_filter(TrainingTask.task_id, user))
            result["task_count"] = (
                await db.execute(select(func.count()).select_from(tasks.subquery()))
            ).scalar()
            rank = _ranking(query_text, TrainingTask.task_name, TrainingTask.task_id)
            tasks = (
                tasks.order_by(rank.desc(), TrainingTask.updated_at.desc())
                if rank is not None
                else tasks.order_by(TrainingTask.updated_at.desc())
            )
            result["tasks"] = [
                dict(row._mapping) for row in (await db.execute(tasks.limit(8))).all()
            ]
            result["tasks_complete"] = len(result["tasks"]) >= result["task_count"]
    return _serialize_context(result)


def _serialize_context(facts: dict) -> str:
    return "\nAPP FACTS (private reference; not wording to repeat)\n" + json.dumps(
        facts, ensure_ascii=False, default=str, separators=(",", ":")
    )
