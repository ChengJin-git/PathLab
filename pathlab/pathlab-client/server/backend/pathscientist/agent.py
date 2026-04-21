"""PathScientist agent assembly — creates an OpenHands SDK Agent with custom tools."""
from __future__ import annotations

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

from .config import (
    PathScientistConfig,
    resolve_llm_api_key,
    resolve_llm_base_url,
    resolve_required_llm_model,
)
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


def preload_all_extractor_guidance() -> str:
    """Return a combined extractor-guidance block covering every registered skill.

    Used by research mode (no ``config.skill_name`` pre-specified) so the agent
    sees pathology-FM preferences for every skill grounding might pick, before
    grounding runs. Returns an empty string if no skill exposes extractor
    guidance, or if the registry fails to load.
    """
    try:
        from .domain.skills import registry as _skill_registry
    except Exception:
        return ""
    try:
        parts: list[str] = []
        for skill in _skill_registry.list_skills():
            guidance = skill.get_extractor_guidance_prompt()
            if guidance.strip():
                parts.append(f"### {skill.name}\n{guidance.strip()}")
        if not parts:
            return ""
        return (
            "The orchestrator will pick one of these skills at grounding time. "
            "Regardless of which skill is selected, default to pathology "
            "foundation models (UNI/UNI2/CONCH/Virchow2/H-Optimus-1/GPFM/"
            "Phikon2/mSTAR) for histopathology tasks; ImageNet backbones "
            "(ResNet50, ViT-L/16) are ablation-only.\n\n"
            + "\n\n".join(parts)
        )
    except Exception:
        return ""


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
    session: PathScientistSession | None = None,
) -> tuple[Agent, Workspace, MetricsTracker, "PathScientistSession"]:
    """Create a PathScientist agent with all custom tools wired up.

    If ``session`` is provided, reuse it (for resume). Otherwise create a new one.
    Returns (agent, workspace, metrics_tracker, session).
    """
    # Use provided session or create new
    if session is None:
        session = config.create_session(research_question)
    session_id = session.session_id
    workspace_path = session.workspace_dir

    # Only create runtime components if not already registered
    try:
        deps = get_session(session_id)
        workspace = deps.workspace
        tracker = deps.tracker
    except KeyError:
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

    # Skill content injection.
    # Two paths:
    #   1. CLI / code mode: config.skill_name is pre-specified. Inject that
    #      skill's constraints + guidance; set its template as the baseline.
    #   2. Research mode: orchestrator's grounding stage picks the skill
    #      AFTER agent creation. To guarantee the agent sees pathology-FM
    #      preferences regardless of which skill grounding ultimately selects,
    #      preload extractor guidance from EVERY skill that provides it.
    #      The extra ~1-3 KB is negligible against the ~100K prompt budget
    #      and avoids a mid-stream prompt rebuild that OpenHands does not
    #      support cleanly.
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
    else:
        skill_extractor_guidance = preload_all_extractor_guidance()

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
    llm_kwargs["model"] = resolve_required_llm_model(
        config.llm_model,
        component="the PathScientist agent",
    )

    api_key = resolve_llm_api_key(config.llm_api_key)
    if api_key:
        llm_kwargs["api_key"] = SecretStr(api_key)

    base_url = resolve_llm_base_url(config.llm_base_url)
    if base_url:
        llm_kwargs["base_url"] = base_url

    llm_kwargs["temperature"] = config.llm_temperature
    llm_kwargs["usage_id"] = "agent"
    llm_kwargs["log_completions"] = True
    llm_kwargs["log_completions_folder"] = str(session.workspace_dir / "logs" / "completions")
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
            Tool(name="ValidateScriptTool", params=session_params),
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
    visualizer=None,
):
    """Create a LocalConversation with OpenHands persistence enabled.

    Pass visualizer=DefaultConversationVisualizer for real-time CLI output,
    or None for silent mode (batch/test).
    """
    from openhands.sdk.conversation import LocalConversation
    from .persistence.state_bridge import update_agent_state

    conversation = LocalConversation(
        agent=agent,
        workspace=workspace.sdk_workspace,
        persistence_dir=str(session.persistence_root),
        conversation_id=session.conversation_id,
        stuck_detection=True,
        visualizer=visualizer,
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
        persistence_root=str(session.persistence_root),
        research_question=session.research_question,
        primary_metric=deps.config.primary_metric if deps.config else "",
    )

    return conversation
