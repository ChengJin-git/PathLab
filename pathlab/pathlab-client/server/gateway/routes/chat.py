"""
Chat and conversation management routes
Handles AI chat, conversation persistence, and task parsing
"""

import asyncio
from copy import deepcopy
import json
import math
import mimetypes
import os
import re
import time
import uuid
from importlib import import_module
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import httpx
from typing import Any, cast
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import FileResponse
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

_database_module = import_module("backend.database")
get_db = _database_module.get_db
async_session = _database_module.async_session
_repositories = import_module("backend.database.repositories")
ChatRepository = _repositories.ChatRepository
WSIRepository = _repositories.WSIRepository
TrainedModelRepository = _repositories.TrainedModelRepository
DatasetGrantRepository = _repositories.DatasetGrantRepository
DatasetRepository = _repositories.DatasetRepository
TrainingTaskRepository = _repositories.TrainingTaskRepository
AITaskRepository = _repositories.AITaskRepository
_models_module = import_module("backend.database.models")
TrainingTask = _models_module.TrainingTask
WSISlide = _models_module.WSISlide
TrainingTaskWSI = _models_module.TrainingTaskWSI
AIResult = _models_module.AIResult
_auth_module = import_module("backend.auth")
current_active_user = _auth_module.current_active_user
User = _auth_module.User
_auth_deps = import_module("backend.auth.dependencies")
get_user_id_filter = _auth_deps.get_user_id_filter
get_user_from_header_or_param = _auth_deps.get_user_from_header_or_param
from .access_control import assert_owner

require_conversation_access = import_module(
    "gateway.chat.permissions"
).require_conversation_access
_context_cache = import_module("gateway.chat.context_cache")
get_cached_context_kwargs_admin = _context_cache.get_cached_context_kwargs_admin
get_cached_context_kwargs = _context_cache.get_cached_context_kwargs
get_training_snapshot = _context_cache.get_training_snapshot
set_cached_context_kwargs_admin = _context_cache.set_cached_context_kwargs_admin
set_cached_context_kwargs = _context_cache.set_cached_context_kwargs
Config = import_module("backend.common.config").Config
get_gpu_summary_for_prompt = import_module(
    "backend.common.gpu_utils"
).get_gpu_summary_for_prompt
is_fm_segmentation_backbone = import_module(
    "backend.ai.segmentors.specs"
).is_fm_segmentation_backbone
from ..dependencies import logger, make_sse_response
from ..prompts import get_chat_system_prompt, format_user_data_context, detect_language
from ..models import (
    ChatRequest,
    CreateConversationRequest,
    UpdateMessageRequest,
    AddMessageRequest,
    ChatPatchInferenceRequest,
    ChatPatchInferenceExitRequest,
)
from .chat_patch_inference import (
    cancel_chat_patch_tasks_for_message,
    cleanup_chat_patch_tasks_from_message,
    cleanup_conversation_chat_patch_tasks,
    create_chat_patch_task,
    get_chat_patch_task,
)
from .chat_pdf import (
    process_pdf_url,
    get_pdf_image_path,
    search_pdf_pages,
    get_cached_markdown,
    get_cached_pdf_meta,
    get_url_hash,
    get_pdf_cache_dir,
    find_cached_articles_by_title,
    _describe_pdf_image_status,
    _format_pdf_block_label,
    _collect_pdf_urls_from_contexts,
    _replace_images_with_fig_aliases,
    _build_merged_pdf_context,
    router as chat_pdf_router,
)

_chat_pdf_shared = import_module("gateway.routes.chat_pdf_shared")
split_md_into_pages = _chat_pdf_shared.split_md_into_pages
tokenize_for_search = _chat_pdf_shared.tokenize_for_search
detect_source_type = _chat_pdf_shared.detect_source_type
is_academic_content = _chat_pdf_shared.is_academic_content
format_reference_card = _chat_pdf_shared.format_reference_card
ACADEMIC_SOURCE_TYPES = _chat_pdf_shared.ACADEMIC_SOURCE_TYPES
from .chat_training_recommendation import (
    build_training_recommendation_evidence_context,
    detect_training_recommendation_profile,
    looks_like_training_recommendation_query,
)
from .chat_intent_policy import (
    ConversationMode,
    SearchPolicy,
    detect_conversation_mode,
    resolve_search_policy,
)
from .external_validation_analysis import (
    check_extval_compatibility,
    ExtvalModelInfo,
    ExtvalDatasetInfo,
)

router = APIRouter(tags=["Chat & Conversations"])

from .chat_conversation import router as chat_conversation_router
from .chat_model_selector import (
    extract_text_from_content,
    _infer_model_request_filters,
    _matches_model_request_filters,
    _matches_quick_model_request_filters,
    _format_model_filter_summary,
    _semantic_top_k_models,
    _should_use_semantic_model_ranking,
    _extract_images_from_content,
    _extract_citation_contexts,
)
from .chat_llm_client import (
    ClientDisconnectedError,
    _get_llm_http_client,
    _stream_from_openai_compatible,
    _check_local_vllm_available,
    _call_ai_complete,
    _execute_exa_search,
    _consume_task_exception,
    _wait_for_disconnect,
    _run_or_cancel_on_disconnect,
    _deduplicate_search_results,
    _format_search_results_for_ai,
    _raise_for_status_with_detail,
    _truncate_error_detail,
)

router.include_router(chat_conversation_router)
router.include_router(chat_pdf_router)

SEGMENTATION_TASK_TYPES = {"patch_segmentation"}
ACTIVE_TRAINING_STATUSES = {
    "pending",
    "queued",
    "patching",
    "resuming",
    "extracting",
    "training",
}
_EPOCH_PROGRESS_RE = re.compile(r"epoch\s+(\d+)\s*/\s*(\d+)", re.IGNORECASE)
MAX_MODELS_IN_CHAT_CONTEXT = 5
# Number of semantically-closest models to surface in the LLM context.
# When a user's query is embedded and compared against cached model embeddings,
# only the top-K matches are included — regardless of total model count.
TOP_K_MODELS_IN_CHAT_CONTEXT = 5
MAX_DATASETS_IN_CHAT_CONTEXT = 30
DEFAULT_MODEL_SCAN_LIMIT = 100
FILTERED_MODEL_SCAN_LIMIT = 5000
MODEL_SCAN_BATCH_SIZE = 200
_PATCH_INFERENCE_BLOCK_RE = re.compile(
    r"\[PATCH_INFERENCE\]([\s\S]*?)\[/PATCH_INFERENCE\]"
)
_TOOL_BLOCK_RE = re.compile(
    r"\[(?:READ_ARTICLE|WEB_SEARCH)\].*?\[/(?:READ_ARTICLE|WEB_SEARCH)\]", re.DOTALL
)

_feature_extractor_scan_cache: dict[tuple[str, str], tuple[list[str], float]] = {}
_FEATURE_SCAN_CACHE_TTL = 60.0

_CompatCacheKey = tuple[str, str, str, str, str | None, tuple[str, ...], int]
_compat_check_cache: dict[_CompatCacheKey, tuple[bool, float]] = {}
_COMPAT_CACHE_TTL = 120.0


def _log_chat_timing(
    request_id: str,
    stage: str,
    started_at: float,
    *,
    now: float | None = None,
    log_fn: Callable[[str], None] = logger.info,
    **metadata: object,
) -> None:
    elapsed_ms = ((time.monotonic() if now is None else now) - started_at) * 1000
    details = " ".join(
        f"{key}={value}" for key, value in metadata.items() if value is not None
    )
    suffix = f" {details}" if details else ""
    message = (
        f"[ChatTiming] req={request_id} stage={stage} "
        f"elapsed_ms={elapsed_ms:.1f}{suffix}"
    )
    log_fn(message)


def _resolve_prompt_language_and_user_text(
    messages: list[dict[str, Any]], ui_lang: str | None
) -> tuple[str, str]:
    """Resolve prompt language while always preserving the latest user text."""
    last_user_text = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            last_user_text = extract_text_from_content(msg.get("content", ""))
            break

    if ui_lang:
        return ui_lang, last_user_text

    return detect_language(last_user_text), last_user_text


def _filter_datasets_by_query(
    dataset_lines: list[str], query_text: str
) -> list[str]:
    if not query_text or not dataset_lines:
        return []
    query_lower = query_text.lower()
    matched: list[str] = []
    for line in dataset_lines:
        id_match = re.search(r"dataset_id=([^\s:)]+)", line)
        if not id_match:
            continue
        dataset_id = id_match.group(1).lower()
        name_match = re.match(r"\s+-\s+(.+?)\s+\(dataset_id=", line)
        display_name = (name_match.group(1) if name_match else "").lower()
        if (
            query_lower in dataset_id
            or dataset_id in query_lower
            or (display_name and query_lower in display_name)
            or (display_name and display_name in query_lower)
        ):
            matched.append(line)
    return matched


def _dataset_line_query_score(line: str, query_text: str) -> int:
    if not query_text:
        return 0
    query_tokens = set(re.findall(r"[a-z0-9]+", query_text.lower()))
    if not query_tokens:
        return 0

    id_match = re.search(r"dataset_id=([^\s:)]+)", line)
    name_match = re.match(r"\s+-\s+(.+?)\s+\(dataset_id=", line)
    searchable_parts = []
    if name_match:
        searchable_parts.append(name_match.group(1))
    if id_match:
        searchable_parts.append(id_match.group(1))
    if not searchable_parts:
        return 0

    line_tokens = set(re.findall(r"[a-z0-9]+", " ".join(searchable_parts).lower()))
    return len(query_tokens & line_tokens)


def _prioritize_dataset_lines_for_query(
    dataset_lines: list[str], query_text: str
) -> list[str]:
    matched_lines = _filter_datasets_by_query(dataset_lines, query_text)
    if not matched_lines:
        scored_lines = [
            (_dataset_line_query_score(line, query_text), index, line)
            for index, line in enumerate(dataset_lines)
        ]
        matched_lines = [line for score, _, line in scored_lines if score > 0]
        if not matched_lines:
            return dataset_lines
        scored_lines.sort(key=lambda item: (-item[0], item[1]))
        return [line for score, _, line in scored_lines if score > 0] + [
            line for score, _, line in scored_lines if score <= 0
        ]
    return matched_lines + [line for line in dataset_lines if line not in matched_lines]


def _is_truncated_dataset_context(datasets_list: object) -> bool:
    return isinstance(datasets_list, str) and "omitted from prompt" in datasets_list


def _format_chat_dataset_list(
    dataset_lines: list[str], *, limit: int = MAX_DATASETS_IN_CHAT_CONTEXT
) -> str:
    if not dataset_lines:
        return "  None"
    if limit <= 0 or len(dataset_lines) <= limit:
        return "\n".join(dataset_lines)
    omitted = len(dataset_lines) - limit
    visible_lines = dataset_lines[:limit]
    visible_lines.append(
        f"  - ... {omitted} more dataset(s) omitted from prompt; "
        "do NOT assume omitted datasets are unavailable. "
        "Ask the user to narrow by dataset name, organ/source, task type, "
        "or access type if needed."
    )
    return "\n".join(visible_lines)


async def _get_available_extractors(features_root: Path, wsi_id: str) -> list[str]:
    cache_key = (str(features_root), wsi_id)
    now = time.monotonic()
    cached_entry = _feature_extractor_scan_cache.get(cache_key)
    if cached_entry is not None:
        cached_result, cached_at = cached_entry
        if now - cached_at < _FEATURE_SCAN_CACHE_TTL:
            return cached_result

    def _scan() -> list[str]:
        result: list[str] = []
        if not features_root.exists():
            return result
        for extractor_dir in features_root.iterdir():
            if extractor_dir.is_dir():
                for params_hash_dir in extractor_dir.iterdir():
                    if (
                        params_hash_dir.is_dir()
                        and (params_hash_dir / f"{wsi_id}.pt").exists()
                    ):
                        result.append(extractor_dir.name)
                        break
        return result

    extractors = await asyncio.to_thread(_scan)
    _feature_extractor_scan_cache[cache_key] = (extractors, now)
    return extractors


def _get_generation_cancelled_text(detected_lang: str) -> str:
    """Return localized cancel text for interrupted AI responses."""
    normalized = (detected_lang or "en").replace("-", "_")
    cancel_messages = {
        "zh_CN": "*用户取消了回答。*",
        "zh_HK": "*用戶取消了回答。*",
        "en": "*Response cancelled by user.*",
        "en_US": "*Response cancelled by user.*",
    }
    return cancel_messages.get(
        normalized, cancel_messages.get(normalized.split("_")[0], cancel_messages["en"])
    )


def _has_training_recommendation_context(messages: list[dict[str, object]]) -> bool:
    for msg in messages:
        if msg.get("role") != "user":
            continue
        raw = extract_text_from_content(msg.get("content", ""))
        if "[TRAINING_RECOMMENDATION_CONTEXT]" in raw:
            return True
    return False


def _build_no_web_search_instruction(detected_lang: str, mode: ConversationMode) -> str:
    if mode == ConversationMode.IMAGE_VISUALIZATION:
        if detected_lang == "zh_CN":
            return (
                "当前这轮是站内图像/热力图浏览回合，不是训练推荐，也不是文献检索。"
                "绝对不要使用 `[WEB_SEARCH]`。请直接继续帮助用户查看该数据集的图像/热力图，"
                "优先输出 `[IMAGE_RECOMMENDATION]`，如果还有必要，只追问剩余的可视化细节。"
            )
        if detected_lang == "zh_HK":
            return (
                "當前這輪是站內影像/熱力圖瀏覽回合，不是訓練推薦，也不是文獻檢索。"
                "絕對不要使用 `[WEB_SEARCH]`。請直接繼續幫助使用者查看該資料集的影像/熱力圖，"
                "優先輸出 `[IMAGE_RECOMMENDATION]`，如果還有必要，只追問剩餘的可視化細節。"
            )
        return (
            "This turn is for in-app image/heatmap browsing, not for training recommendation or literature search. "
            "Do NOT use `[WEB_SEARCH]`. Continue by helping the user browse existing images/heatmaps, "
            "prefer `[IMAGE_RECOMMENDATION]`, and only ask for any remaining visualization-specific details if needed."
        )

    if mode == ConversationMode.PATCH_INFERENCE:
        if detected_lang == "zh_CN":
            return (
                "当前这轮是站内图像分析/图像推理回合，不是文献检索。绝对不要使用 `[WEB_SEARCH]`。"
                "请直接基于现有图像与模型上下文继续，优先输出普通说明或 `[PATCH_INFERENCE]`。"
            )
        if detected_lang == "zh_HK":
            return (
                "當前這輪是站內影像分析/影像推理回合，不是文獻檢索。絕對不要使用 `[WEB_SEARCH]`。"
                "請直接基於現有影像與模型上下文繼續，優先輸出普通說明或 `[PATCH_INFERENCE]`。"
            )
        return (
            "This turn is for in-app image analysis/inference, not literature search. "
            "Do NOT use `[WEB_SEARCH]`. Continue using the existing image and model context, "
            "prefer normal guidance or `[PATCH_INFERENCE]` when appropriate."
        )

    if mode == ConversationMode.INTERNAL_EVALUATION:
        if detected_lang == "zh_CN":
            return (
                "当前这轮是内部验证流程，不是文献检索。绝对不要使用 `[WEB_SEARCH]`。"
                "请直接使用已有任务、模型和数据集上下文继续，优先输出 `[ANALYSIS_CONFIG]`（analysis_type: internal）、`[METRIC_CONFIG]` 或 `[QUICK_ANALYSIS_CONFIG]`。"
            )
        if detected_lang == "zh_HK":
            return (
                "當前這輪是內部驗證流程，不是文獻檢索。絕對不要使用 `[WEB_SEARCH]`。"
                "請直接使用已有任務、模型和資料集上下文繼續，優先輸出 `[ANALYSIS_CONFIG]`（analysis_type: internal）、`[METRIC_CONFIG]` 或 `[QUICK_ANALYSIS_CONFIG]`。"
            )
        return (
            "This turn is for in-app internal validation, not literature search. "
            "Do NOT use `[WEB_SEARCH]`. Continue with the existing task/model/dataset context, "
            "prefer `[ANALYSIS_CONFIG]` (analysis_type: internal), `[METRIC_CONFIG]`, or `[QUICK_ANALYSIS_CONFIG]`."
        )

    if mode == ConversationMode.EXTERNAL_EVALUATION:
        if detected_lang == "zh_CN":
            return (
                "当前这轮是外部评测流程，不是文献检索。绝对不要使用 `[WEB_SEARCH]`。"
                "请直接使用已有任务、模型和数据集上下文继续，优先输出 `[ANALYSIS_CONFIG]`（analysis_type: external）或 `[METRIC_CONFIG]`。"
            )
        if detected_lang == "zh_HK":
            return (
                "當前這輪是外部評測流程，不是文獻檢索。絕對不要使用 `[WEB_SEARCH]`。"
                "請直接使用已有任務、模型和資料集上下文繼續，優先輸出 `[ANALYSIS_CONFIG]`（analysis_type: external）或 `[METRIC_CONFIG]`。"
            )
        return (
            "This turn is for in-app external evaluation, not literature search. "
            "Do NOT use `[WEB_SEARCH]`. Continue with the existing task/model/dataset context, "
            "prefer `[ANALYSIS_CONFIG]` (analysis_type: external) or `[METRIC_CONFIG]`."
        )

    if mode == ConversationMode.BATCH_INFERENCE:
        if detected_lang == "zh_CN":
            return (
                "当前这轮是针对无标注数据集的批量推理流程，不是文献检索。绝对不要使用 `[WEB_SEARCH]`。"
                "请直接使用已有模型和数据集上下文继续，优先输出 `[ANALYSIS_CONFIG]`（analysis_type: batch_inference）或 `[BATCH_INFERENCE_SUMMARY]`。"
            )
        if detected_lang == "zh_HK":
            return (
                "當前這輪是針對無標注資料集的批量推理流程，不是文獻檢索。絕對不要使用 `[WEB_SEARCH]`。"
                "請直接使用已有模型和資料集上下文繼續，優先輸出 `[ANALYSIS_CONFIG]`（analysis_type: batch_inference）或 `[BATCH_INFERENCE_SUMMARY]`。"
            )
        return (
            "This turn is for batch inference on an unlabeled dataset, not literature search. "
            "Do NOT use `[WEB_SEARCH]`. Continue with the existing model and dataset context, "
            "prefer `[ANALYSIS_CONFIG]` (analysis_type: batch_inference) or `[BATCH_INFERENCE_SUMMARY]`."
        )

    if mode == ConversationMode.MODEL_CARD:
        if detected_lang == "zh_CN":
            return (
                "当前这轮是查看已训练模型信息/模型卡片的回合，不是文献检索。绝对不要使用 `[WEB_SEARCH]`。"
                "请直接使用已有的模型上下文，回答用户关于模型架构、特征提取器、聚合器、类别标签和训练配置等信息的问题。"
            )
        if detected_lang == "zh_HK":
            return (
                "當前這輪是查看已訓練模型資訊/模型卡片的回合，不是文獻檢索。絕對不要使用 `[WEB_SEARCH]`。"
                "請直接使用已有的模型上下文，回答用戶關於模型架構、特徵提取器、聚合器、類別標籤和訓練配置等資訊的問題。"
            )
        return (
            "This turn is about viewing a trained model's information or model card, not literature search. "
            "Do NOT use `[WEB_SEARCH]`. Use the existing model context to answer questions about "
            "the model's architecture, feature extractor, aggregator, class labels, and training configuration."
        )

    if detected_lang == "zh_CN":
        return (
            "当前这轮是站内分析/验证/结果展示流程，不是文献检索。绝对不要使用 `[WEB_SEARCH]`。"
            "请直接使用已有任务、模型和数据集上下文继续，优先输出 `[ANALYSIS_CONFIG]`、`[METRIC_CONFIG]`、`[CHART_CONFIG]` 或 `[QUICK_ANALYSIS_CONFIG]`。"
        )
    if detected_lang == "zh_HK":
        return (
            "當前這輪是站內分析/驗證/結果展示流程，不是文獻檢索。絕對不要使用 `[WEB_SEARCH]`。"
            "請直接使用已有任務、模型和資料集上下文繼續，優先輸出 `[ANALYSIS_CONFIG]`、`[METRIC_CONFIG]`、`[CHART_CONFIG]` 或 `[QUICK_ANALYSIS_CONFIG]`。"
        )
    return (
        "This turn is for in-app analysis/validation/result display, not literature search. "
        "Do NOT use `[WEB_SEARCH]`. Continue with the existing task/model/dataset context, "
        "prefer `[ANALYSIS_CONFIG]`, `[METRIC_CONFIG]`, `[CHART_CONFIG]`, or `[QUICK_ANALYSIS_CONFIG]`."
    )


