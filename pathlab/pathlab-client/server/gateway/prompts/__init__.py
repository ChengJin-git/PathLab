"""Prompt templates and helpers for PathLab Agent.

This module also integrates the feature extractor metadata from
``feature_extractors_meta.json`` so that the chat Agent has an
authoritative, non-hallucinating reference for supported feature
extractors (GPFM, UNI, Virchow, etc.).
"""

import json
import re
from pathlib import Path
from typing import Dict, Any, Optional, List

from ..knowledge.chat import (
    FEATURE_EXTRACTOR_META_PATH,
)

PROMPTS_DIR = Path(__file__).parent

# Cache loaded templates to avoid repeated file I/O
_template_cache: Dict[str, str] = {}

# Cache for parsed feature extractor metadata (loaded from JSON once)
_feature_extractor_meta_cache: Optional[Dict[str, Any]] = None

# Supported language codes and their prompt file suffixes
SUPPORTED_LANGS = ("en", "zh_CN", "zh_HK")
_DEFAULT_LANG = "en"


def load_prompt(name: str) -> str:
    """
    Load a prompt template from file (with caching).

    Args:
        name: Name of the prompt file (without .txt extension)

    Returns:
        The prompt content as string
    """
    if name in _template_cache:
        return _template_cache[name]

    prompt_path = PROMPTS_DIR / f"{name}.txt"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt template not found: {prompt_path}")

    content = prompt_path.read_text(encoding="utf-8")
    _template_cache[name] = content
    return content


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

# CJK Unified Ideographs & Extension-A (covers both Simplified & Traditional)
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")

# Characters that appear predominantly in Traditional Chinese but rarely in
# Simplified Chinese.  This is a pragmatic subset – not exhaustive, but
# sufficient for distinguishing zh_HK from zh_CN in typical user messages.
_TRADITIONAL_CHARS = frozenset(
    "書學國會點說開認車錢醫電對陽圖從問個與長設還進關頭種達區計資遠際幾時論環廠節權備術確機園間變報職記連構業總愛達當與線結選該裝層歷華發師設議響選節單識從還龍無範較處過學達關課區競視適種環資設總義論際遠記間論質選記識適單議從選還門課單識適總處際國學書對說電認報開問設進關計區遠際論環資設確機園間變報職記連構業總愛達當與線結選該裝層歷華發師設議響選節單識從還龍無範較處過學達關課區競視適種環資設總義論際遠記間論質選記識適單議從選還門課單識適總處際國學書對說電認報開問設進關計區遠際論環資設確機園間變報職記連構業總愛達當與線結選該裝層歷華發師設議響選節單識從還龍無範較處過學達關課區競視適種環資設總義論際遠記間論質選記識適單議從選還門課單識適總處際"
    # common HK-only chars
    "這裡來為麼發現會說時學點對還過問關開車認電視從種達計結際論環區間連構業總當與選該裝歷華師響節單識較處關競適義記選議質議課門報確設資機備權種術處層園職達備證總幫構結實裡對開場識種環認報設進關計區際論環資設確機園間變報職記連構業總愛達當與線結選該裝層歷華發師設議響選節單識從還龍無範較處過學達關課區競視適種環資設總義論際遠記間論質選記識適單議從選還門課單識適總處際國學書對說電認報開問設進關計區遠際論環資設確機園間變報職記連構業總愛達當與線結選該裝層歷華發師設議響選節單識從還龍無範較處過學達關課區競視適種環資設總義論際遠記間論質選記識適單議從選還門課單識適總處際"
)


def detect_language(text: str) -> str:
    """Detect the dominant language in *text* and return a language code.

    Returns one of ``"en"``, ``"zh_CN"``, or ``"zh_HK"``.

    The heuristic is intentionally simple and cheap:
    1. Count CJK ideograph characters vs total non-whitespace characters.
    2. If CJK ratio ≥ 0.3 → Chinese.  Else → English.
    3. Among the CJK characters, if ≥ 30 % are in the Traditional-only set
       → ``"zh_HK"``; otherwise ``"zh_CN"``.
    """
    if not text or not text.strip():
        return _DEFAULT_LANG

    cjk_chars = _CJK_RE.findall(text)
    non_ws = re.sub(r"\s", "", text)

    if not non_ws:
        return _DEFAULT_LANG

    cjk_ratio = len(cjk_chars) / len(non_ws)
    if cjk_ratio < 0.3:
        return "en"

    # Distinguish Simplified vs Traditional
    if not cjk_chars:
        return "en"

    trad_count = sum(1 for ch in cjk_chars if ch in _TRADITIONAL_CHARS)
    trad_ratio = trad_count / len(cjk_chars)
    return "zh_HK" if trad_ratio >= 0.3 else "zh_CN"


