# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import dataclasses
import os
from datetime import datetime
from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape
from langchain.agents import AgentState

from src.config.configuration import Configuration
from src.pathlab import (
    get_datasets_for_prompt,
    get_models_for_prompt,
    get_extractors_for_prompt,
    get_aggregators_for_prompt,
    get_extractor_count,
    get_aggregator_count,
)

# Initialize Jinja2 environment
env = Environment(
    loader=FileSystemLoader(os.path.dirname(__file__)),
    autoescape=select_autoescape(),
    trim_blocks=True,
    lstrip_blocks=True,
)


def get_prompt_template(prompt_name: str, locale: str = "en-US") -> str:
    """
    Load and return a prompt template using Jinja2 with locale support.

    Args:
        prompt_name: Name of the prompt template file (without .md extension)
        locale: Language locale (e.g., en-US, zh-CN). Defaults to en-US

    Returns:
        The template string with proper variable substitution syntax
    """
    try:
        # Normalize locale format
        normalized_locale = locale.replace("-", "_") if locale and locale.strip() else "en_US"
        
        # Try locale-specific template first (e.g., researcher.zh_CN.md)
        try:
            template = env.get_template(f"{prompt_name}.{normalized_locale}.md")
            return template.render()
        except TemplateNotFound:
            # Fallback to English template if locale-specific not found
            template = env.get_template(f"{prompt_name}.md")
            return template.render()
    except Exception as e:
        raise ValueError(f"Error loading template {prompt_name} for locale {locale}: {e}")


def apply_prompt_template(
    prompt_name: str, state: AgentState, configurable: Configuration = None, locale: str = "en-US"
) -> list:
    """
    Apply template variables to a prompt template and return formatted messages.

    Args:
        prompt_name: Name of the prompt template to use
        state: Current agent state containing variables to substitute
        configurable: Configuration object with additional variables
        locale: Language locale for template selection (e.g., en-US, zh-CN)

    Returns:
        List of messages with the system prompt as the first message
    """
    try:
        system_prompt = get_system_prompt_template(prompt_name, state, configurable, locale)
        return [{"role": "system", "content": system_prompt}] + state["messages"]
    except Exception as e:
        raise ValueError(f"Error applying template {prompt_name} for locale {locale}: {e}")


def _get_voice_control_prompt(locale: str) -> str:
    normalized_locale = locale.replace("_", "-") if locale else "en-US"
    if normalized_locale.startswith("zh-CN") or normalized_locale.startswith("zh-Hans"):
        return """
[语音会话附加规则]
当前用户正在进行语音连续对话。你在每一次面向用户的最终回复结尾，都必须追加一个 [VOICE_CONTROL] JSON block：

[VOICE_CONTROL]
{"action":"continue"}
[/VOICE_CONTROL]

或

[VOICE_CONTROL]
{"action":"stop"}
[/VOICE_CONTROL]

规则：
- 如果你在追问、等待用户确认、给出下一步选择、或判断对话仍应继续，请使用 continue。
- 如果任务已自然结束、用户应先阅读结果、或不应继续保持麦克风会话，请使用 stop。
- 这个 block 只能出现一次，并且必须放在回复最后。
[/语音会话附加规则]
""".strip()
    if normalized_locale.startswith("zh-HK") or normalized_locale.startswith("zh-TW"):
        return """
[語音會話附加規則]
目前用戶正在進行語音連續對話。你在每一次面向用戶的最終回覆結尾，都必須附加一個 [VOICE_CONTROL] JSON block：

[VOICE_CONTROL]
{"action":"continue"}
[/VOICE_CONTROL]

或

[VOICE_CONTROL]
{"action":"stop"}
[/VOICE_CONTROL]

規則：
- 如果你在追問、等待用戶確認、提供下一步選擇、或判斷對話仍應繼續，請使用 continue。
- 如果任務已自然結束、用戶應先閱讀結果、或不應繼續保持麥克風會話，請使用 stop。
- 這個 block 只能出現一次，而且必須放在回覆最後。
[/語音會話附加規則]
""".strip()
    return """
[Voice Session Addendum]
The user is currently in an active multi-turn voice conversation. At the end of every final user-facing response, you must append exactly one [VOICE_CONTROL] JSON block:

[VOICE_CONTROL]
{"action":"continue"}
[/VOICE_CONTROL]

or

[VOICE_CONTROL]
{"action":"stop"}
[/VOICE_CONTROL]

Rules:
- Use continue when you are asking a follow-up question, waiting for confirmation, offering next-step choices, or the dialogue should stay open.
- Use stop when the task has naturally concluded, the user should review the delivered result first, or the voice loop should end.
- The block must appear exactly once and must be the final block in your response.
[/Voice Session Addendum]
""".strip()

def get_system_prompt_template(
    prompt_name: str, state: AgentState, configurable: Configuration = None, locale: str = "en-US"
) -> str:
    """
    Render and return the system prompt template with state and configuration variables.
    This function loads a Jinja2-based prompt template (with optional locale-specific
    variants), applies variables from the agent state and Configuration object, and
    returns the fully rendered system prompt string.
    Args:
        prompt_name: Name of the prompt template to load (without .md extension).
        state: Current agent state containing variables available to the template.
        configurable: Optional Configuration object providing additional template variables.
        locale: Language locale for template selection (e.g., en-US, zh-CN).
    Returns:
        The rendered system prompt string after applying all template variables.
    """
    # Convert state to dict for template rendering
    state_vars = {
        "CURRENT_TIME": datetime.now().strftime("%a %b %d %Y %H:%M:%S %z"),
        **state,
    }

    # Add configurable variables
    if configurable:
        state_vars.update(dataclasses.asdict(configurable))
    
    # Add PathLab dynamic data (datasets, models, extractors, aggregators)
    state_vars["PATHLAB_DATASETS"] = get_datasets_for_prompt()
    state_vars["PATHLAB_MODELS"] = get_models_for_prompt()
    state_vars["PATHLAB_EXTRACTORS"] = get_extractors_for_prompt()
    state_vars["PATHLAB_AGGREGATORS"] = get_aggregators_for_prompt()
    state_vars["PATHLAB_EXTRACTOR_COUNT"] = get_extractor_count()
    state_vars["PATHLAB_AGGREGATOR_COUNT"] = get_aggregator_count()

    try:
        # Normalize locale format
        normalized_locale = locale.replace("-", "_") if locale and locale.strip() else "en_US"

        # Try locale-specific template first
        try:
            template = env.get_template(f"{prompt_name}.{normalized_locale}.md")
        except TemplateNotFound:
            # Fallback to English template
            template = env.get_template(f"{prompt_name}.md")

        system_prompt = template.render(**state_vars)
        if state_vars.get("voice_session_active"):
            system_prompt += "\n\n" + _get_voice_control_prompt(locale)
        return system_prompt
    except Exception as e:
        raise ValueError(f"Error loading template {prompt_name} for locale {locale}: {e}")