def _prepare_generation_messages(
    messages: list[dict[str, object]],
    detected_lang: str,
    disable_web_search: bool,
    conversation_mode: ConversationMode,
) -> list[dict[str, object]]:
    prepared_messages = messages.copy()
    if disable_web_search:
        prepared_messages = prepared_messages + [
            {
                "role": "user",
                "content": _build_no_web_search_instruction(
                    detected_lang, conversation_mode
                ),
            }
        ]
    return prepared_messages


def _should_stream_sniffed_response(
    disable_web_search: bool,
    stripped_content: str,
    tool_prefixes: tuple[str, ...],
) -> bool:
    if disable_web_search:
        return False
    return not any(stripped_content.startswith(prefix) for prefix in tool_prefixes)


def _strip_tool_blocks(text: str) -> str:
    return _TOOL_BLOCK_RE.sub("", text or "").strip()


def _looks_like_training_model_recommendation_output(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    if "[web_search]" in normalized or "[read_article]" in normalized:
        return False
    if "[task_config]" in normalized:
        return True

    model_keywords = (
        "uni",
        "uni2",
        "virchow",
        "virchow2",
        "resnet50",
        "abmil",
        "clam",
        "transmil",
        "conch",
        "phikon",
        "smartccs",
        "smartcyto",
        "unet",
        "segformer",
        "conv_decoder",
        "mit_b",
        "mlp",
        "attention",
    )
    recommendation_keywords = (
        "recommend",
        "recommended",
        "建议",
        "建議",
        "推荐",
        "推薦",
        "最适合",
        "最適合",
    )

    has_model_keyword = any(keyword in normalized for keyword in model_keywords)
    if "[options]" in normalized and has_model_keyword:
        return True
    if has_model_keyword and any(
        keyword in normalized for keyword in recommendation_keywords
    ):
        return True
    return False


def _build_training_recommendation_context_block(
    merged_ctx: str,
    detected_lang: str,
    profile: str,
) -> str:
    profile_notes = {
        "zh_CN": {
            "histopathology": "本轮推荐应优先结合任务/器官匹配的 PathBench 结果，再联网查近期任务证据；不要把 UNI 或任何单一 encoder 视为普遍最优。",
            "segmentation": "本轮推荐应优先结合 PathBench / 病理分割相关证据，再联网查近期任务证据；不要默认任何单一 FM extractor。",
            "cervical_cytology": "本轮推荐对宫颈 / 妇科细胞学应优先考虑 Smart-CCS，再联网查近期任务证据。",
            "general_cytology": "本轮推荐对非宫颈 / 非妇科或通用细胞学，SmartCyto 为优先候选（视觉-语言预训练模型），再联网查同任务公开证据；不要把缺少公开命中当成反证。",
        },
        "zh_HK": {
            "histopathology": "本輪推薦應優先結合任務/器官匹配的 PathBench 結果，再聯網查近期任務證據；不要把 UNI 或任何單一 encoder 視為普遍最優。",
            "segmentation": "本輪推薦應優先結合 PathBench / 病理分割相關證據，再聯網查近期任務證據；不要預設任何單一 FM extractor。",
            "cervical_cytology": "本輪推薦對宮頸 / 婦科細胞學應優先考慮 Smart-CCS，再聯網查近期任務證據。",
            "general_cytology": "本輪推薦對非宮頸 / 非婦科或通用細胞學，SmartCyto 為優先候選（視覺-語言預訓練模型），再聯網查同任務公開證據；不要把缺少公開命中當成反證。",
        },
        "en": {
            "histopathology": "Prioritize task/organ-matched PathBench evidence, then verify with a fresh web search; do not treat UNI or any single encoder as universally best.",
            "segmentation": "Prioritize PathBench/pathology-segmentation evidence, then verify with a fresh web search; do not default to any single FM extractor.",
            "cervical_cytology": "For cervical / gynecologic cytology, prioritize Smart-CCS, then verify with a fresh web search.",
            "general_cytology": "For non-cervical, non-gynecologic, or general cytology, SmartCyto is a preferred candidate (vision-language pretrained); verify with task-matched public evidence and do not treat missing public hits as counter-evidence.",
        },
    }
    notes = profile_notes.get(detected_lang, profile_notes["en"])
    profile_note = notes.get(profile, notes.get("histopathology", ""))

    if detected_lang == "zh_CN":
        header = (
            "[TRAINING_RECOMMENDATION_CONTEXT]\n"
            "这是当前训练推荐的隐藏证据上下文。\n"
            "规则：\n"
            "1. 先使用这里的 PDF / RAG 证据和任务约束；\n"
            "2. 先按全局任务树判断：先判 task_type（classification / survival / segmentation），再进入对应配置空间；\n"
            "3. 如果 task_type 还没确定，不要先提 MIL、classifier、SMP 或 FM segmentation；如果 classification 已确定但 patch / wsi 还没确定，也不要先提 aggregator 或 classifier；如果 task_type 已确定为 survival，在架构层面要把它视为与 WSI classification 同属 encoder + aggregator / MIL 路线，主要区别在 objective / loss；\n"
            "4. 在输出任何训练架构推荐、模型选项、`[OPTIONS]` 或 `[TASK_CONFIG]` 前，必须先执行一次 `[WEB_SEARCH]`；\n"
            "5. 不要向用户直接暴露这里的隐藏证据：禁止输出 Local PDF / 本地证据 / 内置证据 / URL / 论文标题 / 页码，也不要把这里的内容做成 inline citation；\n"
            "6. 最终结论可以综合内置证据与外部搜索，但不要把它们描述成本地数据、内部偏好或私有 benchmark；\n"
            f"7. {profile_note}\n\n"
        )
        empty = "当前没有命中的 PDF 证据；请依然保留上面的任务约束，并执行一次有针对性的联网搜索。"
    elif detected_lang == "zh_HK":
        header = (
            "[TRAINING_RECOMMENDATION_CONTEXT]\n"
            "這是當前訓練推薦的隱藏證據上下文。\n"
            "規則：\n"
            "1. 先使用這裡的 PDF / RAG 證據和任務約束；\n"
            "2. 先按全局任務樹判斷：先判 task_type（classification / survival / segmentation），再進入對應配置空間；\n"
            "3. 如果 task_type 還沒確定，不要先提 MIL、classifier、SMP 或 FM segmentation；如果 classification 已確定但 patch / wsi 還沒確定，也不要先提 aggregator 或 classifier；如果 task_type 已確定為 survival，在架構層面要把它視為與 WSI classification 同屬 encoder + aggregator / MIL 路線，主要差別在 objective / loss；\n"
            "4. 在輸出任何訓練架構推薦、模型選項、`[OPTIONS]` 或 `[TASK_CONFIG]` 前，必須先執行一次 `[WEB_SEARCH]`；\n"
            "5. 不要向使用者直接暴露這裡的隱藏證據：禁止輸出 Local PDF / 本地證據 / 內置證據 / URL / 論文標題 / 頁碼，也不要把這裡的內容做成 inline citation；\n"
            "6. 最終結論可以綜合內置證據與外部搜索，但不要把它們描述成本地數據、內部偏好或私有 benchmark；\n"
            f"7. {profile_note}\n\n"
        )
        empty = "當前沒有命中的 PDF 證據；請依然保留上面的任務約束，並執行一次有針對性的聯網搜索。"
    else:
        header = (
            "[TRAINING_RECOMMENDATION_CONTEXT]\n"
            "This is hidden evidence context for the current training recommendation.\n"
            "Rules:\n"
            "1. Use the bundled PDF/RAG evidence and task-specific constraints here first;\n"
            "2. Follow a global task tree first: resolve task_type (classification / survival / segmentation) before entering any component space;\n"
            "3. If task_type is still unresolved, do not jump to MIL, classifier, SMP, or FM segmentation; if classification is resolved but patch vs. wsi is not, do not jump to aggregator or classifier yet; if task_type is survival, treat it architecturally as the same encoder + aggregator / MIL family as WSI classification, with the main difference in objective / loss;\n"
            "4. Before outputting any architecture recommendation, model options, `[OPTIONS]`, or `[TASK_CONFIG]`, you MUST perform one `[WEB_SEARCH]`;\n"
            "5. Never expose this hidden evidence directly to the user: do not output Local PDF / internal evidence / URLs / paper titles / page numbers, and do not turn bundled evidence into inline citations;\n"
            "6. Synthesize bundled evidence and external web evidence, but do NOT describe them to the user as local/private data, internal priors, or private benchmark results;\n"
            f"7. {profile_note}\n\n"
        )
        empty = "No matched bundled PDF evidence was found for this turn; still preserve the task-specific constraints above and perform one targeted web search."

    body = merged_ctx.strip() or empty
    return f"{header}{body}\n[/TRAINING_RECOMMENDATION_CONTEXT]"


def _build_training_recommendation_search_retry_instruction(
    detected_lang: str, _profile: str
) -> str:
    if detected_lang == "zh_CN":
        return (
            "你正在做训练配置推荐。先不要直接给推荐、`[OPTIONS]` 或 `[TASK_CONFIG]`。"
            "请先基于已有的 `[TRAINING_RECOMMENDATION_CONTEXT]` 执行一次 `[WEB_SEARCH]`，"
            "并先按全局任务树确认当前是 classification、survival 还是 segmentation；如果是 survival，在架构层面按与 WSI classification 相同的 encoder + aggregator / MIL 路线理解，主要区别在 objective / loss；再综合 PDF / RAG 证据与外部搜索结果给出结论；不要把这些依据表述成本地数据或内部偏好，也不要输出 Local PDF、本地证据、URL、论文标题或页码。"
        )
    if detected_lang == "zh_HK":
        return (
            "你正在做訓練配置推薦。先不要直接給推薦、`[OPTIONS]` 或 `[TASK_CONFIG]`。"
            "請先基於已有的 `[TRAINING_RECOMMENDATION_CONTEXT]` 執行一次 `[WEB_SEARCH]`，"
            "並先按全局任務樹確認當前是 classification、survival 還是 segmentation；如果是 survival，在架構層面按與 WSI classification 相同的 encoder + aggregator / MIL 路線理解，主要差別在 objective / loss；再綜合 PDF / RAG 證據與外部搜索結果給出結論；不要把這些依據表述成本地數據或內部偏好，也不要輸出 Local PDF、本地證據、URL、論文標題或頁碼。"
        )
    return (
        "You are in training recommendation mode. Do not output a recommendation, `[OPTIONS]`, or `[TASK_CONFIG]` yet. "
        "First use the existing `[TRAINING_RECOMMENDATION_CONTEXT]` to make one `[WEB_SEARCH]`, "
        "resolve whether the task belongs to classification, survival, or segmentation, treat survival architecturally as the same encoder + aggregator / MIL family as WSI classification with the main difference in objective / loss, and only then synthesize the PDF/RAG evidence and external web evidence without framing them as local/private data or internal priors. Do not output Local PDF, internal evidence, URLs, paper titles, or page numbers from the hidden context."
    )


def _sanitize_training_recommendation_output(text: str) -> str:
    sanitized = text or ""
    leak_patterns = (
        r"\[[^\]]*(?:local|bundled|internal|hidden)\s+(?:pdf(?:-rag)?|evidence|knowledge\s*base)[^\]]*\]",
        r"\([^\)]*(?:local|bundled|internal|hidden)\s+(?:pdf(?:-rag)?|evidence|knowledge\s*base)[^\)]*\)",
        r"\b(?:local|bundled|internal|hidden)\s+(?:pdf(?:-rag)?|evidence|knowledge\s*base)\b(?:\s*[,;:]\s*(?:p\.?\s*\d+(?:\s*[-–]\s*\d+)?|page\s*\d+))?",
        r"\[[^\]]*(?:本地\s*PDF(?:-RAG)?|本地证据|本地證據|内置\s*PDF(?:-RAG)?|內置\s*PDF(?:-RAG)?|内置证据|內置證據|隐藏证据|隱藏證據|内置知识库|內置知識庫)[^\]]*\]",
        r"（[^）]*(?:本地\s*PDF(?:-RAG)?|本地证据|本地證據|内置\s*PDF(?:-RAG)?|內置\s*PDF(?:-RAG)?|内置证据|內置證據|隐藏证据|隱藏證據|内置知识库|內置知識庫)[^）]*）",
        r"(?:本地\s*PDF(?:-RAG)?|本地证据|本地證據|内置\s*PDF(?:-RAG)?|內置\s*PDF(?:-RAG)?|内置证据|內置證據|隐藏证据|隱藏證據|内置知识库|內置知識庫)(?:\s*[，,；;：:]\s*(?:p\.?\s*\d+(?:\s*[-–]\s*\d+)?|第?\s*\d+\s*[页頁]))?",
    )
    for pattern in leak_patterns:
        sanitized = re.sub(pattern, "", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"\n{3,}", "\n\n", sanitized)
    sanitized = re.sub(r"[ \t]{2,}", " ", sanitized)
    sanitized = re.sub(r"[ \t]+([,，.。;；:：)）])", r"\1", sanitized)
    sanitized = re.sub(r"([（(])[ \t]+", r"\1", sanitized)
    return sanitized.strip()


def _apply_patch_inference_exit_updates(
    content: str,
    task_updates: dict[str, dict[str, object]] | None = None,
) -> str:
    """Mark in-message image inference runs as cancelled or with the latest terminal snapshot."""
    match = _PATCH_INFERENCE_BLOCK_RE.search(content or "")
    if not match:
        return content

    try:
        config = json.loads(match.group(1).strip())
    except Exception:
        return content

    updates = task_updates or {}
    changed = False
    for key in ("classification_run", "segmentation_run"):
        run = config.get(key)
        if not isinstance(run, dict):
            continue

        task_id = str(run.get("task_id") or "")
        if task_id and task_id in updates:
            merged_run = {
                **run,
                "status": updates[task_id].get("status", run.get("status")),
                "progress": updates[task_id].get("progress", run.get("progress")),
                "result": updates[task_id].get("result", run.get("result")),
                "error": updates[task_id].get("error", run.get("error")),
            }
            if merged_run != run:
                config[key] = merged_run
                changed = True
            continue

        if run.get("status") in {"queued", "running"}:
            merged_run = {
                **run,
                "status": "cancelled",
                "progress": 100,
                "error": "Task cancelled",
            }
            if merged_run != run:
                config[key] = merged_run
                changed = True

    if not changed:
        return content

    next_block = f"[PATCH_INFERENCE]\n{json.dumps(config, ensure_ascii=False, indent=2)}\n[/PATCH_INFERENCE]"
    return _PATCH_INFERENCE_BLOCK_RE.sub(next_block, content, count=1)


def _get_ai_service_error_text(detected_lang: str) -> str:
    """Return a localized, user-friendly AI service error message."""
    normalized = (detected_lang or "en").replace("-", "_")
    error_messages = {
        "zh_CN": "❌ AI 服务暂时不可用。请稍后重试，或检查本地 vLLM、API Key 和网络连接。",
        "zh_HK": "❌ AI 服務暫時不可用。請稍後重試，或檢查本地 vLLM、API Key 和網絡連線。",
        "en": "❌ AI service is temporarily unavailable. Please try again, or check your local vLLM, API key, and network connection.",
        "en_US": "❌ AI service is temporarily unavailable. Please try again, or check your local vLLM, API key, and network connection.",
    }
    return error_messages.get(
        normalized, error_messages.get(normalized.split("_")[0], error_messages["en"])
    )


def _normalize_lang_key(detected_lang: str) -> str:
    normalized = (detected_lang or "en").replace("-", "_")
    if normalized in {"zh_CN", "zh_HK", "en", "en_US"}:
        return normalized
    base = normalized.split("_")[0]
    return {"zh": "zh_CN", "en": "en"}.get(base, "en")


def _get_read_source_label(source_type: str, detected_lang: str) -> str:
    lang = _normalize_lang_key(detected_lang)
    labels = {
        "zh_CN": {
            "github": "GitHub 仓库页",
            "gitlab": "GitLab 仓库页",
            "gitee": "Gitee 仓库页",
            "zenodo": "Zenodo 记录页",
            "documentation": "文档页面",
            "blog": "网页",
            "web": "网页",
            "pdf": "PDF 文档",
        },
        "zh_HK": {
            "github": "GitHub 倉庫頁",
            "gitlab": "GitLab 倉庫頁",
            "gitee": "Gitee 倉庫頁",
            "zenodo": "Zenodo 記錄頁",
            "documentation": "文件頁面",
            "blog": "網頁",
            "web": "網頁",
            "pdf": "PDF 文件",
        },
        "en": {
            "github": "GitHub repository page",
            "gitlab": "GitLab repository page",
            "gitee": "Gitee repository page",
            "zenodo": "Zenodo record page",
            "documentation": "documentation page",
            "blog": "web page",
            "web": "web page",
            "pdf": "PDF document",
        },
    }
    base = labels.get(lang, labels["en"])
    return base.get(source_type, base.get("web", "web page"))


def _get_read_failure_reason_text(detected_lang: str, error_code: str | None) -> str:
    lang = _normalize_lang_key(detected_lang)
    messages = {
        "zh_CN": {
            "http_status": "目标页面当前拒绝自动访问，可能需要登录、验证码或交互式浏览。",
            "page_too_large": "目标页面内容过大，超出了轻量读取范围。",
            "points_to_pdf": "这个链接实际指向 PDF 文档，更适合按 PDF 方式打开。",
            "unreadable_page": "目标页面可提取的静态正文不足，可能主要依赖前端动态渲染。",
            "network_unreachable": "当前无法连接到目标页面。",
            "request_timeout": "目标页面响应超时。",
            "empty_content": "已访问页面，但没有提取到足够可读的正文。",
            "unexpected_error": "读取过程中出现了未预期的问题。",
        },
        "zh_HK": {
            "http_status": "目標頁面目前拒絕自動訪問，可能需要登入、驗證碼或互動式瀏覽。",
            "page_too_large": "目標頁面內容過大，超出了輕量讀取範圍。",
            "points_to_pdf": "這個連結實際指向 PDF 文件，更適合按 PDF 方式打開。",
            "unreadable_page": "目標頁面可提取的靜態正文不足，可能主要依賴前端動態渲染。",
            "network_unreachable": "目前無法連接到目標頁面。",
            "request_timeout": "目標頁面回應逾時。",
            "empty_content": "已訪問頁面，但沒有提取到足夠可讀的正文。",
            "unexpected_error": "讀取過程中出現了未預期的問題。",
        },
        "en": {
            "http_status": "The target page is currently blocking automatic access and may require login, anti-bot checks, or interactive browsing.",
            "page_too_large": "The target page is too large for lightweight extraction.",
            "points_to_pdf": "This link actually points to a PDF and is better handled through the PDF flow.",
            "unreadable_page": "The page does not expose enough readable static text and may rely on client-side rendering.",
            "network_unreachable": "The target page could not be reached over the network.",
            "request_timeout": "The target page timed out before responding.",
            "empty_content": "The page was reached, but not enough readable content could be extracted.",
            "unexpected_error": "An unexpected issue occurred while preparing this content.",
        },
    }
    base = messages.get(lang, messages["en"])
    return base.get(
        error_code or "", base.get("unexpected_error", "An unexpected issue occurred.")
    )


def _build_read_failure_instruction(
    detected_lang: str,
    *,
    article_title: str,
    article_url: str,
    source_type: str,
    error_code: str | None = None,
    error_detail: str | None = None,
    exception_text: str | None = None,
) -> str:
    lang = _normalize_lang_key(detected_lang)
    source_label = _get_read_source_label(source_type, detected_lang)
    reason = _get_read_failure_reason_text(detected_lang, error_code)
    detail = (error_detail or "").strip()
    exception_detail = (exception_text or "").strip()

    if lang == "zh_CN":
        navigation_hint = (
            "请建议用户直接打开链接，通过页面导航继续查看文件、README、附件或更多细节。"
            if source_type in {"github", "gitlab", "gitee", "zenodo"}
            else "请建议用户直接打开原链接查看更多细节。"
        )
        depth_guard = (
            "如果这是仓库页，请明确说明当前只完成了轻量页面读取，不要假装已经深入分析整个代码仓库。"
            if source_type in {"github", "gitlab", "gitee"}
            else "不要假装已经读取到当前页面未提供的内容。"
        )
        detail_line = (
            f"\n补充信息：{detail}"
            if detail
            else (f"\n补充信息：{exception_detail}" if exception_detail else "")
        )
        return (
            f"未能成功读取《{article_title}》对应的{source_label}（{article_url}）。"
            f"原因：{reason}{detail_line}\n\n"
            "请直接告诉用户本次自动读取失败，并给出简短替代建议。"
            f"{navigation_hint}{depth_guard}"
        )

    if lang == "zh_HK":
        navigation_hint = (
            "請建議用戶直接打開連結，透過頁面導覽繼續查看檔案、README、附件或更多細節。"
            if source_type in {"github", "gitlab", "gitee", "zenodo"}
            else "請建議用戶直接打開原連結查看更多細節。"
        )
        depth_guard = (
            "如果這是倉庫頁，請明確說明目前只完成了輕量頁面讀取，不要假裝已經深入分析整個代碼倉庫。"
            if source_type in {"github", "gitlab", "gitee"}
            else "不要假裝已經讀取到當前頁面未提供的內容。"
        )
        detail_line = (
            f"\n補充資訊：{detail}"
            if detail
            else (f"\n補充資訊：{exception_detail}" if exception_detail else "")
        )
        return (
            f"未能成功讀取《{article_title}》對應的{source_label}（{article_url}）。"
            f"原因：{reason}{detail_line}\n\n"
            "請直接告訴用戶本次自動讀取失敗，並給出簡短替代建議。"
            f"{navigation_hint}{depth_guard}"
        )

    navigation_hint = (
        "Please suggest that the user open the link directly and use page navigation to inspect files, the README, attachments, or more detail."
        if source_type in {"github", "gitlab", "gitee", "zenodo"}
        else "Please suggest that the user open the original link directly for more detail."
    )
    depth_guard = (
        "If this is a repository page, explicitly say that only a lightweight landing-page read was attempted; do not pretend that the full codebase was deeply analyzed."
        if source_type in {"github", "gitlab", "gitee"}
        else "Do not pretend to have read content that was not actually retrieved."
    )
    detail_line = (
        f"\nAdditional detail: {detail}"
        if detail
        else (f"\nAdditional detail: {exception_detail}" if exception_detail else "")
    )
    return (
        f"The {source_label} for '{article_title}' ({article_url}) could not be retrieved automatically. "
        f"Reason: {reason}{detail_line}\n\n"
        "Please tell the user clearly that the automatic read failed and offer a short alternative. "
        f"{navigation_hint} {depth_guard}"
    )


def _is_context_length_exceeded_error(exc: Exception) -> bool:
    """Return True only for explicit upstream context-window overflow errors."""
    pieces = [str(exc)]
    response = getattr(exc, "response", None)
    if response is not None:
        with suppress(Exception):
            if response.text:
                pieces.append(response.text)

    haystack = " ".join(piece for piece in pieces if piece).lower()
    strong_patterns = (
        "maximum context length",
        "context length exceeded",
        "exceeds the model's context length",
        "exceeds model context length",
        "context window",
        "reduce the length of the messages",
        "prompt is too long",
        "input is too long",
        "maximum number of tokens",
    )
    if any(pattern in haystack for pattern in strong_patterns):
        return True

    requested_tokens = "requested" in haystack and "tokens" in haystack
    return requested_tokens and ("context" in haystack or "length" in haystack)


_AUTO_CONTINUE_PROMPTS = {
    "zh_CN": (
        "你上一条回答因为输出长度限制而中断了。请从刚才停止的位置继续，"
        "不要重复已经写过的内容，不要重新开头，不要重复标题。"
        "保持相同语言、结构、引用格式、表格和列表连续性。"
        "如果上一句尚未完成，就从该句继续。直接输出续写内容。"
    ),
    "zh_HK": (
        "你上一條回答因輸出長度限制而中斷了。請從剛才停止的位置繼續，"
        "不要重複已經寫過的內容，不要重新開頭，不要重複標題。"
        "保持相同語言、結構、引用格式、表格和列表連續性。"
        "如果上一句尚未完成，就從該句繼續。直接輸出續寫內容。"
    ),
    "en": (
        "Your previous answer was cut off by the output-length limit. Continue exactly from where you stopped. "
        "Do not repeat earlier content, do not restart, and do not repeat headings. "
        "Preserve the same language, structure, citations, tables, and list continuity. "
        "If the last sentence was incomplete, resume from that sentence. Output only the continuation."
    ),
}
_CONTEXT_COMPACTION_MARKER = (
    "\n\n...[earlier content omitted to fit the model context window]...\n\n"
)
_CONTEXT_RETRY_PLANS = (
    {"recent_messages": 8, "max_chars": 24_000, "pdf_context_chars": 24_000},
    {"recent_messages": 4, "max_chars": 12_000, "pdf_context_chars": 12_000},
)
_MAX_AUTO_CONTINUATIONS = 3


def _message_has_pdf_context(content: object) -> bool:
    raw = extract_text_from_content(content)
    trimmed = raw.strip()
    return trimmed.startswith("[PDF_CONTEXT]") and trimmed.endswith("[/PDF_CONTEXT]")


def _compact_text_for_context_retry(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    marker = _CONTEXT_COMPACTION_MARKER
    if max_chars <= len(marker) + 64:
        return text[:max_chars]

    head_chars = (max_chars - len(marker)) * 2 // 3
    tail_chars = max_chars - len(marker) - head_chars
    if tail_chars < 32:
        tail_chars = 32
        head_chars = max_chars - len(marker) - tail_chars
    return f"{text[:head_chars]}{marker}{text[-tail_chars:]}"


def _compact_message_content_for_context_retry(
    content: object, max_chars: int
) -> object:
    if isinstance(content, str):
        return _compact_text_for_context_retry(content, max_chars)
    if isinstance(content, list):
        compacted_parts: list[object] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                updated_part = dict(part)
                updated_part["text"] = _compact_text_for_context_retry(
                    str(part.get("text", "")), max_chars
                )
                compacted_parts.append(updated_part)
            else:
                compacted_parts.append(deepcopy(part))
        return compacted_parts
    return content


def _build_context_retry_messages(
    messages: list[dict[str, object]], retry_count: int
) -> list[dict[str, object]] | None:
    if retry_count >= len(_CONTEXT_RETRY_PLANS):
        return None

    plan = _CONTEXT_RETRY_PLANS[retry_count]
    keep_indices: set[int] = set()
    pdf_indices: list[int] = []
    non_system_indices: list[int] = []

    for idx, msg in enumerate(messages):
        role = msg.get("role")
        if role == "system":
            keep_indices.add(idx)
            continue
        if _message_has_pdf_context(msg.get("content", "")):
            pdf_indices.append(idx)
            continue
        non_system_indices.append(idx)

    if pdf_indices:
        keep_indices.add(pdf_indices[-1])
    keep_indices.update(non_system_indices[-int(plan["recent_messages"]) :])

    if not keep_indices:
        return None

    compacted_messages: list[dict[str, object]] = []
    changed = len(keep_indices) != len(messages)
    pdf_index_set = set(pdf_indices)

    for idx, msg in enumerate(messages):
        if idx not in keep_indices:
            continue
        cloned = deepcopy(msg)
        max_chars = int(
            plan["pdf_context_chars"] if idx in pdf_index_set else plan["max_chars"]
        )
        compacted_content = _compact_message_content_for_context_retry(
            cloned.get("content", ""), max_chars
        )
        if compacted_content != cloned.get("content"):
            cloned["content"] = compacted_content
            changed = True
        compacted_messages.append(cloned)

    return compacted_messages if changed else None


def _build_auto_continue_messages(
    messages: list[dict[str, object]], partial_response: str, detected_lang: str
) -> list[dict[str, object]]:
    prompt = _AUTO_CONTINUE_PROMPTS.get(detected_lang, _AUTO_CONTINUE_PROMPTS["en"])
    return messages + [
        {"role": "assistant", "content": partial_response},
        {"role": "user", "content": prompt},
    ]


def _should_auto_continue_response(
    response_text: str, was_truncated: bool, continuation_count: int
) -> bool:
    if not was_truncated or continuation_count >= _MAX_AUTO_CONTINUATIONS:
        return False
    stripped = response_text.strip()
    if not stripped:
        return False
    return "[WEB_SEARCH]" not in stripped and "[READ_ARTICLE]" not in stripped


def _should_fallback_from_local_vllm_error(exc: Exception) -> bool:
    """Return True when a local vLLM upstream request failure should trigger remote fallback."""
    return isinstance(exc, httpx.HTTPError)


def _is_segmentation_task(task_type: str | None) -> bool:
    return task_type in SEGMENTATION_TASK_TYPES


def _normalize_label_names(labels: list[str]) -> list[str]:
    return sorted({str(label).strip() for label in labels if str(label).strip()})


def _extract_segmentation_label_names(categories: list[dict[str, object]]) -> list[str]:
    return _normalize_label_names(
        [
            str(category.get("name", "")).strip()
            for category in categories
            if category.get("name")
        ]
    )


async def _get_patch_model_for_chat(
    db: AsyncSession,
    model_id: str,
    user: User,
    inference_type: str,
):
    trained_model = await TrainedModelRepository.get_by_id(db, model_id)
    if not trained_model:
        raise HTTPException(status_code=404, detail="Trained model not found")
    assert_owner(
        str(trained_model.user_id), user, "You don't have permission to use this model"
    )

    training_task = await TrainingTaskRepository.get_by_id(
        db, str(trained_model.task_id)
    )
    if not training_task or not training_task.data_group:
        raise HTTPException(
            status_code=400, detail="Training task metadata is incomplete"
        )

    data_type = training_task.data_group.data_type
    task_type = training_task.data_group.task_type
    if data_type != "patch":
        raise HTTPException(
            status_code=400,
            detail="Only patch models are supported for chat image inference",
        )

    if inference_type == "classification" and _is_segmentation_task(task_type):
        raise HTTPException(
            status_code=400, detail="Selected model is not a patch classification model"
        )
    if inference_type == "segmentation" and not _is_segmentation_task(task_type):
        raise HTTPException(
            status_code=400, detail="Selected model is not a patch segmentation model"
        )

    return trained_model


def _clean_optional_str(value: object) -> str:
    return str(value).strip() if isinstance(value, str) else ""


def _normalize_segmentation_task_config(
    task_config: dict[str, object],
) -> dict[str, object]:
    normalized = dict(task_config)
    normalized["data_type"] = "patch"

    seg_backbone = _clean_optional_str(task_config.get("seg_backbone"))
    encoder = _clean_optional_str(task_config.get("encoder"))
    seg_architecture = _clean_optional_str(task_config.get("seg_architecture"))

    seg_backbone_is_fm = is_fm_segmentation_backbone(seg_backbone)
    encoder_is_fm = is_fm_segmentation_backbone(encoder)

    if seg_backbone_is_fm:
        resolved_backbone = seg_backbone
    elif encoder_is_fm:
        resolved_backbone = encoder
    else:
        resolved_backbone = seg_backbone or encoder

    if resolved_backbone:
        normalized["seg_backbone"] = resolved_backbone

    FM_DECODER_ARCHITECTURES = {
        "linear_decoder",
        "conv_decoder",
        "dpt_decoder",
        "unetr_decoder",
    }
    if is_fm_segmentation_backbone(resolved_backbone):
        if seg_architecture in FM_DECODER_ARCHITECTURES:
            normalized["seg_architecture"] = seg_architecture
        else:
            normalized["seg_architecture"] = "conv_decoder"
    elif seg_architecture:
        normalized["seg_architecture"] = seg_architecture

    _ = normalized.pop("encoder", None)
    return normalized


def _normalize_task_config_blocks(response_text: str) -> str:
    if "[TASK_CONFIG]" not in response_text:
        return response_text

    pattern = re.compile(r"\[TASK_CONFIG\](.*?)\[/TASK_CONFIG\]", re.DOTALL)

    def _replace(match: re.Match[str]) -> str:
        raw_json = match.group(1).strip()
        try:
            task_config = json.loads(raw_json)
        except json.JSONDecodeError:
            return match.group(0)

        if not isinstance(task_config, dict):
            return match.group(0)

        if _is_segmentation_task(task_config.get("task_type")):
            task_config = _normalize_segmentation_task_config(task_config)

        normalized_json = json.dumps(task_config, ensure_ascii=False, indent=2)
        return f"[TASK_CONFIG]\n{normalized_json}\n[/TASK_CONFIG]"

    return pattern.sub(_replace, response_text)


def _format_prompt_number(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        text = str(value).strip()
        return text or None
    if not math.isfinite(number):
        return None
    if number.is_integer():
        return str(int(number))
    if abs(number) >= 1000:
        return f"{number:.1f}"
    if abs(number) >= 1:
        return f"{number:.4f}".rstrip("0").rstrip(".")
    return f"{number:.4g}"


def _shorten_prompt_text(text: str, limit: int = 140) -> str:
    clean = " ".join(str(text).split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3].rstrip() + "..."


def _extract_latest_training_snapshot(logs: list[object]) -> str | None:
    metric_labels = [
        ("train_loss", "train_loss"),
        ("val_loss", "val_loss"),
        ("val_accuracy", "val_accuracy"),
        ("val_acc", "val_accuracy"),
        ("val_auc", "val_auc"),
        ("train_c_index", "train_c_index"),
        ("val_c_index", "val_c_index"),
        ("val_dice", "val_dice"),
        ("val_iou", "val_iou"),
        ("val_mean_iou", "val_mean_iou"),
        ("lr", "lr"),
    ]

    for log in reversed(logs):
        message = str(getattr(log, "message", "") or "").strip()
        metadata = getattr(log, "extra_data", None)
        metadata = metadata if isinstance(metadata, dict) else {}
        epoch_match = _EPOCH_PROGRESS_RE.search(message)

        if not metadata and not epoch_match:
            continue

        summary_parts: list[str] = []
        fold_value = _format_prompt_number(metadata.get("fold"))
        if fold_value:
            summary_parts.append(f"fold={fold_value}")

        epoch_value = _format_prompt_number(metadata.get("epoch"))
        if epoch_value and epoch_match:
            summary_parts.append(f"epoch={epoch_value}/{epoch_match.group(2)}")
        elif epoch_value:
            summary_parts.append(f"epoch={epoch_value}")
        elif epoch_match:
            summary_parts.append(f"epoch={epoch_match.group(1)}/{epoch_match.group(2)}")

        seen_labels = set()
        for key, label in metric_labels:
            if label in seen_labels or key not in metadata:
                continue
            formatted = _format_prompt_number(metadata.get(key))
            if formatted is None:
                continue
            summary_parts.append(f"{label}={formatted}")
            seen_labels.add(label)

        phase = str(metadata.get("phase") or "").strip()
        if phase:
            summary_parts.append(f"phase={phase}")

        if summary_parts:
            return "; ".join(summary_parts)
        if message:
            return f'latest_log="{_shorten_prompt_text(message)}"'

    for log in reversed(logs):
        message = str(getattr(log, "message", "") or "").strip()
        if message:
            return f'latest_log="{_shorten_prompt_text(message)}"'
    return None


def _get_segmentation_model_spec(
    model: Any, training_task: TrainingTask | None
) -> dict[str, str | bool]:
    model_config = (
        training_task.model_config
        if training_task and isinstance(training_task.model_config, dict)
        else {}
    )
    task_architecture = str(model_config.get("architecture") or "").strip()
    task_backbone = str(model_config.get("backbone") or "").strip()
    saved_architecture = str(getattr(model, "aggregator", "") or "").strip()
    saved_backbone = str(getattr(model, "feature_extractor", "") or "").strip()
    is_complete = bool(
        task_architecture and task_backbone and saved_architecture and saved_backbone
    )
    is_consistent = (
        is_complete
        and task_architecture == saved_architecture
        and task_backbone == saved_backbone
    )
    return {
        "task_architecture": task_architecture,
        "task_backbone": task_backbone,
        "saved_architecture": saved_architecture,
        "saved_backbone": saved_backbone,
        "is_complete": is_complete,
        "is_consistent": is_consistent,
    }


# Maximum PDF papers to include in the AI supplement response (awaited tasks).
# ALL PDFs found in search results are started as background tasks (so they get
# cached for follow-up questions), but only the first _MAX_PDFS_SUPPLEMENT are
# awaited and included in the immediate supplement response.
_MAX_PDFS_SUPPLEMENT = 3

# Language-specific PDF supplement prompts (for i18n)
_PDF_SUPPLEMENT_PROMPTS = {
    "en": (
        "Here is the full content from the PDF papers that were being parsed in the background. "
        "Each paper is labelled [Paper N] so you can refer to them by number when the user asks "
        "which paper they mean (e.g. 'the HKUST paper' → look at the title/URL to match). "
        "Please supplement your previous response with specific details and citations from these papers.\n\n"
        "## STRICT GROUNDING RULES (MANDATORY)\n"
        "1. Your answer MUST be based ENTIRELY on the paper content below. "
        "Do NOT use your training knowledge to supplement information not present in the papers.\n"
        "2. Every factual claim MUST include a citation: [N, p.Y] (only when `--- Page Y ---` marker is visible) "
        "or [N] (when no page marker is available). N is the paper number. NEVER guess or invent page numbers.\n"
        "3. If the user asks about information NOT found in the provided paper content, you MUST say: "
        "'I could not find this information in the retrieved paper content. "
        "You can ask me to search specific pages or sections.'\n"
        "4. If a PDF failed to download or parse, you MUST tell the user explicitly. "
        "Do NOT answer from training knowledge as a substitute.\n\n"
        "## IMAGE RULES\n"
        "When a paper's content contains Markdown image links like ![fig](http://...), you MUST "
        "include those links verbatim in your response so the user can see the figures. "
        "Do NOT describe images as a substitute for the actual image link. "
        "If the user asks for a figure but no matching image link appears in the retrieved paper content, "
        "tell the user the current parsed content does not include that figure and avoid guessing.\n\n"
        "## OTHER RULES\n"
        "LONG PAPERS: For papers with many pages, only the beginning, end, and most relevant "
        "middle sections are shown. If the user asks about a section not visible here, tell them "
        "you can search for specific pages or topics if they ask a follow-up question. "
        "Do NOT mention internal parser names, upgrade steps, or GPU/CPU execution details. "
        "If the user asks about processing status, only state whether the PDF is processing, available, or failed. "
        "CRITICAL: The [REFERENCE] blocks in the context are already correctly formatted. "
        "Copy them verbatim into your response - DO NOT modify their format or content."
    ),
    "zh_CN": (
        "以下是后台解析的 PDF 论文完整内容。"
        '每篇论文都标有 [Paper N] 编号，当用户问"哪一篇"时，请通过标题/URL 对应编号来回答。'
        "请用具体细节和论文引用来补充你之前的回答。\n\n"
        "## 严格 Grounding 规则（必须遵守）\n"
        "1. 你的回答**必须完全基于**下方论文内容。**禁止**使用训练知识补充论文中不存在的信息。\n"
        "2. 每个事实性陈述**必须**标注来源：[N, p.Y]（仅当能看到 `--- Page Y ---` 标记时）"
        "或 [N]（无页码标记时）。N 是论文编号。**绝对不要**猜测或捏造页码。\n"
        "3. 如果用户问的信息**不在**已提供的论文内容中，你**必须**说："
        '"我在已检索的论文内容中没有找到这个信息，您可以让我搜索特定页面或章节。"\n'
        "4. 如果某篇 PDF 下载或解析失败，**必须**明确告知用户，**不得**用训练知识替代回答。\n\n"
        "## 图片规则\n"
        "如果论文内容中包含 Markdown 图片链接（如 ![fig](http://...)），你**必须**将这些链接原样放入回答中，"
        "让用户直接看到图片。**不要**用文字描述来替代实际图片链接。"
        "如果用户询问某张图片，但当前检索到的论文内容里没有对应图片链接，请明确说明当前解析内容未包含该图片，禁止猜测。\n\n"
        "## 其他规则\n"
        "长论文提示：对于页数很多的论文，仅展示了开头、结尾和最相关的中间部分。"
        "不要提及内部解析器名称、升级流程或 GPU/CPU 执行细节。"
        "如果用户询问处理状态，只能说明 PDF 处于处理中、可用或失败。"
        "如果用户问到未展示的章节，请告知用户可以通过追问来搜索特定页面或主题。"
        "重要：上下文中的 [REFERENCE] 块格式已正确，请原样复制到回答中，不要修改格式或内容。"
    ),
    "zh_HK": (
        "以下是後台解析的 PDF 論文完整內容。"
        "每篇論文都標有 [Paper N] 編號，當用戶問「哪一篇」時，請透過標題/URL 對應編號來回答。"
        "請用具體細節和論文引用來補充你之前的回答。\n\n"
        "## 嚴格 Grounding 規則（必須遵守）\n"
        "1. 你的回答**必須完全基於**下方論文內容。**禁止**使用訓練知識補充論文中不存在的資訊。\n"
        "2. 每個事實性陳述**必須**標註來源：[N, p.Y]（僅當能看到 `--- Page Y ---` 標記時）"
        "或 [N]（無頁碼標記時）。N 是論文編號。**絕對不要**猜測或捏造頁碼。\n"
        "3. 如果用戶問的資訊**不在**已提供的論文內容中，你**必須**說："
        "「我在已檢索的論文內容中沒有找到這個資訊，您可以讓我搜尋特定頁面或章節。」\n"
        "4. 如果某篇 PDF 下載或解析失敗，**必須**明確告知用戶，**不得**用訓練知識替代回答。\n\n"
        "## 圖片規則\n"
        "如果論文內容中包含 Markdown 圖片連結（如 ![fig](http://...)），你**必須**將這些連結原樣放入回答中，"
        "讓用戶直接看到圖片。**不要**用文字描述來替代實際圖片連結。"
        "如果用戶詢問某張圖片，但當前檢索到的論文內容裡沒有對應圖片連結，請明確說明當前解析內容未包含該圖片，禁止猜測。\n\n"
        "## 其他規則\n"
        "長論文提示：對於頁數很多的論文，僅展示了開頭、結尾和最相關的中間部分。"
        "不要提及內部解析器名稱、升級流程或 GPU/CPU 執行細節。"
        "如果用戶詢問處理狀態，只能說明 PDF 處於處理中、可用或失敗。"
        "如果用戶問到未展示的章節，請告知用戶可以透過追問來搜尋特定頁面或主題。"
        "重要：上下文中的 [REFERENCE] 區塊格式已正確，請原樣複製到回答中，不要修改格式或內容。"
    ),
}

# Language-specific prompts for [READ_ARTICLE] tool — injected when the AI
# explicitly requests to read a full article for the user.
_READ_ARTICLE_PROMPTS = {
    "en": (
        "Here is the full content of the article the user asked to read. "
        "The content includes `--- Page X ---` markers for each page.\n\n"
        "## STRICT GROUNDING RULES (MANDATORY)\n"
        "1. Your answer MUST be based ENTIRELY on the article content below. "
        "Do NOT use your training knowledge to supplement information not present in the article.\n"
        "2. Every factual claim MUST include a citation: [N, p.Y] where N is the search result number "
        "and Y is the page number (only when `--- Page Y ---` marker is visible). "
        "NEVER guess or invent page numbers.\n"
        "3. If asked about information NOT found in the article, say: "
        "'I could not find this information in the retrieved article content.'\n"
        "4. If the article failed to download or parse, tell the user explicitly.\n\n"
        "## IMAGE RULES\n"
        "When the content contains Markdown image links like ![fig](http://...), include them verbatim. "
        "If no matching image link is present for the figure the user asks about, say the current parsed content does not include it.\n\n"
        "## OTHER RULES\n"
        "For long articles, only head/tail sections are shown. If the user asks about a missing section, "
        "tell them to ask a more specific follow-up question.\n"
        "Do NOT mention internal parser names, upgrade steps, or GPU/CPU execution details.\n"
        "If the user asks about processing status, only state whether the PDF is processing, available, or failed.\n"
        "CRITICAL: The [REFERENCE] blocks are already correctly formatted. "
        "Copy them verbatim into your response."
    ),
    "zh_CN": (
        "以下是用户要求阅读的文章完整内容。内容包含 `--- Page X ---` 页码标记。\n\n"
        "## 严格 Grounding 规则（必须遵守）\n"
        "1. 你的回答**必须完全基于**下方文章内容。**禁止**使用训练知识补充。\n"
        "2. 每个事实性陈述**必须**标注来源：[N, p.Y]，其中 N 是搜索结果编号，"
        "Y 是页码（仅当能看到 `--- Page Y ---` 标记时）。**绝对不要**猜测页码。\n"
        "3. 如果用户问的信息**不在**文章内容中，请说："
        '"我在已检索的文章内容中没有找到这个信息。"\n'
        "4. 如果文章下载或解析失败，**必须**明确告知用户。\n\n"
        "## 图片规则\n"
        "如果内容中包含 Markdown 图片链接（如 ![fig](http://...)），请原样放入回答中。"
        "如果用户询问的图片在当前解析内容中没有对应链接，请明确说明当前内容未包含该图片。\n\n"
        "## 其他规则\n"
        "长文章仅展示了开头和结尾部分。如果用户问到未展示的章节，请告知用户提出更具体的问题。\n"
        "不要提及内部解析器名称、升级流程或 GPU/CPU 执行细节。\n"
        "如果用户询问处理状态，只能说明 PDF 处于处理中、可用或失败。\n"
        "重要：[REFERENCE] 块格式已正确，请原样复制到回答中。"
    ),
    "zh_HK": (
        "以下是用戶要求閱讀的文章完整內容。內容包含 `--- Page X ---` 頁碼標記。\n\n"
        "## 嚴格 Grounding 規則（必須遵守）\n"
        "1. 你的回答**必須完全基於**下方文章內容。**禁止**使用訓練知識補充。\n"
        "2. 每個事實性陳述**必須**標註來源：[N, p.Y]，其中 N 是搜尋結果編號，"
        "Y 是頁碼（僅當能看到 `--- Page Y ---` 標記時）。**絕對不要**猜測頁碼。\n"
        "3. 如果用戶問的資訊**不在**文章內容中，請說："
        "「我在已檢索的文章內容中沒有找到這個資訊。」\n"
        "4. 如果文章下載或解析失敗，**必須**明確告知用戶。\n\n"
        "## 圖片規則\n"
        "如果內容中包含 Markdown 圖片連結（如 ![fig](http://...)），請原樣放入回答中。"
        "如果用戶詢問的圖片在當前解析內容中沒有對應連結，請明確說明當前內容未包含該圖片。\n\n"
        "## 其他規則\n"
        "長文章僅展示了開頭和結尾部分。如果用戶問到未展示的章節，請告知用戶提出更具體的問題。\n"
        "不要提及內部解析器名稱、升級流程或 GPU/CPU 執行細節。\n"
        "如果用戶詢問處理狀態，只能說明 PDF 處於處理中、可用或失敗。\n"
        "重要：[REFERENCE] 區塊格式已正確，請原樣複製到回答中。"
    ),
}

_READ_DOCUMENT_PROMPTS = {
    "en": (
        "Here is the retrieved content of the webpage, documentation page, or repository landing page the user asked to read. "
        "The content may be a lightweight extraction rather than a full deep crawl. It includes `--- Page X ---` markers.\n\n"
        "## STRICT GROUNDING RULES (MANDATORY)\n"
        "1. Your answer MUST be based ENTIRELY on the retrieved content below. Do NOT invent details that are not shown.\n"
        "2. Every factual claim MUST include a citation: [N, p.Y] when a `--- Page Y ---` marker is visible, or [N] when only a single lightweight page is available.\n"
        "3. If the user asks for deeper code details, hidden tabs, attached files, or content not shown here, say so explicitly and suggest opening the link directly.\n"
        "4. If this is a repository page, do NOT pretend you deeply analyzed the whole repo; describe only what is visible in the retrieved landing-page / README content.\n"
        "5. If the content failed to download or parse, tell the user explicitly.\n\n"
        "Do NOT mention internal parser names, upgrade steps, or GPU/CPU execution details.\n"
        "CRITICAL: The [REFERENCE] blocks are already correctly formatted. Copy them verbatim into your response."
    ),
    "zh_CN": (
        "以下是用户要求阅读的网页、文档页或仓库落地页内容。"
        "这些内容可能只是轻量提取结果，而不是完整深度抓取；其中包含 `--- Page X ---` 标记。\n\n"
        "## 严格 Grounding 规则（必须遵守）\n"
        "1. 你的回答**必须完全基于**下方已检索内容，**禁止**补充未展示的细节。\n"
        "2. 每个事实性陈述**必须**标注来源：当能看到 `--- Page Y ---` 时使用 [N, p.Y]；如果只有单页轻量内容，可使用 [N]。\n"
        "3. 如果用户追问更深的代码细节、隐藏标签、附件或当前内容未展示的信息，必须明确说明当前内容里没有，并建议用户直接打开链接。\n"
        "4. 如果这是仓库页，不要假装已经深入分析整个仓库；只描述当前提取到的落地页 / README 内容。\n"
        "5. 如果内容下载或解析失败，必须明确告知用户。\n\n"
        "不要提及内部解析器名称、升级流程或 GPU/CPU 执行细节。\n"
        "重要：[REFERENCE] 块格式已正确，请原样复制到回答中。"
    ),
    "zh_HK": (
        "以下是用戶要求閱讀的網頁、文件頁或倉庫落地頁內容。"
        "這些內容可能只是輕量提取結果，而不是完整深度抓取；其中包含 `--- Page X ---` 標記。\n\n"
        "## 嚴格 Grounding 規則（必須遵守）\n"
        "1. 你的回答**必須完全基於**下方已檢索內容，**禁止**補充未展示的細節。\n"
        "2. 每個事實性陳述**必須**標註來源：當能看到 `--- Page Y ---` 時使用 [N, p.Y]；如果只有單頁輕量內容，可使用 [N]。\n"
        "3. 如果用戶追問更深的代碼細節、隱藏標籤、附件或當前內容未展示的資訊，必須明確說明目前內容裡沒有，並建議用戶直接打開連結。\n"
        "4. 如果這是倉庫頁，不要假裝已經深入分析整個倉庫；只描述當前提取到的落地頁 / README 內容。\n"
        "5. 如果內容下載或解析失敗，必須明確告知用戶。\n\n"
        "不要提及內部解析器名稱、升級流程或 GPU/CPU 執行細節。\n"
        "重要：[REFERENCE] 區塊格式已正確，請原樣複製到回答中。"
    ),
}


# Include feedback sub-router
from .chat_feedback import router as chat_feedback_router

router.include_router(chat_feedback_router)


async def stream_ai_response(
    messages: list[dict[str, Any]],
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    detected_lang: str = "en",
    request: Request | None = None,
    disable_web_search: bool = False,
    conversation_mode: ConversationMode = ConversationMode.GENERAL_CHAT,
    timing_request_id: str | None = None,
) -> AsyncIterator[str]:
    """
    Stream AI response using OpenAI-compatible API with Exa search support.
    Priority: Local vLLM (if enabled and online) > OpenRouter (fallback)

    Supports both text-only and multimodal messages.
    Supports web search via Exa API when AI outputs [WEB_SEARCH] blocks.

    When *request* is provided, long-running operations (AI completion,
    Exa search, PDF download/parse) are raced against client disconnect
    so the stop button cancels them immediately.

    Args:
        messages: Chat messages (text or multimodal format)
        api_key: OpenRouter API key (from global settings or env)
        base_url: OpenRouter base URL (from global settings or env)
        model: Model name (from global settings or env)
        request: FastAPI Request for disconnect detection (optional)
    """
    request_id = timing_request_id or "unknown"
    stream_started_at = time.monotonic()
    stage_started_at = stream_started_at
    global_settings = Config.get_global_settings()
    _log_chat_timing(request_id, "stream_config", stage_started_at)

    # Local vLLM settings
    local_vllm_enabled = global_settings.get("local_vllm_enabled", False)
    local_vllm_base_url = global_settings.get(
        "local_vllm_base_url", "http://127.0.0.1:8000/v1"
    )
    local_vllm_model = global_settings.get("local_vllm_model", "")
    local_vllm_api_key = global_settings.get("local_vllm_api_key", "")

    # OpenRouter settings (fallback)
    openrouter_api_key = (
        api_key
        or global_settings.get("openrouter_api_key")
        or os.environ.get("OPENROUTER_API_KEY")
    )
    openrouter_base_url = (
        base_url
        or global_settings.get("openrouter_base_url")
        or os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    )
    openrouter_model = (
        model
        or global_settings.get("openrouter_model")
        or os.environ.get("OPENROUTER_MODEL", "qwen/qwen3.5-plus-02-15")
    )

    # Exa search settings
    exa_api_key = global_settings.get("exa_api_key", "")

    # Determine which API to use
    use_local = False
    detected_model = None
    if local_vllm_enabled and local_vllm_base_url:
        stage_started_at = time.monotonic()
        logger.info(f"Checking local vLLM server at {local_vllm_base_url}...")
        is_available, detected_model = await _check_local_vllm_available(
            local_vllm_base_url, local_vllm_api_key
        )
        _log_chat_timing(
            request_id,
            "local_vllm_probe",
            stage_started_at,
            available=is_available,
        )
        if is_available:
            use_local = True
            logger.info("Local vLLM server is online, using local server")
        else:
            logger.warning("Local vLLM server is offline, falling back to OpenRouter")

    # Determine effective API settings
    effective_model: str = openrouter_model
    effective_base_url: str = str(openrouter_base_url or "")
    effective_api_key: str = str(openrouter_api_key or "")

    if use_local:
        local_model_resolved = local_vllm_model or detected_model
        if local_model_resolved:
            effective_model = local_model_resolved
            effective_base_url = local_vllm_base_url
            effective_api_key = local_vllm_api_key
        else:
            logger.error(
                "No model specified and auto-detect failed, falling back to OpenRouter"
            )
            use_local = False

    if not use_local:
        if not openrouter_api_key:
            # Return error message if no API key is configured
            error_msg = """**AI Configuration Required**

To use the AI assistant, please configure your OpenRouter API key or enable local vLLM server:

1. Click **Settings** in the left sidebar
2. Enter your **OpenRouter API Key** in the configuration form
   - OR enable **Local vLLM Server** and configure the server URL
3. Click **Save Settings**

**Get your API key:** [OpenRouter Console](https://openrouter.ai/keys)

After saving, return here and start chatting!"""

            yield f"data: {json.dumps({'content': error_msg})}\n\n"
            yield "data: [DONE]\n\n"
            return

        effective_model = openrouter_model
        effective_base_url = str(openrouter_base_url or "")
        effective_api_key = str(openrouter_api_key or "")

    provider_name = "Local vLLM" if use_local else "OpenRouter"

    def _switch_to_remote_fallback(reason: Exception, *, stage: str) -> bool:
        nonlocal \
            use_local, \
            effective_model, \
            effective_base_url, \
            effective_api_key, \
            provider_name
        if not use_local or not openrouter_api_key:
            return False
        if not _should_fallback_from_local_vllm_error(reason):
            return False

        logger.warning(
            f"Local vLLM failed during {stage}: {reason}. Falling back to OpenRouter."
        )
        use_local = False
        effective_model = openrouter_model
        effective_base_url = str(openrouter_base_url or "")
        effective_api_key = str(openrouter_api_key or "")
        provider_name = "OpenRouter"
        return True

    # Tool loop also covers automatic continuation / context-compaction retries.
    # Need enough iterations for: search → re-search → read article → auto-continue.
    max_tool_iterations = 8
    current_messages = _prepare_generation_messages(
        messages, detected_lang, disable_web_search, conversation_mode
    )
    _requires_training_recommendation_search = _has_training_recommendation_context(
        current_messages
    )
    article_pdf_content: str | None = (
        None  # raw PDF markdown (with page markers) for citation context extraction
    )
    _per_paper_pdf_content: dict[int, str] | None = (
        None  # per-paper content for multi-paper follow-ups
    )
    _per_paper_source_ids: dict[int, str] | None = (
        None  # stable source ids aligned with per-paper content
    )
    _current_read_reference_card: str | None = None

    # ── Pre-populate PDF context for follow-up citation support ──────────
    # When conversation history contains [PDF_CONTEXT] blocks (from prior
    # article reads), pre-read the full cached markdown so
    # _extract_citation_contexts can work for follow-up questions.
    # Also prepare reference cards for the frontend's citationMap.
    _followup_reference_cards: list[str] = []
    _followup_pdf_urls = _collect_pdf_urls_from_contexts(messages)
    if _followup_pdf_urls:
        stage_started_at = time.monotonic()
        _per_paper_pdf_content = {}
        _per_paper_source_ids = {}
        for idx, url in enumerate(_followup_pdf_urls, 1):
            cached_md = get_cached_markdown(url)
            if cached_md:
                _per_paper_pdf_content[idx] = cached_md
            _per_paper_source_ids[idx] = get_url_hash(url)
            meta = get_cached_pdf_meta(url) or {}
            title = meta.get("title", "Unknown")
            src_type = detect_source_type(url)
            is_acad = meta.get("is_academic", False)
            if not is_acad and cached_md:
                is_acad = is_academic_content(cached_md, src_type)
            _followup_reference_cards.append(
                format_reference_card(title, url, src_type, is_acad)
            )
        if _per_paper_pdf_content:
            # Concatenated content for backward compat (single-paper case)
            article_pdf_content = "\n\n".join(_per_paper_pdf_content.values())
            logger.info(
                f"[FollowUp] Pre-populated article_pdf_content from "
                f"{len(_followup_pdf_urls)} cached PDF(s) for citation support"
            )
        _log_chat_timing(
            request_id,
            "followup_pdf_prep",
            stage_started_at,
            pdfs=len(_followup_pdf_urls),
            cached=len(_per_paper_pdf_content),
        )

    # Track the URL currently being processed so we can clean up on cancel.
    _active_pdf_url: str | None = None

    # When True, the next iteration streams the AI response token-by-token
    # instead of buffering it.  Set after article content is injected so the
    # user sees the summary appear progressively.
    _stream_next_iteration = False
    _response_already_streamed = False
    full_response = ""
    aggregated_response = ""
    _final_response_truncated = False
    _search_count = 0  # Track consecutive web searches to prevent infinite loops
    _search_artifacts_emitted = False
    _MAX_SEARCHES = 2  # Max web searches per user message
    _auto_continue_count = 0
    _context_retry_count = 0

    for iteration in range(max_tool_iterations):
        # ── Streaming path: yield tokens directly to the client ──────────
        if _stream_next_iteration:
            streamed_response = ""
            try:
                response_truncated = False
                iteration_started_at = time.monotonic()
                first_chunk_logged = False
                async for chunk in _stream_from_openai_compatible(
                    messages=current_messages,
                    base_url=effective_base_url,
                    api_key=effective_api_key,
                    model=effective_model,
                    source_name=f"{provider_name} (streaming)",
                ):
                    if not first_chunk_logged:
                        first_chunk_logged = True
                        _log_chat_timing(
                            request_id,
                            "llm_first_chunk_streaming",
                            iteration_started_at,
                            iteration=iteration + 1,
                            provider=provider_name,
                        )
                    # _stream_from_openai_compatible yields SSE lines; forward them
                    if chunk == "data: [DONE]\n\n":
                        break  # we emit our own [DONE] below
                    if chunk.startswith("data: "):
                        try:
                            d = json.loads(chunk[6:])
                            if d.get("response_truncated"):
                                response_truncated = True
                                continue
                            if "content" in d and d["content"] is not None:
                                streamed_response += d["content"]
                        except (json.JSONDecodeError, KeyError):
                            pass
                    yield chunk
                full_response = streamed_response
            except ClientDisconnectedError:
                logger.info(
                    "Client disconnected during streaming AI completion — stopping"
                )
                return
            except Exception as e:
                if not streamed_response and _switch_to_remote_fallback(
                    e, stage="streaming AI completion"
                ):
                    logger.info(
                        "Retrying streaming AI completion with remote fallback after local vLLM failure"
                    )
                    continue
                if _is_context_length_exceeded_error(e):
                    retry_messages = _build_context_retry_messages(
                        current_messages, _context_retry_count
                    )
                    if retry_messages is not None:
                        _context_retry_count += 1
                        current_messages = retry_messages
                        logger.info(
                            "Retrying streaming AI completion after context compaction "
                            f"(attempt {_context_retry_count}/{len(_CONTEXT_RETRY_PLANS)})"
                        )
                        continue
                    logger.warning(
                        f"Context length exceeded during streaming AI completion: {e}"
                    )
                    yield f"data: {json.dumps({'context_limit': True})}\n\n"
                    yield "data: [DONE]\n\n"
                    return
                logger.error(f"Error in streaming AI completion: {e}")
                error_msg = _get_ai_service_error_text(detected_lang)
                yield f"data: {json.dumps({'content': error_msg})}\n\n"
                yield "data: [DONE]\n\n"
                return

            # If the streamed response is empty, emit a fallback so the user
            # isn't left staring at a blank message.
            if not full_response.strip():
                _EMPTY_STREAM_FALLBACK = {
                    "zh_CN": "抱歉，生成回复时出现了问题。请再发一条消息让我重试 😊",
                    "zh_HK": "抱歉，生成回覆時出現了問題。請再發一條訊息讓我重試 😊",
                    "en": "Sorry, something went wrong while generating the response. Please send another message so I can try again 😊",
                }
                fb = _EMPTY_STREAM_FALLBACK.get(
                    detected_lang, _EMPTY_STREAM_FALLBACK["en"]
                )
                logger.warning(
                    f"Streaming path produced empty response — emitting fallback"
                )
                yield f"data: {json.dumps({'content': fb})}\n\n"

            if _should_auto_continue_response(
                full_response, response_truncated, _auto_continue_count
            ):
                aggregated_response += full_response
                current_messages = _build_auto_continue_messages(
                    current_messages, full_response, detected_lang
                )
                _auto_continue_count += 1
                _stream_next_iteration = True
                logger.info(
                    "Auto-continuing truncated streamed response "
                    f"(attempt {_auto_continue_count}/{_MAX_AUTO_CONTINUATIONS})"
                )
                continue

            combined_response = aggregated_response + full_response

            # Streaming path always breaks after emitting — no tool detection needed
            # because the AI was given article content and asked to summarize.
            # Inject CITATION_CONTEXTS before [DONE] if article was read
            if article_pdf_content and combined_response:
                try:
                    ctx = _extract_citation_contexts(
                        combined_response,
                        article_pdf_content,
                        _per_paper_pdf_content,
                        _per_paper_source_ids,
                    )
                    if ctx:
                        ctx_block = f"[CITATION_CONTEXTS]{json.dumps(ctx, ensure_ascii=False)}[/CITATION_CONTEXTS]"
                        yield f"data: {json.dumps({'content': ctx_block})}\n\n"
                except Exception as e:
                    logger.warning(f"Failed to extract citation contexts: {e}")

            # Emit follow-up reference cards so the frontend can build
            # citationMap with paper title/URL for InlineCitation tooltips.
            # Without this, the streaming early-return would skip the
            # _followup_reference_cards emission at the end of the function.
            reference_cards_to_emit = list(_followup_reference_cards)
            if (
                _current_read_reference_card
                and _current_read_reference_card not in reference_cards_to_emit
            ):
                reference_cards_to_emit.append(_current_read_reference_card)
            if reference_cards_to_emit:
                ref_block = "\n".join(reference_cards_to_emit)
                yield f"data: {json.dumps({'content': ref_block})}\n\n"

            if response_truncated and full_response.strip():
                yield f"data: {json.dumps({'response_truncated': True})}\n\n"

            yield "data: [DONE]\n\n"
            return

        # ── Smart streaming: stream tokens, sniff for tool blocks ──────
        # Stream from the API while sniffing the first few tokens to detect
        # tool-call blocks ([WEB_SEARCH], [READ_ARTICLE]).
        # Normal responses are yielded to the client in real-time;
        # tool-call responses are buffered for processing.
        _TOOL_PREFIXES = ("[WEB_SEARCH]", "[READ_ARTICLE]")
        _SNIFF_CHARS = 14

        content_so_far = ""
        pending_sse_chunks: list[str] = []
        decided_streaming = False
        is_streaming_to_client = False
        iteration_response_truncated = False

        try:
            iteration_started_at = time.monotonic()
            first_chunk_logged = False
            async for chunk in _stream_from_openai_compatible(
                messages=current_messages,
                base_url=effective_base_url,
                api_key=effective_api_key,
                model=effective_model,
                source_name=provider_name,
            ):
                if not first_chunk_logged:
                    first_chunk_logged = True
                    _log_chat_timing(
                        request_id,
                        "llm_first_chunk",
                        iteration_started_at,
                        iteration=iteration + 1,
                        provider=provider_name,
                    )
                if chunk == "data: [DONE]\n\n":
                    break

                if chunk.startswith("data: "):
                    try:
                        control_data = json.loads(chunk[6:])
                        if control_data.get("response_truncated"):
                            iteration_response_truncated = True
                            continue
                    except (json.JSONDecodeError, KeyError):
                        pass

                # Accumulate content for tool detection
                if chunk.startswith("data: "):
                    try:
                        d = json.loads(chunk[6:])
                        if "content" in d and d["content"] is not None:
                            content_so_far += d["content"]
                    except (json.JSONDecodeError, KeyError):
                        pass

                if not decided_streaming:
                    pending_sse_chunks.append(chunk)
                    if len(content_so_far) >= _SNIFF_CHARS:
                        decided_streaming = True
                        stripped = content_so_far.lstrip()
                        is_streaming_to_client = _should_stream_sniffed_response(
                            disable_web_search,
                            stripped,
                            _TOOL_PREFIXES,
                        )
                        if is_streaming_to_client:
                            for pc in pending_sse_chunks:
                                yield pc
                            pending_sse_chunks = []
                elif is_streaming_to_client:
                    yield chunk
                # else: buffering for tool processing

        except ClientDisconnectedError:
            logger.info("Client disconnected during AI completion — stopping")
            return
        except Exception as e:
            if not is_streaming_to_client and _switch_to_remote_fallback(
                e, stage="AI completion"
            ):
                logger.info(
                    "Retrying AI completion with remote fallback after local vLLM failure"
                )
                continue
            if _is_context_length_exceeded_error(e):
                retry_messages = _build_context_retry_messages(
                    current_messages, _context_retry_count
                )
                if retry_messages is not None:
                    _context_retry_count += 1
                    current_messages = retry_messages
                    logger.info(
                        "Retrying AI completion after context compaction "
                        f"(attempt {_context_retry_count}/{len(_CONTEXT_RETRY_PLANS)})"
                    )
                    continue
                logger.warning(f"Context length exceeded during AI completion: {e}")
                yield f"data: {json.dumps({'context_limit': True})}\n\n"
                yield "data: [DONE]\n\n"
                return
            logger.error(f"Error in AI completion: {e}")
            error_msg = _get_ai_service_error_text(detected_lang)
            yield f"data: {json.dumps({'content': error_msg})}\n\n"
            yield "data: [DONE]\n\n"
            return

        # Short responses that never crossed the sniff threshold
        if not decided_streaming:
            stripped = content_so_far.lstrip()
            is_streaming_to_client = _should_stream_sniffed_response(
                disable_web_search,
                stripped,
                _TOOL_PREFIXES,
            )
            if is_streaming_to_client:
                for pc in pending_sse_chunks:
                    yield pc
                pending_sse_chunks = []

        full_response = content_so_far
        _final_response_truncated = iteration_response_truncated and bool(
            full_response.strip()
        )

        # Mark if response was already streamed to client.
        # Do NOT break here — always continue to tool detection below.
        # [WEB_SEARCH] / [READ_ARTICLE] blocks may appear after normal text;
        # the frontend strips them from display (AssistantMessage.tsx L496-498).
        if is_streaming_to_client:
            _response_already_streamed = True

        # Check if AI requested web search
        search_match = json.loads("null")
        _search_json_error = False
        try:
            pattern = r"\[WEB_SEARCH\](.*?)\[/WEB_SEARCH\]"
            match = re.search(pattern, full_response, re.DOTALL)
            if match:
                search_match = json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            # #19: AI produced malformed JSON in tool block — flag for retry
            _search_json_error = True
            search_match = None
            logger.warning(
                f"Malformed JSON in [WEB_SEARCH] block: {full_response[:200]}"
            )
        except Exception:
            search_match = None

        # #19: Retry on malformed tool block JSON
        if _search_json_error:
            if disable_web_search:
                cleaned_response = _strip_tool_blocks(full_response)
                if cleaned_response:
                    current_messages = current_messages + [
                        {"role": "assistant", "content": cleaned_response}
                    ]
                    current_messages = current_messages + [
                        {
                            "role": "user",
                            "content": _build_no_web_search_instruction(
                                detected_lang, conversation_mode
                            ),
                        }
                    ]
                continue
            current_messages = current_messages + [
                {"role": "assistant", "content": full_response},
                {
                    "role": "user",
                    "content": (
                        "Your [WEB_SEARCH] tool call contained invalid JSON. "
                        "Please re-format and try again with valid JSON."
                    ),
                },
            ]
            continue

        if search_match:
            query = search_match.get("query", "")
            reason = search_match.get("reason", "")
            ai_num_results = min(int(search_match.get("num_results", 5)), 10)
            if ai_num_results < 1:
                ai_num_results = 5

            if disable_web_search:
                logger.info(
                    f"Blocking [WEB_SEARCH] for mode {conversation_mode.value!r} (query={query!r}, reason={reason!r})"
                )
                cleaned_response = _strip_tool_blocks(full_response)
                if cleaned_response:
                    current_messages = current_messages + [
                        {"role": "assistant", "content": cleaned_response}
                    ]
                current_messages = current_messages + [
                    {
                        "role": "user",
                        "content": _build_no_web_search_instruction(
                            detected_lang, conversation_mode
                        ),
                    },
                ]
                continue

            cached_article_matches = find_cached_articles_by_title(
                query, max_results=ai_num_results
            )
            if cached_article_matches:
                if _response_already_streamed:
                    yield f"data: {json.dumps({'type': 'search_clear'})}\n\n"

                logger.info(
                    f"Using {len(cached_article_matches)} locally cached article match(es) for WEB_SEARCH query: {query}"
                )
                local_search_results = {
                    "query": query,
                    "reason": reason,
                    "source": "local_cache",
                    "results": cached_article_matches,
                }
                yield f"data: {json.dumps({'type': 'web_search_result', 'result': local_search_results})}\n\n"
                _search_artifacts_emitted = True

                local_results_text = _format_search_results_for_ai(local_search_results)
                if len(cached_article_matches) == 1:
                    cache_instruction = (
                        "I found a single strong LOCAL CACHE match for this article request. "
                        "Prefer this cached URL instead of using [WEB_SEARCH] again. "
                        "If the user wants the full article, use the [READ_ARTICLE] tool with this URL."
                    )
                else:
                    cache_instruction = (
                        "I found multiple LOCAL CACHE candidates with the same normalized title. "
                        "Do NOT guess and do NOT use [WEB_SEARCH] again yet. "
                        "If the user did not clearly specify which one they mean, ask a brief clarification question first."
                    )

                current_messages = current_messages + [
                    {"role": "assistant", "content": full_response},
                    {
                        "role": "user",
                        "content": (
                            f"I found locally cached article matches for '{query}':\n{local_results_text}\n\n"
                            f"{cache_instruction}"
                        ),
                    },
                ]
                continue

            # #2: AI wants to search but Exa API key is not configured
            if not exa_api_key:
                logger.warning(
                    "AI requested [WEB_SEARCH] but no Exa API key is configured"
                )
                current_messages = current_messages + [
                    {"role": "assistant", "content": full_response},
                    {
                        "role": "user",
                        "content": (
                            "Web search is currently unavailable (API key not configured). "
                            "Please answer the user's question using your existing knowledge. "
                            "Do NOT attempt to use [WEB_SEARCH] again."
                        ),
                    },
                ]
                continue

            # #4: Enforce search count limit
            _search_count += 1
            if _search_count > _MAX_SEARCHES:
                logger.info(
                    f"Search limit reached ({_MAX_SEARCHES}), forcing AI to answer with existing results"
                )
                current_messages = current_messages + [
                    {"role": "assistant", "content": full_response},
                    {
                        "role": "user",
                        "content": (
                            f"You have already performed {_MAX_SEARCHES} web searches. "
                            "Please synthesize the information from the results you already have "
                            "and provide your answer now. Do NOT search again."
                        ),
                    },
                ]
                continue

            # ── Handle [WEB_SEARCH] ──
            # If text was already streamed before the tool block, tell the
            # frontend to clear it so the search results appear cleanly
            # instead of being concatenated with the initial text.
            if _response_already_streamed:
                yield f"data: {json.dumps({'type': 'search_clear'})}\n\n"

            yield f"data: {json.dumps({'type': 'search_status', 'query': query, 'reason': reason})}\n\n"
            _search_artifacts_emitted = True

            # Execute Exa search
            try:
                search_results = await _run_or_cancel_on_disconnect(
                    _execute_exa_search(query, exa_api_key, num_results=ai_num_results),
                    request,
                )

                # Deduplicate results — the same paper often appears via
                # multiple mirrors (PubMed, nature.com, arxiv, lab pages…).
                search_results["results"] = _deduplicate_search_results(
                    search_results["results"]
                )

                # #1/#5: Handle empty search results explicitly
                if not search_results["results"]:
                    logger.info(f"Exa search returned 0 results for query: {query}")
                    # Emit empty result to frontend so search card shows "no results"
                    web_search_result_block = json.dumps(search_results)
                    yield f"data: {json.dumps({'type': 'web_search_result', 'result': search_results})}\n\n"
                    current_messages = current_messages + [
                        {"role": "assistant", "content": full_response},
                        {
                            "role": "user",
                            "content": (
                                f"The web search for '{query}' returned NO results. "
                                "Please answer the user's question using your existing knowledge, "
                                "or suggest alternative search terms the user could try. "
                                "Do NOT fabricate references or citations."
                            ),
                        },
                    ]
                    continue

                web_search_result_block = json.dumps(search_results)
                yield f"data: {json.dumps({'type': 'web_search_result', 'result': search_results})}\n\n"
                yield f"data: {json.dumps({'type': 'search_phase', 'phase': 'summarizing'})}\n\n"

                # Format search results for AI — include source type hints
                results_text = _format_search_results_for_ai(search_results)

                # Add search results to messages for next AI iteration
                current_messages = current_messages + [
                    {"role": "assistant", "content": full_response},
                    {
                        "role": "user",
                        "content": (
                            f"Here are the search results for '{query}':\n{results_text}\n\n"
                            "NOTE: These results contain SNIPPETS (partial text), NOT full articles. "
                            "Synthesize the information, cite sources using inline [N] references matching the result numbers above, "
                            "and generate [REFERENCE] blocks. "
                            "If the user wants to read a full article, use the [READ_ARTICLE] tool.\n"
                            "IMPORTANT: Each result above includes a 'reference type' hint (paper or webpage). "
                            "Use `type: paper` ONLY for academic papers/journals; use `type: webpage` for GitHub repos, blogs, documentation, HuggingFace, and all other non-academic sources.\n"
                            "CRITICAL: If a blog or other secondary webpage merely discusses a paper, do NOT present that webpage as the original paper or journal source. "
                            "When multiple results refer to the same paper, prefer the academic publisher / journal / PubMed / PMC / arXiv URL for both `[REFERENCE]` and `[READ_ARTICLE]`. "
                            "If you only cite a secondary source, label it honestly as `type: webpage` and describe it as a secondary report, not the original publication."
                        ),
                    },
                ]
                continue

            except ClientDisconnectedError:
                logger.info("Client disconnected during Exa search — stopping")
                return
            except httpx.TimeoutException:
                # #3: Search timeout — update frontend card and let AI answer with existing knowledge
                logger.warning(f"Exa search timed out for query: {query}")
                yield f"data: {json.dumps({'type': 'search_status', 'query': query, 'reason': reason, 'status': 'timeout'})}\n\n"
                current_messages = current_messages + [
                    {"role": "assistant", "content": full_response},
                    {
                        "role": "user",
                        "content": (
                            f"The web search for '{query}' timed out. "
                            "Please answer the user's question using your existing knowledge. "
                            "Do NOT attempt to use [WEB_SEARCH] again."
                        ),
                    },
                ]
                continue
            except Exception as e:
                logger.error(f"Exa search error: {e}")
                # Emit failed status so frontend search card updates
                yield f"data: {json.dumps({'type': 'search_status', 'query': query, 'reason': reason, 'status': 'error'})}\n\n"
                break

        # ── Check for [READ_ARTICLE] ──
        read_article_match = None
        try:
            ra_pattern = r"\[READ_ARTICLE\](.*?)\[/READ_ARTICLE\]"
            ra_match = re.search(ra_pattern, full_response, re.DOTALL)
            if ra_match:
                read_article_match = json.loads(ra_match.group(1).strip())
        except Exception:
            read_article_match = None

        if read_article_match:
            # If text was already streamed before the tool block, clear it.
            if _response_already_streamed:
                yield f"data: {json.dumps({'type': 'search_clear'})}\n\n"

            article_url = read_article_match.get("url", "")
            article_title = read_article_match.get("title", "Unknown")
            article_index = read_article_match.get("index")  # search result number

            if not article_url:
                break

            # Emit PDF_PARSE_STATUS: "downloading" (uncached) or "parsing" (cached)
            has_cache = get_cached_markdown(article_url) is not None
            initial_status = "parsing" if has_cache else "downloading"
            yield f"data: {json.dumps({'type': 'pdf_status', 'url': article_url, 'title': article_title, 'status': initial_status})}\n\n"
            _search_artifacts_emitted = True

            try:
                _active_pdf_url = article_url
                _pdf_task: asyncio.Task[dict[str, Any]] | None = None
                # #22: Run PDF processing as a task and emit heartbeats every
                # 10 s to prevent frontend silence-timeout (~60 s).
                try:
                    _pdf_task = asyncio.create_task(
                        _run_or_cancel_on_disconnect(
                            process_pdf_url(
                                url=article_url,
                                title=article_title,
                                base_url=effective_base_url,
                                api_key=effective_api_key,
                                model=effective_model,
                                use_cache=True,
                            ),
                            request,
                        )
                    )
                    _pdf_task.add_done_callback(_consume_task_exception)
                    _HEARTBEAT_INTERVAL = 10  # seconds
                    while not _pdf_task.done():
                        try:
                            await asyncio.wait_for(
                                asyncio.shield(_pdf_task), timeout=_HEARTBEAT_INTERVAL
                            )
                        except asyncio.TimeoutError:
                            # Task still running — emit heartbeat to keep connection alive
                            yield f"data: {json.dumps({'type': 'pdf_status', 'url': article_url, 'title': article_title, 'status': 'parsing'})}\n\n"
                    pdf_result = await _pdf_task
                finally:
                    _active_pdf_url = None
                    if _pdf_task is not None and not _pdf_task.done():
                        _pdf_task.cancel()
                        with suppress(asyncio.CancelledError, Exception):
                            await _pdf_task

                # For uncached PDFs: transition downloading → parsing → completed
                if not has_cache and pdf_result.get("success"):
                    yield f"data: {json.dumps({'type': 'pdf_status', 'url': article_url, 'title': article_title, 'status': 'parsing'})}\n\n"

                # Emit PDF_PARSE_STATUS: completed or error
                if pdf_result.get("success"):
                    pdf_status = {
                        "url": article_url,
                        "title": article_title,
                        "status": "completed",
                        "from_cache": pdf_result.get("from_cache", False),
                        "parse_method": pdf_result.get("parse_method"),
                    }
                else:
                    pdf_status = {
                        "url": article_url,
                        "title": article_title,
                        "status": pdf_result.get("error", "unknown_error"),
                    }
                yield f"data: {json.dumps({'type': 'pdf_parse_result', 'result': pdf_status})}\n\n"

                if pdf_result.get("success"):
                    # Build article content for AI
                    content = (
                        pdf_result.get("pdf_content") or pdf_result.get("summary") or ""
                    )
                    # 改动 9b: Replace hash-based image filenames with fig-N aliases
                    # (first-read path — same as 改动 9 in _build_merged_pdf_context)
                    _first_read_url_hash = get_url_hash(article_url)
                    content = _replace_images_with_fig_aliases(
                        content, _first_read_url_hash
                    )
                    # Save raw PDF content (with page markers) for citation context extraction
                    article_pdf_content = content
                    _per_paper_pdf_content = {1: content}
                    _per_paper_source_ids = {1: _first_read_url_hash}
                    # Head + tail truncation for long articles
                    _PDF_MAX_CHARS = 40000
                    _PDF_HEAD_CHARS = 28000
                    _PDF_TAIL_CHARS = 12000
                    if len(content) > _PDF_MAX_CHARS:
                        head = content[:_PDF_HEAD_CHARS]
                        tail = content[-_PDF_TAIL_CHARS:]
                        content = (
                            head
                            + "\n\n...[middle pages omitted for length]...\n\n"
                            + tail
                        )

                    # Build metadata
                    page_count = pdf_result.get("page_count")
                    page_info = (
                        f"{page_count} pages" if page_count else "page count unknown"
                    )
                    is_academic = pdf_result.get("is_academic", False)
                    label = "Paper" if is_academic else "Doc"
                    ref_label = (
                        f"[{label}]" if not article_index else f"[{article_index}]"
                    )

                    article_parts = [
                        f"### {ref_label} {article_title}\n"
                        f"- **URL**: {article_url}\n"
                        f"- **Total pages**: {page_info}\n",
                        content,
                    ]
                    if pdf_result.get("reference_card"):
                        article_parts.append(pdf_result["reference_card"])
                        _current_read_reference_card = pdf_result["reference_card"]
                    else:
                        _current_read_reference_card = format_reference_card(
                            article_title,
                            article_url,
                            str(
                                pdf_result.get("source_type")
                                or detect_source_type(article_url)
                            ),
                            bool(pdf_result.get("is_academic", False)),
                        )

                    article_text = "\n".join(article_parts)

                    # Emit PDF context for persistence
                    yield f"data: {json.dumps({'pdf_context': article_text})}\n\n"

                    # Inject article content into conversation
                    prompt_map = (
                        _READ_ARTICLE_PROMPTS
                        if bool(pdf_result.get("is_academic", False))
                        else _READ_DOCUMENT_PROMPTS
                    )
                    read_prompt = prompt_map.get(detected_lang, prompt_map["en"])
                    current_messages = current_messages + [
                        {"role": "assistant", "content": full_response},
                        {"role": "user", "content": f"{read_prompt}\n\n{article_text}"},
                    ]
                    _stream_next_iteration = True
                    continue
                else:
                    # PDF failed — let AI know; use smart-streaming (NOT the
                    # dumb streaming path) so tool blocks like [WEB_SEARCH]
                    # can still be detected if the AI wants to retry.
                    source_type = str(
                        pdf_result.get("source_type") or detect_source_type(article_url)
                    )
                    error_detail = (
                        str(pdf_result.get("error_detail") or "").strip() or None
                    )
                    error_code = str(pdf_result.get("error_code") or "").strip() or None
                    current_messages = current_messages + [
                        {"role": "assistant", "content": full_response},
                        {
                            "role": "user",
                            "content": _build_read_failure_instruction(
                                detected_lang,
                                article_title=article_title,
                                article_url=article_url,
                                source_type=source_type,
                                error_code=error_code,
                                error_detail=error_detail,
                            ),
                        },
                    ]
                    # Keep _stream_next_iteration = False so smart-streaming
                    # can detect any follow-up tool calls (e.g. [WEB_SEARCH]).
                    continue

            except ClientDisconnectedError:
                logger.info(
                    f"Client disconnected during PDF processing ({article_url}) — preserving any completed cache artifacts"
                )
                return
            except Exception as e:
                logger.error(f"READ_ARTICLE error for {article_url}: {e}")
                pdf_status = {
                    "url": article_url,
                    "title": article_title,
                    "status": "download_failed",
                }
                yield f"data: {json.dumps({'type': 'pdf_parse_result', 'result': pdf_status})}\n\n"
                # Add error context so the next AI call can inform the user
                current_messages = current_messages + [
                    {"role": "assistant", "content": full_response},
                    {
                        "role": "user",
                        "content": _build_read_failure_instruction(
                            detected_lang,
                            article_title=article_title,
                            article_url=article_url,
                            source_type=detect_source_type(article_url),
                            error_code="unexpected_error",
                            exception_text=str(e),
                        ),
                    },
                ]
                # Keep _stream_next_iteration = False so smart-streaming
                # can detect any follow-up tool calls (e.g. [WEB_SEARCH]).
                continue

        if (
            _requires_training_recommendation_search
            and _search_count == 0
            and _looks_like_training_model_recommendation_output(full_response)
        ):
            if _response_already_streamed:
                yield f"data: {json.dumps({'content': '__CLEAR_CONTENT__'})}\n\n"
            current_messages = current_messages + [
                {"role": "assistant", "content": full_response},
                {
                    "role": "user",
                    "content": _build_training_recommendation_search_retry_instruction(
                        detected_lang,
                        detect_training_recommendation_profile(full_response),
                    ),
                },
            ]
            continue

        _original_response = full_response

        normalized_response = _normalize_task_config_blocks(full_response)
        if normalized_response != full_response:
            full_response = normalized_response

        if _requires_training_recommendation_search:
            sanitized_response = _sanitize_training_recommendation_output(full_response)
            if sanitized_response != full_response:
                full_response = sanitized_response

        if full_response != _original_response and is_streaming_to_client:
            yield f"data: {json.dumps({'content': '__CLEAR_CONTENT__'})}\n\n"
            _CHUNK_SIZE = 80
            for i in range(0, len(full_response), _CHUNK_SIZE):
                yield f"data: {json.dumps({'content': full_response[i : i + _CHUNK_SIZE]})}\n\n"

        aggregated_response += full_response

        if _should_auto_continue_response(
            full_response, iteration_response_truncated, _auto_continue_count
        ):
            current_messages = _build_auto_continue_messages(
                current_messages, full_response, detected_lang
            )
            _auto_continue_count += 1
            _stream_next_iteration = True
            _response_already_streamed = True
            logger.info(
                "Auto-continuing truncated response "
                f"(attempt {_auto_continue_count}/{_MAX_AUTO_CONTINUATIONS})"
            )
            continue

        _final_response_truncated = iteration_response_truncated and bool(
            full_response.strip()
        )

        # No tool requested — break out of loop
        break

    # ── Emit final AI response ──
    final_response_text = aggregated_response or full_response or ""
    if _requires_training_recommendation_search:
        final_response_text = _sanitize_training_recommendation_output(
            final_response_text
        )

    # If the loop exhausted without streaming a proper response (e.g. the last
    # iteration set _stream_next_iteration but ran out of iterations, or the
    # buffered response is just a raw tool-call block), emit a friendly fallback
    # so the user isn't left staring at a dead chat.
    _has_dangling_tool_block = (
        "[READ_ARTICLE]" in final_response_text or "[WEB_SEARCH]" in final_response_text
    )
    # Trigger fallback when:
    # - Response was NOT streamed and is empty/has dangling tool blocks, OR
    # - Response WAS "streamed" but contained only whitespace (nothing visible)
    _response_effectively_empty = (
        not final_response_text.strip() or _has_dangling_tool_block
    )
    _needs_fallback = (
        (not _response_already_streamed and _response_effectively_empty)
        or (_response_already_streamed and not final_response_text.strip())
    ) and not _search_artifacts_emitted
    if _needs_fallback:
        _FALLBACK_MSGS = {
            "zh_CN": (
                "抱歉，这次请求在处理中断了，未能完整完成。"
                "您可以再发一条消息让我重试，或者换一种说法试试看 😊"
            ),
            "zh_HK": (
                "抱歉，這次請求在處理途中中斷了，未能完整完成。"
                "您可以再發一條訊息讓我重試，或者換一種說法試試看 😊"
            ),
            "en": (
                "Sorry, this request was interrupted before it could finish. "
                "Feel free to send another message so I can try again, "
                "or try rephrasing it 😊"
            ),
        }
        fallback_msg = _FALLBACK_MSGS.get(detected_lang, _FALLBACK_MSGS["en"])
        # Strip the raw tool block from the response — only keep natural text
        if _has_dangling_tool_block:
            cleaned = _strip_tool_blocks(final_response_text)
            if cleaned:
                chunk_size = 80
                for i in range(0, len(cleaned), chunk_size):
                    yield f"data: {json.dumps({'content': cleaned[i : i + chunk_size]})}\n\n"
                yield f"data: {json.dumps({'content': chr(10) + chr(10)})}\n\n"
        yield f"data: {json.dumps({'content': fallback_msg})}\n\n"
        final_response_text = fallback_msg

    elif not _response_already_streamed and final_response_text:
        chunk_size = 80
        for i in range(0, len(final_response_text), chunk_size):
            yield f"data: {json.dumps({'content': final_response_text[i : i + chunk_size]})}\n\n"

    if (
        _final_response_truncated
        and final_response_text.strip()
        and not _needs_fallback
    ):
        yield f"data: {json.dumps({'response_truncated': True})}\n\n"

    # Inject CITATION_CONTEXTS before [DONE] if article was read
    if article_pdf_content and final_response_text:
        try:
            ctx = _extract_citation_contexts(
                final_response_text,
                article_pdf_content,
                _per_paper_pdf_content,
                _per_paper_source_ids,
            )
            if ctx:
                ctx_block = f"[CITATION_CONTEXTS]{json.dumps(ctx, ensure_ascii=False)}[/CITATION_CONTEXTS]"
                yield f"data: {json.dumps({'content': ctx_block})}\n\n"
        except Exception as e:
            logger.warning(f"Failed to extract citation contexts: {e}")

    # Emit reference cards for follow-up messages so frontend can build
    # citationMap with paper title/URL for InlineCitation tooltips.
    reference_cards_to_emit = list(_followup_reference_cards)
    if (
        _current_read_reference_card
        and _current_read_reference_card not in reference_cards_to_emit
    ):
        reference_cards_to_emit.append(_current_read_reference_card)
    if reference_cards_to_emit:
        ref_block = "\n".join(reference_cards_to_emit)
        yield f"data: {json.dumps({'content': ref_block})}\n\n"

    yield "data: [DONE]\n\n"


@router.post("/patch-inference")
async def start_chat_patch_inference(
    req: ChatPatchInferenceRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Start a temporary chat-only patch inference task."""
    conversation = await require_conversation_access(db, req.conversation_id, user)
    if not any(message.id == req.message_id for message in conversation.messages):
        raise HTTPException(status_code=404, detail="Message not found")

    trained_model = await _get_patch_model_for_chat(
        db, req.model_id, user, req.inference_type
    )
    task = await create_chat_patch_task(
        conversation_id=req.conversation_id,
        message_id=req.message_id,
        user_id=str(user.id),
        inference_type=req.inference_type,
        model_id=str(trained_model.model_id),
        model_name=str(trained_model.model_name),
        image_data_url=req.image_data_url,
        source=req.source,
    )
    return task


@router.get("/patch-inference/{task_id}")
async def get_chat_patch_inference_status(
    task_id: str,
    user: User = Depends(current_active_user),
):
    """Get status for a temporary chat-only patch inference task."""
    task = await get_chat_patch_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.user_id != str(user.id) and not user.is_admin():
        raise HTTPException(
            status_code=403, detail="You don't have permission to view this task"
        )
    return task.to_public_dict()


@router.post("/patch-inference/cancel-on-exit")
async def cancel_chat_patch_inference_on_exit(
    req: ChatPatchInferenceExitRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel active chat image inference for a message and persist a localized cancel reply."""
    conversation = await require_conversation_access(db, req.conversation_id, user)

    target_message = next(
        (message for message in conversation.messages if message.id == req.message_id),
        None,
    )
    if not target_message:
        raise HTTPException(status_code=404, detail="Message not found")

    task_snapshots = await cancel_chat_patch_tasks_for_message(
        req.conversation_id, req.message_id
    )
    task_updates = {
        snapshot["task_id"]: snapshot
        for snapshot in task_snapshots
        if snapshot.get("task_id")
    }

    updated_content = _apply_patch_inference_exit_updates(
        target_message.content, task_updates
    )
    updated_message = updated_content != target_message.content
    if updated_message:
        await ChatRepository.update_message(db, req.message_id, updated_content)

    last_message = max(
        conversation.messages, key=lambda message: message.id, default=None
    )
    cancel_message = req.cancel_message.strip()
    added_cancel_message = False
    if cancel_message and not (
        last_message
        and last_message.role == "assistant"
        and (last_message.content or "").strip() == cancel_message
    ):
        await ChatRepository.add_message(
            db,
            {
                "conversation_id": req.conversation_id,
                "role": "assistant",
                "content": cancel_message,
            },
        )
        added_cancel_message = True

    await db.commit()
    return {
        "cancelled_task_count": len(task_snapshots),
        "updated_message": updated_message,
        "added_cancel_message": added_cancel_message,
    }


@router.post("/chat")
async def chat_with_ai(
    req: ChatRequest,
    request: Request,
    user: User = Depends(current_active_user),
    user_id_filter: str | None = Depends(get_user_id_filter),
    db: AsyncSession = Depends(get_db),
):
    """
    Chat with AI assistant (streaming).
    Returns Server-Sent Events (SSE) stream.

    If conversation_id is provided, messages will be persisted to database.

    AI configuration is read from HTTP headers:
    - X-OpenRouter-API-Key: OpenRouter API key
    - X-OpenRouter-Base-URL: OpenRouter base URL
    - X-OpenRouter-Model: Model name
    - X-Language: Frontend i18n language code (e.g. en_US, zh_CN, zh_HK)
    - X-Timezone: IANA timezone string from the browser (e.g. Asia/Shanghai)
    """
    chat_request_id = uuid.uuid4().hex[:8]
    chat_started_at = time.monotonic()
    stage_started_at = chat_started_at

    # Get AI configuration from request headers
    api_key = request.headers.get("X-OpenRouter-API-Key")
    base_url = request.headers.get("X-OpenRouter-Base-URL")
    model = request.headers.get("X-OpenRouter-Model")

    # Read the frontend i18n language preference. Maps frontend codes (en_US / zh_CN / zh_HK)
    # to the backend prompt language codes (en / zh_CN / zh_HK).
    _LANG_HEADER_MAP = {
        "en_US": "en",
        "zh_CN": "zh_CN",
        "zh_HK": "zh_HK",
    }
    ui_lang_header = request.headers.get("X-Language", "")
    ui_lang = _LANG_HEADER_MAP.get(ui_lang_header) if ui_lang_header else None

    if req.conversation_id:
        await require_conversation_access(db, req.conversation_id, user)
    _log_chat_timing(
        chat_request_id,
        "request_auth",
        stage_started_at,
        conversation=bool(req.conversation_id),
    )

    # Resolve current datetime in the user's browser timezone (falls back to UTC).
    tz_header = request.headers.get("X-Timezone", "").strip()
    try:
        user_tz = ZoneInfo(tz_header) if tz_header else ZoneInfo("UTC")
    except ZoneInfoNotFoundError:
        user_tz = ZoneInfo("UTC")
    current_datetime = datetime.now(user_tz).strftime("%Y-%m-%d %H:%M:%S %Z")

    temp_permissions = []
    elevated_dataset_ids = None
    if not user.is_admin():
        stage_started_at = time.monotonic()
        temp_permissions = await DatasetGrantRepository.get_valid_by_user(
            db, str(user.id)
        )
        if temp_permissions:
            elevated_dataset_ids = [
                str(perm.dataset_id)
                for perm in temp_permissions
                if bool(perm.can_read) and perm.is_valid()
            ]
        _log_chat_timing(
            chat_request_id,
            "permission_lookup",
            stage_started_at,
            grants=len(temp_permissions),
        )

    latest_user_text = ""
    recent_user_texts: list[str] = []
    for msg in reversed(req.messages):
        if msg.get("role") == "user":
            _msg_text = extract_text_from_content(msg.get("content", ""))
            if _msg_text.strip():
                if not latest_user_text:
                    latest_user_text = _msg_text
                recent_user_texts.append(_msg_text)
                if len(recent_user_texts) >= 3:
                    break
    inferred_model_filters = _infer_model_request_filters(latest_user_text)
    semantic_query_text = (
        "\n".join(reversed(recent_user_texts))
        if recent_user_texts
        else latest_user_text
    )
    use_semantic_model_ranking = _should_use_semantic_model_ranking(
        latest_user_text,
        inferred_model_filters,
        recent_user_texts,
    )
    models_selection_note = (
        "semantic relevance to current request"
        if use_semantic_model_ranking
        else "most recent training time (newest first)"
    )

    _ctx_cache_uid = str(user.id)
    _ctx_cached = None
    _cached_models_list = "  None - user needs to train a model first"
    _cached_models_count = 0
    _cached_models_shown = 0
    stage_started_at = time.monotonic()
    if user.is_admin():
        _ctx_cached = await get_cached_context_kwargs_admin()
    elif elevated_dataset_ids is None:
        _ctx_cached = await get_cached_context_kwargs(_ctx_cache_uid)

    if _ctx_cached is not None and "other_public_datasets_count" not in _ctx_cached:
        _ctx_cached = None
    if _ctx_cached is not None and _is_truncated_dataset_context(
        _ctx_cached.get("datasets_list")
    ):
        _ctx_cached = None
    _log_chat_timing(
        chat_request_id,
        "context_cache_read",
        stage_started_at,
        cache="hit" if _ctx_cached is not None else "miss",
        semantic=use_semantic_model_ranking,
    )

    if _ctx_cached is not None:
        _cached_models_count = _ctx_cached.get("trained_models_total", 0)
        _model_summaries_from_cache = _ctx_cached.get("model_summaries") or []
        if _model_summaries_from_cache:
            _summaries_for_ranking = _model_summaries_from_cache
            if inferred_model_filters:
                _pre_filtered = [
                    s
                    for s in _model_summaries_from_cache
                    if _matches_model_request_filters(s, inferred_model_filters)
                ]
                if _pre_filtered:
                    _summaries_for_ranking = _pre_filtered
            if use_semantic_model_ranking:
                stage_started_at = time.monotonic()
                _cached_model_entries = await asyncio.to_thread(
                    _semantic_top_k_models,
                    semantic_query_text,
                    _summaries_for_ranking,
                )
                _log_chat_timing(
                    chat_request_id,
                    "semantic_rank_cached",
                    stage_started_at,
                    models=len(_summaries_for_ranking),
                )
            else:
                _cached_model_entries = _summaries_for_ranking[
                    :TOP_K_MODELS_IN_CHAT_CONTEXT
                ]
            _cached_models_list = (
                "\n".join(s["line"] for s in _cached_model_entries)
                if _cached_model_entries
                else "  None - user needs to train a model first"
            )
            _cached_models_shown = len(_cached_model_entries)

    gpu_summary = (
        get_gpu_summary_for_prompt()
        if user.is_admin()
        else "GPU details hidden for non-admin users"
    )
    user_role = user.role
    can_use_gpu_base = user.can_use_gpu()

    if temp_permissions:
        _tp_dataset_ids = [str(perm.dataset_id) for perm in temp_permissions]
        _tp_datasets = await DatasetRepository.get_by_ids(db, _tp_dataset_ids)
        _tp_dataset_map = {d.dataset_id: d for d in _tp_datasets}
        _tp_details = []
        for perm in temp_permissions:
            _tp_ds = _tp_dataset_map.get(perm.dataset_id)
            _tp_ds_name = _tp_ds.name if _tp_ds else "Unknown Dataset"
            _perm_expires_at = getattr(perm, "expires_at", None)
            _tp_expires = (
                f", expires: {_perm_expires_at.strftime('%Y-%m-%d %H:%M UTC')}"
                if _perm_expires_at is not None
                else ", no expiration"
            )
            _tp_grants = []
            if bool(perm.can_use_gpu):
                _tp_grants.append("gpu")
            if bool(perm.can_collaborate):
                _tp_grants.append("annotate")
            _tp_grant_label = ", ".join(_tp_grants) if _tp_grants else "none"
            _tp_details.append(
                f"  - **{_tp_ds_name}** (dataset_id={perm.dataset_id}): grants={_tp_grant_label}{_tp_expires}"
            )
        temp_perms_list = "\n".join(_tp_details)
    else:
        temp_perms_list = "  None"

    if _ctx_cached is not None:
        _cached_datasets_list = _ctx_cached.get("datasets_list", "  None")
        _cached_dataset_lines = (
            _cached_datasets_list.splitlines()
            if isinstance(_cached_datasets_list, str)
            else []
        )
        _prioritized_cached = _prioritize_dataset_lines_for_query(
            _cached_dataset_lines, latest_user_text
        )
        user_data_context = format_user_data_context(
            wsi_count=_ctx_cached.get("wsi_count", 0),
            data_types_info=_ctx_cached.get("data_types_info", "None"),
            datasets_list=_format_chat_dataset_list(_prioritized_cached),
            models_count=_cached_models_count,
            models_list=_cached_models_list,
            models_shown=_cached_models_shown,
            models_selection_note=models_selection_note,
            training_tasks_total=_ctx_cached.get("training_tasks_total", 0),
            training_tasks_completed=_ctx_cached.get("training_tasks_completed", 0),
            training_tasks_running=_ctx_cached.get("training_tasks_running", 0),
            training_tasks_failed=_ctx_cached.get("training_tasks_failed", 0),
            training_tasks_list=_ctx_cached.get(
                "training_tasks_list",
                "  None - user has not created any training tasks yet",
            ),
            inference_tasks_total=_ctx_cached.get("inference_tasks_total", 0),
            inference_tasks_completed=_ctx_cached.get("inference_tasks_completed", 0),
            inference_tasks_running=_ctx_cached.get("inference_tasks_running", 0),
            inference_tasks_list=_ctx_cached.get(
                "inference_tasks_list",
                "  None - user has not run any inference tasks yet",
            ),
            gpu_summary=gpu_summary,
            user_role=user_role,
            is_admin=user.is_admin(),
            can_use_gpu_base=can_use_gpu_base,
            temp_perms_list=temp_perms_list,
            own_public_datasets_count=_ctx_cached.get("own_public_datasets_count", 0),
            own_private_datasets_count=_ctx_cached.get("own_private_datasets_count", 0),
            elevated_datasets_count=_ctx_cached.get("elevated_datasets_count", 0),
            other_public_datasets_count=_ctx_cached.get(
                "other_public_datasets_count", 0
            ),
            current_datetime=current_datetime,
        )
    else:
        _uid = user_id_filter
        _eids = elevated_dataset_ids

        async def _with_new_session(coro_factory):
            async with async_session() as _s:
                return await coro_factory(_s)

        stage_started_at = time.monotonic()
        (
            _fb_stats,
            _fb_trained_models,
            _fb_trained_models_total,
            _fb_training_tasks,
            _fb_training_tasks_stats,
            _fb_inference_tasks,
            _fb_inference_tasks_stats,
        ) = await asyncio.gather(
            _with_new_session(
                lambda s: WSIRepository.get_chat_context_stats(
                    s, user_id=_uid, elevated_dataset_ids=_eids
                )
            ),
            _with_new_session(
                lambda s: TrainedModelRepository.get_all(
                    s, limit=200, offset=0, user_id=_uid
                )
            ),
            _with_new_session(lambda s: TrainedModelRepository.count(s, user_id=_uid)),
            _with_new_session(
                lambda s: TrainingTaskRepository.get_all(
                    s, limit=10, offset=0, user_id=_uid
                )
            ),
            _with_new_session(
                lambda s: TrainingTaskRepository.get_status_counts(s, user_id=_uid)
            ),
            _with_new_session(
                lambda s: AITaskRepository.get_recent(s, limit=10, user_id=_uid)
            ),
            _with_new_session(
                lambda s: AITaskRepository.get_status_counts(s, user_id=_uid)
            ),
        )
        _log_chat_timing(
            chat_request_id,
            "context_rebuild_core_queries",
            stage_started_at,
            models=len(_fb_trained_models),
            elevated=bool(_eids),
        )

        _fb_wsi_count = _fb_stats.get("total_count", 0)
        _fb_data_type_dist = _fb_stats.get("data_types", {})
        _fb_wsi_val = _fb_data_type_dist.get("wsi", 0)
        _fb_patch_val = _fb_data_type_dist.get("patch", 0)
        if _fb_wsi_val > 0 and _fb_patch_val > 0:
            _fb_data_types_info = f"WSI: {_fb_wsi_val}, Patches: {_fb_patch_val}"
        elif _fb_wsi_val > 0:
            _fb_data_types_info = f"WSI only: {_fb_wsi_val}"
        elif _fb_patch_val > 0:
            _fb_data_types_info = f"Patches only: {_fb_patch_val}"
        else:
            _fb_data_types_info = "None"

        _fb_own_public = 0
        _fb_own_private = 0
        _fb_elevated = 0
        _fb_other_public = 0
        _fb_datasets_details = []
        for _d in _fb_stats.get("datasets") or []:
            _d_access = _d.get("access_type", "own")
            _d_name = _d.get("dataset_name", "unknown")
            _d_id = _d.get("dataset_id", "unknown")
            _d_fc = _d.get("file_count", 0)
            _d_type = _d.get("data_type", "unknown")
            if _d_access == "elevated":
                _fb_elevated += 1
                _d_marker = " [ELEVATED ACCESS - temporary permission]"
            elif _d_access == "public":
                _fb_other_public += 1
                _d_marker = " [PUBLIC ACCESS - shared by other user]"
            elif _d_access == "other_user":
                _d_marker = " [OTHER USER'S DATA - admin view]"
            else:
                if _d.get("is_public"):
                    _fb_own_public += 1
                else:
                    _fb_own_private += 1
                _d_marker = ""
            _d_source = _d.get("source_organ") or "unknown"
            _d_task_type = _d.get("group_task_type")
            _d_task_type_suffix = f", task_type={_d_task_type}" if _d_task_type else ""
            _d_labels_suffix = ""
            _d_labels = _d.get("labels") or {}
            if _d_labels:
                _d_label_parts = [
                    f"{lbl}:{cnt}" for lbl, cnt in sorted(_d_labels.items())
                ]
                _d_labels_suffix = f", labels={{{', '.join(_d_label_parts)}}}"
            _d_survival_suffix = ""
            _d_survival = _d.get("survival_count", 0)
            if _d_survival:
                _d_event_dist = _d.get("event_status") or {}
                _d_ev = _d_event_dist.get("event", 0)
                _d_cens = _d_event_dist.get("censored", 0)
                _d_survival_suffix = (
                    f", survival_data={_d_survival} (event={_d_ev}, censored={_d_cens})"
                )
            _d_split_suffix = ""
            if _d.get("has_predefined_splits"):
                _d_sc = _d.get("predefined_split_counts", {})
                _d_unit = "cases" if _d.get("aggregation_level") == "case" else "slides"
                _d_split_suffix = (
                    f", predefined_split_distribution({_d_unit}):"
                    f" train={_d_sc.get('train', 0)}, val={_d_sc.get('val', 0)}, test={_d_sc.get('test', 0)}"
                )
            _d_unlabeled_suffix = (
                " [UNLABELED - eligible for batch inference]"
                if _d.get("is_unlabeled")
                else ""
            )
            _fb_datasets_details.append(
                f"  - {_d_name} (dataset_id={_d_id}): {_d_fc} files, type={_d_type}, source={_d_source}{_d_task_type_suffix}{_d_labels_suffix}{_d_survival_suffix}{_d_marker}{_d_split_suffix}{_d_unlabeled_suffix}"
            )
        _prioritized_fb = _prioritize_dataset_lines_for_query(
            _fb_datasets_details, latest_user_text
        )
        _fb_datasets_list = _format_chat_dataset_list(_prioritized_fb)
        _fb_datasets_list_for_cache = (
            "\n".join(_fb_datasets_details) if _fb_datasets_details else "  None"
        )

        _fb_task_ids = list({str(m.task_id) for m in _fb_trained_models if m.task_id})
        _fb_task_meta: dict[str, tuple[str, str, str]] = {}
        if _fb_task_ids:
            stage_started_at = time.monotonic()
            async with async_session() as _fb_db:
                _fb_stmt = (
                    sa_select(TrainingTask)
                    .options(selectinload(TrainingTask.data_group))
                    .where(TrainingTask.task_id.in_(_fb_task_ids))
                )
                _fb_result = await _fb_db.execute(_fb_stmt)
                for _fb_task in _fb_result.scalars().all():
                    _fb_dg = _fb_task.data_group
                    _fb_task_meta[str(_fb_task.task_id)] = (
                        str((_fb_dg.task_type if _fb_dg else None) or "unknown"),
                        str((_fb_dg.data_type if _fb_dg else None) or "unknown"),
                        str(_fb_task.task_name or ""),
                    )
            _log_chat_timing(
                chat_request_id,
                "context_rebuild_task_meta",
                stage_started_at,
                tasks=len(_fb_task_ids),
            )

        _fb_source_dataset_ids: dict[str, str | None] = {}
        _fb_dataset_names: dict[str, str] = {}
        if _fb_task_ids:
            stage_started_at = time.monotonic()
            async with async_session() as _fb_ds_db:
                _fb_source_dataset_ids = (
                    await TrainingTaskRepository.get_source_dataset_ids_batch(
                        _fb_ds_db, _fb_task_ids
                    )
                )
                _fb_unique_ds_ids = [
                    str(v) for v in _fb_source_dataset_ids.values() if v is not None
                ]
                if _fb_unique_ds_ids:
                    _fb_ds_list = await DatasetRepository.get_by_ids(
                        _fb_ds_db, _fb_unique_ds_ids
                    )
                    _fb_dataset_names = {
                        str(d.dataset_id): str(d.name)
                        for d in _fb_ds_list
                        if d.dataset_id is not None
                    }
            _log_chat_timing(
                chat_request_id,
                "context_rebuild_dataset_meta",
                stage_started_at,
                datasets=len(_fb_dataset_names),
            )

        _fb_model_summaries = []
        for _m in _fb_trained_models:
            _m_tt, _m_dt, _m_tn = _fb_task_meta.get(
                str(_m.task_id) if _m.task_id else "",
                ("unknown", "unknown", ""),
            )
            _fb_ds_id = (
                _fb_source_dataset_ids.get(str(_m.task_id)) if _m.task_id else None
            )
            _fb_ds_name = _fb_dataset_names.get(_fb_ds_id, "") if _fb_ds_id else ""
            _fb_model_summaries.append(
                {
                    "id": _m.model_id,
                    "task_type": _m_tt,
                    "data_type": _m_dt,
                    "classes": [c.lower() for c in (_m.classes or [])],
                    "source_dataset_id": _fb_ds_id,
                    "dataset_names": [_fb_ds_name] if _fb_ds_name else [],
                    "dataset_sources": [],
                    "task_name": _m_tn.lower(),
                    "line": f"  - {_m.model_name} (id={_m.model_id}, task_type={_m_tt}, data_type={_m_dt}, trained_on_task={_m.task_id}, task_name={_m_tn or 'unknown'}, feature_extractor={_m.feature_extractor or 'unknown'}, aggregator={_m.aggregator or 'unknown'}, classes={[c.lower() for c in (_m.classes or [])]}, dataset={_fb_ds_name or 'unknown'})",
                    "embedding": None,
                }
            )

        if _fb_model_summaries:
            try:
                stage_started_at = time.monotonic()
                module_name = ".".join(("gateway", "routes", "chat_pdf_vectorstore"))
                _ctx_embed_texts = import_module(module_name)._embed_texts

                _fb_lines_for_embed = [s["line"] for s in _fb_model_summaries]
                _fb_vecs = await asyncio.to_thread(
                    _ctx_embed_texts, _fb_lines_for_embed
                )
                for _fb_i, _fb_s in enumerate(_fb_model_summaries):
                    _fb_s["embedding"] = _fb_vecs[_fb_i].tolist()
                _log_chat_timing(
                    chat_request_id,
                    "context_rebuild_embeddings",
                    stage_started_at,
                    models=len(_fb_model_summaries),
                )
            except Exception as _fb_emb_exc:
                _log_chat_timing(
                    chat_request_id,
                    "context_rebuild_embeddings_failed",
                    stage_started_at,
                    models=len(_fb_model_summaries),
                )
                logger.warning(
                    f"[ChatCtxFallback] model embedding failed: {_fb_emb_exc}"
                )

        if _fb_model_summaries:
            _fb_summaries_for_ranking = _fb_model_summaries
            if inferred_model_filters:
                _fb_pre_filtered = [
                    s
                    for s in _fb_model_summaries
                    if _matches_model_request_filters(s, inferred_model_filters)
                ]
                if _fb_pre_filtered:
                    _fb_summaries_for_ranking = _fb_pre_filtered
            if use_semantic_model_ranking:
                stage_started_at = time.monotonic()
                _fb_models_list_entries = await asyncio.to_thread(
                    _semantic_top_k_models,
                    semantic_query_text,
                    _fb_summaries_for_ranking,
                )
                _log_chat_timing(
                    chat_request_id,
                    "semantic_rank_rebuilt",
                    stage_started_at,
                    models=len(_fb_summaries_for_ranking),
                )
            else:
                _fb_models_list_entries = _fb_summaries_for_ranking[
                    :TOP_K_MODELS_IN_CHAT_CONTEXT
                ]
        else:
            _fb_models_list_entries = []

        _fb_models_list = (
            "\n".join(s["line"] for s in _fb_models_list_entries)
            if _fb_models_list_entries
            else "  None - user needs to train a model first"
        )
        _fb_models_count = _fb_trained_models_total
        _fb_models_shown = len(_fb_models_list_entries)

        _fb_training_total = _fb_training_tasks_stats.get("total", 0)
        _fb_training_completed = _fb_training_tasks_stats.get("completed", 0)
        _fb_training_running = _fb_training_tasks_stats.get("running", 0)
        _fb_training_failed = _fb_training_tasks_stats.get("failed", 0)
        if _fb_training_tasks:
            _fb_training_list = "\n".join(
                f"  - [{str(t.status).upper()}] {t.task_name} (id={t.task_id})"
                for t in _fb_training_tasks
            )
        else:
            _fb_training_list = "  None - user has not created any training tasks yet"

        _fb_inference_total = _fb_inference_tasks_stats.get("total", 0)
        _fb_inference_completed = _fb_inference_tasks_stats.get("completed", 0)
        _fb_inference_running = _fb_inference_tasks_stats.get("running", 0)
        if _fb_inference_tasks:
            _fb_inference_list = "\n".join(
                f"  - [{str(t.status).upper()}] {t.task_type} on {t.wsi_id} (id={t.task_id})"
                for t in _fb_inference_tasks
            )
        else:
            _fb_inference_list = "  None - user has not run any inference tasks yet"

        user_data_context = format_user_data_context(
            wsi_count=_fb_wsi_count,
            data_types_info=_fb_data_types_info,
            datasets_list=_fb_datasets_list,
            models_count=_fb_models_count,
            models_list=_fb_models_list,
            models_shown=_fb_models_shown,
            models_selection_note=models_selection_note,
            training_tasks_total=_fb_training_total,
            training_tasks_completed=_fb_training_completed,
            training_tasks_running=_fb_training_running,
            training_tasks_failed=_fb_training_failed,
            training_tasks_list=_fb_training_list,
            inference_tasks_total=_fb_inference_total,
            inference_tasks_completed=_fb_inference_completed,
            inference_tasks_running=_fb_inference_running,
            inference_tasks_list=_fb_inference_list,
            gpu_summary=gpu_summary,
            user_role=user_role,
            is_admin=user.is_admin(),
            can_use_gpu_base=can_use_gpu_base,
            temp_perms_list=temp_perms_list,
            own_public_datasets_count=_fb_own_public,
            own_private_datasets_count=_fb_own_private,
            elevated_datasets_count=_fb_elevated,
            other_public_datasets_count=_fb_other_public,
            current_datetime=current_datetime,
        )

        _fb_cache_payload = {
            "wsi_count": _fb_wsi_count,
            "data_types_info": _fb_data_types_info,
            "datasets_list": _fb_datasets_list_for_cache,
            "own_public_datasets_count": _fb_own_public,
            "own_private_datasets_count": _fb_own_private,
            "elevated_datasets_count": _fb_elevated,
            "other_public_datasets_count": _fb_other_public,
            "trained_models_total": _fb_trained_models_total,
            "model_summaries": _fb_model_summaries,
            "training_tasks_total": _fb_training_total,
            "training_tasks_completed": _fb_training_completed,
            "training_tasks_running": _fb_training_running,
            "training_tasks_failed": _fb_training_failed,
            "training_tasks_list": _fb_training_list,
            "inference_tasks_total": _fb_inference_total,
            "inference_tasks_completed": _fb_inference_completed,
            "inference_tasks_running": _fb_inference_running,
            "inference_tasks_list": _fb_inference_list,
        }
        if user.is_admin():
            stage_started_at = time.monotonic()
            await set_cached_context_kwargs_admin(_fb_cache_payload)
        elif elevated_dataset_ids is None:
            stage_started_at = time.monotonic()
            await set_cached_context_kwargs(_ctx_cache_uid, _fb_cache_payload)
        else:
            stage_started_at = 0.0
        if stage_started_at:
            _log_chat_timing(chat_request_id, "context_cache_write", stage_started_at)

    # Log the user_data_context for debugging
    # logger.info(f"[Chat] User data context for agent:\n{user_data_context}")

    # Determine language for system prompt.
    # Priority: explicit X-Language header (user's i18n setting) > content-based heuristic.
    detected_lang, last_user_text = _resolve_prompt_language_and_user_text(
        req.messages, ui_lang
    )

    # Add system prompt if not present
    messages = req.messages.copy()
    if not messages or messages[0].get("role") != "system":
        stage_started_at = time.monotonic()
        # Load language-specific system prompt from template file
        base_system_prompt = get_chat_system_prompt(detected_lang, user_text=last_user_text)

        system_prompt = {
            "role": "system",
            "content": base_system_prompt + user_data_context,
        }
        messages.insert(0, system_prompt)
        _log_chat_timing(
            chat_request_id,
            "system_prompt_build",
            stage_started_at,
            chars=len(system_prompt["content"]),
        )

    if req.conversation_id and len(req.messages) > 0 and not req.regenerate_message_id:
        last_user_message = req.messages[-1]
        if last_user_message.get("role") == "user":
            stage_started_at = time.monotonic()
            content = last_user_message.get("content", "")
            text_content = extract_text_from_content(content)
            images = _extract_images_from_content(content)
            message_data: dict[str, Any] = {
                "conversation_id": req.conversation_id,
                "role": "user",
                "content": text_content,
            }
            if images:
                message_data["extra_metadata"] = {"images": images}
            await ChatRepository.add_message(db, message_data)
            await db.commit()
            _log_chat_timing(chat_request_id, "persist_user_message", stage_started_at)

    # ── BM25-enhanced PDF context for follow-up questions ────────────────────
    # Collect ALL [PDF_CONTEXT] blocks from conversation history, merge them
    # into a single unified view with global paper numbering, then replace all
    # original blocks with the merged version.
    all_pdf_urls = _collect_pdf_urls_from_contexts(messages)

    user_query_for_bm25 = ""
    if all_pdf_urls:
        for msg in reversed(messages):
            if msg.get("role") == "user":
                txt = extract_text_from_content(msg.get("content", ""))
                if not txt.strip().startswith("[PDF_CONTEXT]"):
                    user_query_for_bm25 = txt
                    break

    if user_query_for_bm25 and all_pdf_urls:
        stage_started_at = time.monotonic()
        merged_ctx = await asyncio.to_thread(
            _build_merged_pdf_context, all_pdf_urls, user_query_for_bm25, detected_lang
        )
        _log_chat_timing(
            chat_request_id,
            "pdf_bm25_merge",
            stage_started_at,
            pdfs=len(all_pdf_urls),
        )
        merged_content = f"[PDF_CONTEXT]\n{merged_ctx}\n[/PDF_CONTEXT]"

        # Remove all old [PDF_CONTEXT] messages
        _pdf_ctx_re = re.compile(r"\[PDF_CONTEXT\]\n?[\s\S]*?\n?\[/PDF_CONTEXT\]")
        first_ctx_idx: int | None = None
        indices_to_remove: list[int] = []
        for i, msg in enumerate(messages):
            if msg.get("role") != "user":
                continue
            raw = extract_text_from_content(msg.get("content", ""))
            if _pdf_ctx_re.search(raw):
                if first_ctx_idx is None:
                    first_ctx_idx = i
                else:
                    indices_to_remove.append(i)

        # Replace the first block with the merged version; remove the rest
        if first_ctx_idx is not None:
            messages[first_ctx_idx] = {
                **messages[first_ctx_idx],
                "content": merged_content,
            }
            for idx in reversed(indices_to_remove):
                messages.pop(idx)

        logger.info(
            f"[BM25] Merged {len(all_pdf_urls)} documents into unified PDF context "
            f"for follow-up query: '{user_query_for_bm25[:80]}...'"
        )

    # ── Evidence-backed training recommendation context ──────────────────────
    training_recommendation_profile: str | None = None
    conversation_mode = detect_conversation_mode(req.messages)
    search_policy = resolve_search_policy(conversation_mode)
    disable_web_search = search_policy == SearchPolicy.DENY
    if (
        looks_like_training_recommendation_query(latest_user_text)
        and not disable_web_search
    ):
        stage_started_at = time.monotonic()
        training_recommendation_profile = detect_training_recommendation_profile(
            latest_user_text
        )
        bundled_ctx = await build_training_recommendation_evidence_context(
            latest_user_text, detected_lang
        )
        _log_chat_timing(
            chat_request_id,
            "training_evidence_context",
            stage_started_at,
            profile=training_recommendation_profile,
        )

        training_context_message = {
            "role": "user",
            "content": _build_training_recommendation_context_block(
                bundled_ctx,
                detected_lang,
                training_recommendation_profile,
            ),
        }

        last_user_idx = None
        for idx in range(len(messages) - 1, -1, -1):
            if messages[idx].get("role") == "user":
                last_user_idx = idx
                break
        if last_user_idx is not None:
            messages.insert(last_user_idx, training_context_message)
        else:
            messages.append(training_context_message)

    # Stream AI response
    def _prepare_content_for_persistence(content: str) -> str:
        if _has_training_recommendation_context(messages):
            content = _sanitize_training_recommendation_output(content)
        return content.strip()

    async def stream_with_persistence():
        """Stream AI response and save to database if conversation_id is provided.

        Uses try/finally to ensure partial responses are saved even when the
        client disconnects mid-stream (e.g. user navigates away during PDF
        parsing).  Without this, the assistant message is lost and the UI shows
        a broken state when the user returns.
        """
        # Liveness signals: keep the SSE stream alive during context assembly
        # and confirm to the client that the LLM call is about to start. These
        # events contain no prompt content or model output.
        yield f"data: {json.dumps({'type': 'pre_gen_status', 'phase': 'context_load'}, ensure_ascii=False)}\n\n"
        full_response = ""
        saved_to_db = False  # Track whether we already persisted via [DONE]
        first_stream_chunk_logged = False
        try:
            yield f"data: {json.dumps({'type': 'pre_gen_status', 'phase': 'llm_start'}, ensure_ascii=False)}\n\n"
            async for chunk in stream_ai_response(
                messages,
                api_key,
                base_url,
                model,
                detected_lang,
                request,
                disable_web_search=disable_web_search,
                conversation_mode=conversation_mode,
                timing_request_id=chat_request_id,
            ):
                if not first_stream_chunk_logged:
                    first_stream_chunk_logged = True
                    _log_chat_timing(
                        chat_request_id,
                        "first_sse_chunk",
                        chat_started_at,
                    )
                # Intercept pdf_context event: persist it as a hidden user message,
                # and also forward the event so the frontend can mirror that hidden
                # state locally for immediate follow-up questions.
                if chunk.startswith("data: ") and chunk != "data: [DONE]\n\n":
                    try:
                        data = json.loads(chunk[6:])
                        if "pdf_context" in data:
                            if req.conversation_id:
                                async for db_session in get_db():
                                    try:
                                        message_data = {
                                            "conversation_id": req.conversation_id,
                                            "role": "user",
                                            "content": f"[PDF_CONTEXT]\n{data['pdf_context']}\n[/PDF_CONTEXT]",
                                        }
                                        await ChatRepository.add_message(
                                            db_session, message_data
                                        )
                                        await db_session.commit()
                                    finally:
                                        await db_session.close()
                            # Also forward the hidden pdf_context event to the frontend
                            # so the in-memory message list can stay in sync with the DB.
                            # The frontend does not render [PDF_CONTEXT] bubbles, but it
                            # needs the hidden message locally for immediate follow-up turns
                            # before a conversation reload happens.
                            yield chunk
                            continue
                    except (json.JSONDecodeError, KeyError):
                        pass

                if chunk == "data: [DONE]\n\n":
                    if req.conversation_id and full_response:
                        async for db_session in get_db():
                            try:
                                save_content = _prepare_content_for_persistence(
                                    full_response
                                )
                                message_data = {
                                    "conversation_id": req.conversation_id,
                                    "role": "assistant",
                                    "content": save_content,
                                }
                                message_data = cast(dict[str, Any], message_data)
                                if req.regenerate_message_id:
                                    group_id = (
                                        await ChatRepository.prepare_variant_group(
                                            db_session, req.regenerate_message_id
                                        )
                                    )
                                    message_data["variant_group_id"] = group_id
                                    message_data["is_active_variant"] = True
                                persist_started_at = time.monotonic()
                                saved_message = await ChatRepository.add_message(
                                    db_session, message_data
                                )
                                await db_session.commit()
                                _log_chat_timing(
                                    chat_request_id,
                                    "persist_assistant_message",
                                    persist_started_at,
                                )
                                saved_to_db = True
                                if saved_message:
                                    event_payload = {"message_id": saved_message.id}
                                    if req.regenerate_message_id:
                                        event_payload["old_message_id"] = (
                                            req.regenerate_message_id
                                        )
                                    yield f"data: {json.dumps(event_payload)}\n\n"
                            finally:
                                await db_session.close()
                    else:
                        saved_to_db = True
                    yield chunk
                else:
                    yield chunk
                    # Extract content from SSE chunk
                    if chunk.startswith("data: "):
                        try:
                            data = json.loads(chunk[6:])
                            if data.get("type") == "search_clear":
                                # Search-related clear: keep existing content
                                # (pre-search text is valid, new response appends after search)
                                pass
                            elif "content" in data and data["content"] is not None:
                                if data["content"] == "__CLEAR_CONTENT__":
                                    full_response = ""
                                else:
                                    full_response += data["content"]
                        except:
                            pass
        finally:
            if (
                not saved_to_db
                and req.conversation_id
                and not req.regenerate_message_id
            ):
                cancel_text = _get_generation_cancelled_text(detected_lang)
                # If there was partial content, append cancel notice after it
                if full_response.strip():
                    save_content = _prepare_content_for_persistence(full_response)
                    save_content = f"{save_content}\n\n---\n\n{cancel_text}"
                else:
                    save_content = cancel_text
                try:
                    async for db_session in get_db():
                        try:
                            persist_started_at = time.monotonic()
                            message_data = {
                                "conversation_id": req.conversation_id,
                                "role": "assistant",
                                "content": save_content,
                            }
                            await ChatRepository.add_message(db_session, message_data)
                            await db_session.commit()
                            _log_chat_timing(
                                chat_request_id,
                                "persist_cancelled_message",
                                persist_started_at,
                            )
                            logger.info(
                                f"Saved cancelled assistant response on stream interruption"
                            )
                        finally:
                            await db_session.close()
                except Exception as e:
                    logger.warning(
                        f"Failed to save cancelled response on disconnect: {e}"
                    )

    _log_chat_timing(chat_request_id, "pre_stream_total", chat_started_at)
    return make_sse_response(stream_with_persistence())
