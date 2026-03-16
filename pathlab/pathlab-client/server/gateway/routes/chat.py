"""
Chat and conversation management routes
Handles AI chat, conversation persistence, and task parsing
"""

import asyncio
import json
import math
import mimetypes
import os
import re
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import httpx
from typing import Any, TypedDict
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse, FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db, async_session
from backend.database.repositories import (
    ChatRepository,
    WSIRepository,
    TrainedModelRepository,
    DatasetPermissionRepository,
    DatasetRepository,
    TrainingTaskRepository,
    AITaskRepository,
)
from backend.database.models import (
    TrainingTask,
    WSISlide,
    TrainingTaskWSI,
    AIResult,
)
from backend.auth import current_active_user, User
from backend.auth.dependencies import (
    check_data_ownership,
    get_user_id_filter,
    get_user_from_header_or_param,
)
from backend.common.chat_context_cache import (
    get_cached_context_kwargs_admin,
    get_cached_context_kwargs,
    get_training_snapshot,
    set_cached_context_kwargs_admin,
    set_cached_context_kwargs,
)
from backend.common.config import Config
from backend.common.gpu_utils import get_gpu_summary_for_prompt
from backend.ai.segmentors.specs import is_fm_segmentation_backbone
from ..dependencies import logger
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
    split_md_into_pages,
    get_url_hash,
    get_pdf_cache_dir,
    tokenize_for_search,
    detect_source_type,
    is_academic_content,
    format_reference_card,
    ACADEMIC_SOURCE_TYPES,
    find_cached_articles_by_title,
)
from .chat_pdf_vectorstore import search_pdf_chunks
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
    EXTRACTOR_EMBED_DIM,
)

router = APIRouter(tags=["Chat & Conversations"])

SEGMENTATION_TASK_TYPES = {"segmentation", "patch_segmentation"}
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
DEFAULT_MODEL_SCAN_LIMIT = 100
FILTERED_MODEL_SCAN_LIMIT = 5000
MODEL_SCAN_BATCH_SIZE = 200
_PATCH_INFERENCE_BLOCK_RE = re.compile(
    r"\[PATCH_INFERENCE\]([\s\S]*?)\[/PATCH_INFERENCE\]"
)
_TOOL_BLOCK_RE = re.compile(
    r"\[(?:READ_ARTICLE|WEB_SEARCH)\].*?\[/(?:READ_ARTICLE|WEB_SEARCH)\]", re.DOTALL
)

# ── Persistent httpx client (reuse TCP connections across requests) ──────────
# Creating a new AsyncClient per request pays ~10-50 ms in TLS handshake /
# connection setup every time.  A single module-level client with keepalive
# reuses existing connections so the first streaming token arrives faster.
_llm_http_client: httpx.AsyncClient | None = None


def _get_llm_http_client() -> httpx.AsyncClient:
    global _llm_http_client
    if _llm_http_client is None or _llm_http_client.is_closed:
        _llm_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
        )
    return _llm_http_client


# ── vLLM availability cache ─────────────────────────────────────────────────
# _check_local_vllm_available() does an HTTP round-trip (3 s timeout) on every
# chat request.  Cache the result for 30 s on success, use exponential backoff
# on repeated failures so a down server doesn't add 3 s latency per request.
_vllm_cache: dict[str, Any] = {
    "available": None,
    "model": None,
    "base_url": None,
    "checked_at": 0.0,
    "fail_count": 0,
}
_VLLM_CACHE_TTL_OK = 30.0
_VLLM_CACHE_TTL_FAIL_BASE = 5.0

_feature_extractor_scan_cache: dict[tuple[str, str], tuple[list[str], float]] = {}
_FEATURE_SCAN_CACHE_TTL = 60.0

_CompatCacheKey = tuple[str, str, str, str, str | None, tuple[str, ...], int]
_compat_check_cache: dict[_CompatCacheKey, tuple[bool, float]] = {}
_COMPAT_CACHE_TTL = 120.0


