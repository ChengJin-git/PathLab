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
    _get_url_hash,
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


def looks_like_training_recommendation_query(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    has_training_action = any(keyword in normalized for keyword in _TRAINING_ACTION_KEYWORDS)
    has_recommendation = any(keyword in normalized for keyword in _RECOMMENDATION_KEYWORDS)
    has_task_context = any(keyword in normalized for keyword in _TASK_CONTEXT_KEYWORDS)
    has_model_component = any(keyword in normalized for keyword in _MODEL_COMPONENT_KEYWORDS)
    has_dataset_hint = any(keyword in normalized for keyword in _DATASET_HINT_KEYWORDS)
    return bool(
        (has_training_action and (has_task_context or has_dataset_hint or has_model_component))
        or (has_recommendation and (has_task_context or has_dataset_hint or has_training_action or has_model_component))
        or (has_model_component and (has_task_context or has_training_action or has_dataset_hint))
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
        url_hash = _get_url_hash(url)
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

        url_hash = _get_url_hash(url)
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
    structured_content: dict | None,
    *,
    force: bool = False,
) -> None:
    url_hash = _get_url_hash(url)
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
        url_hash = _get_url_hash(url)
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
    meta_path = _get_bundled_cache_dir() / f"{_get_url_hash(url)}.json"
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _get_bundled_markdown(url: str) -> str | None:
    md_path = _get_bundled_cache_dir() / f"{_get_url_hash(url)}{MARKER_CACHE_SUFFIX}"
    if not md_path.exists():
        return None
    try:
        return md_path.read_text(encoding="utf-8")
    except Exception:
        return None


def _get_bundled_structured_content(url: str) -> dict[str, Any] | None:
    structured_path = _get_bundled_cache_dir() / f"{_get_url_hash(url)}{STRUCTURED_CACHE_SUFFIX}"
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
    url_hash = _get_url_hash(url)
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

