"""Main LangGraph implementation for the Deep Research agent."""

import asyncio
from typing import Literal

from langchain.chat_models import init_chat_model
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    filter_messages,
    get_buffer_string,
)
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from open_deep_research.configuration import (
    Configuration,
)
from open_deep_research.prompts import (
    PATHLAB_LIST_WSI_TOOLS_LINE,
    clarify_with_user_instructions,
    compress_research_simple_human_message,
    compress_research_system_prompt,
    confirm_research_brief_instructions,
    final_report_generation_prompt,
    lead_researcher_prompt,
    research_system_prompt,
    transform_messages_into_research_topic_prompt,
)
from open_deep_research.state import (
    AgentInputState,
    AgentState,
    ClarifyWithUser,
    ConfirmResearchBrief,
    ConductResearch,
    ResearchComplete,
    ResearcherOutputState,
    ResearcherState,
    ResearchQuestion,
    SupervisorState,
)
from open_deep_research.utils import (
    get_all_tools,
    get_model_config_for_role,
    get_model_token_limit,
    get_notes_from_tool_calls,
    get_pathlab_tools,
    get_today_str,
    is_pathlab_tools_available,
    is_token_limit_exceeded,
    remove_up_to_last_ai_message,
    think_tool,
)

configurable_model = init_chat_model(
    configurable_fields=("model", "max_tokens", "api_key"),
)


def _stream_emit(ev: dict) -> None:
    """Emit a custom stream event when astream(stream_mode=['custom']) is used.
    Safe no-op when get_stream_writer is None or not in stream context.
    """
    try:
        w = get_stream_writer()
        if w is not None and callable(w):
            w(ev)
    except Exception:
        pass


def _base_llm_for_role(role: str, config: RunnableConfig):
    """VLLM_URL 时返回 ChatOpenAI(base_url=...)，否则 configurable_model.with_config(mc)。"""
    mc = get_model_config_for_role(role, config)
    if "base_url" in mc:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            base_url=mc["base_url"],
            api_key=mc["api_key"],
            model=mc["model"],
            max_tokens=mc["max_tokens"],
            stream_usage=True,
        )
    return configurable_model.with_config(mc)

async def clarify_with_user(state: AgentState, config: RunnableConfig) -> Command[Literal["write_research_brief", "clarify_with_user", "confirm_research_brief", "__end__"]]:
    """Analyze user messages and ask clarifying questions if the research scope is unclear.
    
    This function determines whether the user's request needs clarification before proceeding
    with research. If clarification is disabled or not needed, it proceeds directly to research.
    If clarification is needed, it loops back to itself to continue the clarification conversation.
    
    Args:
        state: Current agent state containing user messages
        config: Runtime configuration with model settings and preferences
        
    Returns:
        Command to either loop back for more clarification or proceed to research brief
    """
    # Step 0: Check if we're continuing a research session (has research_brief)
    # 如果 research_brief 存在，说明 write_research_brief 已经执行过，应该直接到 confirm_research_brief
    # confirm_research_brief 会检查是否已显示过 Research Brief，如果没有则显示，如果已显示则处理用户回复
    research_brief = state.get("research_brief")
    if research_brief:
        return Command(goto="confirm_research_brief")
    
    # Step 1: Check if clarification is enabled in configuration
    configurable = Configuration.from_runnable_config(config)
    if not configurable.allow_clarification:
        return Command(goto="write_research_brief")

    # Step 1b: 调用 list_wsi 查看是否已有上传数据，供澄清时参考（有数据则可少问数据来源/规模）
    wsi_context = "PathLab is not connected; uploaded WSI cannot be queried."
    if is_pathlab_tools_available():
        try:
            tools = get_pathlab_tools() or []
            list_wsi_tool = next((t for t in tools if getattr(t, "name", None) == "list_wsi"), None)
            if list_wsi_tool:
                res = await list_wsi_tool.ainvoke({"skip": 0, "limit": 50}, config=config)
                wsi_context = (res or "")[:600]
            else:
                wsi_context = "PathLab tools available but list_wsi not found."
        except Exception:
            wsi_context = "PathLab list_wsi call failed."

    # Step 2: Prepare the model for structured clarification (VLLM_URL 时用本地 vLLM)
    messages = state["messages"]
    clarification_model = (
        _base_llm_for_role("research", config)
        .with_structured_output(ClarifyWithUser)
        .with_retry(stop_after_attempt=configurable.max_structured_output_retries)
    )

    # Step 3: Analyze whether clarification is needed（wsi_context 注入：有数据则少问数据来源/规模）
    prompt_content = clarify_with_user_instructions.format(
        messages=get_buffer_string(messages),
        date=get_today_str(),
        wsi_context=wsi_context,
    )
    response = await clarification_model.ainvoke([HumanMessage(content=prompt_content)], config=config)

    # Step 4: Route based on clarification analysis
    if response.need_clarification:
        # Stream the question as llm_chunk (same as chat) so __main__ prints 一个词一个词
        if response.question:
            for c in response.question:
                _stream_emit({"type": "llm_chunk", "content": c})
        # Return to END with clarifying question for user
        return Command(
            goto=END,
            update={"messages": [AIMessage(content=response.question)]}
        )
    else:
        # Proceed to research with verification message
        return Command(
            goto="write_research_brief", 
            update={"messages": [AIMessage(content=response.verification)]}
        )


