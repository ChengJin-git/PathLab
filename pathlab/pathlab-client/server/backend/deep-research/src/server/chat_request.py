# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from typing import List, Optional, Union

from pydantic import BaseModel, Field

from src.config.report_style import ReportStyle
from src.rag.retriever import Resource


class ContentItem(BaseModel):
    type: str = Field(..., description="The type of content (text, image, etc.)")
    text: Optional[str] = Field(None, description="The text content if type is 'text'")
    image_url: Optional[str] = Field(
        None, description="The image URL if type is 'image'"
    )


class ChatMessage(BaseModel):
    role: str = Field(
        ..., description="The role of the message sender (user or assistant)"
    )
    content: Union[str, List[ContentItem]] = Field(
        ...,
        description="The content of the message, either a string or a list of content items",
    )


class LLMOverride(BaseModel):
    """Override LLM configuration per request (e.g., from PathLab frontend settings)."""
    base_url: Optional[str] = Field(None, description="LLM API base URL")
    model: Optional[str] = Field(None, description="Model name")
    api_key: Optional[str] = Field(None, description="API key")


class ChatRequest(BaseModel):
    messages: Optional[List[ChatMessage]] = Field(
        [], description="History of messages between the user and the assistant"
    )
    llm_override: Optional[LLMOverride] = Field(
        None, description="Override LLM config for this request (base_url, model, api_key)"
    )
    resources: Optional[List[Resource]] = Field(
        [], description="Resources to be used for the research"
    )
    debug: Optional[bool] = Field(False, description="Whether to enable debug logging")
    thread_id: Optional[str] = Field(
        "__default__", description="A specific conversation identifier"
    )
    locale: Optional[str] = Field(
        "en-US", description="Language locale for the conversation (e.g., en-US, zh-CN)"
    )
    voice_session_active: Optional[bool] = Field(
        False, description="Whether the current turn is part of an active voice session"
    )
    max_plan_iterations: Optional[int] = Field(
        1, description="The maximum number of plan iterations"
    )
    max_step_num: Optional[int] = Field(
        3, description="The maximum number of steps in a plan"
    )
    max_search_results: Optional[int] = Field(
        3, description="The maximum number of search results"
    )
    auto_accepted_plan: Optional[bool] = Field(
        False, description="Whether to automatically accept the plan"
    )
    interrupt_feedback: Optional[str] = Field(
        None, description="Interrupt feedback from the user on the plan"
    )
    mcp_settings: Optional[dict] = Field(
        None, description="MCP settings for the chat request"
    )
    enable_background_investigation: Optional[bool] = Field(
        True, description="Whether to get background investigation before plan"
    )
    enable_web_search: Optional[bool] = Field(
        True, description="Whether to enable web search, set to False to use only local RAG"
    )
    search_provider: Optional[str] = Field(
        None, description="Selected web search provider (e.g. exa or tavily)"
    )
    report_style: Optional[ReportStyle] = Field(
        ReportStyle.ACADEMIC, description="The style of the report"
    )
    enable_deep_thinking: Optional[bool] = Field(
        False, description="Whether to enable deep thinking"
    )
    enable_clarification: Optional[bool] = Field(
        True,
        description="Whether to enable multi-turn clarification for PathLab (default: True)",
    )
    max_clarification_rounds: Optional[int] = Field(
        None,
        description="Maximum number of clarification rounds (default: None, uses State default=3)",
    )
    interrupt_before_tools: List[str] = Field(
        default_factory=list,
        description="List of tool names to interrupt before execution (e.g., ['db_tool', 'api_tool'])",
    )
    pathlab_auth_token: Optional[str] = Field(
        None, description="Bearer token injected by gateway for PathLab API calls"
    )


class GenerateProseRequest(BaseModel):
    prompt: str = Field(..., description="The content of the prose")
    option: str = Field(..., description="The option of the prose writer")
    command: Optional[str] = Field(
        "", description="The user custom command of the prose writer"
    )
    locale: str = Field(
        "en-US", description="Language locale for the conversation (e.g., en-US, zh-CN, zh-HK)"
    )


class EnhancePromptRequest(BaseModel):
    prompt: str = Field(..., description="The original prompt to enhance")
    context: Optional[str] = Field(
        "", description="Additional context about the intended use"
    )
    report_style: Optional[str] = Field(
        "academic", description="The style of the report"
    )
    locale: str = Field(
        "en-US", description="Language locale for the conversation (e.g., en-US, zh-CN, zh-HK)"
    )


class StopRequest(BaseModel):
    thread_id: str = Field(..., description="Thread ID to stop")
    reason: Optional[str] = Field("Stopped by user", description="Stop reason")
