"""
Prompt templates for PathLab Agent.
"""
import re
from pathlib import Path
from typing import Dict, Any, Optional

PROMPTS_DIR = Path(__file__).parent

# Cache loaded templates to avoid repeated file I/O
_template_cache: Dict[str, str] = {}

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
_CJK_RE = re.compile(
    r"[\u4e00-\u9fff\u3400-\u4dbf]"
)

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


def get_chat_system_prompt(lang: Optional[str] = None) -> str:
    """
    Get the PathLab Agent system prompt for the given language.

    Args:
        lang: Language code (``"en"``, ``"zh_CN"``, or ``"zh_HK"``).
              Falls back to ``"en"`` when *None* or unsupported.

    Returns:
        The full system prompt content
    """
    if lang not in SUPPORTED_LANGS:
        lang = _DEFAULT_LANG
    return load_prompt(f"chat_system_prompt_{lang}")


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
) -> str:
    """
    Format the user data context template with actual values.

    Args:
        wsi_count: Total number of WSI/images
        data_types_info: Data types distribution info
        datasets_list: Formatted list of datasets
        models_count: Number of trained models
        models_list: Formatted list of models
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

    Returns:
        Formatted user data context string
    """
    template = get_user_data_context_template()

    data_visibility = "Can see ALL users' data" if is_admin else "Can only see OWN data (plus datasets with temporary access below)"
    can_use_gpu = "Yes" if can_use_gpu_base else "No (Guest role - requires admin-granted permission)"

    return template.format(
        wsi_count=wsi_count,
        data_types_info=data_types_info,
        datasets_list=datasets_list,
        models_count=models_count,
        models_list=models_list,
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
    )