class _PaperMeta(TypedDict):
    url: str
    meta: dict[str, Any]
    title: str
    parse_method: str | None
    image_count: int
    is_academic: bool


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
            "general_cytology": "本轮推荐对非宫颈 / 非妇科或通用细胞学应优先考虑 SmartCyto，再联网查同任务公开证据；不要把缺少公开命中当成反证。",
        },
        "zh_HK": {
            "histopathology": "本輪推薦應優先結合任務/器官匹配的 PathBench 結果，再聯網查近期任務證據；不要把 UNI 或任何單一 encoder 視為普遍最優。",
            "segmentation": "本輪推薦應優先結合 PathBench / 病理分割相關證據，再聯網查近期任務證據；不要預設任何單一 FM extractor。",
            "cervical_cytology": "本輪推薦對宮頸 / 婦科細胞學應優先考慮 Smart-CCS，再聯網查近期任務證據。",
            "general_cytology": "本輪推薦對非宮頸 / 非婦科或通用細胞學應優先考慮 SmartCyto，再聯網查同任務公開證據；不要把缺少公開命中當成反證。",
        },
        "en": {
            "histopathology": "Prioritize task/organ-matched PathBench evidence, then verify with a fresh web search; do not treat UNI or any single encoder as universally best.",
            "segmentation": "Prioritize PathBench/pathology-segmentation evidence, then verify with a fresh web search; do not default to any single FM extractor.",
            "cervical_cytology": "For cervical / gynecologic cytology, prioritize Smart-CCS, then verify with a fresh web search.",
            "general_cytology": "For non-cervical, non-gynecologic, or general cytology, prioritize SmartCyto, then verify with task-matched public evidence; do not treat missing public hits as counter-evidence.",
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


def _truncate_error_detail(text: str, limit: int = 1200) -> str:
    """Trim upstream error payloads so logs stay readable."""
    normalized = " ".join((text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


async def _raise_for_status_with_detail(response: httpx.Response) -> None:
    """Raise HTTPStatusError enriched with a trimmed upstream response body."""
    if not response.is_error:
        return

    detail = ""
    with suppress(Exception):
        _ = await response.aread()
        detail = response.text or ""

    status_kind = "Client" if 400 <= response.status_code < 500 else "Server"
    message = (
        f"{status_kind} error '{response.status_code} {response.reason_phrase}' "
        f"for url '{response.request.url}'"
    )
    if detail.strip():
        message = f"{message} | response_body={_truncate_error_detail(detail)}"

    raise httpx.HTTPStatusError(message, request=response.request, response=response)


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


def _should_fallback_from_local_vllm_error(exc: Exception) -> bool:
    """Return True when a local vLLM upstream request failure should trigger remote fallback."""
    return isinstance(exc, httpx.HTTPError)


async def _require_conversation_write_access(
    db: AsyncSession,
    conversation_id: str,
    user: User,
) -> None:
    """Ensure the current user can persist data into the target conversation."""
    conversation = await ChatRepository.get_conversation(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not check_data_ownership(str(conversation.user_id), user):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to modify this conversation",
        )


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
    if not check_data_ownership(str(trained_model.user_id), user):
        raise HTTPException(
            status_code=403, detail="You don't have permission to use this model"
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

    if is_fm_segmentation_backbone(resolved_backbone):
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

# Prompt fragment appended when PDF context is rebuilt for follow-up questions.
_PDF_FOLLOWUP_NOTE = {
    "en": (
        "NOTE: The PDF content below has been semantically searched to show the most relevant "
        "chunks for the user's latest question, along with the first and last pages for context. "
        "Retrieved blocks are labelled with page number and block type (e.g. `Page 3, Table 5`). "
        "When citing, use [N, p.Y] format where N is the paper number. If the user asks about content not shown here, "
        "tell them to ask a more specific follow-up question so the system can retrieve it.\n"
        "STRICT GROUNDING: Your answer MUST be based ENTIRELY on the paper content below. "
        "Do NOT use training knowledge to fill gaps. "
        "When quoting original text from the paper, use blockquotes (> ...) to clearly distinguish "
        "the paper's original words from your own analysis.\n"
        "Do NOT mention internal parser names, upgrade steps, or GPU/CPU execution details.\n"
        "If the user asks about processing status, only state whether the PDF is processing, available, or failed.\n"
        "If a paper's images are available (shown in Paper Registry), include image links verbatim."
    ),
    "zh_CN": (
        "注意：以下 PDF 内容已通过语义搜索筛选，展示与用户最新提问最相关的文本片段以及首尾页作为上下文。"
        "片段标记了页码和块类型（如 `Page 3, Table 5`）。引用格式：[N, p.Y]，其中 N 是论文编号。"
        "如果用户询问的信息不在这些片段中，请告诉用户提出更具体的追问以便系统检索。\n"
        "严格 Grounding：你的回答**必须完全基于**下方论文内容，**禁止**用训练知识填补空白。"
        "引用论文原文时，请使用引用块（> ...）来清楚区分论文原文和你自己的分析。\n"
        "不要提及内部解析器名称、升级流程或 GPU/CPU 执行细节。\n"
        "如果用户询问处理状态，只能说明 PDF 处于处理中、可用或失败。\n"
        "如果论文图片可用（见 Paper Registry），请将图片链接原样包含在回答中。"
    ),
    "zh_HK": (
        "注意：以下 PDF 內容已透過語義搜尋篩選，展示與用戶最新提問最相關的文本片段以及首尾頁作為上下文。"
        "片段標記了頁碼和塊類型（如 `Page 3, Table 5`）。引用格式：[N, p.Y]，其中 N 是論文編號。"
        "如果用戶詢問的資訊不在這些片段中，請告訴用戶提出更具體的追問以便系統檢索。\n"
        "嚴格 Grounding：你的回答**必須完全基於**下方論文內容，**禁止**用訓練知識填補空白。"
        "引用論文原文時，請使用引用區塊（> ...）來清楚區分論文原文和你自己的分析。\n"
        "不要提及內部解析器名稱、升級流程或 GPU/CPU 執行細節。\n"
        "如果用戶詢問處理狀態，只能說明 PDF 處於處理中、可用或失敗。\n"
        "如果論文圖片可用（見 Paper Registry），請將圖片連結原樣包含在回答中。"
    ),
}


def _describe_pdf_image_status(image_count: int) -> str:
    return f"{image_count} figures ✅" if image_count > 0 else "none"


def _format_pdf_block_label(chunk: dict[str, Any]) -> str:
    block_type_raw = str(chunk.get("block_type") or "chunk").strip().lower()
    block_index = int(chunk.get("chunk_index", 0)) + 1
    label_map = {
        "paragraph": "Paragraph",
        "list": "List",
        "code": "Code",
        "table": "Table",
        "figure": "Figure",
        "equation": "Equation",
        "section": "Section",
    }
    block_label = label_map.get(block_type_raw, block_type_raw.title() or "Chunk")
    section_path = str(chunk.get("section_path") or "").strip()
    label = f"Page {chunk.get('page_num', 0)}, {block_label} {block_index}"
    if section_path:
        label += f" [{section_path}]"
    return label


def _collect_pdf_urls_from_contexts(messages: list[dict[str, object]]) -> list[str]:
    """Extract all unique PDF URLs from all [PDF_CONTEXT] blocks in conversation history.

    Returns a deduplicated list of URLs preserving first-seen order.
    """
    pdf_ctx_re = re.compile(r"\[PDF_CONTEXT\]\n?([\s\S]*?)\n?\[/PDF_CONTEXT\]")
    seen: dict[str, None] = {}  # ordered dict for dedup
    for msg in messages:
        if msg.get("role") != "user":
            continue
        raw = extract_text_from_content(msg.get("content", ""))
        m = pdf_ctx_re.search(raw)
        if m:
            urls = re.findall(r"- \*\*URL\*\*: (https?://[^\s\n]+)", m.group(1))
            for u in urls:
                seen.setdefault(u, None)
    return list(seen.keys())


def _replace_images_with_fig_aliases(md_content: str, url_hash: str) -> str:
    """Replace hash-based image filenames with simple ``fig-N`` aliases.

    LLMs cannot reliably reproduce 64-char SHA-256 hashes, leading to
    hallucinated filenames and cascading 404 errors.  This replaces e.g.

        ![](http://host/pdf-images/hash/abc123…def.jpg)

    with:

        ![Figure 3](http://host/pdf-images/hash/fig-3.jpg)

    The server endpoint ``get_pdf_image_path`` resolves ``fig-N`` back to
    the real file by alphabetically sorted directory listing.
    """
    images_dir = get_pdf_cache_dir() / "images" / url_hash
    if not images_dir.is_dir():
        return md_content

    # Canonical file list — sorted, excluding any fig-* aliases or meta files
    image_files = sorted(
        f.name
        for f in images_dir.iterdir()
        if f.is_file() and not f.name.startswith("fig-") and not f.name.startswith("_")
    )
    if not image_files:
        return md_content

    # Reverse map: real filename → fig-N number (1-based)
    file_to_fig: dict[str, int] = {name: i + 1 for i, name in enumerate(image_files)}

    def _replacer(match: re.Match[str]) -> str:
        alt = match.group(1)
        prefix = match.group(2)  # up to and including …/pdf-images/hash/
        filename_with_ext = match.group(3)  # e.g. "abc123…def.jpg"

        fig_num = file_to_fig.get(filename_with_ext)
        if fig_num is None:
            return match.group(0)  # unknown file — leave as-is

        ext = filename_with_ext.rsplit(".", 1)[-1]
        new_alt = alt.strip() if alt.strip() else f"Figure {fig_num}"
        return f"![{new_alt}]({prefix}fig-{fig_num}.{ext})"

    # Pattern: ![alt](…/pdf-images/{url_hash}/filename.ext)
    pattern = (
        r"!\[([^\]]*)\]\("
        + r"((?:[^\)]*?/)?pdf-images/"
        + re.escape(url_hash)
        + r"/)"
        + r"([^/\)\s]+)"
        + r"\)"
    )
    return re.sub(pattern, _replacer, md_content, flags=re.IGNORECASE)


def _build_merged_pdf_context(
    all_urls: list[str], user_query: str, detected_lang: str = "en"
) -> str:
    """Build a single merged PDF context from all unique URLs with BM25 page selection.

    This replaces the old per-block `_enhance_pdf_context_for_query` with a
    global merge that:
      1. Builds a Paper Registry with global sequential numbering and image status.
      2. Re-reads the **latest** cached markdown for each URL from disk.
      3. Uses BM25 to select the most relevant pages per paper.
      4. Returns one unified context string.
    """
    _PDF_MAX_CHARS_PER_PAPER = 40_000

    if not all_urls:
        return ""

    total = len(all_urls)
    enhanced_parts: list[str] = []

    # ── Global Document Registry ─────────────────────────────────────────────
    registry_lines = [f"## Document Registry ({total} documents):\n"]
    paper_metas: list[_PaperMeta] = []
    for idx, url in enumerate(all_urls, 1):
        meta = get_cached_pdf_meta(url) or {}
        title = meta.get("title", "Unknown")
        parse_method = meta.get("parse_method")

        # Determine academic status from cache meta (persisted by process_pdf_url).
        # If not in cache (legacy), re-detect from cached markdown + source type.
        if "is_academic" in meta:
            is_academic = meta["is_academic"]
        else:
            cached_md = get_cached_markdown(url)
            src_type = detect_source_type(url)
            is_academic = (
                is_academic_content(cached_md or "", src_type) if cached_md else False
            )

        label = "Paper" if is_academic else "Doc"

        # Image status detection
        url_hash = get_url_hash(url)
        images_dir = get_pdf_cache_dir() / "images" / url_hash
        image_count = 0
        if images_dir.is_dir():
            image_count = sum(1 for f in images_dir.iterdir() if f.is_file())
        image_status = _describe_pdf_image_status(image_count)

        registry_lines.append(
            f"- [{label} {idx}] {title} ({url}) | Images: {image_status}"
        )
        paper_metas.append(
            {
                "url": url,
                "meta": meta,
                "title": title,
                "parse_method": parse_method,
                "image_count": image_count,
                "is_academic": is_academic,
            }
        )

        logger.info(
            f"[BM25] {label} {idx} '{title}': parse_method={parse_method},"
            + f" is_academic={is_academic}, images_available={image_count > 0} ({image_count} images)"
        )

    registry_lines.append("")
    enhanced_parts.extend(registry_lines)

    followup_note = _PDF_FOLLOWUP_NOTE.get(detected_lang, _PDF_FOLLOWUP_NOTE["en"])
    enhanced_parts.append(followup_note + "\n")
    enhanced_parts.append("## PDF Content (query-relevant pages):\n")

    # ── Per-document rebuild ─────────────────────────────────────────────────
    for paper_idx, pd in enumerate(paper_metas, 1):
        url = pd["url"]
        meta = pd["meta"]
        title = pd["title"]
        page_count = meta.get("page_count")
        parse_method = pd["parse_method"]
        is_academic = pd.get("is_academic", False)
        label = "Paper" if is_academic else "Doc"
        content_type = "Academic Paper" if is_academic else "General Document"
        page_info = f"{page_count} pages" if page_count else "page count unknown"

        enhanced_parts.append(
            f"### [{label} {paper_idx} of {total}] {title}\n"
            + f"- **URL**: {url}\n"
            + f"- **Content type**: {content_type}\n"
            + f"- **Total pages**: {page_info}\n"
        )

        # Read full cached markdown (always re-reads from disk → picks up newer high-quality cache)
        full_md = get_cached_markdown(url)
        if not full_md:
            enhanced_parts.append(
                "[Content not available — cache may have expired]\n---\n"
            )
            continue

        # 改动 9: Replace hash-based image filenames with fig-N aliases.
        # LLMs hallucinate 64-char SHA-256 hashes → cascading 404 errors.
        url_hash_for_imgs = get_url_hash(url)
        full_md = _replace_images_with_fig_aliases(full_md, url_hash_for_imgs)

        # Short papers: include everything
        if len(full_md) <= _PDF_MAX_CHARS_PER_PAPER:
            enhanced_parts.append(full_md)
            enhanced_parts.append("---\n")
            continue

        # ── Vector search for relevant chunks (with BM25 fallback) ──────────
        url_hash = get_url_hash(url)
        vector_results = search_pdf_chunks(user_query, url_hashes=[url_hash], top_k=15)

        if vector_results:
            # Use vector search results — group by page, sorted by page_num
            logger.info(
                f"[VectorSearch] {label} {paper_idx}: {len(vector_results)} chunks"
                + f" retrieved (best distance={vector_results[0]['_distance']:.3f})"
            )
            # Always include first and last page for context
            all_pages = split_md_into_pages(full_md)
            first_pn, first_content = all_pages[0] if all_pages else (0, "")
            last_pn, last_content = all_pages[-1] if all_pages else (0, "")

            content_parts: list[str] = []
            char_count = 0

            # Add first page
            if first_content:
                first_text = f"--- Page {first_pn} ---\n{first_content}\n"
                content_parts.append(first_text)
                char_count += len(first_text)

            # Add vector-retrieved chunks, sorted by page then chunk_index
            sorted_chunks = sorted(
                vector_results, key=lambda c: (c["page_num"], c["chunk_index"])
            )
            seen_chunks = set()
            for chunk in sorted_chunks:
                chunk_key = (chunk["page_num"], chunk["chunk_index"])
                if chunk_key in seen_chunks:
                    continue
                seen_chunks.add(chunk_key)
                # Skip if this chunk is from first or last page (already included)
                if chunk["page_num"] == first_pn or chunk["page_num"] == last_pn:
                    continue
                chunk_body = chunk.get("display_text") or chunk.get("chunk_text") or ""
                chunk_text = f"--- {_format_pdf_block_label(chunk)} ---\n{chunk_body}\n"
                if char_count + len(chunk_text) > _PDF_MAX_CHARS_PER_PAPER:
                    break
                content_parts.append(chunk_text)
                char_count += len(chunk_text)

            # Add last page
            if last_pn != first_pn and last_content:
                last_text = f"--- Page {last_pn} ---\n{last_content}\n"
                if char_count + len(last_text) <= _PDF_MAX_CHARS_PER_PAPER:
                    content_parts.append(last_text)

            # ── Re-hydrate image links from pages referenced by vector results ──
            # Image markdown (![...](http://...pdf-images/...)) often ends up in
            # its own chunk and scores poorly in semantic search.  To ensure the
            # LLM can reference figures, we scan the *full* page text for every
            # page that contributed a chunk and collect any image links that are
            # NOT already present in the assembled content.
            chunk_page_nums = {c["page_num"] for c in sorted_chunks}
            # Also include first/last page nums which are already fully included
            chunk_page_nums.discard(first_pn)
            chunk_page_nums.discard(last_pn)
            page_map = {pn: content for pn, content in all_pages}
            assembled_text = "\n".join(content_parts)
            image_lines: list[str] = []
            for pn in sorted(chunk_page_nums):
                page_content = page_map.get(pn, "")
                for m in re.finditer(r"!\[[^\]]*\]\([^\)]+\)", page_content):
                    img_md = m.group(0)
                    if img_md not in assembled_text:
                        image_lines.append(f"[From Page {pn}] {img_md}")
            if image_lines:
                img_section = (
                    "\n\n--- Figures from relevant pages ---\n"
                    + "\n".join(image_lines)
                    + "\n"
                )
                if char_count + len(img_section) <= _PDF_MAX_CHARS_PER_PAPER:
                    content_parts.append(img_section)
                    logger.info(
                        f"[ImageRehydrate] Added {len(image_lines)} image links from relevant pages"
                    )

            total_p = page_count or (len(all_pages) if all_pages else 0)
            note = (
                f"[Semantic search: showing {len(seen_chunks)} most relevant chunks "
                f"from {total_p} total pages. Ask about specific topics for more.]\n"
            )
            content_parts.insert(0, note)
            enhanced_parts.append("\n".join(content_parts))
        else:
            # ── BM25 fallback for documents not yet vector-indexed ────────────
            logger.info(
                f"[BM25 Fallback] {label} {paper_idx}: no vector results, using BM25"
            )
            all_pages = split_md_into_pages(full_md)
            if not all_pages:
                enhanced_parts.append(
                    full_md[:_PDF_MAX_CHARS_PER_PAPER] + "\n[...truncated]\n"
                )
            else:
                first_pn, first_content = all_pages[0]
                last_pn, last_content = all_pages[-1]

                bm25_results = search_pdf_pages(full_md, user_query, top_k=10)
                bm25_extras = [
                    (pn, content, score)
                    for pn, content, score in bm25_results
                    if pn != first_pn and pn != last_pn
                ]

                selected: list[tuple[int, str]] = [(first_pn, first_content)]
                for pn, content, _ in sorted(bm25_extras, key=lambda x: x[0]):
                    selected.append((pn, content))
                if last_pn != first_pn:
                    selected.append((last_pn, last_content))

                content_parts = []
                char_count = 0
                prev_pn = None
                for pn, page_content in selected:
                    page_text = f"--- Page {pn} ---\n{page_content}\n"
                    if char_count + len(page_text) > _PDF_MAX_CHARS_PER_PAPER:
                        remaining = _PDF_MAX_CHARS_PER_PAPER - char_count
                        if remaining > 200:
                            content_parts.append(
                                page_text[:remaining]
                                + "\n[...page truncated for length]"
                            )
                        break
                    if prev_pn is not None and pn > prev_pn + 1:
                        content_parts.append(
                            f"\n[...pages {prev_pn + 1}–{pn - 1} omitted — ask about them if needed...]\n"
                        )
                    content_parts.append(page_text)
                    char_count += len(page_text)
                    prev_pn = pn

                shown = len([p for p in content_parts if p.startswith("--- Page")])
                total_p = page_count or len(all_pages)
                if shown < total_p:
                    note = (
                        f"[Showing {shown} of {total_p} pages: page 1 + "
                        f"{max(shown - 2, 0)} query-relevant pages + last page. "
                        f"Ask about specific pages or topics for more.]\n"
                    )
                    content_parts.insert(0, note)
                enhanced_parts.append("\n".join(content_parts))

        enhanced_parts.append("---\n")

    return "\n".join(enhanced_parts)


# Include feedback sub-router
from .chat_feedback import router as chat_feedback_router

router.include_router(chat_feedback_router)


def extract_text_from_content(content: object) -> str:
    """Extract text content from message content (handles both string and multimodal format)"""
    if isinstance(content, str):
        return content
    elif isinstance(content, list):
        # Multimodal format: [{"type": "text", "text": "..."}, {"type": "image_url", ...}]
        text_parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text_parts.append(part.get("text", ""))
        return " ".join(text_parts)
    return ""


def _infer_model_request_filters(user_text: str) -> dict[str, Any]:
    normalized_text = (user_text or "").strip().lower()
    if not normalized_text:
        return {}

    generic_model_listing_patterns = [
        "我有什么模型",
        "我有哪些模型",
        "有多少模型",
        "多少模型",
        "列出模型",
        "看下模型",
        "看看模型",
        "show models",
        "list models",
        "how many models",
        "latest model",
        "newest model",
        "最新模型",
        "最新训练的模型",
    ]
    if any(p in normalized_text for p in generic_model_listing_patterns):
        return {}

    task_type_keywords: dict[str, list[str]] = {
        "classification": ["classification", "classify", "classifier", "分类"],
        "survival": ["survival", "prognosis", "prognostic", "生存", "预后"],
        "segmentation": [
            "segmentation",
            "segment",
            "mask",
            "分割",
            "掩膜",
            "勾边",
            "圈区域",
        ],
    }
    data_type_keywords: dict[str, list[str]] = {
        "wsi": [
            "wsi",
            "whole slide",
            "whole-slide",
            "全切片",
            "全视野",
            "病理大图",
            "大图",
        ],
        "patch": ["patch", "tile", "patches", "小图", "切块", "瓦片"],
    }

    _SURVIVAL_SIGNAL_WORDS = {
        "event",
        "censored",
        "risk",
        "high risk",
        "low risk",
        "intermediate",
        "event_status",
        "risk_group",
        "生存期",
        "事件",
        "删失",
    }

    _STOP_WORDS = {
        "the",
        "a",
        "an",
        "in",
        "on",
        "of",
        "with",
        "for",
        "and",
        "or",
        "my",
        "me",
        "i",
        "is",
        "are",
        "was",
        "were",
        "have",
        "has",
        "that",
        "this",
        "to",
        "from",
        "by",
        "be",
        "can",
        "at",
        "model",
        "models",
        "data",
        "dataset",
        "image",
        "images",
        "图像",
        "模型",
        "数据集",
        "数据",
        "heatmap",
        "热力图",
        "热图",
        "attention",
        "注意力",
        "给",
        "我",
        "看",
        "show",
        "display",
        "view",
        "find",
        "get",
        "list",
        "all",
        "some",
    }

    def _detect_single_match(keyword_map: dict[str, list[str]]) -> str | None:
        matches = [
            value
            for value, keywords in keyword_map.items()
            if any(keyword in normalized_text for keyword in keywords)
        ]
        return matches[0] if len(matches) == 1 else None

    filters: dict[str, Any] = {}
    task_type = _detect_single_match(task_type_keywords)
    data_type = _detect_single_match(data_type_keywords)
    if task_type:
        filters["task_type"] = task_type
    if data_type:
        filters["data_type"] = data_type

    all_indicator_tokens: set[str] = set()
    for tokens in task_type_keywords.values():
        all_indicator_tokens.update(tokens)
    for tokens in data_type_keywords.values():
        all_indicator_tokens.update(tokens)

    import re as _re

    raw_tokens = _re.split(r"[\s,;/|，；、。\-]+", normalized_text)

    text_keywords: list[str] = []
    seen: set[str] = set()
    for tok in raw_tokens:
        tok = tok.strip()
        if not tok or len(tok) < 2:
            continue
        if tok in seen:
            continue
        seen.add(tok)
        if any(tok == ind or tok in ind for ind in all_indicator_tokens):
            continue
        if tok in _SURVIVAL_SIGNAL_WORDS:
            continue
        if tok in _STOP_WORDS:
            continue
        text_keywords.append(tok)

    if text_keywords:
        filters["text_keywords"] = text_keywords

    return filters


def _matches_model_request_filters(
    model_meta: dict[str, Any], filters: dict[str, Any]
) -> bool:
    for key, expected in filters.items():
        if key in ("task_type", "data_type"):
            if expected and model_meta.get(key) != expected:
                return False
        elif key == "text_keywords":
            searchable_lists: list[list[str]] = [
                model_meta.get("classes", []),
                model_meta.get("dataset_names", []),
                model_meta.get("dataset_sources", []),
            ]
            task_name_str: str = model_meta.get("task_name", "")
            for kw in expected:
                kw_lower = kw.lower()
                in_list = any(
                    kw_lower in item
                    for field_list in searchable_lists
                    for item in field_list
                )
                if not in_list and kw_lower not in task_name_str:
                    return False
    return True


def _matches_quick_model_request_filters(model: Any, filters: dict[str, Any]) -> bool:
    """Fast keyword-only model match used for chunked scan early-stop.

    This intentionally performs a conservative subset of full matching logic
    without DB joins. Full filtering still happens later via
    _matches_model_request_filters on enriched model summaries.
    """
    text_keywords = filters.get("text_keywords") or []
    if not text_keywords:
        return False

    classes = model.classes or []
    if not isinstance(classes, list):
        classes = []

    search_space: list[str] = [
        (model.model_name or "").lower(),
        (model.feature_extractor or "").lower(),
        (model.aggregator or "").lower(),
        (model.task_id or "").lower(),
    ] + [str(cls).lower() for cls in classes]

    return all(
        any(keyword.lower() in field for field in search_space)
        for keyword in text_keywords
    )


def _format_model_filter_summary(filters: dict[str, Any]) -> str:
    parts = []
    if filters.get("task_type"):
        parts.append(f"task_type={filters['task_type']}")
    if filters.get("data_type"):
        parts.append(f"data_type={filters['data_type']}")
    if filters.get("text_keywords"):
        parts.append(f"keywords={','.join(filters['text_keywords'])}")
    return ", ".join(parts)


def _semantic_top_k_models(
    query_text: str,
    model_summaries: list[dict[str, Any]],
    k: int = TOP_K_MODELS_IN_CHAT_CONTEXT,
) -> list[dict[str, Any]]:
    if not model_summaries or len(model_summaries) <= k:
        return model_summaries

    has_embeddings = any(
        isinstance(s.get("embedding"), list) and len(s["embedding"]) > 0
        for s in model_summaries
    )
    if not has_embeddings or not query_text.strip():
        return model_summaries[:k]

    try:
        import numpy as np
        from .chat_pdf_vectorstore import _embed_texts

        q_vec = _embed_texts([query_text])[0]
        q_norm = np.linalg.norm(q_vec)
        if q_norm == 0:
            return model_summaries[:k]
        q_vec = q_vec / q_norm

        scores: list[tuple[float, int]] = []
        for idx, s in enumerate(model_summaries):
            emb = s.get("embedding")
            if not isinstance(emb, list):
                scores.append((0.0, idx))
                continue
            v = np.array(emb, dtype=np.float32)
            v_norm = np.linalg.norm(v)
            if v_norm == 0:
                scores.append((0.0, idx))
                continue
            sim = float(np.dot(q_vec, v / v_norm))
            scores.append((sim, idx))

        scores.sort(key=lambda x: x[0], reverse=True)
        top_indices = [idx for _, idx in scores[:k]]
        return [model_summaries[i] for i in top_indices]

    except Exception:
        return model_summaries[:k]


def _should_use_semantic_model_ranking(
    latest_user_text: str,
    inferred_model_filters: dict[str, Any],
    recent_user_texts: list[str],
) -> bool:
    normalized = (latest_user_text or "").strip().lower()
    if not normalized:
        return False

    generic_patterns = [
        "有多少模型",
        "多少模型",
        "看下模型",
        "看看模型",
        "列出模型",
        "有哪些模型",
        "show models",
        "list models",
        "how many models",
        "latest model",
        "newest model",
        "最新模型",
        "最新训练的模型",
    ]
    if any(p in normalized for p in generic_patterns):
        return False

    if inferred_model_filters:
        return True

    return len(recent_user_texts) > 1


def _extract_images_from_content(content: object) -> list[str]:
    """Extract image base64 URLs from multimodal message content.

    Returns a list of data URLs (e.g. 'data:image/jpeg;base64,...') for persistence.
    Returns empty list for text-only messages.
    """
    if not isinstance(content, list):
        return []
    images = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "image_url":
            url = part.get("image_url", {}).get("url", "")
            if url:
                images.append(url)
    return images


def _extract_citation_contexts(
    ai_response: str,
    article_pdf_content: str,
    per_paper_content: dict[int, str] | None = None,
    per_paper_source_ids: dict[int, str] | None = None,
) -> dict[str, dict[str, Any]] | None:
    """Extract citation contexts from AI response using BM25 paragraph search.

    For each ``[N, p.Y]`` citation found in *ai_response*, locate the
    most relevant ~200-char snippet from the corresponding page in the
    article PDF content (which contains ``--- Page X ---`` markers).

    Also handles bare ``[N]`` citations (without page numbers) by using
    BM25 on the full paper content.  These are keyed ``"N-bare"`` in the
    returned dict so the frontend can distinguish them.

    When *per_paper_content* is provided (multi-paper follow-up), each
    paper's pages are stored separately so page numbers from different
    papers don't collide.

    Returns a dict keyed by ``"N-pY"`` or ``"N-bare"`` with
    ``{page, context, source_id?}`` values, or ``None`` if no citations are found.
    """
    import math
    from collections import Counter

    # General pattern: [N, p.ANY_PAGE_DESCRIPTION] — matches p.2, p.2-3, p.2, p.4, etc.
    citation_pattern = re.compile(r"\[(\d{1,2}),\s*(p\.[^\]]+)\]")
    citations = citation_pattern.findall(ai_response)

    # Also detect bare [N] citations (no page number).
    # Negative lookbehind avoids matching inside [N, p.Y] or markdown links.
    bare_pattern = re.compile(r"(?<![,\w])\[(\d{1,2})\](?!\()")
    bare_matches = set(bare_pattern.findall(ai_response))
    # Remove indices already covered by [N, p.Y] patterns
    covered_indices = {idx_str for idx_str, _ in citations}
    bare_only = bare_matches - covered_indices

    if not citations and not bare_only:
        return None

    # Build per-paper page maps to avoid page-number collisions
    _single_page_map: dict[int, str] = {}
    if per_paper_content:
        paper_page_maps: dict[int, dict[int, str]] = {}
        for paper_idx, content in per_paper_content.items():
            pgs = split_md_into_pages(content)
            paper_page_maps[paper_idx] = {pn: ct for pn, ct in pgs}
    else:
        # Single-paper mode: all citations share the same page map
        pages = split_md_into_pages(article_pdf_content)
        _single_page_map = {pn: ct for pn, ct in pages}
        paper_page_maps = {}  # unused in single mode

    def _best_paragraph(page_text: str, query: str, max_len: int = 200) -> str:
        """BM25-rank paragraphs of *page_text* against *query*,
        return the best-matching snippet truncated to *max_len* chars."""

        def _clean_snippet_text(text: str) -> str:
            text = re.sub(r"^\s*--- Page \d+ ---\s*$", "", text, flags=re.MULTILINE)
            text = re.sub(
                r"^\s*!\[[^\]]*\]\([^\)]+\)\s*$", "", text, flags=re.MULTILINE
            )
            text = re.sub(r"https?://[^\s)\]]+", "", text).strip()
            text = re.sub(r"\s+", " ", text)
            return text.strip()

        def _is_low_value_paragraph(text: str) -> bool:
            compact = _clean_snippet_text(text)
            if not compact:
                return True
            lower = compact.lower()
            if compact.count("@") >= 2:
                return True
            if any(
                marker in lower
                for marker in (
                    "correspondence:",
                    "corresponding author",
                    "orcid",
                    "all rights reserved",
                )
            ):
                return True
            if len(compact) <= 140 and re.match(
                r"^(figure|fig\.?|table)\s*[0-9ivx]+", lower
            ):
                return True
            affiliation_hits = sum(
                lower.count(token)
                for token in (
                    "department of",
                    "university",
                    "hospital",
                    "institute",
                )
            )
            if affiliation_hits >= 2 and len(re.findall(r"[\.!?]", compact)) <= 1:
                return True
            return False

        paragraphs = [p.strip() for p in re.split(r"\n{2,}", page_text) if p.strip()]
        if not paragraphs:
            return _clean_snippet_text(page_text)[:max_len].strip()

        q_tokens = tokenize_for_search(query)
        if not q_tokens:
            for paragraph in paragraphs:
                cleaned = _clean_snippet_text(paragraph)
                if cleaned and not _is_low_value_paragraph(paragraph):
                    return cleaned[:max_len]
            cleaned_page = _clean_snippet_text(page_text)
            return cleaned_page[:max_len] if cleaned_page else paragraphs[0][:max_len]

        para_tokens = [tokenize_for_search(p) for p in paragraphs]
        N = len(paragraphs)
        avgdl = sum(len(t) for t in para_tokens) / N if N else 1
        k1, b = 1.5, 0.75

        unique_qt = set(q_tokens)
        df: dict[str, int] = {qt: 0 for qt in unique_qt}
        for tl in para_tokens:
            for qt in unique_qt & set(tl):
                df[qt] += 1

        best_score, best_idx = -1.0, 0
        best_non_noise_score, best_non_noise_idx = -1.0, None
        for idx, tl in enumerate(para_tokens):
            tf = Counter(tl)
            dl = len(tl)
            score = 0.0
            for qt in q_tokens:
                if qt not in tf:
                    continue
                n_qt = df[qt]
                idf = math.log((N - n_qt + 0.5) / (n_qt + 0.5) + 1)
                score += (
                    idf * (tf[qt] * (k1 + 1)) / (tf[qt] + k1 * (1 - b + b * dl / avgdl))
                )
            if score > best_score:
                best_score = score
                best_idx = idx
            if (
                not _is_low_value_paragraph(paragraphs[idx])
                and score > best_non_noise_score
            ):
                best_non_noise_score = score
                best_non_noise_idx = idx

        chosen_idx = best_idx
        if best_non_noise_idx is not None and (
            _is_low_value_paragraph(paragraphs[best_idx]) or best_non_noise_score > 0
        ):
            chosen_idx = best_non_noise_idx

        best_text = _clean_snippet_text(paragraphs[chosen_idx])
        if not best_text:
            best_text = _clean_snippet_text(page_text)
        snippet = best_text[:max_len].strip()
        if len(best_text) > max_len:
            snippet += "…"
        return snippet

    contexts: dict[str, dict[str, Any]] = {}
    for idx_str, page_part in citations:
        # Normalize key: remove whitespace from page part for consistent lookup
        key = f"{idx_str}-{page_part.replace(' ', '')}"
        if key in contexts:
            continue

        # Select the correct page map for this paper
        paper_idx = int(idx_str)
        if per_paper_content:
            page_map = paper_page_maps.get(paper_idx, {})
        else:
            page_map = _single_page_map

        # Extract ALL page numbers mentioned in page_part (handles p.2, p.2-3, p.2, p.4, etc.)
        page_numbers = [int(x) for x in re.findall(r"\d+", page_part)]
        if not page_numbers:
            continue
        # For ranges like p.2-3, expand to [2, 3]
        expanded_pages: list[int] = []
        for rng in re.findall(r"(\d+)(?:-(\d+))?", page_part):
            start_p = int(rng[0])
            end_p = int(rng[1]) if rng[1] else start_p
            expanded_pages.extend(range(start_p, end_p + 1))
        # Deduplicate while preserving order
        seen: set[int] = set()
        unique_pages: list[int] = []
        for p in expanded_pages:
            if p not in seen:
                seen.add(p)
                unique_pages.append(p)
        # Concatenate content from all referenced pages
        page_content = "\n\n".join(
            page_map.get(p, "") for p in unique_pages if page_map.get(p)
        ).strip()
        if not page_content:
            continue

        # Extract ~100 chars around the citation in the AI response for BM25 query
        citation_text = f"[{idx_str}, {page_part}]"
        pos = ai_response.find(citation_text)
        if pos >= 0:
            start = max(0, pos - 80)
            end = min(len(ai_response), pos + 80)
            query = ai_response[start:end]
        else:
            query = ai_response[:160]

        source_id = (
            per_paper_source_ids.get(paper_idx) if per_paper_source_ids else None
        )
        contexts[key] = {
            "page": unique_pages[0],
            "context": _best_paragraph(page_content, query),
            **({"source_id": source_id} if source_id else {}),
        }

    # ── Bare [N] citations — BM25 on full paper content ──────────────────
    for idx_str in bare_only:
        key = f"{idx_str}-bare"
        if key in contexts:
            continue
        paper_idx = int(idx_str)

        # Select full content for this paper
        if per_paper_content and paper_idx in per_paper_content:
            full_content = per_paper_content[paper_idx]
        elif not per_paper_content:
            full_content = article_pdf_content
        else:
            continue

        # Extract ~160 chars around the bare citation for BM25 query
        citation_text = f"[{idx_str}]"
        pos = ai_response.find(citation_text)
        if pos >= 0:
            start = max(0, pos - 80)
            end = min(len(ai_response), pos + 80)
            query = ai_response[start:end]
        else:
            query = ai_response[:160]

        source_id = (
            per_paper_source_ids.get(paper_idx) if per_paper_source_ids else None
        )
        contexts[key] = {
            "page": 0,  # no specific page
            "context": _best_paragraph(full_content, query),
            **({"source_id": source_id} if source_id else {}),
        }

    return contexts if contexts else None


async def _stream_from_openai_compatible(
    messages: list[dict[str, Any]],
    base_url: str,
    api_key: str,
    model: str,
    source_name: str = "API",
) -> AsyncIterator[str]:
    """
    Stream AI response from an OpenAI-compatible API endpoint.

    Args:
        messages: Chat messages (text or multimodal format)
        base_url: API base URL (e.g., http://127.0.0.1:8000/v1)
        api_key: API key for authentication
        model: Model name to use
        source_name: Name of the source for logging (e.g., "Local vLLM", "OpenRouter")

    Yields:
        SSE formatted response chunks
    """
    logger.info(f"Using {source_name} with model: {model}")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    client = _get_llm_http_client()
    async with client.stream(
        "POST",
        f"{base_url}/chat/completions",
        headers=headers,
        json={
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": 0.7,
            "max_tokens": 2048,
        },
    ) as response:
        await _raise_for_status_with_detail(response)

        last_finish_reason = None
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                data = line[6:]
                if data == "[DONE]":
                    if last_finish_reason == "length":
                        yield f"data: {json.dumps({'response_truncated': True})}\n\n"
                    yield "data: [DONE]\n\n"
                    break
                try:
                    parsed = json.loads(data)
                    if "choices" in parsed and len(parsed["choices"]) > 0:
                        choice = parsed["choices"][0]
                        delta = choice.get("delta", {})
                        if "content" in delta and delta["content"] is not None:
                            yield f"data: {json.dumps({'content': delta['content']})}\n\n"
                        fr = choice.get("finish_reason")
                        if fr:
                            last_finish_reason = fr
                except json.JSONDecodeError:
                    continue
        if last_finish_reason == "length":
            yield f"data: {json.dumps({'response_truncated': True})}\n\n"


async def _check_local_vllm_available(
    base_url: str, api_key: str | None = None
) -> tuple[bool, str | None]:
    now = time.monotonic()
    cached = _vllm_cache

    if cached["base_url"] != base_url:
        cached.update(
            {
                "available": None,
                "model": None,
                "base_url": base_url,
                "checked_at": 0.0,
                "fail_count": 0,
            }
        )

    if cached["available"] is True and now - cached["checked_at"] < _VLLM_CACHE_TTL_OK:
        return True, cached["model"]

    if cached["available"] is False:
        fail_ttl = min(_VLLM_CACHE_TTL_FAIL_BASE * (2 ** cached["fail_count"]), 60.0)
        if now - cached["checked_at"] < fail_ttl:
            return False, None

    try:
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        client = _get_llm_http_client()
        response = await client.get(f"{base_url}/models", headers=headers, timeout=3.0)
        if response.status_code == 200:
            data = response.json()
            model_name = None
            if "data" in data and len(data["data"]) > 0:
                model_name = data["data"][0].get("id")
            cached.update(
                {
                    "available": True,
                    "model": model_name,
                    "checked_at": now,
                    "fail_count": 0,
                }
            )
            return True, model_name
        cached.update(
            {
                "available": False,
                "checked_at": now,
                "fail_count": cached["fail_count"] + 1,
            }
        )
        return False, None
    except Exception:
        cached.update(
            {
                "available": False,
                "checked_at": now,
                "fail_count": cached["fail_count"] + 1,
            }
        )
        return False, None


async def _call_ai_complete(
    messages: list[dict[str, Any]], base_url: str, api_key: str, model: str
) -> str:
    """
    Call AI completion API (non-streaming) and return the full response content.

    Args:
        messages: Chat messages
        base_url: API base URL
        api_key: API key
        model: Model name

    Returns:
        Full response content as string
    """
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    client = _get_llm_http_client()
    response = await client.post(
        f"{base_url}/chat/completions",
        headers=headers,
        json={
            "model": model,
            "messages": messages,
            "stream": False,
            "temperature": 0.7,
            "max_tokens": 2048,
        },
    )
    await _raise_for_status_with_detail(response)
    data = response.json()

    if "choices" in data and len(data["choices"]) > 0:
        return data["choices"][0]["message"]["content"]
    return ""


async def _execute_exa_search(
    query: str, exa_api_key: str, num_results: int = 5
) -> dict[str, Any]:
    """
    Execute Exa search and return results.

    Args:
        query: Search query
        exa_api_key: Exa API key
        num_results: Number of results to return

    Returns:
        Dict with query and results array
    """
    headers = {"Content-Type": "application/json", "x-api-key": exa_api_key}

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.exa.ai/search",
            headers=headers,
            json={
                "query": query,
                "num_results": num_results,
                "type": "auto",
                "contents": {"text": True},
            },
        )
        _ = response.raise_for_status()
        data = response.json()

        # Extract results
        results = []
        for item in data.get("results", []):
            results.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("text", "")[
                        :2000
                    ],  # Extended snippet for better AI context
                }
            )

        return {"query": query, "results": results}


# ── Client disconnect detection for immediate cancellation ──────────────────


class ClientDisconnectedError(Exception):
    """Raised when the SSE client disconnects during a long-running operation."""

    pass


def _consume_task_exception(task: asyncio.Task[object]) -> None:
    """Drain task exceptions so detached cleanup paths do not emit warnings."""
    try:
        _ = task.exception()
    except (asyncio.CancelledError, Exception):
        pass


async def _wait_for_disconnect(request: Request) -> None:
    """Poll ``request.is_disconnected()`` until the client drops the connection."""
    while not await request.is_disconnected():
        await asyncio.sleep(0.25)


async def _run_or_cancel_on_disconnect(coro, request: Request | None):
    """Race *coro* against client disconnect.

    If *request* is ``None`` (no disconnect detection available), simply
    ``await coro``.  Otherwise, the coroutine is cancelled as soon as the
    SSE client disconnects, and :class:`ClientDisconnectedError` is raised.
    """
    if request is None:
        return await coro

    task = asyncio.ensure_future(coro)
    disconnect_task = asyncio.ensure_future(_wait_for_disconnect(request))

    done, pending = await asyncio.wait(
        {task, disconnect_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    for p in pending:
        _ = p.cancel()
        try:
            await p
        except (asyncio.CancelledError, Exception):
            pass

    if disconnect_task in done:
        raise ClientDisconnectedError()

    return task.result()


def _deduplicate_search_results(
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Remove duplicate search results based on title similarity.

    Two results are considered duplicates when their normalised titles share
    a Jaccard word-overlap > 0.6. When duplicates are found, prefer the
    most authoritative source (journal / academic publisher / PDF) rather
    than blindly keeping the first occurrence.

    This prevents the same paper from appearing N times via different
    mirrors (PubMed, nature.com, arxiv.org, lab pages, …) and ensures
    inline citation indices [N] remain consistent for the AI and the frontend.
    """
    if not results:
        return results

    _bracket_re = re.compile(r"\[.*?\]")
    _word_re = re.compile(r"[a-zA-Z0-9]{3,}")

    def _title_words(title: str) -> set[str]:
        title = _bracket_re.sub("", title)
        return set(w.lower() for w in _word_re.findall(title))

    def _source_priority(result: dict[str, Any]) -> int:
        source_type = detect_source_type(str(result.get("url", "")))
        if source_type in ACADEMIC_SOURCE_TYPES:
            return 50
        if source_type == "pdf":
            return 40
        if source_type == "web":
            return 20
        if source_type in {"documentation", "github", "huggingface", "wikipedia"}:
            return 10
        if source_type == "blog":
            return 0
        return 5

    seen: list[dict[str, Any]] = []
    deduplicated: list[dict[str, Any]] = []

    for result in results:
        words = _title_words(result.get("title", ""))
        if not words:
            deduplicated.append(result)
            continue

        duplicate_idx: int | None = None
        for idx, seen_entry in enumerate(seen):
            seen_words = seen_entry["words"]
            intersection = words & seen_words
            union = words | seen_words
            if union and len(intersection) / len(union) > 0.6:
                duplicate_idx = idx
                break

        if duplicate_idx is None:
            seen.append({"words": words, "result_index": len(deduplicated)})
            deduplicated.append(result)
            continue

        existing_result_index = seen[duplicate_idx]["result_index"]
        existing_result = deduplicated[existing_result_index]
        if _source_priority(result) > _source_priority(existing_result):
            deduplicated[existing_result_index] = result
            seen[duplicate_idx]["words"] = words

    return deduplicated


def _format_search_results_for_ai(search_results: dict[str, Any]) -> str:
    """Format search-like results for the next AI iteration."""
    query = str(search_results.get("query", "") or "")
    source = str(search_results.get("source", "web") or "web")
    results_text = "\n\nSEARCH_RESULTS_CONTEXT\n"
    if query:
        results_text += f"Query: {query}\n"
    results_text += f"Source: {source}\n"
    results_text += "Search results:\n"
    for idx, result in enumerate(search_results.get("results", []), 1):
        r_url = str(result.get("url", "") or "")
        src_type = str(result.get("source_type") or detect_source_type(r_url))
        is_academic_src = src_type in ACADEMIC_SOURCE_TYPES
        ref_type = "paper" if is_academic_src else "webpage"
        results_text += (
            f"{idx}. {result.get('title', '')}\n"
            f"   URL: {r_url}\n"
            f"   Source: {src_type} (reference type: {ref_type})\n"
            f"   {result.get('snippet', '')}\n\n"
        )
    return results_text


async def stream_ai_response(
    messages: list[dict[str, Any]],
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    detected_lang: str = "en",
    request: Request | None = None,
    disable_web_search: bool = False,
    conversation_mode: ConversationMode = ConversationMode.GENERAL_CHAT,
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
    global_settings = Config.get_global_settings()

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
        logger.info(f"Checking local vLLM server at {local_vllm_base_url}...")
        is_available, detected_model = await _check_local_vllm_available(
            local_vllm_base_url, local_vllm_api_key
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

    # Tool loop: up to 5 iterations (web search + read article)
    # Need enough iterations for: search → re-search → read article → stream summary
    max_tool_iterations = 5
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

    # Track the URL currently being processed so we can clean up on cancel.
    _active_pdf_url: str | None = None

    # When True, the next iteration streams the AI response token-by-token
    # instead of buffering it.  Set after article content is injected so the
    # user sees the summary appear progressively.
    _stream_next_iteration = False
    _response_already_streamed = False
    full_response = ""
    _final_response_truncated = False
    _search_count = 0  # Track consecutive web searches to prevent infinite loops
    _search_artifacts_emitted = False
    _MAX_SEARCHES = 2  # Max web searches per user message

    for iteration in range(max_tool_iterations):
        # ── Streaming path: yield tokens directly to the client ──────────
        if _stream_next_iteration:
            streamed_response = ""
            try:
                response_truncated = False
                async for chunk in _stream_from_openai_compatible(
                    messages=current_messages,
                    base_url=effective_base_url,
                    api_key=effective_api_key,
                    model=effective_model,
                    source_name=f"{provider_name} (streaming)",
                ):
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

            # Streaming path always breaks after emitting — no tool detection needed
            # because the AI was given article content and asked to summarize.
            # Inject CITATION_CONTEXTS before [DONE] if article was read
            if article_pdf_content:
                try:
                    ctx = _extract_citation_contexts(
                        full_response,
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
            async for chunk in _stream_from_openai_compatible(
                messages=current_messages,
                base_url=effective_base_url,
                api_key=effective_api_key,
                model=effective_model,
                source_name=provider_name,
            ):
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

        # No tool requested — break out of loop
        break

    # ── Emit final AI response ──
    final_response_text = full_response or ""
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


@router.post("/conversations")
async def create_conversation(
    req: CreateConversationRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new conversation for the current user"""
    conversation_id = f"conv_{uuid.uuid4().hex[:16]}"
    conversation_data = {
        "conversation_id": conversation_id,
        "user_id": str(user.id),  # Use authenticated user's ID
        "title": req.title or "New Conversation",
    }
    conversation = await ChatRepository.create_conversation(db, conversation_data)
    await db.commit()
    return conversation.to_dict()


@router.get("/conversations")
async def list_conversations(
    skip: int = 0,
    limit: int = 50,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List all conversations for the current user"""
    user_id = str(user.id)
    conversations = await ChatRepository.get_user_conversations(
        db, user_id, skip, limit
    )
    total = await ChatRepository.count_user_conversations(db, user_id)
    return {"items": [conv.to_dict() for conv in conversations], "total": total}


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a conversation with all messages. Users can only view their own conversations."""
    conversation = await ChatRepository.get_conversation(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check ownership
    if not check_data_ownership(conversation.user_id, user):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to view this conversation",
        )

    # Sort messages by id to ensure chronological order (defense-in-depth)
    sorted_messages = sorted(conversation.messages, key=lambda m: m.id)
    return {
        **conversation.to_dict(),
        "messages": [msg.to_dict() for msg in sorted_messages],
    }


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a conversation. Users can only delete their own conversations."""
    conversation = await ChatRepository.get_conversation(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check ownership
    if not check_data_ownership(conversation.user_id, user):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to delete this conversation",
        )

    await cleanup_conversation_chat_patch_tasks(conversation_id)
    success = await ChatRepository.delete_conversation(db, conversation_id)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await db.commit()
    return {"message": "Conversation deleted successfully"}


@router.patch("/conversations/{conversation_id}/messages/{message_id}")
async def update_message(
    conversation_id: str,
    message_id: int,
    req: UpdateMessageRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a message's content. Used to persist task submission status."""
    # First check conversation exists and user owns it
    conversation = await ChatRepository.get_conversation(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not check_data_ownership(conversation.user_id, user):
        raise HTTPException(
            status_code=403, detail="You don't have permission to update this message"
        )

    # Update the message
    message = await ChatRepository.update_message(
        db, message_id, req.content, req.metadata
    )
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    await db.commit()
    return message.to_dict()


@router.delete("/conversations/{conversation_id}/messages/{message_id}")
async def delete_messages_from(
    conversation_id: str,
    message_id: int,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete a message and all subsequent messages in a conversation.
    Used for conversation branching - allows users to delete from a point and restart.
    Users can only delete messages in their own conversations.
    """
    # First check conversation exists and user owns it
    conversation = await ChatRepository.get_conversation(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not check_data_ownership(conversation.user_id, user):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to delete messages in this conversation",
        )

    await cleanup_chat_patch_tasks_from_message(conversation_id, message_id)
    # Delete the message and all subsequent messages
    deleted_count = await ChatRepository.delete_messages_from_id(
        db, conversation_id, message_id
    )
    if deleted_count == 0:
        raise HTTPException(status_code=404, detail="Message not found")

    await db.commit()
    return {
        "message": f"Deleted {deleted_count} message(s)",
        "deleted_count": deleted_count,
    }


@router.post("/conversations/{conversation_id}/messages")
async def add_message(
    conversation_id: str,
    req: AddMessageRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a message to a conversation. Used to persist task submission success messages."""
    # First check conversation exists and user owns it
    conversation = await ChatRepository.get_conversation(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not check_data_ownership(conversation.user_id, user):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to add messages to this conversation",
        )

    # Add the message
    message_data = {
        "conversation_id": conversation_id,
        "role": req.role,
        "content": req.content,
    }
    message = await ChatRepository.add_message(db, message_data)
    await db.commit()
    return message.to_dict()


@router.post("/patch-inference")
async def start_chat_patch_inference(
    req: ChatPatchInferenceRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Start a temporary chat-only patch inference task."""
    conversation = await ChatRepository.get_conversation(db, req.conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not check_data_ownership(conversation.user_id, user):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to modify this conversation",
        )
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
        model_id=trained_model.model_id,
        model_name=trained_model.model_name,
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
    conversation = await ChatRepository.get_conversation(db, req.conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not check_data_ownership(conversation.user_id, user):
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to modify this conversation",
        )

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
        await _require_conversation_write_access(db, req.conversation_id, user)

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
        temp_permissions = await DatasetPermissionRepository.get_valid_by_user(
            db, str(user.id)
        )
        if temp_permissions:
            elevated_dataset_ids = [perm.dataset_id for perm in temp_permissions]

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
    if user.is_admin():
        _ctx_cached = await get_cached_context_kwargs_admin()
    elif elevated_dataset_ids is None:
        _ctx_cached = await get_cached_context_kwargs(_ctx_cache_uid)

    if _ctx_cached is not None:
        stats = {"total_count": 0, "datasets": [], "data_types": {}}
        rich_datasets = []
        trained_models = []
        trained_models_total = 0
        training_tasks = []
        training_tasks_stats = {}
        inference_tasks = []
        inference_tasks_stats = {}
        _cached_model_summaries_raw = _ctx_cached.get("model_summaries", [])
        _cached_model_summaries = []
        if isinstance(_cached_model_summaries_raw, list):
            for item in _cached_model_summaries_raw:
                if not isinstance(item, dict):
                    continue
                line = item.get("line")
                model_id = item.get("id")
                if not isinstance(line, str):
                    continue
                _cached_model_summaries.append({**item, "line": line, "id": model_id})
        _cached_trained_models_total = _ctx_cached.get("trained_models_total", 0)
        if _cached_model_summaries:
            if use_semantic_model_ranking:
                _relevant_summaries = _semantic_top_k_models(
                    semantic_query_text, _cached_model_summaries
                )
            else:
                _relevant_summaries = _cached_model_summaries[
                    :TOP_K_MODELS_IN_CHAT_CONTEXT
                ]
            _cached_models_list = "\n".join(s["line"] for s in _relevant_summaries)
            _cached_models_count = _cached_trained_models_total
            _cached_models_shown = len(_relevant_summaries)
        else:
            _cached_models_list = "  None - user needs to train a model first"
            _cached_models_count = 0
            _cached_models_shown = 0

    async def _with_new_session(coro_factory):
        async with async_session() as s:
            return await coro_factory(s)

    _uid = user_id_filter
    _eids = elevated_dataset_ids

    if _ctx_cached is None and inferred_model_filters:
        (
            stats,
            rich_datasets,
            trained_models_total,
            training_tasks,
            training_tasks_stats,
            inference_tasks,
            inference_tasks_stats,
        ) = await asyncio.gather(
            _with_new_session(
                lambda s: WSIRepository.get_chat_context_stats(
                    s, user_id=_uid, elevated_dataset_ids=_eids
                )
            ),
            _with_new_session(
                lambda s: WSIRepository.get_datasets(
                    s, user_id=_uid, elevated_dataset_ids=_eids
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

        trained_models = []
        scanned_count = 0
        quick_match_count = 0
        while scanned_count < FILTERED_MODEL_SCAN_LIMIT:
            batch_limit = min(
                MODEL_SCAN_BATCH_SIZE,
                FILTERED_MODEL_SCAN_LIMIT - scanned_count,
            )
            batch = await TrainedModelRepository.get_all(
                db,
                limit=batch_limit,
                offset=scanned_count,
                user_id=user_id_filter,
            )
            if not batch:
                break
            trained_models.extend(batch)
            scanned_count += len(batch)
            if inferred_model_filters.get("text_keywords"):
                quick_match_count += sum(
                    1
                    for item in batch
                    if _matches_quick_model_request_filters(
                        item, inferred_model_filters
                    )
                )
                if (
                    quick_match_count >= MAX_MODELS_IN_CHAT_CONTEXT
                    and scanned_count >= DEFAULT_MODEL_SCAN_LIMIT
                ):
                    break
            if len(batch) < batch_limit:
                break
    elif _ctx_cached is None:
        (
            stats,
            rich_datasets,
            trained_models,
            trained_models_total,
            training_tasks,
            training_tasks_stats,
            inference_tasks,
            inference_tasks_stats,
        ) = await asyncio.gather(
            _with_new_session(
                lambda s: WSIRepository.get_chat_context_stats(
                    s, user_id=_uid, elevated_dataset_ids=_eids
                )
            ),
            _with_new_session(
                lambda s: WSIRepository.get_datasets(
                    s, user_id=_uid, elevated_dataset_ids=_eids
                )
            ),
            _with_new_session(
                lambda s: TrainedModelRepository.get_all(
                    s, limit=DEFAULT_MODEL_SCAN_LIMIT, offset=0, user_id=_uid
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

    # Format user data context for System Prompt
    wsi_count = stats["total_count"]
    stats_datasets = stats[
        "datasets"
    ]  # Keep original reference; `datasets` may be overwritten later
    rich_datasets_map = {dataset["dataset_id"]: dataset for dataset in rich_datasets}
    datasets = stats_datasets
    data_type_dist = stats["data_types"]

    # Auxiliary lookup dict built during the dataset loop (used later for model compatibility)
    available_extractors_per_dataset: dict[str, list[str]] = {}
    dataset_wsi_ids_per_dataset: dict[str, list[str]] = {}

    # Format datasets with detailed info (data_type and labels per dataset)
    # Each dataset has its own labels and survival data - do NOT show global labels to avoid confusion
    # Datasets are now marked with access_type: "own" (user's own) or "elevated" (temporary permission)
    if datasets:
        _batch_dataset_ids = [
            d["dataset_id"]
            for d in datasets
            if d.get("dataset_id") and d.get("dataset_id") != "unknown"
        ]
        _wsi_ids_batch = await DatasetRepository.get_wsi_ids_batch(
            db, _batch_dataset_ids
        )

        datasets_details = []
        for d in datasets:
            ds_name = d["dataset_name"]
            ds_id = d.get("dataset_id", "unknown")
            ds_count = d["file_count"]
            ds_type = d.get("data_type", "unknown")
            ds_labels = d.get("labels", {})
            ds_survival = d.get("survival_count", 0)
            ds_event_status = d.get("event_status", {})
            ds_access_type = d.get("access_type", "own")
            rich_ds = rich_datasets_map.get(ds_id, {})
            ds_task_type = rich_ds.get("task_type") or d.get(
                "group_task_type", "unknown"
            )
            is_segmentation_dataset = _is_segmentation_task(
                ds_task_type
            ) or _is_segmentation_task(d.get("group_task_type"))
            effective_ds_labels = {} if is_segmentation_dataset else ds_labels
            ds_aggregation_level = rich_ds.get("aggregation_level", "")
            ds_split_counts = rich_ds.get("predefined_split_counts") or d.get(
                "predefined_split_counts", {}
            )
            ds_split_unit = rich_ds.get("predefined_split_unit") or (
                "cases" if ds_aggregation_level == "case" else "files"
            )
            ds_train_split = int(ds_split_counts.get("train", 0) or 0)
            ds_val_split = int(ds_split_counts.get("val", 0) or 0)
            ds_test_split = int(ds_split_counts.get("test", 0) or 0)
            ds_has_splits = d.get("has_predefined_splits", False) or any(
                count > 0 for count in (ds_train_split, ds_val_split, ds_test_split)
            )
            ds_segmentation_labels = _extract_segmentation_label_names(
                rich_ds.get("coco_categories", []) or []
            )
            d["task_type"] = ds_task_type
            d["labels"] = effective_ds_labels
            d["aggregation_level"] = ds_aggregation_level
            d["segmentation_labels"] = ds_segmentation_labels

            # Build info parts
            labels_str = (
                ", ".join([f"{lbl}({cnt})" for lbl, cnt in effective_ds_labels.items()])
                if effective_ds_labels
                else "none"
            )

            # Format survival data with event_status distribution
            if ds_survival > 0 and ds_event_status:
                event_count = ds_event_status.get("event", 0)
                censored_count = ds_event_status.get("censored", 0)
                survival_str = f", survival_data={ds_survival} (event={event_count}, censored={censored_count})"
            elif ds_survival > 0:
                survival_str = f", survival_data={ds_survival}"
            else:
                survival_str = ""

            splits_str = (
                f", has_predefined_splits=true, predefined_split_distribution({ds_split_unit})="
                f"[train:{ds_train_split}, val:{ds_val_split}, test:{ds_test_split}]"
                if ds_has_splits
                else ""
            )

            # Determine supported task types based on data
            task_types = []
            if effective_ds_labels:
                task_types.append("classification")
            if ds_survival > 0:
                task_types.append("survival")
            ds_group_task_type = d.get("group_task_type", "")
            if _is_segmentation_task(ds_group_task_type) or is_segmentation_dataset:
                task_types.append("segmentation")
            task_types_str = (
                f", supported_tasks=[{', '.join(task_types)}]" if task_types else ""
            )
            aggregation_str = (
                f", aggregation_level={ds_aggregation_level}"
                if ds_aggregation_level
                else ""
            )
            segmentation_labels_str = (
                f", segmentation_labels=[{', '.join(ds_segmentation_labels)}]"
                if ds_segmentation_labels
                else ""
            )
            ds_source = rich_ds.get("source_organ") or d.get("source_organ")
            if isinstance(ds_source, str):
                ds_source = ds_source.strip()

            dataset_wsi_ids = (
                _wsi_ids_batch.get(ds_id, []) if ds_id != "unknown" else []
            )
            dataset_wsi_ids_per_dataset[ds_id] = dataset_wsi_ids
            d["wsi_ids"] = dataset_wsi_ids

            available_extractors = []
            available_extractors_str = ""
            if ds_type == "wsi" and dataset_wsi_ids:
                features_root = Config.get_uploads_dir() / "features"
                available_extractors = await _get_available_extractors(
                    features_root, dataset_wsi_ids[0]
                )
                if available_extractors:
                    available_extractors_str = (
                        f", available_extractors=[{', '.join(available_extractors)}]"
                    )
            # Store for model compatibility lookup
            available_extractors_per_dataset[ds_id] = available_extractors
            d["available_feature_extractors"] = available_extractors

            # Add access type marker for elevated (temporary permission) datasets
            access_marker = (
                " [ELEVATED ACCESS - temporary permission]"
                if ds_access_type == "elevated"
                else ""
            )

            datasets_details.append(
                f"  - {ds_name} (dataset_id={ds_id}){access_marker}: {ds_count} files, type={ds_type}, "
                f"source={ds_source or 'unknown'}, labels=[{labels_str}]{survival_str}{splits_str}{task_types_str}{aggregation_str}"
                f"{segmentation_labels_str}{available_extractors_str}"
            )
        datasets_list = "\n".join(datasets_details)
    else:
        datasets_list = "  None"

    # Format data type distribution (overall summary only)
    wsi_count_val = data_type_dist.get("wsi", 0)
    patch_count_val = data_type_dist.get("patch", 0)
    if wsi_count_val > 0 and patch_count_val > 0:
        data_types_info = f"WSI: {wsi_count_val}, Patches: {patch_count_val}"
    elif wsi_count_val > 0:
        data_types_info = f"WSI only: {wsi_count_val}"
    elif patch_count_val > 0:
        data_types_info = f"Patches only: {patch_count_val}"
    else:
        data_types_info = "None"

    if trained_models:
        model_summaries = []
        # Batch query all training tasks to get detailed info with eager loading
        task_ids = list(set(m.task_id for m in trained_models if m.task_id))
        training_tasks_map = {}
        # task_id -> set of dataset_ids actually used in training (via TrainingTaskWSI → WSISlide)
        training_dataset_ids_map: dict[str, set[str]] = {}
        training_wsi_ids_map: dict[str, set[str]] = {}
        source_dataset_ids_map: dict[str, str | None] = {}
        # task_id -> dataset_ids with persisted AI results/heatmap artifacts
        result_dataset_ids_map: dict[str, set[str]] = {}
        heatmap_dataset_ids_map: dict[str, set[str]] = {}
        if task_ids:
            from sqlalchemy import select

            # Eager load data_group (for data_type / task_type), no need to load datasets relation
            stmt = (
                select(TrainingTask)
                .options(selectinload(TrainingTask.data_group))
                .where(TrainingTask.task_id.in_(task_ids))
            )
            result = await db.execute(stmt)
            tasks = result.scalars().all()
            for task in tasks:
                training_tasks_map[task.task_id] = task

            training_wsi_ids_raw = await TrainingTaskRepository.get_wsi_ids_batch(
                db, task_ids
            )
            training_wsi_ids_map = {
                task_id: set(wsi_ids)
                for task_id, wsi_ids in training_wsi_ids_raw.items()
            }
            source_dataset_ids_map = (
                await TrainingTaskRepository.get_source_dataset_ids_batch(db, task_ids)
            )

            # Batch-query the actual dataset_ids used in each training task
            # Join TrainingTaskWSI → WSISlide to get the real training datasets
            ds_rows = await db.execute(
                select(TrainingTaskWSI.task_id, WSISlide.dataset_id)
                .join(WSISlide, TrainingTaskWSI.wsi_id == WSISlide.wsi_id)
                .where(
                    TrainingTaskWSI.task_id.in_(task_ids),
                    WSISlide.dataset_id.isnot(None),
                )
                .distinct()
            )
            for row in ds_rows.all():
                tid, did = row[0], row[1]
                if tid not in training_dataset_ids_map:
                    training_dataset_ids_map[tid] = set()
                training_dataset_ids_map[tid].add(did)

            # Batch-query persisted AI results to provide dataset-specific evidence
            # for image/heatmap browsing prompts.
            result_rows = await db.execute(
                select(AIResult.task_id, WSISlide.dataset_id, AIResult.extra_metadata)
                .join(WSISlide, AIResult.wsi_id == WSISlide.wsi_id)
                .where(AIResult.task_id.in_(task_ids), WSISlide.dataset_id.isnot(None))
            )
            for task_id, dataset_id, extra_metadata in result_rows.all():
                if task_id not in result_dataset_ids_map:
                    result_dataset_ids_map[task_id] = set()
                result_dataset_ids_map[task_id].add(dataset_id)

                meta = extra_metadata if isinstance(extra_metadata, dict) else {}
                has_heatmap_artifact = bool(
                    meta.get("attention_path")
                    or meta.get("cam_file")
                    or meta.get("heatmap_path")
                    or meta.get("attention_scores_path")
                )
                if has_heatmap_artifact:
                    if task_id not in heatmap_dataset_ids_map:
                        heatmap_dataset_ids_map[task_id] = set()
                    heatmap_dataset_ids_map[task_id].add(dataset_id)

        for m in trained_models:
            model_name = m.model_name
            model_id = m.model_id
            model_classes = m.classes or []
            model_task_id = m.task_id
            model_feature_extractor = m.feature_extractor or "unknown"
            classes_str = ", ".join(model_classes) if model_classes else "none"

            # Get data_type and task_type from training task's DataGroup
            training_task = training_tasks_map.get(model_task_id)
            # Actual dataset_ids this model was trained on (from WSI associations)
            training_dataset_ids = training_dataset_ids_map.get(model_task_id, set())
            model_wsi_ids = training_wsi_ids_map.get(model_task_id, set())
            source_dataset_id = source_dataset_ids_map.get(model_task_id)
            if training_task and training_task.data_group:
                data_type = training_task.data_group.data_type
                task_type = training_task.data_group.task_type
            else:
                data_type = "unknown"
                task_type = "unknown"
            # Resolve training dataset names / sources using the stats_datasets lookup
            dataset_id_to_name = {
                ds["dataset_id"]: ds["dataset_name"] for ds in stats_datasets
            }
            dataset_id_to_source = {}
            for ds in stats_datasets:
                ds_id = ds.get("dataset_id")
                if not ds_id:
                    continue
                rich_ds = rich_datasets_map.get(ds_id, {})
                ds_source = rich_ds.get("source_organ") or ds.get("source_organ")
                if isinstance(ds_source, str):
                    ds_source = ds_source.strip()
                if ds_source:
                    dataset_id_to_source[ds_id] = ds_source
            training_dataset_names = [
                dataset_id_to_name[did]
                for did in training_dataset_ids
                if did in dataset_id_to_name
            ]
            training_dataset_sources = []
            seen_sources = set()
            for did in training_dataset_ids:
                ds_source = dataset_id_to_source.get(did)
                if ds_source and ds_source not in seen_sources:
                    training_dataset_sources.append(ds_source)
                    seen_sources.add(ds_source)

            # Dataset-level evidence from persisted AI results (and heatmap artifacts)
            result_dataset_ids = result_dataset_ids_map.get(model_task_id, set())
            heatmap_dataset_ids = heatmap_dataset_ids_map.get(model_task_id, set())
            result_dataset_names = [
                dataset_id_to_name[did]
                for did in result_dataset_ids
                if did in dataset_id_to_name
            ]
            heatmap_dataset_names = [
                dataset_id_to_name[did]
                for did in heatmap_dataset_ids
                if did in dataset_id_to_name
            ]

            # Get embedding dimension for WSI models
            embed_dim = EXTRACTOR_EMBED_DIM.get(model_feature_extractor, 0)

            _seg_spec = _get_segmentation_model_spec(m, training_task)
            _model_raw_classes = list(
                (
                    training_task.classes
                    if isinstance(training_task, TrainingTask)
                    else None
                )
                or m.classes
                or []
            )
            _extval_model_info = ExtvalModelInfo(
                data_type=data_type,
                task_type=task_type,
                classes=_model_raw_classes,
                feature_extractor=str(getattr(m, "feature_extractor", "") or ""),
                wsi_ids=model_wsi_ids,
                source_dataset_id=source_dataset_id,
                seg_task_architecture=_seg_spec["task_architecture"],
                seg_task_backbone=_seg_spec["task_backbone"],
                seg_saved_architecture=_seg_spec["saved_architecture"],
                seg_saved_backbone=_seg_spec["saved_backbone"],
                segmentation_labels=_model_raw_classes,
                training_dataset_ids=training_dataset_ids,
            )

            compatible_datasets = []
            if data_type != "unknown" and task_type != "unknown":
                _now_compat = time.monotonic()
                for ds in stats_datasets:
                    cand_id = ds["dataset_id"]
                    cand_name = ds["dataset_name"]
                    cand_extractors = tuple(
                        sorted(available_extractors_per_dataset.get(cand_id, []))
                    )
                    cand_wsi_count = len(dataset_wsi_ids_per_dataset.get(cand_id, []))
                    _ck = (
                        model_id,
                        cand_id,
                        data_type,
                        task_type,
                        source_dataset_id,
                        cand_extractors,
                        cand_wsi_count,
                    )
                    _cached_compat = _compat_check_cache.get(_ck)
                    if (
                        _cached_compat is not None
                        and _now_compat - _cached_compat[1] < _COMPAT_CACHE_TTL
                    ):
                        if _cached_compat[0]:
                            compatible_datasets.append(
                                f"{cand_name} (dataset_id={cand_id})"
                            )
                        continue

                    compatibility_error = check_extval_compatibility(
                        model_info=_extval_model_info,
                        dataset_info=ExtvalDatasetInfo(
                            dataset_id=cand_id,
                            data_type=ds.get("data_type", "unknown"),
                            task_type=ds.get("task_type", "unknown"),
                            aggregation_level=ds.get("aggregation_level", "file"),
                            labels=list((ds.get("labels") or {}).keys()),
                            segmentation_labels=ds.get("segmentation_labels") or [],
                            feature_extractors=available_extractors_per_dataset.get(
                                cand_id, []
                            ),
                            wsi_ids=set(dataset_wsi_ids_per_dataset.get(cand_id, [])),
                        ),
                    )
                    _compat_check_cache[_ck] = (
                        compatibility_error is None,
                        _now_compat,
                    )
                    if compatibility_error is not None:
                        continue

                    compatible_datasets.append(f"{cand_name} (dataset_id={cand_id})")

            # Build model info string
            info_parts = [
                f"id={model_id}",
                f"task_type={task_type}",
                f"data_type={data_type}",
            ]

            # Add classes for classification models
            if model_classes:
                info_parts.append(f"classes=[{classes_str}]")

            if _is_segmentation_task(task_type):
                segmentation_spec = _get_segmentation_model_spec(m, training_task)
                if segmentation_spec["task_architecture"]:
                    info_parts.append(
                        f"architecture={segmentation_spec['task_architecture']}"
                    )
                if segmentation_spec["task_backbone"]:
                    info_parts.append(f"backbone={segmentation_spec['task_backbone']}")
                if source_dataset_id:
                    info_parts.append(f"source_dataset_id={source_dataset_id}")

            # Add feature extractor info for WSI models
            if data_type == "wsi" and model_feature_extractor != "unknown":
                info_parts.append(f"feature_extractor={model_feature_extractor}")
                if embed_dim > 0:
                    info_parts.append(f"embedding_dim={embed_dim}")

            # Add training dataset source / names for reference
            if training_dataset_sources:
                info_parts.append(f"source={', '.join(training_dataset_sources)}")

            if training_dataset_names:
                info_parts.append(
                    f"trained_on_dataset={', '.join(training_dataset_names)}"
                )

            if result_dataset_names:
                result_datasets_str = ", ".join(
                    f"{dataset_id_to_name[did]} (dataset_id={did})"
                    for did in result_dataset_ids
                    if did in dataset_id_to_name
                )
                info_parts.append(f"result_evidence_datasets=[{result_datasets_str}]")
            else:
                info_parts.append("result_evidence_datasets=[]")

            if heatmap_dataset_names:
                heatmap_datasets_str = ", ".join(
                    f"{dataset_id_to_name[did]} (dataset_id={did})"
                    for did in heatmap_dataset_ids
                    if did in dataset_id_to_name
                )
                info_parts.append(f"heatmap_result_datasets=[{heatmap_datasets_str}]")
            else:
                info_parts.append("heatmap_result_datasets=[]")

            info_parts.append(f"trained_on_task={model_task_id}")

            # Add pre-computed compatible datasets list (API-level filtering)
            if compatible_datasets:
                compat_str = ", ".join(compatible_datasets)
                info_parts.append(f"compatible_validation_datasets=[{compat_str}]")
            else:
                info_parts.append("compatible_validation_datasets=[]")

            if m.created_at:
                info_parts.append(f"created_at={m.created_at.isoformat()}Z")

            model_summaries.append(
                {
                    "id": model_id,
                    "task_type": task_type,
                    "data_type": data_type,
                    # Extra fields for richer filter matching (used by
                    # _matches_model_request_filters to surface models by
                    # label/dataset/task_name even when they fall outside the
                    # MAX_MODELS_IN_CHAT_CONTEXT recent-model window).
                    "classes": [c.lower() for c in model_classes],
                    "dataset_names": [
                        n.lower()
                        for n in (training_dataset_names + result_dataset_names)
                    ],
                    "dataset_sources": [s.lower() for s in training_dataset_sources],
                    "task_name": (training_task.task_name or "").lower()
                    if training_task
                    else "",
                    "line": f"  - {model_name} ({', '.join(info_parts)})",
                }
            )

        if (
            use_semantic_model_ranking
            and model_summaries
            and len(model_summaries) > TOP_K_MODELS_IN_CHAT_CONTEXT
        ):
            try:
                from .chat_pdf_vectorstore import _embed_texts as _emb

                _emb_vecs = _emb([s["line"] for s in model_summaries])
                for _i, _s in enumerate(model_summaries):
                    _s["embedding"] = _emb_vecs[_i].tolist()
            except Exception:
                pass
        if use_semantic_model_ranking:
            relevant_summaries = _semantic_top_k_models(
                semantic_query_text, model_summaries
            )
        else:
            relevant_summaries = model_summaries[:TOP_K_MODELS_IN_CHAT_CONTEXT]
        models_list = "\n".join(summary["line"] for summary in relevant_summaries)
        models_count = trained_models_total
        models_shown = len(relevant_summaries)
    else:
        models_list = "  None - user needs to train a model first"
        models_count = 0
        models_shown = 0

    # Format user permissions info
    user_role = user.role
    can_use_gpu_base = user.can_use_gpu()

    # Format temporary permissions if any (for non-admin users)
    # These are datasets owned by OTHER users that this user has been granted access to
    if temp_permissions:
        # Batch query all datasets at once to avoid N+1 query problem
        dataset_ids = [perm.dataset_id for perm in temp_permissions]
        datasets = await DatasetRepository.get_by_ids(db, dataset_ids)
        dataset_map = {d.dataset_id: d for d in datasets}

        temp_perms_details = []
        for perm in temp_permissions:
            dataset = dataset_map.get(perm.dataset_id)
            dataset_name = dataset.name if dataset else "Unknown Dataset"

            # Format expiration info
            expires_info = ""
            if perm.expires_at:
                expires_info = (
                    f", expires: {perm.expires_at.strftime('%Y-%m-%d %H:%M UTC')}"
                )
            else:
                expires_info = ", no expiration"

            temp_perms_details.append(
                f"  - **{dataset_name}** (dataset_id={perm.dataset_id}): {perm.permission_level} access{expires_info}"
            )
        temp_perms_list = "\n".join(temp_perms_details)
    else:
        temp_perms_list = "  None"

    # Get GPU status for system prompt
    gpu_summary = (
        get_gpu_summary_for_prompt()
        if user.is_admin()
        else "GPU details hidden for non-admin users"
    )

    # Format training tasks info (recent 10 tasks with summary)
    training_tasks_total = training_tasks_stats.get("total", 0)
    training_tasks_completed = training_tasks_stats.get("completed", 0)
    training_tasks_running = training_tasks_stats.get("running", 0)
    training_tasks_failed = training_tasks_stats.get("failed", 0)

    if training_tasks:
        from backend.common.progress_store import get_all_progress

        active_task_ids = [
            t.task_id
            for t in training_tasks
            if str(getattr(t, "status", "") or "").lower() in ACTIVE_TRAINING_STATUSES
        ]
        live_progress_map = await get_all_progress() if active_task_ids else {}
        recent_logs_by_task_id: dict[str, list[object]] = {}
        if active_task_ids:
            recent_logs_batches = await asyncio.gather(
                *(get_training_snapshot(task_id) for task_id in active_task_ids)
            )
            recent_logs_by_task_id = {
                task_id: (logs or [])
                for task_id, logs in zip(active_task_ids, recent_logs_batches)
            }

        training_tasks_details = []
        for t in training_tasks:
            created_str = (
                t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else "unknown"
            )
            status_lower = str(t.status or "").lower()
            # Get task_type and data_type from DataGroup relationship
            if t.data_group:
                task_type = t.data_group.task_type
                data_type = t.data_group.data_type
            else:
                task_type = "unknown"
                data_type = "unknown"

            detail_parts = [f"created={created_str}"]
            if status_lower in ACTIVE_TRAINING_STATUSES:
                live_progress = live_progress_map.get(t.task_id)
                if live_progress is None:
                    live_progress = getattr(t, "progress", None)
                progress_value = _format_prompt_number(live_progress)
                if progress_value is not None:
                    detail_parts.append(f"progress={progress_value}%")

                latest_snapshot = _extract_latest_training_snapshot(
                    recent_logs_by_task_id.get(t.task_id, [])
                )
                if latest_snapshot:
                    detail_parts.append(latest_snapshot)

            training_tasks_details.append(
                f"  - [{t.status.upper()}] {t.task_name} (id={t.task_id}): {task_type}, {data_type}, "
                + "; ".join(detail_parts)
            )
        if training_tasks_total > 10:
            training_tasks_details.append(
                f"  ... and {training_tasks_total - 10} more tasks"
            )
        training_tasks_list = "\n".join(training_tasks_details)
    else:
        training_tasks_list = "  None - user has not created any training tasks yet"

    # Format inference tasks info (recent 10 tasks with summary)
    inference_tasks_total = inference_tasks_stats.get("total", 0)
    inference_tasks_completed = inference_tasks_stats.get("completed", 0)
    inference_tasks_running = inference_tasks_stats.get("running", 0)

    if inference_tasks:
        inference_task_wsi_map = await WSIRepository.get_by_ids_with_dataset(
            db, [t.wsi_id for t in inference_tasks if t.wsi_id]
        )
        inference_tasks_details = []
        for t in inference_tasks:
            created_str = (
                t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else "unknown"
            )
            task_wsi = inference_task_wsi_map.get(t.wsi_id)
            dataset_name = (
                task_wsi.dataset.name
                if task_wsi and task_wsi.dataset and task_wsi.dataset.name
                else "unknown dataset"
            )
            dataset_id = (
                task_wsi.dataset_id if task_wsi and task_wsi.dataset_id else "unknown"
            )
            inference_tasks_details.append(
                f"  - [{t.status.upper()}] {t.task_type} on {t.wsi_id} (dataset={dataset_name}, dataset_id={dataset_id}, id={t.task_id}): created={created_str}"
            )
        if inference_tasks_total > 10:
            inference_tasks_details.append(
                f"  ... and {inference_tasks_total - 10} more tasks"
            )
        inference_tasks_list = "\n".join(inference_tasks_details)
    else:
        inference_tasks_list = "  None - user has not run any inference tasks yet"

    # Format user data context using template
    user_data_context = format_user_data_context(
        wsi_count=wsi_count,
        data_types_info=data_types_info,
        datasets_list=datasets_list,
        models_count=models_count,
        models_list=models_list,
        models_shown=models_shown,
        models_selection_note=models_selection_note,
        training_tasks_total=training_tasks_total,
        training_tasks_completed=training_tasks_completed,
        training_tasks_running=training_tasks_running,
        training_tasks_failed=training_tasks_failed,
        training_tasks_list=training_tasks_list,
        inference_tasks_total=inference_tasks_total,
        inference_tasks_completed=inference_tasks_completed,
        inference_tasks_running=inference_tasks_running,
        inference_tasks_list=inference_tasks_list,
        gpu_summary=gpu_summary,
        user_role=user_role,
        is_admin=user.is_admin(),
        can_use_gpu_base=can_use_gpu_base,
        temp_perms_list=temp_perms_list,
        current_datetime=current_datetime,
    )

    if _ctx_cached is None and user.is_admin():
        await set_cached_context_kwargs_admin(
            {
                "wsi_count": wsi_count,
                "data_types_info": data_types_info,
                "datasets_list": datasets_list,
                "trained_models_total": trained_models_total,
                "model_summaries": model_summaries,
                "training_tasks_total": training_tasks_total,
                "training_tasks_completed": training_tasks_completed,
                "training_tasks_running": training_tasks_running,
                "training_tasks_failed": training_tasks_failed,
                "training_tasks_list": training_tasks_list,
                "inference_tasks_total": inference_tasks_total,
                "inference_tasks_completed": inference_tasks_completed,
                "inference_tasks_running": inference_tasks_running,
                "inference_tasks_list": inference_tasks_list,
            }
        )
    elif _ctx_cached is None and elevated_dataset_ids is None:
        await set_cached_context_kwargs(
            _ctx_cache_uid,
            {
                "wsi_count": wsi_count,
                "data_types_info": data_types_info,
                "datasets_list": datasets_list,
                "trained_models_total": trained_models_total,
                "model_summaries": model_summaries,
                "training_tasks_total": training_tasks_total,
                "training_tasks_completed": training_tasks_completed,
                "training_tasks_running": training_tasks_running,
                "training_tasks_failed": training_tasks_failed,
                "training_tasks_list": training_tasks_list,
                "inference_tasks_total": inference_tasks_total,
                "inference_tasks_completed": inference_tasks_completed,
                "inference_tasks_running": inference_tasks_running,
                "inference_tasks_list": inference_tasks_list,
            },
        )

    if _ctx_cached is not None:
        user_data_context = format_user_data_context(
            wsi_count=_ctx_cached.get("wsi_count", 0),
            data_types_info=_ctx_cached.get("data_types_info", "None"),
            datasets_list=_ctx_cached.get("datasets_list", "  None"),
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
            current_datetime=current_datetime,
        )

    # Log the user_data_context for debugging
    # logger.info(f"[Chat] User data context for agent:\n{user_data_context}")

    # Determine language for system prompt.
    # Priority: explicit X-Language header (user's i18n setting) > content-based heuristic.
    if ui_lang:
        detected_lang = ui_lang
    else:
        # Fallback: infer from the last user message content
        detected_lang = "en"
        for msg in reversed(req.messages):
            if msg.get("role") == "user":
                user_text = extract_text_from_content(msg.get("content", ""))
                detected_lang = detect_language(user_text)
                break

    # Add system prompt if not present
    messages = req.messages.copy()
    if not messages or messages[0].get("role") != "system":
        # Load language-specific system prompt from template file
        base_system_prompt = get_chat_system_prompt(detected_lang)

        system_prompt = {
            "role": "system",
            "content": base_system_prompt + user_data_context,
        }
        messages.insert(0, system_prompt)

    # If conversation_id is provided, save user message to database
    # For multimodal messages, save text content and persist images in extra_metadata
    if req.conversation_id and len(req.messages) > 0:
        last_user_message = req.messages[-1]
        if last_user_message.get("role") == "user":
            # Extract text content (handles both string and multimodal format)
            content = last_user_message.get("content", "")
            text_content = extract_text_from_content(content)
            # Extract image URLs from multimodal content for persistence
            images = _extract_images_from_content(content)
            message_data = {
                "conversation_id": req.conversation_id,
                "role": "user",
                "content": text_content,
            }
            if images:
                message_data["extra_metadata"] = {"images": images}
            await ChatRepository.add_message(db, message_data)
            await db.commit()

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
        merged_ctx = await asyncio.to_thread(
            _build_merged_pdf_context, all_pdf_urls, user_query_for_bm25, detected_lang
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
        training_recommendation_profile = detect_training_recommendation_profile(
            latest_user_text
        )
        bundled_ctx = await build_training_recommendation_evidence_context(
            latest_user_text, detected_lang
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
        full_response = ""
        saved_to_db = False  # Track whether we already persisted via [DONE]
        try:
            async for chunk in stream_ai_response(
                messages,
                api_key,
                base_url,
                model,
                detected_lang,
                request,
                disable_web_search=disable_web_search,
                conversation_mode=conversation_mode,
            ):
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

                # Don't yield [DONE] yet - we need to send message_id first
                if chunk == "data: [DONE]\n\n":
                    # Save assistant response to database and return message_id BEFORE [DONE]
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
                                saved_message = await ChatRepository.add_message(
                                    db_session, message_data
                                )
                                await db_session.commit()
                                saved_to_db = True
                                # Send message_id back to frontend so it can update the message ID
                                # This enables proper persistence of task submission status
                                if saved_message:
                                    yield f"data: {json.dumps({'message_id': saved_message.id})}\n\n"
                            finally:
                                await db_session.close()
                    else:
                        saved_to_db = True  # Nothing to save
                    # Now yield [DONE] after message_id has been sent
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
            # Save a "cancelled" assistant message on abnormal exit (client disconnect,
            # error, etc.) so the conversation isn't left with a dangling user message
            # and no reply.  When the user returns, they see a clean cancel notice
            # instead of a broken UI state.
            if not saved_to_db and req.conversation_id:
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
                            message_data = {
                                "conversation_id": req.conversation_id,
                                "role": "assistant",
                                "content": save_content,
                            }
                            await ChatRepository.add_message(db_session, message_data)
                            await db_session.commit()
                            logger.info(
                                f"Saved cancelled assistant response on stream interruption"
                            )
                        finally:
                            await db_session.close()
                except Exception as e:
                    logger.warning(
                        f"Failed to save cancelled response on disconnect: {e}"
                    )

    return StreamingResponse(
        stream_with_persistence(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ──────────────────────────────────────────────────────────────────────────────
# PDF image serving
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/pdf-images/{url_hash}/{filename}")
async def serve_pdf_image(
    url_hash: str, filename: str, user: User = Depends(get_user_from_header_or_param)
):
    """Serve extracted PDF images from persistent cache.

    Images are stored at: uploads/pdf_cache/images/{url_hash}/{filename}
    They are created during PDF parsing and referenced by absolute URLs inside
    cached markdown.
    """
    # Prevent path traversal: url_hash must be hex chars only; filename must be
    # a plain filename with no directory separators or parent-dir references.
    if not re.match(r"^[0-9a-f]+$", url_hash, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="Invalid url_hash")
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    image_path = get_pdf_image_path(url_hash, filename)

    if not image_path.exists() or not image_path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")

    content_type, _ = mimetypes.guess_type(str(image_path))
    if content_type is None:
        content_type = "application/octet-stream"

    return FileResponse(image_path, media_type=content_type)
