"""Helpers for evidence-backed training recommendation in chat."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from ..dependencies import logger
from ..knowledge.chat import (
    BUNDLED_TRAINING_PDF_SOURCES,
    TRAINING_RAG_CACHE_DIR,
    TRAINING_RAG_VECTORSTORE_DIR,
    get_bundled_training_pdf_source_by_url,
)
from .chat_pdf import (
    MARKER_CACHE_SUFFIX,
    PDF_PARSE_METHOD_MARKER,
    STRUCTURED_CACHE_SUFFIX,
    get_url_hash,
    _parse_pdf_with_marker_best_effort,
    override_marker_gpu_queue,
)
from .chat_pdf_vectorstore import (
    index_pdf_to_vectorstore,
    is_pdf_indexed,
    prewarm_embedding_model,
    search_pdf_chunks,
)


_LOCAL_SOURCE_LOCKS: Dict[str, asyncio.Lock] = {}
_LOCAL_INDEX_READY: set[str] = set()

_TRAINING_ACTION_KEYWORDS = (
    "train", "training", "submit", "create", "start", "launch", "task",
    "训练", "提交", "创建", "新建", "任务", "建一个", "建個",
)
_RECOMMENDATION_KEYWORDS = (
    "recommend", "recommended", "best", "suitable", "architecture", "backbone",
    "feature extractor", "hyperparameter", "config", "recipe",
    "推荐", "建議", "最适合", "最適合", "架构", "架構", "特征提取器", "特徵提取器", "参数", "參數",
)
_TASK_CONTEXT_KEYWORDS = (
    "classification", "segmentation", "survival", "pathology", "histology", "cytology",
    "wsi", "patch", "dataset", "mil", "foundation model",
    "分类", "分類", "分割", "生存", "病理", "细胞", "細胞", "数据集", "資料集",
)
_MODEL_COMPONENT_KEYWORDS = (
    "encoder", "feature extractor", "extractor", "aggregator", "classifier", "mil",
    "backbone", "seg_backbone", "segmentation backbone",
    "编码器", "編碼器", "特征提取器", "特徵提取器", "聚合器", "分类头", "分類頭",
    "骨干", "骨幹",
)
_CERVICAL_KEYWORDS = (
    "cervical", "宫颈", "宮頸", "ccs", "cervix",
    "gynecologic", "gynaecologic", "gyn", "妇科", "婦科",
)
_CYTOLOGY_KEYWORDS = ("cytology", "细胞学", "細胞學", "细胞", "細胞")
_SEGMENTATION_KEYWORDS = ("segmentation", "分割")
_DATASET_HINT_KEYWORDS = ("bracs", "luad", "lusc", "tcga", "crc", "camelyon", "prostate", "kidney")
_HEATMAP_KEYWORDS = (
    "heatmap", "attention map", "attention maps", "attention", "cam",
    "热力图", "熱力圖", "注意力图", "注意力圖",
)
_VISUALIZATION_ACTION_KEYWORDS = (
    "show", "view", "display", "browse", "see", "visualize", "visualization",
    "显示", "顯示", "查看", "檢視", "看", "看看", "浏览", "瀏覽", "可视化", "可視化",
)
_EXISTING_MODEL_VISUALIZATION_KEYWORDS = (
    "trained model", "trained models", "existing trained model", "existing trained models",
    "已有训练模型", "已有訓練模型", "已训练模型", "已訓練模型",
    "可显示热力图", "可顯示熱力圖", "可看热力图", "可看熱力圖",
)
_EXPLICIT_TRAINING_CREATION_KEYWORDS = (
    "train a", "start training", "submit training", "create training", "launch training",
    "训练一个", "訓練一個", "开始训练", "開始訓練", "提交训练", "提交訓練", "新建训练", "新建訓練",
)
_TRAINING_STATUS_KEYWORDS = (
    "trained model", "trained models", "you trained", "you have trained",
    "existing trained model", "existing trained models",
    "已有训练模型", "已有訓練模型", "已训练模型", "已訓練模型",
    "您训练了", "你训练了", "训练了", "您訓練了", "你訓練了", "訓練了",
)
_HEATMAP_SELECTION_PROMPT_KEYWORDS = (
    "which dataset", "what dataset", "which one", "which wsi dataset",
    "available heatmap", "available attention heatmap", "available attention map",
    "please choose", "please select", "select the dataset", "choose the dataset",
    "您想查看哪个数据集", "您想看哪个数据集", "您想查看哪個資料集", "您想看哪個資料集",
    "请选择", "請選擇", "选择您想查看", "選擇您想查看",
    "有可用的注意力热力图", "有可用的注意力圖", "有可用的热力图", "有可用的熱力圖",
)
_DATASET_OPTION_HINT_KEYWORDS = (
    "tcga", "cohort", "wsi", "dataset", "model",
    "数据集", "資料集", "模型",
)
_SEARCH_KEYWORDS = ("search", "web search", "搜索", "搜尋", "检索", "檢索")
_SELECTION_VERB_KEYWORDS = (
    "choose", "select", "pick", "which", "what dataset",
    "请选择", "請選擇", "选择", "選擇", "哪个", "哪個", "哪一个", "哪一個",
)
_MODEL_SELECTION_INTENT_KEYWORDS = (
    "which", "or", "vs", "versus", "compare", "comparison", "better", "best",
    "choose", "select", "pick", "should i use",
    "还是", "比較", "比较", "哪个好", "哪個好", "怎么选", "怎麼選", "选哪个", "選哪個",
)
_VISUALIZATION_TARGET_KEYWORDS = (
    "image", "images", "visualization", "visualize", "view",
    "图像", "影像", "图片", "圖像", "圖", "展示", "查看", "檢視", "浏览", "瀏覽",
    "结果", "結果",
)
_NO_SEARCH_BLOCK_TAGS = (
    "[IMAGE_RECOMMENDATION]",
    "[PATCH_INFERENCE]",
    "[ANALYSIS_CONFIG]",
    "[METRIC_CONFIG]",
    "[CHART_CONFIG]",
    "[QUICK_ANALYSIS_CONFIG]",
)
_VALIDATION_KEYWORDS = (
    "internal validation", "external validation",
    "内部验证", "內部驗證", "外部验证", "外部驗證",
)
_ANALYSIS_PROMPT_KEYWORDS = (
    "which validation", "what validation", "show metrics", "show charts", "show results",
    "full analysis", "analysis result", "analysis results",
    "哪种验证", "哪種驗證", "内部验证", "內部驗證", "外部验证", "外部驗證",
    "显示指标", "顯示指標", "显示图表", "顯示圖表", "显示结果", "顯示結果",
    "完整分析", "分析结果", "分析結果",
)
_RESULT_ACTION_KEYWORDS = (
    "show", "view", "display", "check", "see", "what is", "how much", "give me",
    "显示", "顯示", "查看", "檢視", "展示", "看", "看看", "看一下", "多少", "给我看", "給我看",
)
_LOCAL_RESULT_CONTEXT_KEYWORDS = (
    "this task", "that task", "my task", "this model", "that model", "my model",
    "task result", "analysis result", "validation result", "trained model",
    "这个任务", "這個任務", "该任务", "該任務", "我的任务", "我的任務",
    "这个模型", "這個模型", "该模型", "該模型", "我的模型", "已训练模型", "已訓練模型",
    "这个结果", "這個結果", "该结果", "該結果", "分析结果", "分析結果", "验证结果", "驗證結果",
)
_METRIC_RESULT_KEYWORDS = (
    "metric", "metrics", "chart", "charts", "roc", "roc curve", "auc", "accuracy",
    "precision", "recall", "sensitivity", "specificity", "f1", "weighted kappa", "kappa",
    "confusion matrix", "loss curve", "survival curve", "km curve", "c-index", "c index",
    "integrated brier score", "brier score", "confidence interval", "95% ci",
    "指标", "指標", "图表", "圖表", "roc曲线", "roc 曲线", "roc 曲線", "auc",
    "准确率", "準確率", "精确率", "精確率", "召回率", "灵敏度", "靈敏度", "特异度", "特異度",
    "混淆矩阵", "混淆矩陣", "损失曲线", "損失曲線", "生存曲线", "生存曲線",
    "c-index", "c指数", "brier", "置信区间", "置信區間", "95%置信区间", "95% 置信区间",
)
_FULL_RESULT_KEYWORDS = (
    "full analysis", "full results", "analysis results", "analysis dashboard",
    "完整分析", "完整结果", "完整結果", "分析结果", "分析結果", "分析详情", "分析詳情",
)
_IMAGE_ANALYSIS_KEYWORDS = (
    "analyze this image", "analyse this image", "classify this image", "segment this image",
    "image inference", "run inference on this image", "run classification on this image",
    "run segmentation on this image", "image analysis",
    "分析这张图", "分析這張圖", "分析这个图", "分析這個圖", "分析图片", "分析圖片",
    "图像分析", "圖像分析", "图片分析", "圖片分析", "图像推理", "圖像推理",
    "图片推理", "圖片推理", "对这张图分类", "對這張圖分類", "对这张图分割", "對這張圖分割",
)
_IMAGE_VISUALIZATION_KEYWORDS = (
    "annotation", "annotations", "annotated", "manual annotation", "human annotation",
    "ground truth", "gt", "mask", "masks", "prediction mask", "prediction masks",
    "ai prediction", "ai predictions", "model prediction", "model predictions",
    "model output", "ai output", "overlay", "overlays", "region", "regions",
    "人工标注", "人工標註", "标注", "標註", "真实标注", "真實標註", "真值",
    "掩膜", "mask", "标注区域", "標註區域", "标签区域", "標籤區域",
    "ai 预测", "ai 預測", "ai 识别", "ai 識別", "模型预测", "模型預測",
    "预测区域", "預測區域", "识别区域", "識別區域", "圈出的区域", "圈出的區域",
)
_IMAGE_VISUALIZATION_PROMPT_KEYWORDS = (
    "which model", "what model", "choose model", "select model", "pick a model",
    "latest model", "use latest model", "use the latest model",
    "which source", "mask source", "ground truth or prediction", "gt or prediction",
    "use newest model", "which one should i use",
    "哪个模型", "哪個模型", "选择模型", "選擇模型", "用哪个模型", "用哪個模型",
    "最新模型", "使用最新模型", "请选择模型", "請選擇模型",
    "看人工标注", "看人工標註", "看 ai 预测", "看 ai 預測", "看 ai 识别", "看 ai 識別",
    "看标注区域", "看標註區域", "看预测区域", "看預測區域",
)
_SHORT_FOLLOWUP_KEYWORDS = (
    "start", "run", "submit", "continue", "confirm", "yes", "ok", "okay",
    "classify", "classification", "segment", "segmentation", "internal", "external",
    "开始", "開始", "运行", "運行", "提交", "继续", "繼續", "确认", "確認",
    "可以", "好的", "就这个", "就這個", "这个", "這個", "那个", "那個",
    "分类", "分類", "分割", "内部", "內部", "外部",
)
_SEARCH_ACTION_KEYWORDS = (
    "search", "web search", "look up", "find", "查", "搜", "搜索", "搜尋", "检索", "檢索",
)
_RESEARCH_OBJECT_KEYWORDS = (
    "paper", "papers", "article", "articles", "literature", "pubmed", "arxiv",
    "reference", "references", "citation", "citations", "论文", "論文", "文献", "文獻",
    "参考文献", "參考文獻", "引用", "最新研究",
)


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(part for part in parts if part)
    return str(content or "")


def _message_content_has_image(content: Any) -> bool:
    if not isinstance(content, list):
        return False
    for item in content:
        if isinstance(item, dict) and "image" in str(item.get("type", "")).lower():
            return True
    return False


def _contains_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def looks_like_explicit_research_search_query(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    return bool(
        _contains_any_keyword(normalized, _SEARCH_ACTION_KEYWORDS)
        and _contains_any_keyword(normalized, _RESEARCH_OBJECT_KEYWORDS)
    )


def looks_like_image_analysis_query(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    return _contains_any_keyword(normalized, _IMAGE_ANALYSIS_KEYWORDS)


def looks_like_image_visualization_query(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False

    has_visualization_action = _contains_any_keyword(normalized, _VISUALIZATION_ACTION_KEYWORDS) or _contains_any_keyword(normalized, _RESULT_ACTION_KEYWORDS)
    has_visualization_target = _contains_any_keyword(normalized, _VISUALIZATION_TARGET_KEYWORDS) or _contains_any_keyword(normalized, _HEATMAP_KEYWORDS)
    has_visualization_payload = _contains_any_keyword(normalized, _IMAGE_VISUALIZATION_KEYWORDS)

    return bool((has_visualization_action or has_visualization_target) and has_visualization_payload)


def looks_like_validation_query(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    return _contains_any_keyword(normalized, _VALIDATION_KEYWORDS)


def looks_like_metric_or_result_display_query(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False

    has_metric = _contains_any_keyword(normalized, _METRIC_RESULT_KEYWORDS)
    has_action = _contains_any_keyword(normalized, _RESULT_ACTION_KEYWORDS)
    has_local_context = _contains_any_keyword(normalized, _LOCAL_RESULT_CONTEXT_KEYWORDS)
    has_full_results = _contains_any_keyword(normalized, _FULL_RESULT_KEYWORDS)

    return bool(
        (has_metric and has_action and has_local_context)
        or (has_full_results and (has_local_context or has_metric or has_action))
    )


def looks_like_local_flow_followup(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False

    has_option_shape = any(token in text for token in ("(", ")", "（", "）"))
    has_short_followup = _contains_any_keyword(normalized, _SHORT_FOLLOWUP_KEYWORDS)
    has_local_entity = _contains_any_keyword(
        normalized,
        (
            "task", "dataset", "model", "result", "analysis", "validation",
            "任务", "任務", "数据集", "資料集", "模型", "结果", "結果", "分析", "验证", "驗證",
        ),
    )

    return bool(len(normalized) <= 220 and (has_option_shape or has_short_followup or has_local_entity))


def looks_like_analysis_prompt(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    return bool(
        any(tag in text for tag in _NO_SEARCH_BLOCK_TAGS)
        or _contains_any_keyword(normalized, _ANALYSIS_PROMPT_KEYWORDS)
    )


def looks_like_image_visualization_prompt(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False

    has_visualization_context = (
        "[IMAGE_RECOMMENDATION]" in text
        or _contains_any_keyword(normalized, _IMAGE_VISUALIZATION_KEYWORDS)
        or _contains_any_keyword(normalized, _HEATMAP_KEYWORDS)
    )
    has_selection_prompt = (
        "[OPTIONS]" in text
        or _contains_any_keyword(normalized, _IMAGE_VISUALIZATION_PROMPT_KEYWORDS)
        or (_contains_any_keyword(normalized, _SELECTION_VERB_KEYWORDS) and _contains_any_keyword(normalized, _VISUALIZATION_TARGET_KEYWORDS))
    )

    return bool(has_visualization_context and has_selection_prompt)


def looks_like_heatmap_visualization_query(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False

    has_heatmap = any(keyword in normalized for keyword in _HEATMAP_KEYWORDS)
    if not has_heatmap:
        return False

    has_visualization_action = any(keyword in normalized for keyword in _VISUALIZATION_ACTION_KEYWORDS)
    has_existing_model_visualization = any(
        keyword in normalized for keyword in _EXISTING_MODEL_VISUALIZATION_KEYWORDS
    )
    has_explicit_training_creation = any(
        keyword in normalized for keyword in _EXPLICIT_TRAINING_CREATION_KEYWORDS
    )

    return bool(
        (has_visualization_action or has_existing_model_visualization)
        and not has_explicit_training_creation
    )


def looks_like_heatmap_dataset_selection_prompt(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False

    has_heatmap = any(keyword in normalized for keyword in _HEATMAP_KEYWORDS)
    has_selection_prompt = any(keyword in normalized for keyword in _HEATMAP_SELECTION_PROMPT_KEYWORDS)
    has_selection_verb = any(keyword in normalized for keyword in _SELECTION_VERB_KEYWORDS)
    has_visualization_target = any(keyword in normalized for keyword in _VISUALIZATION_TARGET_KEYWORDS)
    return bool(has_heatmap and ((has_selection_prompt) or (has_selection_verb and has_visualization_target)))


def looks_like_heatmap_dataset_option_selection(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False

    has_heatmap = any(keyword in normalized for keyword in _HEATMAP_KEYWORDS)
    has_dataset_hint = any(keyword in normalized for keyword in _DATASET_HINT_KEYWORDS) or any(
        keyword in normalized for keyword in _DATASET_OPTION_HINT_KEYWORDS
    )
    has_option_shape = any(token in text for token in ("(", ")", "（", "）"))
    has_training_creation = any(keyword in normalized for keyword in _EXPLICIT_TRAINING_CREATION_KEYWORDS)
    has_training_status = any(keyword in normalized for keyword in _TRAINING_STATUS_KEYWORDS)
    has_search = any(keyword in normalized for keyword in _SEARCH_KEYWORDS)
    has_recommendation = any(keyword in normalized for keyword in _RECOMMENDATION_KEYWORDS)

    if has_training_creation or has_search or has_recommendation:
        return False

    return bool(
        len(normalized) <= 220
        and has_dataset_hint
        and (has_option_shape or has_heatmap or has_training_status)
    )


def is_heatmap_visualization_followup(messages: List[Dict[str, Any]]) -> bool:
    if not messages:
        return False

    last_user_idx = None
    for idx in range(len(messages) - 1, -1, -1):
        if messages[idx].get("role") == "user":
            content = messages[idx].get("content", "")
            if isinstance(content, str) and content.strip():
                last_user_idx = idx
                break
            if not isinstance(content, str):
                last_user_idx = idx
                break

    if last_user_idx is None:
        return False

    latest_user_text = _message_content_to_text(messages[last_user_idx].get("content", ""))
    if looks_like_heatmap_visualization_query(latest_user_text):
        return True
    if not looks_like_heatmap_dataset_option_selection(latest_user_text):
        return False

    previous_assistant_text = ""
    for idx in range(last_user_idx - 1, -1, -1):
        if messages[idx].get("role") == "assistant":
            previous_assistant_text = _message_content_to_text(messages[idx].get("content", ""))
            break

    return looks_like_heatmap_dataset_selection_prompt(previous_assistant_text)


def detect_no_web_search_mode(messages: List[Dict[str, Any]]) -> str | None:
    if not messages:
        return None

    last_user_idx = None
    for idx in range(len(messages) - 1, -1, -1):
        if messages[idx].get("role") == "user":
            content = messages[idx].get("content", "")
            if isinstance(content, str) and content.strip():
                last_user_idx = idx
                break
            if not isinstance(content, str):
                last_user_idx = idx
                break

    if last_user_idx is None:
        return None

    last_user_message = messages[last_user_idx]
    latest_user_text = _message_content_to_text(last_user_message.get("content", ""))
    if looks_like_explicit_research_search_query(latest_user_text):
        return None

    previous_assistant_text = ""
    for idx in range(last_user_idx - 1, -1, -1):
        if messages[idx].get("role") == "assistant":
            previous_assistant_text = _message_content_to_text(messages[idx].get("content", ""))
            break

    if _message_content_has_image(last_user_message.get("content")) or looks_like_image_analysis_query(latest_user_text):
        return "patch_inference"

    if looks_like_image_visualization_query(latest_user_text):
        return "image_visualization"

    if is_heatmap_visualization_followup(messages):
        return "image_visualization"

    if looks_like_validation_query(latest_user_text) or looks_like_metric_or_result_display_query(latest_user_text):
        return "analysis_results"

    if "[PATCH_INFERENCE]" in previous_assistant_text and looks_like_local_flow_followup(latest_user_text):
        return "patch_inference"

    if "[IMAGE_RECOMMENDATION]" in previous_assistant_text and looks_like_local_flow_followup(latest_user_text):
        return "image_visualization"

    if looks_like_image_visualization_prompt(previous_assistant_text) and looks_like_local_flow_followup(latest_user_text):
        return "image_visualization"

    if looks_like_analysis_prompt(previous_assistant_text) and looks_like_local_flow_followup(latest_user_text):
        return "analysis_results"

    return None


def looks_like_training_recommendation_query(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    if looks_like_heatmap_visualization_query(normalized):
        return False
    if looks_like_image_visualization_query(normalized):
        return False
    has_training_status = any(keyword in normalized for keyword in _TRAINING_STATUS_KEYWORDS)
    has_training_action = any(keyword in normalized for keyword in _TRAINING_ACTION_KEYWORDS) and not has_training_status
    has_recommendation = any(keyword in normalized for keyword in _RECOMMENDATION_KEYWORDS)
    has_task_context = any(keyword in normalized for keyword in _TASK_CONTEXT_KEYWORDS)
    has_model_component = any(keyword in normalized for keyword in _MODEL_COMPONENT_KEYWORDS)
    has_dataset_hint = any(keyword in normalized for keyword in _DATASET_HINT_KEYWORDS)
    has_model_selection_intent = any(keyword in normalized for keyword in _MODEL_SELECTION_INTENT_KEYWORDS)
    return bool(
        (has_training_action and (has_task_context or has_dataset_hint or has_model_component))
        or (has_recommendation and (has_task_context or has_dataset_hint or has_training_action or has_model_component))
        or (has_model_component and has_dataset_hint and has_model_selection_intent)
    )


def detect_training_recommendation_profile(text: str) -> str:
    normalized = (text or "").strip().lower()
    if any(keyword in normalized for keyword in _CERVICAL_KEYWORDS):
        return "cervical_cytology"
    if any(keyword in normalized for keyword in _CYTOLOGY_KEYWORDS):
        return "general_cytology"
    if any(keyword in normalized for keyword in _SEGMENTATION_KEYWORDS):
        return "segmentation"
    return "histopathology"


def get_training_recommendation_source_urls(profile: str) -> List[str]:
    if profile == "cervical_cytology":
        source_ids = ["smart_ccs"]
    elif profile in {"histopathology", "segmentation"}:
        source_ids = ["pathbench"]
    else:
        source_ids = []
    return [str(BUNDLED_TRAINING_PDF_SOURCES[source_id]["url"]) for source_id in source_ids if source_id in BUNDLED_TRAINING_PDF_SOURCES]


def get_bundled_training_knowledge_status() -> Dict[str, bool]:
    status: Dict[str, bool] = {}
    for source in BUNDLED_TRAINING_PDF_SOURCES.values():
        url = str(source["url"])
        url_hash = get_url_hash(url)
        marker_ready = _get_bundled_markdown(url) is not None
        structured_ready = _get_bundled_structured_content(url) is not None
        vector_ready = bool(url_hash in _LOCAL_INDEX_READY or is_pdf_indexed(url_hash, vectorstore_dir=TRAINING_RAG_VECTORSTORE_DIR))
        status[str(source["id"])] = bool(marker_ready and structured_ready and vector_ready)
    return status


async def ensure_training_recommendation_sources_for_query(
    text: str,
    *,
    force_upgrade: bool = False,
) -> List[str]:
    profile = detect_training_recommendation_profile(text)
    urls = get_training_recommendation_source_urls(profile)
    for url in urls:
        await _ensure_local_source_ready(url, force_upgrade=force_upgrade)
    return urls


async def prewarm_training_recommendation_sources(
    *,
    force_upgrade: bool = False,
    skip_marker_gpu_queue: bool = False,
    prewarm_embedding: bool = True,
) -> Dict[str, bool]:
    results: Dict[str, bool] = {}
    if prewarm_embedding:
        await asyncio.to_thread(prewarm_embedding_model)
    with override_marker_gpu_queue(skip_marker_gpu_queue):
        for source in BUNDLED_TRAINING_PDF_SOURCES.values():
            source_id = str(source["id"])
            source_url = str(source["url"])
            logger.info(f"[BundledTrainingRAG] Preparing source: {source_id}")
            results[source_id] = await _ensure_local_source_ready(source_url, force_upgrade=force_upgrade)
    return results


async def build_training_recommendation_evidence_context(text: str, detected_lang: str) -> str:
    profile = detect_training_recommendation_profile(text)
    urls = await ensure_training_recommendation_sources_for_query(text, force_upgrade=False)
    sections: list[str] = []

    prior_lines = _build_profile_prior_lines(profile, detected_lang)
    if prior_lines:
        sections.append("\n".join(prior_lines))

    evidence_lines = _build_bundled_evidence_lines(text, urls, detected_lang)
    if evidence_lines:
        sections.append("\n".join(evidence_lines))

    return "\n\n".join(section for section in sections if section.strip())


async def _ensure_local_source_ready(url: str, *, force_upgrade: bool = False) -> bool:
    source = get_bundled_training_pdf_source_by_url(url)
    if source is None:
        return False

    lock = _LOCAL_SOURCE_LOCKS.setdefault(url, asyncio.Lock())
    async with lock:
        path = Path(source["path"])
        if not path.exists():
            logger.warning(f"Bundled training recommendation PDF not found: {path}")
            return False

        url_hash = get_url_hash(url)
        ready = bool(
            _get_bundled_markdown(url)
            and _get_bundled_structured_content(url)
            and is_pdf_indexed(url_hash, vectorstore_dir=TRAINING_RAG_VECTORSTORE_DIR)
        )
        if ready and not force_upgrade:
            _LOCAL_INDEX_READY.add(url_hash)
            return True

        logger.info(f"[BundledTrainingRAG] Parsing {source['id']} with Marker directly")
        marker_result = await _parse_pdf_with_marker_best_effort(
            path.read_bytes(),
            0,
            None,
            None,
            upgrade_url=None,
        )
        if marker_result is None or not marker_result.markdown.strip() or marker_result.markdown.startswith("[Error"):
            logger.warning(f"Bundled training recommendation parse failed: {path}")
            return False

        await asyncio.to_thread(
            _save_bundled_marker_cache,
            url,
            str(source["title"]),
            str(source["id"]),
            marker_result.markdown,
            marker_result.structured_content,
            marker_result.page_count,
        )
        await _ensure_vector_index(
            url,
            marker_result.markdown,
            str(source["title"]),
            marker_result.structured_content,
            force=True,
        )
        return True


async def _ensure_vector_index(
    url: str,
    markdown: str,
    paper_title: str,
    structured_content: dict[str, Any] | None,
    *,
    force: bool = False,
) -> None:
    url_hash = get_url_hash(url)
    if not force and url_hash in _LOCAL_INDEX_READY:
        return
    if not force and is_pdf_indexed(url_hash, vectorstore_dir=TRAINING_RAG_VECTORSTORE_DIR):
        _LOCAL_INDEX_READY.add(url_hash)
        return
    await asyncio.to_thread(
        index_pdf_to_vectorstore,
        url_hash,
        markdown,
        paper_title,
        structured_content,
        vectorstore_dir=TRAINING_RAG_VECTORSTORE_DIR,
    )
    _LOCAL_INDEX_READY.add(url_hash)


def _build_profile_prior_lines(profile: str, detected_lang: str) -> list[str]:
    if detected_lang == "zh-CN":
        if profile == "cervical_cytology":
            return [
                "## 任务相关证据约束",
                "- 宫颈 / 妇科细胞学任务优先考虑 Smart-CCS。",
                "- 不要让组织病理 benchmark 结论覆盖这个细胞学任务边界。",
            ]
        if profile == "general_cytology":
            return [
                "## 任务相关证据约束",
                "- 非宫颈 / 非妇科或通用细胞学任务优先把 SmartCyto 作为细胞学 encoder 选项。",
                "- 如果公开搜索没有直接命中 SmartCyto，不要把它当成反证；改用同任务公开证据来校准 encoder、MIL 或 segmentation 方案。",
            ]
        if profile == "segmentation":
            return [
                "## 任务相关证据约束",
                "- 组织病理分割优先参考任务匹配的 PathBench / 分割 benchmark 证据，再结合联网搜索判断标准分割还是 FM 分割。",
                "- 不要默认 UNI 或任何单一 FM extractor 是通用最优。",
            ]
        return [
            "## 任务相关证据约束",
            "- 组织病理训练推荐优先参考任务/器官匹配的 PathBench 结果，再结合联网搜索补时效性。",
            "- 不要把 UNI 或任何单一 encoder 表述成普遍最优；根据任务、器官、数据规模和模型形式（encoder/MIL/segmentation）来选。",
        ]

    if detected_lang == "zh-HK":
        if profile == "cervical_cytology":
            return [
                "## 任務相關證據約束",
                "- 宮頸 / 婦科細胞學任務優先考慮 Smart-CCS。",
                "- 不要讓組織病理 benchmark 結論覆蓋這個細胞學任務邊界。",
            ]
        if profile == "general_cytology":
            return [
                "## 任務相關證據約束",
                "- 非宮頸 / 非婦科或通用細胞學任務優先把 SmartCyto 作為細胞學 encoder 選項。",
                "- 如果公開搜索沒有直接命中 SmartCyto，不要把它當成反證；改用同任務公開證據來校準 encoder、MIL 或 segmentation 方案。",
            ]
        if profile == "segmentation":
            return [
                "## 任務相關證據約束",
                "- 組織病理分割優先參考任務匹配的 PathBench / 分割 benchmark 證據，再結合聯網搜索判斷標準分割還是 FM 分割。",
                "- 不要預設 UNI 或任何單一 FM extractor 是通用最優。",
            ]
        return [
            "## 任務相關證據約束",
            "- 組織病理訓練推薦優先參考任務/器官匹配的 PathBench 結果，再結合聯網搜索補時效性。",
            "- 不要把 UNI 或任何單一 encoder 表述成普遍最優；應根據任務、器官、資料規模和模型形式（encoder/MIL/segmentation）來選。",
        ]

    if profile == "cervical_cytology":
        return [
            "## Task-specific Evidence Constraints",
            "- Prefer Smart-CCS for cervical / gynecologic cytology tasks.",
            "- Do not let histopathology benchmark conclusions override this cytology task boundary.",
        ]
    if profile == "general_cytology":
        return [
            "## Task-specific Evidence Constraints",
            "- For non-cervical, non-gynecologic, or general cytology tasks, keep SmartCyto as the preferred cytology encoder option.",
            "- If public search does not directly surface SmartCyto, do not treat that as counter-evidence; use task-matched public evidence to calibrate encoder, MIL, or segmentation choices.",
        ]
    if profile == "segmentation":
        return [
            "## Task-specific Evidence Constraints",
            "- For pathology segmentation, prioritize task-matched PathBench / segmentation-benchmark evidence, then verify freshness on the web.",
            "- Do not assume UNI or any single FM extractor is universally best.",
        ]
    return [
        "## Task-specific Evidence Constraints",
        "- For histopathology training recommendation, prioritize task/organ-matched PathBench evidence, then verify freshness on the web.",
        "- Do not present UNI or any single encoder as universally best; choose according to task, organ, data scale, and model form (encoder/MIL/segmentation).",
    ]


def _build_bundled_evidence_lines(query: str, urls: list[str], detected_lang: str) -> list[str]:
    if detected_lang == "zh-CN":
        header = "## 内部检索线索（仅供内部判断，不可直接向用户引用）"
        guard_lines = [
            "- 不要向用户提及内置 PDF、Local PDF、本地证据、页码、URL、论文标题或隐藏来源。",
            "- 只把下面线索消化成推荐判断、搜索方向和最终结论，不要把它们当成可见引文或 inline citation。",
        ]
        cue_prefix = "- 线索"
    elif detected_lang == "zh-HK":
        header = "## 內部檢索線索（僅供內部判斷，不可直接向使用者引用）"
        guard_lines = [
            "- 不要向使用者提及內置 PDF、Local PDF、本地證據、頁碼、URL、論文標題或隱藏來源。",
            "- 只把下面線索消化成推薦判斷、搜尋方向和最終結論，不要把它們當成可見引文或 inline citation。",
        ]
        cue_prefix = "- 線索"
    else:
        header = "## Internal Retrieval Cues (reason privately; do not cite verbatim to the user)"
        guard_lines = [
            "- Never mention bundled PDF, Local PDF, internal evidence, page numbers, URLs, paper titles, or hidden sources to the user.",
            "- Convert the cues below into recommendation reasoning, search directions, and conclusions instead of visible citations or inline references.",
        ]
        cue_prefix = "- Cue"

    lines: list[str] = [header, *guard_lines]
    found_any = False
    seen_excerpts: set[str] = set()
    for url in urls:
        url_hash = get_url_hash(url)
        results = search_pdf_chunks(
            query,
            url_hashes=[url_hash],
            top_k=6,
            vectorstore_dir=TRAINING_RAG_VECTORSTORE_DIR,
        )
        if not results:
            continue
        for item in results[:4]:
            excerpt = _sanitize_bundled_evidence_excerpt(
                str(item.get("display_text") or item.get("chunk_text") or "")
            )
            if not excerpt or excerpt in seen_excerpts:
                continue
            found_any = True
            seen_excerpts.add(excerpt)
            lines.append(f"{cue_prefix}: {excerpt}")
            if len(seen_excerpts) >= 6:
                break
        if len(seen_excerpts) >= 6:
            break
    if not found_any:
        if detected_lang == "zh-CN":
            lines.append("- 当前没有检索到匹配片段，但仍应保留上述任务约束，并继续联网搜索。")
        elif detected_lang == "zh-HK":
            lines.append("- 當前沒有檢索到匹配片段，但仍應保留上述任務約束，並繼續聯網搜索。")
        else:
            lines.append("- No matching bundled excerpts were retrieved, but you should still preserve the task-specific constraints above and continue with web search.")
    return lines


def _get_bundled_meta(url: str) -> dict[str, Any] | None:
    meta_path = _get_bundled_cache_dir() / f"{get_url_hash(url)}.json"
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _get_bundled_markdown(url: str) -> str | None:
    md_path = _get_bundled_cache_dir() / f"{get_url_hash(url)}{MARKER_CACHE_SUFFIX}"
    if not md_path.exists():
        return None
    try:
        return md_path.read_text(encoding="utf-8")
    except Exception:
        return None


def _get_bundled_structured_content(url: str) -> dict[str, Any] | None:
    structured_path = _get_bundled_cache_dir() / f"{get_url_hash(url)}{STRUCTURED_CACHE_SUFFIX}"
    if not structured_path.exists():
        return None
    try:
        data = json.loads(structured_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _save_bundled_marker_cache(
    url: str,
    title: str,
    source_id: str,
    markdown: str,
    structured_content: dict[str, Any] | None,
    page_count: int,
) -> None:
    cache_dir = _get_bundled_cache_dir()
    url_hash = get_url_hash(url)
    (cache_dir / f"{url_hash}{MARKER_CACHE_SUFFIX}").write_text(markdown, encoding="utf-8")
    structured_path = cache_dir / f"{url_hash}{STRUCTURED_CACHE_SUFFIX}"
    structured_path.write_text(
        json.dumps(structured_content or {}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    meta = {
        "url": url,
        "title": title,
        "source_id": source_id,
        "source_type": "bundled_training_pdf",
        "cached_at": datetime.now().isoformat(),
        "parse_method": PDF_PARSE_METHOD_MARKER,
        "structured_parse_method": PDF_PARSE_METHOD_MARKER,
        "structured_parse_ready": True,
        "high_quality_parse_pending": False,
        "high_quality_parse_ready": True,
        "page_count": page_count,
    }
    (cache_dir / f"{url_hash}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _get_bundled_cache_dir() -> Path:
    TRAINING_RAG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return TRAINING_RAG_CACHE_DIR


def _clean_excerpt(text: str, max_chars: int = 380) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 1].rstrip() + "…"


def _sanitize_bundled_evidence_excerpt(text: str) -> str:
    compact = _clean_excerpt(text, max_chars=280)
    compact = re.sub(r"^\[Section:[^\]]+\]\s*", "", compact, flags=re.IGNORECASE)
    compact = re.sub(r"\b(?:p\.?|page)\s*\d+(?:\s*[-–]\s*\d+)?\b", "", compact, flags=re.IGNORECASE)
    compact = re.sub(r"\s+", " ", compact).strip(" -:;,.，；：")
    return compact