async def write_research_brief(state: AgentState, config: RunnableConfig) -> Command[Literal["confirm_research_brief"]]:
    """Transform user messages into a structured research brief.
    
    This function analyzes the user's messages and generates a focused research brief
    that will guide the research supervisor. The brief will be confirmed by the user
    before proceeding to research.
    
    Args:
        state: Current agent state containing user messages
        config: Runtime configuration with model settings
        
    Returns:
        Command to proceed to confirm_research_brief for user confirmation
    """
    # Step 1: Set up the research model (VLLM_URL 时用本地 vLLM)
    configurable = Configuration.from_runnable_config(config)
    research_model = (
        _base_llm_for_role("research", config)
        .with_structured_output(ResearchQuestion)
        .with_retry(stop_after_attempt=configurable.max_structured_output_retries)
    )
    
    # Step 2: Generate structured research brief from user messages
    prompt_content = transform_messages_into_research_topic_prompt.format(
        messages=get_buffer_string(state.get("messages", [])),
        date=get_today_str()
    )
    response = await research_model.ainvoke([HumanMessage(content=prompt_content)])
    research_brief = (getattr(response, "research_brief", None) or "").strip()
    if not research_brief:
        research_brief = "基于当前对话中的研究需求进行病理学文献调研与实验设计建议。"

    # Step 3: Proceed to confirmation step with the generated brief
    return Command(
        goto="confirm_research_brief",
        update={"research_brief": research_brief},
    )


