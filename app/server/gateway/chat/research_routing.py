"""Interpret the LLM's explicit research decision, never user-text keywords."""

import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from backend.services.workbench import ResourceReference
from backend.database.models import ChatMessage
from sqlalchemy import func, select


async def research_request_id(db, message: ChatMessage) -> str:
    """Every regenerated sibling shares the original answer's execution identity."""
    anchor = message.id
    if message.variant_group_id:
        anchor = await db.scalar(select(func.min(ChatMessage.id)).where(
            ChatMessage.conversation_id == message.conversation_id,
            ChatMessage.variant_group_id == message.variant_group_id,
        ))
    return f"chat-message-{anchor}"


def research_handoff_pending(content: str) -> bool:
    """Only a model-authored execution envelope starts the handoff indicator."""
    start = content.rfind('[NAVIGATE]')
    if start < 0:
        return False
    payload = content[start:].split('[/NAVIGATE]', 1)[0]
    return bool(re.search(r'"type"\s*:\s*"research"', payload)
                and re.search(r'"execute"\s*:\s*true\b', payload))


class ResearchGoal(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    researchGoal: str = Field(min_length=1, max_length=4000)
    handoffReason: str = Field(min_length=1, max_length=2000)
    datasetIds: list[str] = Field(max_length=200)
    taskKind: Literal["analysis", "experiment", "document"]
    reportPolicy: Literal["auto", "summary", "manuscript"]
    researchStandard: Literal['standard', 'scientific']
    references: list[ResourceReference] = Field(max_length=16)


def research_decision(content: str) -> ResearchGoal | None:
    for match in re.finditer(r"\[NAVIGATE\]\s*(.*?)\s*\[/NAVIGATE\]", content, re.S):
        try:
            value = json.loads(match.group(1))
            if (
                not isinstance(value, dict)
                or value.get("type") != "research"
                or value.get("execute") is not True
            ):
                continue
            return ResearchGoal.model_validate(value.get("state"))
        except (ValueError, TypeError, ValidationError):
            continue
    return None
