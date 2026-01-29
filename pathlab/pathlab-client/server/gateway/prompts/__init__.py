"""
Prompt templates for PathLab Agent.
"""
from pathlib import Path
from typing import Dict, Any

PROMPTS_DIR = Path(__file__).parent

# Cache loaded templates to avoid repeated file I/O
_template_cache: Dict[str, str] = {}


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


def get_chat_system_prompt() -> str:
    """
    Get the PathLab Agent system prompt for chat.

    Returns:
        The full system prompt content
    """
    return load_prompt("chat_system_prompt")


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