async def confirm_research_brief(state: AgentState, config: RunnableConfig) -> Command[Literal["research_supervisor", "write_research_brief"]]:
    """Confirm or request modification of the research brief before proceeding.
    
    This function presents the generated research brief to the user and determines
    whether modifications are needed before starting research. If modification is needed,
    it returns to write_research_brief with the modification request in messages.
    
    Args:
        state: Current agent state containing the research brief
        config: Runtime configuration with model settings
        
    Returns:
        Command to either proceed to research supervisor or return to write_research_brief for modification
    """
    configurable = Configuration.from_runnable_config(config)
    research_brief = (state.get("research_brief") or "").strip()

    # 当 research_brief 为空时，不使用「直接进入 research_supervisor」跳过展示；
    # 用 fallback 保证用户一定会看到「Research Brief 确认」这一步。
    _FALLBACK_BRIEF = "基于当前对话中的研究需求进行病理学文献调研与实验设计建议。"
    if not research_brief:
        research_brief = _FALLBACK_BRIEF

    # Step 2: Check if user has replied (last message is HumanMessage and previous is confirmation request)
    messages = state.get("messages", [])
    if len(messages) >= 2:
        last_msg = messages[-1]
        second_last_msg = messages[-2]

        # Check if last message is user's reply to the confirmation request
        if isinstance(last_msg, HumanMessage) and hasattr(second_last_msg, "content"):
            user_reply = last_msg.content.strip().lower()
            second_last_content = second_last_msg.content if hasattr(second_last_msg, "content") else ""

            # Check if second_last_msg is the confirmation request (contains "Research Brief" or "研究简报")
            # 必须明确包含这些关键词，避免误判澄清问题为 Research Brief 确认
            has_research_brief_marker = (
                "research brief" in second_last_content.lower() or 
                "研究简报" in second_last_content.lower() or
                "<research brief>" in second_last_content.lower() or
                "<Research Brief>" in second_last_content
            )
            
            if has_research_brief_marker:
                # Check if user wants to modify (contains modification keywords)
                modification_keywords = ["修改", "改", "change", "modify", "update", "revise", "adjust", "需要改"]
                confirmation_keywords = ["确认", "开始", "可以", "好的", "ok", "yes", "confirm", "start", "proceed", "go", "开始研究", "开始"]

                wants_modification = any(keyword in user_reply for keyword in modification_keywords)
                wants_confirmation = any(keyword in user_reply for keyword in confirmation_keywords)

                if wants_modification and not wants_confirmation:
                    return Command(
                        goto="write_research_brief",
                        update={
                            "research_brief": None,  # Clear brief so it will be regenerated
                        }
                    )
                elif wants_confirmation:
                    # 只有明确包含确认关键词时才进入 research_supervisor
                    # 移除 "len(user_reply) < 30" 的自动确认逻辑，避免误判
                    supervisor_system_prompt = lead_researcher_prompt.format(
                        date=get_today_str(),
                        max_concurrent_research_units=configurable.max_concurrent_research_units,
                        max_researcher_iterations=configurable.max_researcher_iterations
                    )
                    return Command(
                        goto="research_supervisor",
                        update={
                            "supervisor_messages": {
                                "type": "override",
                                "value": [
                                    SystemMessage(content=supervisor_system_prompt),
                                    HumanMessage(content=research_brief)
                                ]
                            },
                            "messages": [AIMessage(content="Research Brief 已确认，开始研究...")]
                        }
                    )
                # If unclear, continue to show the brief and ask again
    
    # Step 3: No user reply yet, or unclear intent - show research brief and ask for confirmation
    # Construct message that always shows the research brief
    confirmation_message = f"""这是生成的 Research Brief：

<Research Brief>
{research_brief}
</Research Brief>

请确认这个 Research Brief 是否符合您的要求。
- 如果需要修改，请说明需要修改的部分
- 如果确认无误，请回复'确认'、'开始研究'或类似表达"""
    # 流式输出，与 chat 一致
    if confirmation_message:
        for c in confirmation_message:
            _stream_emit({"type": "llm_chunk", "content": c})
    return Command(
        goto=END,
        update={
            "research_brief": research_brief,  # Keep the brief for reference
            "messages": [AIMessage(content=confirmation_message)]
        }
    )


async def supervisor(state: SupervisorState, config: RunnableConfig) -> Command[Literal["supervisor_tools"]]:
    """Lead research supervisor that plans research strategy and delegates to researchers.
    
    The supervisor analyzes the research brief and decides how to break down the research
    into manageable tasks. It can use think_tool for strategic planning, ConductResearch
    to delegate tasks to sub-researchers, or ResearchComplete when satisfied with findings.
    
    Args:
        state: Current supervisor state with messages and research context
        config: Runtime configuration with model settings
        
    Returns:
        Command to proceed to supervisor_tools for tool execution
    """
    # Step 1: Configure the supervisor model (VLLM_URL 时用本地 vLLM)
    configurable = Configuration.from_runnable_config(config)
    lead_researcher_tools = [ConductResearch, ResearchComplete, think_tool]
    research_model = (
        _base_llm_for_role("research", config)
        .bind_tools(lead_researcher_tools)
        .with_retry(stop_after_attempt=configurable.max_structured_output_retries)
    )
    
    # Step 2: Generate supervisor response based on current context
    supervisor_messages = state.get("supervisor_messages", [])
    response = await research_model.ainvoke(supervisor_messages, config=config)
    
    # Step 3: Update state and proceed to tool execution
    return Command(
        goto="supervisor_tools",
        update={
            "supervisor_messages": [response],
            "research_iterations": state.get("research_iterations", 0) + 1
        }
    )

