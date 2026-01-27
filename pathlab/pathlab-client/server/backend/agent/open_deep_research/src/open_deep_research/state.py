"""Graph state definitions and data structures for the Deep Research agent."""

import operator
from typing import Annotated, List, Literal, Optional

from langchain_core.messages import MessageLikeRepresentation
from langgraph.graph import MessagesState
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


###################
# Structured Outputs
###################
class ConductResearch(BaseModel):
    """Call this tool to conduct research on a specific topic."""
    research_topic: str = Field(
        description="The topic to research. Should be a single topic, and should be described in high detail (at least a paragraph).",
    )

class ResearchComplete(BaseModel):
    """Call this tool to indicate that the research is complete."""

class Summary(BaseModel):
    """Research summary with key findings."""
    
    summary: str
    key_excerpts: str

class ClarifyWithUser(BaseModel):
    """Model for user clarification requests."""
    
    need_clarification: bool = Field(
        description="Whether the user needs to be asked a clarifying question.",
    )
    question: str = Field(
        description="A question to ask the user to clarify the report scope",
    )
    verification: str = Field(
        description="Verify message that we will start research after the user has provided the necessary information.",
    )

class ResearchQuestion(BaseModel):
    """Research question and brief for guiding research."""
    
    research_brief: str = Field(
        description="A research question that will be used to guide the research.",
    )

class ResearchPlanItem(BaseModel):
    """A single research point in the research plan."""
    
    idx: int = Field(description="Index of this research point (1-based)")
    goal: str = Field(description="The research goal/question for this point")
    extract_fields: List[str] = Field(description="List of fields to extract from papers (e.g., 'topic', 'model_family', 'dataset_name')")
    queries: List[str] = Field(description="List of search queries to execute for this research point")

class ResearchPlan(BaseModel):
    """Structured research plan with items for systematic execution."""
    
    language: Literal["zh", "en"] = Field(description="Language of the research plan: 'zh' for Chinese, 'en' for English")
    brief_text: str = Field(description="Human-readable brief text for user confirmation (only goals, no extraction fields or queries)")
    items: List[ResearchPlanItem] = Field(description="List of research plan items, each with goal, extract_fields, and queries")

class ConfirmResearchBrief(BaseModel):
    """Model for confirming or requesting modification of research brief."""
    
    need_modification: bool = Field(
        description="Whether the user needs to modify the research brief.",
    )
    question: str = Field(
        description="A question to ask the user about modifying the research brief, or empty if no modification needed.",
    )
    verification: str = Field(
        description="Verification message that we will proceed with research using the current brief.",
    )


###################
# State Definitions
###################

def override_reducer(current_value, new_value):
    """Reducer function that allows overriding values in state."""
    if isinstance(new_value, dict) and new_value.get("type") == "override":
        return new_value.get("value", new_value)
    else:
        return operator.add(current_value, new_value)
    
class AgentInputState(MessagesState):
    """InputState for research graph, includes messages and optional research_brief for continuation."""
    research_brief: Optional[str] = None

class AgentState(MessagesState):
    """Main agent state containing messages and research data."""
    
    supervisor_messages: Annotated[list[MessageLikeRepresentation], override_reducer]
    research_brief: Optional[str]  # Human-readable brief for display
    research_plan: Optional[dict]  # Structured plan (ResearchPlan as dict) for system use
    raw_notes: Annotated[list[str], override_reducer] = []
    notes: Annotated[list[str], override_reducer] = []
    final_report: str

class SupervisorState(TypedDict):
    """State for the supervisor that manages research tasks."""
    
    supervisor_messages: Annotated[list[MessageLikeRepresentation], override_reducer]
    research_brief: str  # Human-readable brief
    research_plan: Optional[dict]  # Structured plan (ResearchPlan as dict) for system use
    notes: Annotated[list[str], override_reducer] = []
    research_iterations: int = 0
    raw_notes: Annotated[list[str], override_reducer] = []

class ResearcherState(TypedDict):
    """State for individual researchers conducting research."""
    
    researcher_messages: Annotated[list[MessageLikeRepresentation], operator.add]
    tool_call_iterations: int = 0
    research_topic: str
    compressed_research: str
    raw_notes: Annotated[list[str], override_reducer] = []

class ResearcherOutputState(BaseModel):
    """Output state from individual researchers."""
    
    compressed_research: str
    raw_notes: Annotated[list[str], override_reducer] = []