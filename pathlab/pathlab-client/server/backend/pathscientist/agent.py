"""PathScientist agent assembly — creates an OpenHands SDK Agent with custom tools."""
from __future__ import annotations

import os
from pathlib import Path

from pydantic import SecretStr

from openhands.sdk.agent.agent import Agent
from openhands.sdk.context.agent_context import AgentContext
from openhands.sdk.context.condenser import LLMSummarizingCondenser
from openhands.sdk.llm import LLM
from openhands.sdk.tool import Tool, register_tool

# Import openhands.tools to register built-in tools (TerminalTool, FileEditorTool, etc.)
from openhands.tools.terminal import TerminalTool
from openhands.tools.file_editor import FileEditorTool

from .config import PathScientistConfig
from .context import build_environment_context
from .knowledge import build_domain_skills
from .runtime.session import PathScientistSession
from .runtime.session_registry import SessionDeps, get_session, register_session
from .runtime.workspace import Workspace
from .tools.metrics import GetMetricsTool, MetricsTracker
from .tools.ratchet import RatchetCommitTool, RatchetRevertTool
from .tools.run_experiment import RunExperimentTool
from .tools.validate_script import ValidateScriptTool
from .tools.checkpoint import CheckpointTool
from .tools.skill_browser import SkillBrowserTool
from .tools.workspace_info import GetWorkspaceInfoTool

# Register tool classes ONCE (idempotent — SDK warns on duplicate but doesn't crash).
# Each tool resolves session-specific deps via session_id param at create() time.
_tools_registered = False


def _ensure_tools_registered():
    global _tools_registered
    if _tools_registered:
        return
    register_tool("RunExperimentTool", RunExperimentTool)
    register_tool("ValidateScriptTool", ValidateScriptTool)
    register_tool("RatchetCommitTool", RatchetCommitTool)
    register_tool("RatchetRevertTool", RatchetRevertTool)
    register_tool("GetMetricsTool", GetMetricsTool)
    register_tool("GetWorkspaceInfoTool", GetWorkspaceInfoTool)
    register_tool("SkillBrowserTool", SkillBrowserTool)
    register_tool("CheckpointTool", CheckpointTool)
    _tools_registered = True