async def supervisor_tools(state: SupervisorState, config: RunnableConfig) -> Command[Literal["supervisor", "__end__"]]:
    """Execute tools called by the supervisor, including research delegation and strategic thinking.
    
    This function handles three types of supervisor tool calls:
    1. think_tool - Strategic reflection that continues the conversation
    2. ConductResearch - Delegates research tasks to sub-researchers
    3. ResearchComplete - Signals completion of research phase
    
    Args:
        state: Current supervisor state with messages and iteration count
        config: Runtime configuration with research limits and model settings
        
    Returns:
        Command to either continue supervision loop or end research phase
    """
    # Step 1: Extract current state and check exit conditions
    configurable = Configuration.from_runnable_config(config)
    supervisor_messages = state.get("supervisor_messages", [])
    research_iterations = state.get("research_iterations", 0)
    most_recent_message = supervisor_messages[-1]
    
    # Define exit criteria for research phase
    exceeded_allowed_iterations = research_iterations > configurable.max_researcher_iterations
    no_tool_calls = not most_recent_message.tool_calls
    research_complete_tool_call = any(
        tool_call["name"] == "ResearchComplete" 
        for tool_call in most_recent_message.tool_calls
    )
    
    # Exit if any termination condition is met
    if exceeded_allowed_iterations or no_tool_calls or research_complete_tool_call:
        return Command(
            goto=END,
            update={
                "notes": get_notes_from_tool_calls(supervisor_messages),
                "research_brief": state.get("research_brief", "")
            }
        )
    
    # Step 2: Process all tool calls together (both think_tool and ConductResearch)
    all_tool_messages = []
    update_payload = {"supervisor_messages": []}
    
    # Handle think_tool calls (strategic reflection)
    think_tool_calls = [
        tool_call for tool_call in most_recent_message.tool_calls 
        if tool_call["name"] == "think_tool"
    ]
    
    for tool_call in think_tool_calls:
        reflection_content = tool_call["args"]["reflection"]
        all_tool_messages.append(ToolMessage(
            content=f"Reflection recorded: {reflection_content}",
            name="think_tool",
            tool_call_id=tool_call["id"]
        ))
    
    # Handle ConductResearch calls (research delegation)
    conduct_research_calls = [
        tool_call for tool_call in most_recent_message.tool_calls 
        if tool_call["name"] == "ConductResearch"
    ]
    
    if conduct_research_calls:
        try:
            # Limit concurrent research units to prevent resource exhaustion
            allowed_conduct_research_calls = conduct_research_calls[:configurable.max_concurrent_research_units]
            overflow_conduct_research_calls = conduct_research_calls[configurable.max_concurrent_research_units:]

            async def _run_one(tc):
                topic = tc["args"]["research_topic"]
                _stream_emit({"type": "status", "stage": "searching", "topic": topic[:300]})
                obs = await researcher_subgraph.ainvoke({
                    "researcher_messages": [HumanMessage(content=topic)],
                    "research_topic": topic,
                }, config)
                return (tc, obs)

            tasks = [asyncio.create_task(_run_one(tc)) for tc in allowed_conduct_research_calls]
            results_by_id = {}
            for coro in asyncio.as_completed(tasks):
                tc, obs = await coro
                topic = (tc["args"].get("research_topic") or "")[:300]
                snip = (obs.get("compressed_research") or "")[:500]
                _stream_emit({"type": "search_result", "topic": topic, "snippet": snip})
                results_by_id[tc["id"]] = (tc, obs)

            # Create tool messages in original order
            for tc in allowed_conduct_research_calls:
                _, obs = results_by_id[tc["id"]]
                all_tool_messages.append(ToolMessage(
                    content=obs.get("compressed_research", "Error synthesizing research report: Maximum retries exceeded"),
                    name=tc["name"],
                    tool_call_id=tc["id"]
                ))

            # Handle overflow research calls with error messages
            for overflow_call in overflow_conduct_research_calls:
                all_tool_messages.append(ToolMessage(
                    content=f"Error: Did not run this research as you have already exceeded the maximum number of concurrent research units. Please try again with {configurable.max_concurrent_research_units} or fewer research units.",
                    name="ConductResearch",
                    tool_call_id=overflow_call["id"]
                ))

            # Aggregate raw notes from all research results (original order)
            raw_notes_concat = "\n".join([
                "\n".join(results_by_id[tc["id"]][1].get("raw_notes", []))
                for tc in allowed_conduct_research_calls
            ])
            if raw_notes_concat:
                update_payload["raw_notes"] = [raw_notes_concat]
                
        except Exception as e:
            # Handle research execution errors
            if is_token_limit_exceeded(e, configurable.research_model) or True:
                # Token limit exceeded or other error - end research phase
                return Command(
                    goto=END,
                    update={
                        "notes": get_notes_from_tool_calls(supervisor_messages),
                        "research_brief": state.get("research_brief", "")
                    }
                )
    
    # Step 3: Return command with all tool results
    update_payload["supervisor_messages"] = all_tool_messages
    return Command(
        goto="supervisor",
        update=update_payload
    ) 

