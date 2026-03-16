"""Conversation intent detection and search policy for PathLab chat.

Two-step architecture:
  ConversationMode  — typed enum for current conversation intent
  SearchPolicy      — DENY / ALLOW_IF_MODEL_REQUESTS / REQUIRE_BEFORE_RECOMMENDATION

Detection priority in detect_conversation_mode:
  1. Explicit research intent  → LITERATURE_RESEARCH
  2. Image attachment           → PATCH_INFERENCE
  3. Structural block in last assistant message (primary)
  4. Keyword / prompt-text fallback
  5. Default                   → GENERAL_CHAT
"""

from __future__ import annotations

import json
import re
from enum import Enum
from typing import Any, Dict, List, Optional

from .chat_training_recommendation import (
    _message_content_to_text,
    _message_content_has_image,
    looks_like_explicit_research_search_query,
    looks_like_image_analysis_query,
    looks_like_image_visualization_query,
    looks_like_validation_query,
    looks_like_metric_or_result_display_query,
    looks_like_local_flow_followup,
    looks_like_analysis_prompt,
    looks_like_image_visualization_prompt,
    is_heatmap_visualization_followup,
    looks_like_model_card_query,
)


class ConversationMode(str, Enum):
    GENERAL_CHAT = "general_chat"
    TRAINING_RECOMMENDATION = "training_recommendation"
    IMAGE_VISUALIZATION = "image_visualization"
    PATCH_INFERENCE = "patch_inference"
    INTERNAL_EVALUATION = "internal_evaluation"
    EXTERNAL_EVALUATION = "external_evaluation"
    ANALYSIS_RESULTS = "analysis_results"
    LITERATURE_RESEARCH = "literature_research"
    MODEL_CARD = "model_card"


class SearchPolicy(str, Enum):
    DENY = "deny"
    ALLOW_IF_MODEL_REQUESTS = "allow_if_model_requests"
    REQUIRE_BEFORE_RECOMMENDATION = "require_before_recommendation"


SEARCH_POLICY: Dict[ConversationMode, SearchPolicy] = {
    ConversationMode.GENERAL_CHAT: SearchPolicy.ALLOW_IF_MODEL_REQUESTS,
    ConversationMode.TRAINING_RECOMMENDATION: SearchPolicy.REQUIRE_BEFORE_RECOMMENDATION,
    ConversationMode.IMAGE_VISUALIZATION: SearchPolicy.DENY,
    ConversationMode.PATCH_INFERENCE: SearchPolicy.DENY,
    ConversationMode.INTERNAL_EVALUATION: SearchPolicy.DENY,
    ConversationMode.EXTERNAL_EVALUATION: SearchPolicy.DENY,
    ConversationMode.ANALYSIS_RESULTS: SearchPolicy.DENY,
    ConversationMode.LITERATURE_RESEARCH: SearchPolicy.ALLOW_IF_MODEL_REQUESTS,
    ConversationMode.MODEL_CARD: SearchPolicy.DENY,
}

_ANALYSIS_CONFIG_RE = re.compile(r"\[ANALYSIS_CONFIG\]([\s\S]*?)\[/ANALYSIS_CONFIG\]")

_BLOCK_MODE_MAP: List[tuple[str, ConversationMode]] = [
    ("[IMAGE_RECOMMENDATION]", ConversationMode.IMAGE_VISUALIZATION),
    ("[PATCH_INFERENCE]", ConversationMode.PATCH_INFERENCE),
    ("[METRIC_CONFIG]", ConversationMode.ANALYSIS_RESULTS),
    ("[CHART_CONFIG]", ConversationMode.ANALYSIS_RESULTS),
    ("[QUICK_ANALYSIS_CONFIG]", ConversationMode.ANALYSIS_RESULTS),
]


def _parse_analysis_type(content: str) -> Optional[str]:
    m = _ANALYSIS_CONFIG_RE.search(content)
    if not m:
        return None
    try:
        return json.loads(m.group(1).strip()).get("analysis_type")
    except (json.JSONDecodeError, AttributeError):
        return None


def _mode_from_assistant_blocks(assistant_content: str) -> Optional[ConversationMode]:
    for block_tag, mode in _BLOCK_MODE_MAP:
        if block_tag in assistant_content:
            return mode
    if "[ANALYSIS_CONFIG]" in assistant_content:
        analysis_type = _parse_analysis_type(assistant_content)
        if analysis_type == "external":
            return ConversationMode.EXTERNAL_EVALUATION
        # "internal" or any unrecognised value → internal evaluation
        return ConversationMode.INTERNAL_EVALUATION
    return None


def _last_assistant_content(messages: List[Dict[str, Any]], before_idx: int) -> str:
    for idx in range(before_idx - 1, -1, -1):
        if messages[idx].get("role") == "assistant":
            return _message_content_to_text(messages[idx].get("content", ""))
    return ""


def detect_conversation_mode(messages: List[Dict[str, Any]]) -> ConversationMode:
    """Infer ConversationMode for the current turn (see module docstring for priority order)."""
    if not messages:
        return ConversationMode.GENERAL_CHAT

    last_user_idx: Optional[int] = None
    for idx in range(len(messages) - 1, -1, -1):
        msg = messages[idx]
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str) and content.strip():
            last_user_idx = idx
            break
        if not isinstance(content, str):
            last_user_idx = idx
            break

    if last_user_idx is None:
        return ConversationMode.GENERAL_CHAT

    last_user_message = messages[last_user_idx]
    latest_user_text = _message_content_to_text(last_user_message.get("content", ""))

    # 1. Explicit research / literature search
    if looks_like_explicit_research_search_query(latest_user_text):
        return ConversationMode.LITERATURE_RESEARCH

    # 2. Image attachment or image-analysis phrasing → patch inference
    if _message_content_has_image(
        last_user_message.get("content")
    ) or looks_like_image_analysis_query(latest_user_text):
        return ConversationMode.PATCH_INFERENCE

    # 3. Structural block in the previous assistant message (primary signal)
    previous_assistant_text = _last_assistant_content(messages, last_user_idx)
    if previous_assistant_text:
        block_mode = _mode_from_assistant_blocks(previous_assistant_text)
        if block_mode is not None:
            return block_mode

    # 4. Heatmap visualisation follow-up (needs full history scan)
    if is_heatmap_visualization_followup(messages):
        return ConversationMode.IMAGE_VISUALIZATION

    # 5. Keyword / prompt-text fallback
    if looks_like_image_visualization_query(latest_user_text):
        return ConversationMode.IMAGE_VISUALIZATION

    if looks_like_validation_query(
        latest_user_text
    ) or looks_like_metric_or_result_display_query(latest_user_text):
        return ConversationMode.ANALYSIS_RESULTS

    if looks_like_model_card_query(latest_user_text):
        return ConversationMode.MODEL_CARD

    if previous_assistant_text:
        if looks_like_image_visualization_prompt(
            previous_assistant_text
        ) and looks_like_local_flow_followup(latest_user_text):
            return ConversationMode.IMAGE_VISUALIZATION
        if looks_like_analysis_prompt(
            previous_assistant_text
        ) and looks_like_local_flow_followup(latest_user_text):
            return ConversationMode.ANALYSIS_RESULTS

    return ConversationMode.GENERAL_CHAT


def resolve_search_policy(mode: ConversationMode) -> SearchPolicy:
    return SEARCH_POLICY.get(mode, SearchPolicy.ALLOW_IF_MODEL_REQUESTS)