def create_agent(
    config: PathScientistConfig,
    research_question: str = "",
) -> tuple[Agent, Workspace, MetricsTracker, "PathScientistSession"]:
    """Create a PathScientist agent with all custom tools wired up.

    Returns (agent, workspace, metrics_tracker) so the caller can
    access workspace and metrics after the agent finishes.
    """
    # Create session with unique workspace
    session = config.create_session(research_question)
    session_id = session.session_id
    workspace_path = session.workspace_dir

    # Create sandbox if configured
    sandbox = None
    sandbox_mode = config.sandbox_mode
    if sandbox_mode in ("apptainer", "auto"):
        from .runtime.sandbox import ApptainerSandbox
        if sandbox_mode == "apptainer" or ApptainerSandbox.check_available():
            sandbox = ApptainerSandbox(
                image=config.sandbox_image,
                gpu_ids=config.gpu_ids,
                memory_limit=config.sandbox_memory_limit,
                cpus=config.sandbox_cpus,
            )

    # Create runtime components
    workspace = Workspace(workspace_path, sandbox=sandbox)
    tracker = MetricsTracker(primary_metric=config.primary_metric)

    from .runtime.iteration_state import IterationState
    iteration_state = IterationState(max_iterations=config.max_iterations)

    # Register session deps so tools can resolve via session_id
    register_session(session_id, SessionDeps(
        workspace=workspace, tracker=tracker, config=config,
        iteration_state=iteration_state,
    ))

    # Register tool classes once (not per-session lambdas)
    _ensure_tools_registered()

    # Session-specific tool params — passed to each tool's create() via Tool(params=...)
    session_params = {"session_id": session_id}

    # Build system prompt kwargs
    prompt_kwargs = {
        "primary_metric": config.primary_metric,
        "max_iterations": config.max_iterations,
        "research_question": research_question,
    }

    # If skill is pre-specified, load it directly (backward compat)
    skill_constraints = ""
    skill_extractor_guidance = ""
    if config.skill_name:
        try:
            from .domain.skills import registry
            skill = registry.get(config.skill_name)
            skill_constraints = skill.get_constraints_prompt()
            skill_extractor_guidance = skill.get_extractor_guidance_prompt()
            template = skill.get_template_content()
            workspace.set_baseline({"train.py": template})
        except Exception:
            pass

    prompt_kwargs["skill_constraints"] = skill_constraints
    prompt_kwargs["skill_extractor_guidance"] = skill_extractor_guidance

    # Build environment context (GPU, packages, data paths)
    env_context = build_environment_context(
        data_mounts=config.data_mounts,
        gpu_ids=config.gpu_ids,
    )
    prompt_kwargs["environment_context"] = env_context

    # Build AgentContext with domain knowledge skills
    domain_skills = build_domain_skills()
    agent_context = AgentContext(
        skills=domain_skills,
        system_message_suffix=env_context,
    )

    # Build LLM config
    llm_kwargs = {}
    if config.llm_model:
        llm_kwargs["model"] = config.llm_model
    else:
        llm_kwargs["model"] = os.environ.get("LLM_MODEL", "claude-sonnet-4-20250514")

    if config.llm_api_key:
        llm_kwargs["api_key"] = SecretStr(config.llm_api_key)
    elif os.environ.get("LLM_API_KEY"):
        llm_kwargs["api_key"] = SecretStr(os.environ["LLM_API_KEY"])

    if config.llm_base_url:
        llm_kwargs["base_url"] = config.llm_base_url
    elif os.environ.get("LLM_BASE_URL"):
        llm_kwargs["base_url"] = os.environ["LLM_BASE_URL"]

    llm_kwargs["temperature"] = config.llm_temperature
    llm_kwargs["usage_id"] = "agent"
    llm = LLM(**llm_kwargs)

    # Build condenser
    condenser_kwargs = {**llm_kwargs, "temperature": 0.0, "usage_id": "condenser"}
    condenser = LLMSummarizingCondenser(
        llm=LLM(**condenser_kwargs),
        max_size=120,
        keep_first=2,
    )

    # Create Agent — tools get session_id via params, resolve deps from registry
    agent = Agent(
        llm=llm,
        tools=[
            Tool(name=TerminalTool.name),
            Tool(name=FileEditorTool.name),
            Tool(name="RunExperimentTool", params=session_params),
            Tool(name="ValidateScriptTool"),
            Tool(name="RatchetCommitTool", params=session_params),
            Tool(name="RatchetRevertTool", params=session_params),
            Tool(name="GetMetricsTool", params=session_params),
            Tool(name="GetWorkspaceInfoTool", params=session_params),
            Tool(name="SkillBrowserTool", params=session_params),
            Tool(name="CheckpointTool", params=session_params),
        ],
        system_prompt_filename=str(
            Path(__file__).parent / "prompts" / "system_prompt.j2"
        ),
        system_prompt_kwargs=prompt_kwargs,
        condenser=condenser,
        agent_context=agent_context,
    )

    return agent, workspace, tracker, session


def create_conversation(
    agent: Agent,
    workspace: Workspace,
    session: PathScientistSession,
):
    """Create a LocalConversation with OpenHands persistence enabled."""
    from openhands.sdk.conversation import LocalConversation
    from .persistence.state_bridge import update_agent_state

    conversation = LocalConversation(
        agent=agent,
        workspace=workspace.sdk_workspace,
        persistence_dir=str(session.persistence_root),
        conversation_id=session.conversation_id,
        stuck_detection=True,
        visualizer=None,
        delete_on_close=False,
        tags={
            "project": "pathscientist",
        },
    )

    # Store conversation in SessionDeps so tools can persist metadata
    deps = get_session(session.session_id)
    deps.conversation = conversation

    # Persist initial session metadata
    update_agent_state(
        conversation,
        workspace_dir=str(session.workspace_dir),
        output_dir=str(session.output_dir),
        research_question=session.research_question,
        primary_metric=deps.config.primary_metric if deps.config else "",
    )

    return conversation