# Supervisor Subgraph Construction
# Creates the supervisor workflow that manages research delegation and coordination
supervisor_builder = StateGraph(SupervisorState, config_schema=Configuration)

# Add supervisor nodes for research management
supervisor_builder.add_node("supervisor", supervisor)           # Main supervisor logic
supervisor_builder.add_node("supervisor_tools", supervisor_tools)  # Tool execution handler

# Define supervisor workflow edges
supervisor_builder.add_edge(START, "supervisor")  # Entry point to supervisor

# Compile supervisor subgraph for use in main workflow
supervisor_subgraph = supervisor_builder.compile()

async def researcher(state: ResearcherState, config: RunnableConfig) -> Command[Literal["researcher_tools"]]:
    """Individual researcher that conducts focused research on specific topics.
    
    This researcher is given a specific research topic by the supervisor and uses
    available tools (search, think_tool, MCP tools) to gather comprehensive information.
    It can use think_tool for strategic planning between searches.
    
    Args:
        state: Current researcher state with messages and topic context
        config: Runtime configuration with model settings and tool availability
        
    Returns:
        Command to proceed to researcher_tools for tool execution
    """
    # Step 1: Load configuration and validate tool availability
    configurable = Configuration.from_runnable_config(config)
    researcher_messages = state.get("researcher_messages", [])
    
    # Get all available research tools (search, MCP, think_tool)
    tools = await get_all_tools(config)
    if len(tools) == 0:
        raise ValueError(
            "No tools found to conduct research: Set TAVILY_API_KEY for Tavily search, "
            "or add MCP tools in configuration."
        )
    
    # Step 2: Configure the researcher model (VLLM_URL 时用本地 vLLM)
    pathlab_tools_prompt = (PATHLAB_LIST_WSI_TOOLS_LINE + "\n") if is_pathlab_tools_available() else ""
    researcher_prompt = research_system_prompt.format(
        mcp_prompt=configurable.mcp_prompt or "",
        pathlab_tools_prompt=pathlab_tools_prompt,
        date=get_today_str(),
    )
    research_model = (
        _base_llm_for_role("research", config)
        .bind_tools(tools)
        .with_retry(stop_after_attempt=configurable.max_structured_output_retries)
    )
    
    # Step 3: Generate researcher response with system context
    messages = [SystemMessage(content=researcher_prompt)] + researcher_messages
    response = await research_model.ainvoke(messages, config=config)
    
    # Step 4: Update state and proceed to tool execution
    return Command(
        goto="researcher_tools",
        update={
            "researcher_messages": [response],
            "tool_call_iterations": state.get("tool_call_iterations", 0) + 1
        }
    )

# Tool Execution Helper Function
async def execute_tool_safely(tool, args, config):
    """Safely execute a tool with error handling."""
    try:
        return await tool.ainvoke(args, config)
    except Exception as e:
        return f"Error executing tool: {str(e)}"