def _load_feature_extractor_meta() -> Dict[str, Any]:
    """Load feature extractor metadata from JSON (with caching).

    The metadata file is optional. If it is missing or cannot be
    parsed, this function returns an empty structure so that the chat
    agent continues to work without raising errors.
    """

    global _feature_extractor_meta_cache

    if _feature_extractor_meta_cache is not None:
        return _feature_extractor_meta_cache

    meta_path = FEATURE_EXTRACTOR_META_PATH
    if not meta_path.exists():
        _feature_extractor_meta_cache = {"metadata_version": 1, "extractors": {}}
        return _feature_extractor_meta_cache

    try:
        content = meta_path.read_text(encoding="utf-8")
        data = json.loads(content)
        # Basic shape check – be tolerant and never raise here
        if not isinstance(data, dict):
            data = {"metadata_version": 1, "extractors": {}}
    except Exception:
        data = {"metadata_version": 1, "extractors": {}}

    _feature_extractor_meta_cache = data
    return data


def _build_feature_extractor_reference(lang: str) -> str:
    """Build a language-specific reference section for feature extractors.

    This section is appended to the base system prompt so that the AI
    Agent has authoritative, non-hallucinated descriptions for all
    *supported* feature extractors.

    Behavioural rules encoded here:
    - Only describe feature extractors that exist in this metadata
      file; never invent new ones.
    - For names like "GPFM", always use the provided expansion and
      description (Generalizable Pathology Foundation Model), and NEVER
      reinterpret it as "General Purpose Foundation Model".
    - Ask for web search (via [WEB_SEARCH]) when the user explicitly
      asks for papers, external benchmarks, or latest research beyond
      PathLab's own integration, OR when a current evidence-based
      training recommendation depends on external benchmark/literature
      evidence.
    """

    if lang not in SUPPORTED_LANGS:
        lang = _DEFAULT_LANG

    meta = _load_feature_extractor_meta()
    extractors = meta.get("extractors", {}) or {}
    if not extractors:
        return ""

    # Language-specific text fragments
    if lang == "zh_CN":
        header = (
            "\n\n## 特征提取器参考（严格遵守）\n\n"
            "下面是可引用的特征提取器参考。回答相关问题时：\n"
            "- **只使用这里列出的名称和简介**，不要编造新的特征提取器；\n"
            "- **不要告诉用户总共有多少个特征提取器**，也不要自己数数后输出总数；如需回答范围，只说有多个受支持选项，并根据任务给出相关候选；\n"
            "- **不要改变或推测含义**，尤其是 GPFM，只能理解为 Generalizable Pathology Foundation Model；\n"
            "- **当用户明确要求“帮我查论文 / 更多背景 / 最新进展”时，或当训练推荐明显需要外部 benchmark / 文献证据时，才使用 [WEB_SEARCH] 查找外部资料。**\n\n"
            "支持的特征提取器参考（按 id 排序）：\n"
        )
        desc_key = "desc_zh_CN"
        line_template = (
            "- {display_name}（id: {id}，backbone: {backbone}，dim: {dim}）：{desc}\n"
        )
    elif lang == "zh_HK":
        header = (
            "\n\n## 特徵提取器參考（必須遵守）\n\n"
            "以下是可引用的特徵提取器參考。回應相關問題時：\n"
            "- **只使用這裡列出的名稱和簡介**，不要編造新的特徵提取器；\n"
            "- **不要告訴使用者總共有多少個特徵提取器**，也不要自己數數後輸出總數；如需回答範圍，只說有多個受支援選項，並按任務給出相關候選；\n"
            "- **不要改變或猜測含義**，特別是 GPFM，只能理解為 Generalizable Pathology Foundation Model；\n"
            "- **當使用者明確要求「幫我查論文 / 更多背景 / 最新進展」時，或當訓練推薦明顯需要外部 benchmark / 文獻證據時，才使用 [WEB_SEARCH] 查找外部資料。**\n\n"
            "支援的特徵提取器參考（按 id 排序）：\n"
        )
        desc_key = "desc_zh_HK"
        line_template = (
            "- {display_name}（id: {id}，backbone: {backbone}，dim: {dim}）：{desc}\n"
        )
    else:  # "en"
        header = (
            "\n\n## Feature Extractor Reference (authoritative)\n\n"
            "The following is the feature extractor reference to cite from. When answering questions about them:\n"
            "- **Only use the names and descriptions listed here**; never invent new extractors;\n"
            "- **Do not tell the user the total number of feature extractors** and do not count them yourself for the reply; if scope matters, just say there are multiple supported options and narrow to task-relevant candidates;\n"
            "- **Do not change or guess meanings** – in particular, GPFM **must** be understood as Generalizable Pathology Foundation Model,\n"
            '  not "General Purpose Foundation Model";\n'
            "- **Request web search ([WEB_SEARCH]) when the user explicitly asks** for papers, external benchmarks, or latest research beyond PathLab, **or when an evidence-based training recommendation clearly depends on current external benchmark/literature evidence.**\n\n"
            "Supported feature extractor reference (sorted by id):\n"
        )
        desc_key = "desc_en"
        line_template = (
            "- {display_name} (id: {id}, backbone: {backbone}, dim: {dim}): {desc}\n"
        )

    lines: List[str] = [header]
    for extractor_id in sorted(extractors.keys()):
        info = extractors.get(extractor_id) or {}
        display_name = info.get("display_name", extractor_id)
        backbone = info.get("backbone", "unknown")
        dim = info.get("embedding_dim", "?")
        desc = info.get(desc_key) or info.get("desc_en") or ""
        if not desc:
            # Skip entries without any usable description to avoid noise
            continue
        lines.append(
            line_template.format(
                display_name=display_name,
                id=extractor_id,
                backbone=backbone,
                dim=dim,
                desc=desc,
            )
        )

    return "".join(lines)