async def researcher_tools(state: ResearcherState, config: RunnableConfig) -> Command[Literal["researcher", "compress_research"]]:
    """Execute tools called by the researcher, including search tools and strategic thinking.
    
    This function handles various types of researcher tool calls:
    1. think_tool - Strategic reflection that continues the research conversation
    2. Search tools (tavily_search, web_search) - Information gathering
    3. MCP tools - External tool integrations
    4. ResearchComplete - Signals completion of individual research task
    
    Args:
        state: Current researcher state with messages and iteration count
        config: Runtime configuration with research limits and tool settings
        
    Returns:
        Command to either continue research loop or proceed to compression
    """
    # Step 1: Extract current state and check early exit conditions
    configurable = Configuration.from_runnable_config(config)
    researcher_messages = state.get("researcher_messages", [])
    most_recent_message = researcher_messages[-1]
    
    # Early exit if no tool calls were made (search is Tavily only)
    has_tool_calls = bool(most_recent_message.tool_calls)
    if not has_tool_calls:
        return Command(goto="compress_research")
    
    # Step 2: Handle other tool calls (search, MCP tools, etc.)
    tools = await get_all_tools(config)
    tools_by_name = {
        tool.name if hasattr(tool, "name") else tool.get("name", "web_search"): tool 
        for tool in tools
    }
    
    # Execute all tool calls in parallel
    tool_calls = most_recent_message.tool_calls
    tool_execution_tasks = [
        execute_tool_safely(tools_by_name[tool_call["name"]], tool_call["args"], config) 
        for tool_call in tool_calls
    ]
    observations = await asyncio.gather(*tool_execution_tasks)

    # Stream search_hit for each non–think tool (tavily, MCP, etc.) so UI can show "搜索到了哪些内容"
    topic = (state.get("research_topic") or "")[:200]
    for obs, tc in zip(observations, tool_calls):
        if tc.get("name") != "think_tool":
            _stream_emit({"type": "search_hit", "source": tc.get("name", "tool"), "topic": topic, "snippet": (str(obs))[:300]})

    # Create tool messages from execution results
    tool_outputs = [
        ToolMessage(
            content=observation,
            name=tool_call["name"],
            tool_call_id=tool_call["id"]
        )
        for observation, tool_call in zip(observations, tool_calls)
    ]

    # Step 3: Check late exit conditions (after processing tools)
    exceeded_iterations = state.get("tool_call_iterations", 0) >= configurable.max_react_tool_calls
    research_complete_called = any(
        tool_call["name"] == "ResearchComplete" 
        for tool_call in most_recent_message.tool_calls
    )
    
    if exceeded_iterations or research_complete_called:
        # End research and proceed to compression
        return Command(
            goto="compress_research",
            update={"researcher_messages": tool_outputs}
        )
    
    # Continue research loop with tool results
    return Command(
        goto="researcher",
        update={"researcher_messages": tool_outputs}
    )

async def compress_research(state: ResearcherState, config: RunnableConfig):
    """Compress and synthesize research findings into a concise, structured summary.
    
    This function takes all the research findings, tool outputs, and AI messages from
    a researcher's work and distills them into a clean, comprehensive summary while
    preserving all important information and findings.
    
    Args:
        state: Current researcher state with accumulated research messages
        config: Runtime configuration with compression model settings
        
    Returns:
        Dictionary containing compressed research summary and raw notes
    """
    # Step 1: Configure the compression model (VLLM_URL 时用本地 vLLM)
    configurable = Configuration.from_runnable_config(config)
    synthesizer_model = _base_llm_for_role("compression", config)
    
    # Stream compressing status for UI
    topic = (state.get("research_topic") or "")[:200]
    _stream_emit({"type": "status", "stage": "compressing", "topic": topic})
    
    # Step 2: Prepare messages for compression
    researcher_messages = state.get("researcher_messages", [])
    
    # Add instruction to switch from research mode to compression mode
    researcher_messages.append(HumanMessage(content=compress_research_simple_human_message))
    
    # Step 3: Attempt compression with retry logic for token limit issues
    synthesis_attempts = 0
    max_attempts = 3
    
    while synthesis_attempts < max_attempts:
        try:
            # Create system prompt focused on compression task
            compression_prompt = compress_research_system_prompt.format(date=get_today_str())
            messages = [SystemMessage(content=compression_prompt)] + researcher_messages
            
            # Execute compression
            response = await synthesizer_model.ainvoke(messages, config=config)
            
            # Extract raw notes from all tool and AI messages
            raw_notes_content = "\n".join([
                str(message.content) 
                for message in filter_messages(researcher_messages, include_types=["tool", "ai"])
            ])
            
            # Return successful compression result
            return {
                "compressed_research": str(response.content),
                "raw_notes": [raw_notes_content]
            }
            
        except Exception as e:
            synthesis_attempts += 1
            
            # Handle token limit exceeded by removing older messages
            if is_token_limit_exceeded(e, configurable.research_model):
                researcher_messages = remove_up_to_last_ai_message(researcher_messages)
                continue
            
            # For other errors, continue retrying
            continue
    
    # Step 4: Return error result if all attempts failed
    raw_notes_content = "\n".join([
        str(message.content) 
        for message in filter_messages(researcher_messages, include_types=["tool", "ai"])
    ])
    
    return {
        "compressed_research": "Error synthesizing research report: Maximum retries exceeded",
        "raw_notes": [raw_notes_content]
    }

# Researcher Subgraph Construction
# Creates individual researcher workflow for conducting focused research on specific topics
researcher_builder = StateGraph(
    ResearcherState, 
    output=ResearcherOutputState, 
    config_schema=Configuration
)

# Add researcher nodes for research execution and compression
researcher_builder.add_node("researcher", researcher)                 # Main researcher logic
researcher_builder.add_node("researcher_tools", researcher_tools)     # Tool execution handler
researcher_builder.add_node("compress_research", compress_research)   # Research compression

# Define researcher workflow edges
researcher_builder.add_edge(START, "researcher")           # Entry point to researcher
researcher_builder.add_edge("compress_research", END)      # Exit point after compression

# Compile researcher subgraph for parallel execution by supervisor
researcher_subgraph = researcher_builder.compile()

async def show_search_results(state: AgentState, config: RunnableConfig) -> Command[Literal["final_report_generation"]]:
    """Display raw search results before generating the final report.
    
    This node checks if there are raw_notes (search results) and displays them
    to the user before proceeding to final report generation.
    
    Args:
        state: Agent state containing raw_notes from search
        config: Runtime configuration
        
    Returns:
        Command to proceed to final_report_generation
    """
    raw_notes = state.get("raw_notes", [])
    
    if raw_notes:
        # Format raw search results for display
        search_results_text = "\n\n".join(str(note) for note in raw_notes if note)
        
        # Truncate if too long (for display purposes, but keep full content in state)
        max_display_length = 16000
        if len(search_results_text) > max_display_length:
            display_text = search_results_text[:max_display_length] + f"\n\n... (已截断，原文共 {len(search_results_text)} 字)"
        else:
            display_text = search_results_text
        
        # Output search results as an intermediate message
        search_message = f"""--- 搜索与参考 ---

{display_text}

--- 正在整合报告 ---"""
        
        return Command(
            goto="final_report_generation",
            update={
                "messages": [AIMessage(content=search_message)]
            }
        )
    else:
        # No raw_notes, proceed directly to final report generation
        return Command(goto="final_report_generation")