def get_chat_system_prompt(lang: Optional[str] = None) -> str:
    """Get the full PathLab Agent system prompt for the given language.

    This concatenates the language-specific base prompt with an
    auto-generated **Feature Extractor Reference** section built from
    ``knowledge/chat/feature_extractors_meta.json``.

    If anything goes wrong when building the reference (missing file,
    JSON parse error, etc.), the function gracefully falls back to the
    base prompt only.
    """

    if lang not in SUPPORTED_LANGS:
        lang = _DEFAULT_LANG

    base_prompt = load_prompt(f"chat_system_prompt_{lang}")

    try:
        fe_ref = _build_feature_extractor_reference(lang)
    except Exception:
        fe_ref = ""

    return base_prompt + fe_ref


def get_user_data_context_template() -> str:
    """
    Get the user data context template for chat.

    Returns:
        The template string with placeholders
    """
    return load_prompt("user_data_context")


def format_user_data_context(
    wsi_count: int,
    data_types_info: str,
    datasets_list: str,
    models_count: int,
    models_list: str,
    models_shown: int,
    models_selection_note: str,
    training_tasks_total: int,
    training_tasks_completed: int,
    training_tasks_running: int,
    training_tasks_failed: int,
    training_tasks_list: str,
    inference_tasks_total: int,
    inference_tasks_completed: int,
    inference_tasks_running: int,
    inference_tasks_list: str,
    gpu_summary: str,
    user_role: str,
    is_admin: bool,
    can_use_gpu_base: bool,
    temp_perms_list: str,
    own_public_datasets_count: int,
    own_private_datasets_count: int,
    elevated_datasets_count: int,
    other_public_datasets_count: int,
    current_datetime: str,
) -> str:
    """
    Format the user data context template with actual values.

    Args:
        wsi_count: Total number of WSI/images
        data_types_info: Data types distribution info
        datasets_list: Formatted list of datasets
        models_count: Number of trained models
        models_list: Formatted list of models
        models_shown: Number of model entries shown in context
        models_selection_note: Human-readable selection strategy note
        training_tasks_total: Total number of training tasks
        training_tasks_completed: Number of completed training tasks
        training_tasks_running: Number of running training tasks
        training_tasks_failed: Number of failed training tasks
        training_tasks_list: Formatted list of recent training tasks
        inference_tasks_total: Total number of inference tasks
        inference_tasks_completed: Number of completed inference tasks
        inference_tasks_running: Number of running inference tasks
        inference_tasks_list: Formatted list of recent inference tasks
        gpu_summary: GPU status summary
        user_role: User's role (admin, pathologist, guest)
        is_admin: Whether user is admin
        can_use_gpu_base: Whether user can use GPU by default
        temp_perms_list: Formatted list of temporary permissions
        own_public_datasets_count: Number of user's own public datasets
        own_private_datasets_count: Number of user's own private datasets
        elevated_datasets_count: Number of temporarily elevated-access datasets
        current_datetime: Current datetime string in the user's local timezone

    Returns:
        Formatted user data context string
    """
    template = get_user_data_context_template()

    data_visibility = (
        "Can see ALL users' data (admin)"
        if is_admin
        else "Can only see OWN data, other users' PUBLIC datasets, and datasets with temporary elevated access"
    )
    if is_admin:
        can_use_gpu = "Yes"
    elif can_use_gpu_base:
        can_use_gpu = "Yes (GPU operations allowed by role, but GPU usage details are hidden for non-admin users)"
    else:
        can_use_gpu = "No (GPU operations not allowed by role; GPU usage details are hidden for non-admin users)"

    return template.format(
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
        data_visibility=data_visibility,
        can_use_gpu=can_use_gpu,
        temp_perms_list=temp_perms_list,
        own_public_datasets_count=own_public_datasets_count,
        own_private_datasets_count=own_private_datasets_count,
        elevated_datasets_count=elevated_datasets_count,
        other_public_datasets_count=other_public_datasets_count,
        current_datetime=current_datetime,
    )