async def final_report_generation(state: AgentState, config: RunnableConfig):
    """Generate the final comprehensive research report with retry logic for token limits.
    
    This function takes all collected research findings and synthesizes them into a 
    well-structured, comprehensive final report using the configured report generation model.
    
    Args:
        state: Agent state containing research findings and context
        config: Runtime configuration with model settings and API keys
        
    Returns:
        Dictionary containing the final report and cleared state
    """
    # Step 1: Extract research findings and prepare state cleanup
    notes = state.get("notes", [])
    raw_notes = state.get("raw_notes", [])
    cleared_state = {"notes": {"type": "override", "value": []}}
    findings = "\n".join(notes)
    
    # Extract URLs from raw_notes for Sources section
    import re
    all_urls = set()
    for raw_note in raw_notes:
        if isinstance(raw_note, str):
            # Extract URLs from raw_notes (Tavily search results contain URLs)
            urls = re.findall(r'https?://[^\s<>"{}|\\^`\[\]]+', raw_note)
            all_urls.update(urls)
    # Also extract from notes (compressed research may contain URLs)
    for note in notes:
        if isinstance(note, str):
            urls = re.findall(r'https?://[^\s<>"{}|\\^`\[\]]+', note)
            all_urls.update(urls)
    
    # Format URLs for inclusion in prompt
    sources_list = "\n".join([f"- {url}" for url in sorted(all_urls)]) if all_urls else "（研究中未找到具体来源URL）"
    
    # Step 2: Configure the final report generation model (VLLM_URL 时用本地 vLLM)
    configurable = Configuration.from_runnable_config(config)
    eff_model = get_model_config_for_role("final_report", config)["model"]

    # Stream generating report status for UI
    _stream_emit({"type": "status", "stage": "generating_report"})

    # Step 3: Attempt report generation with token limit retry logic
    max_retries = 3
    current_retry = 0
    findings_token_limit = None
    
    while current_retry <= max_retries:
        try:
            # Create comprehensive prompt with all research context
            final_report_prompt = final_report_generation_prompt.format(
                research_brief=state.get("research_brief", ""),
                messages=get_buffer_string(state.get("messages", [])),
                findings=findings,
                date=get_today_str(),
                sources_list=sources_list  # Pass extracted URLs for Sources section
            )
            
            # Generate the final report (VLLM_URL 时 _base_llm_for_role 已用 ChatOpenAI)
            final_report = await _base_llm_for_role("final_report", config).ainvoke([
                HumanMessage(content=final_report_prompt)
            ], config=config)
            
            # Return successful report generation
            return {
                "final_report": final_report.content, 
                "messages": [final_report],
                **cleared_state
            }
            
        except Exception as e:
            # Handle token limit exceeded errors with progressive truncation
            if is_token_limit_exceeded(e, eff_model):
                current_retry += 1
                
                if current_retry == 1:
                    # First retry: determine initial truncation limit
                    model_token_limit = get_model_token_limit(eff_model)
                    if not model_token_limit:
                        return {
                            "final_report": f"Error generating final report: Token limit exceeded, however, we could not determine the model's maximum context length. Please update the model map in deep_researcher/utils.py with this information. {e}",
                            "messages": [AIMessage(content="Report generation failed due to token limits")],
                            **cleared_state
                        }
                    # Use 4x token limit as character approximation for truncation
                    findings_token_limit = model_token_limit * 4
                else:
                    # Subsequent retries: reduce by 10% each time
                    findings_token_limit = int(findings_token_limit * 0.9)
                
                # Truncate findings and retry
                findings = findings[:findings_token_limit]
                continue
            else:
                # Non-token-limit error: return error immediately
                return {
                    "final_report": f"Error generating final report: {e}",
                    "messages": [AIMessage(content="Report generation failed due to an error")],
                    **cleared_state
                }
    
    # Step 4: Return failure result if all retries exhausted
    return {
        "final_report": "Error generating final report: Maximum retries exceeded",
        "messages": [AIMessage(content="Report generation failed after maximum retries")],
        **cleared_state
    }

# Main Deep Researcher Graph Construction
# Creates the complete deep research workflow from user input to final report
deep_researcher_builder = StateGraph(
    AgentState, 
    input=AgentInputState, 
    config_schema=Configuration
)

# Add main workflow nodes for the complete research process
deep_researcher_builder.add_node("clarify_with_user", clarify_with_user)           # User clarification phase
deep_researcher_builder.add_node("write_research_brief", write_research_brief)     # Research planning phase
deep_researcher_builder.add_node("confirm_research_brief", confirm_research_brief) # Research brief confirmation
deep_researcher_builder.add_node("research_supervisor", supervisor_subgraph)       # Research execution phase
deep_researcher_builder.add_node("show_search_results", show_search_results)        # Display search results
deep_researcher_builder.add_node("final_report_generation", final_report_generation)  # Report generation phase

# Define main workflow edges for sequential execution
deep_researcher_builder.add_edge(START, "clarify_with_user")                       # Entry point
deep_researcher_builder.add_edge("research_supervisor", "show_search_results")      # Research to show results
deep_researcher_builder.add_edge("show_search_results", "final_report_generation") # Show results to report
deep_researcher_builder.add_edge("final_report_generation", END)                   # Final exit point

# Compile the complete deep researcher workflow
deep_researcher = deep_researcher_builder.compile()