"""
Agent Chat Route - Direct integration with LangGraph Agent
Based on backend.agent.__main__.py REPL logic
"""
import os
import json
import uuid
from typing import List, Dict, Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.auth import current_active_user, User
from ..dependencies import logger
from ..models import ChatRequest

# Import LangGraph Agent
try:
    from backend.agent.graph import create_agent
    from backend.agent import api_keys
    from langchain_core.messages import HumanMessage, AIMessage
    from langchain_core.callbacks import UsageMetadataCallbackHandler
    AGENT_AVAILABLE = True
    logger.info("✅ Agent Chat: LangGraph Agent loaded successfully")
    print("✅ Agent Chat: LangGraph Agent loaded successfully")
except Exception as e:
    AGENT_AVAILABLE = False
    logger.error(f"❌ Agent Chat: LangGraph Agent not available: {e}")
    print(f"❌ Agent Chat: LangGraph Agent not available: {e}")
    import traceback
    traceback.print_exc()

router = APIRouter(tags=["Agent Chat"])


@router.get("/agent/health")
async def agent_health():
    """Health check for agent chat endpoint"""
    return {
        "status": "ok",
        "agent_available": AGENT_AVAILABLE,
        "endpoint": "/agent/chat",
        "message": "Agent chat router is working"
    }

@router.get("/agent/test")
async def agent_test():
    """Simple test endpoint"""
    return {"message": "Agent chat router is accessible", "path": "/agent/chat"}


def _usage_from_callback(handler: UsageMetadataCallbackHandler) -> tuple[int, int, int]:
    """从 UsageMetadataCallbackHandler.usage_metadata 汇总 input/output/total。"""
    um = getattr(handler, "usage_metadata", None) or {}
    if not isinstance(um, dict):
        return 0, 0, 0
    inp, out, tot = 0, 0, 0
    for k, v in um.items():
        if isinstance(v, dict):
            inp += int(v.get("input_tokens") or v.get("prompt_tokens") or 0)
            out += int(v.get("output_tokens") or v.get("completion_tokens") or 0)
            tot += int(v.get("total_tokens") or 0)
        elif k in ("input_tokens", "prompt_tokens") and isinstance(v, (int, float)):
            inp = int(v)
        elif k in ("output_tokens", "completion_tokens") and isinstance(v, (int, float)):
            out = int(v)
        elif k == "total_tokens" and isinstance(v, (int, float)):
            tot = int(v)
    if inp == 0 and out == 0 and tot == 0 and um:
        inp = int(um.get("input_tokens") or um.get("prompt_tokens") or 0)
        out = int(um.get("output_tokens") or um.get("completion_tokens") or 0)
        tot = int(um.get("total_tokens") or 0)
    if tot == 0 and (inp or out):
        tot = inp + out
    return inp, out, tot


@router.post("/agent/chat")
async def agent_chat(
    req: ChatRequest,
    request: Request,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Direct agent chat endpoint - replicates __main__.py REPL logic.
    Returns Server-Sent Events (SSE) stream with agent responses.
    
    Request body:
    - messages: List of messages (only last user message is processed)
    - conversation_id: Optional, used as thread_id for state persistence
    - clear_history: Optional, if true, clears agent state
    """
    if not AGENT_AVAILABLE:
        error_msg = "❌ Agent is not available. Please check server logs for details."
        async def error_stream():
            yield f"data: {json.dumps({'type': 'error', 'content': error_msg})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(
            error_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )
    
    logger.info(f"[Agent Chat] Request received, messages_count={len(req.messages)}")
    print(f"[Agent Chat] Request received, messages_count={len(req.messages)}")
    
    # Check for clear_history in request (custom field)
    clear_history = getattr(req, 'clear_history', False) or request.query_params.get('clear_history') == 'true'
    
    # Get user input (last message)
    if not req.messages:
        error_msg = "No messages provided"
        async def error_stream():
            yield f"data: {json.dumps({'type': 'error', 'content': error_msg})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(
            error_stream(),
            media_type="text/event-stream"
        )
    
    last_message = req.messages[-1]
    user_input = last_message.get("content", "").strip()
    
    if not user_input:
        error_msg = "Empty message"
        async def error_stream():
            yield f"data: {json.dumps({'type': 'error', 'content': error_msg})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(
            error_stream(),
            media_type="text/event-stream"
        )
    
    # Handle special commands
    if user_input.lower() in ("/quit", "/q", "quit", "exit"):
        async def quit_stream():
            yield f"data: {json.dumps({'type': 'system', 'content': 'Bye.'})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(
            quit_stream(),
            media_type="text/event-stream"
        )
    
    # Setup environment variables (same as __main__.py)
    for k, v in [
        ("VLLM_URL", api_keys.vllm_url()),
        ("VLLM_KEY", api_keys.vllm_key()),
        ("VLLM_MODEL", api_keys.vllm_model()),
        ("TAVILY_API_KEY", api_keys.tavily_api_key()),
    ]:
        if v and not os.environ.get(k):
            os.environ[k] = str(v)
    
    # Create agent and state (use conversation_id as thread_id)
    thread_id = req.conversation_id or f"agent-{uuid.uuid4()}"
    agent = create_agent()
    
    # Initialize or get state (in real implementation, you'd persist this)
    # For now, we'll use a simple in-memory state per thread
    # In production, you'd want to persist state in database
    state = {
        "messages": [],
        "research_status": "idle",
        "proposed_training": None,
        "initial_training_params": None,
        "_shown_final_report": False,
    }
    
    if clear_history:
        logger.info(f"[Agent Chat] Clearing history for thread {thread_id}")
        print(f"[Agent Chat] Clearing history for thread {thread_id}")
    else:
        # TODO: Load state from database if conversation_id is provided
        # For now, we start fresh each time (you can implement state persistence later)
        pass
    
    # Add user message to state
    state["messages"].append(HumanMessage(content=user_input))
    
    # Show hints for special commands
    if user_input.lower().startswith("/research"):
        async def hint_stream():
            yield f"data: {json.dumps({'type': 'system', 'content': 'Research 运行中（Tavily 搜索 + 多轮推理，可能需要较长时间，请稍候）…'})}\n\n"
        # Note: We'll continue with the actual stream below
    
    if (
        user_input.strip().lower().startswith("/training")
        or "根据报告建任务" in user_input
        or "根据报告创建" in user_input
    ):
        async def hint_stream():
            yield f"data: {json.dumps({'type': 'system', 'content': 'Training 运行中（list_wsi → propose → 确认/修改 → create_training_task）…'})}\n\n"
    
    # Setup callback for token usage tracking
    callback = UsageMetadataCallbackHandler()
    config = {
        "configurable": {"thread_id": thread_id},
        "callbacks": [callback]
    }
    
    async def stream_agent_response():
        """Stream agent response - replicates __main__.py logic"""
        try:
            last_values = None
            did_stream_llm = False
            need_agent_prefix = True
            last_custom_was_llm_chunk = False
            
            # Show hints for special commands
            if user_input.lower().startswith("/research"):
                yield f"data: {json.dumps({'type': 'system', 'content': 'Research 运行中（Tavily 搜索 + 多轮推理，可能需要较长时间，请稍候）…'})}\n\n"
            if (
                user_input.strip().lower().startswith("/training")
                or "根据报告建任务" in user_input
                or "根据报告创建" in user_input
            ):
                yield f"data: {json.dumps({'type': 'system', 'content': 'Training 运行中（list_wsi → propose → 确认/修改 → create_training_task）…'})}\n\n"
            
            # Stream agent response
            async for event in agent.astream(state, config, stream_mode=["values", "custom"]):
                if isinstance(event, (list, tuple)) and len(event) >= 2:
                    mode, chunk = event[0], event[1]
                else:
                    mode, chunk = "values", event
                
                if mode == "custom":
                    if isinstance(chunk, dict) and chunk.get("type") == "llm_chunk":
                        # LLM content chunk - stream as content
                        content = chunk.get("content", "")
                        if content:
                            if need_agent_prefix:
                                yield f"data: {json.dumps({'type': 'agent_prefix'})}\n\n"
                                need_agent_prefix = False
                            did_stream_llm = True
                            last_custom_was_llm_chunk = True
                            yield f"data: {json.dumps({'type': 'content', 'content': content})}\n\n"
                    else:
                        # Other custom events (status, search_result, etc.)
                        last_custom_was_llm_chunk = False
                        # Format custom events similar to __main__.py
                        if isinstance(chunk, dict):
                            event_type = chunk.get("type", "")
                            if event_type == "status":
                                stage = chunk.get("stage", "")
                                topic = (chunk.get("topic") or "")[:80]
                                yield f"data: {json.dumps({'type': 'status', 'stage': stage, 'topic': topic})}\n\n"
                            elif event_type == "search_result":
                                topic = (chunk.get("topic") or "")[:60]
                                snippet = (chunk.get("snippet") or "")[:100]
                                yield f"data: {json.dumps({'type': 'search_result', 'topic': topic, 'snippet': snippet})}\n\n"
                            elif event_type == "search_hit":
                                source = chunk.get("source", "")
                                topic = (chunk.get("topic") or "")[:60]
                                yield f"data: {json.dumps({'type': 'search_hit', 'source': source, 'topic': topic})}\n\n"
                            else:
                                yield f"data: {json.dumps({'type': 'custom', 'data': chunk})}\n\n"
                        else:
                            yield f"data: {json.dumps({'type': 'custom', 'data': str(chunk)})}\n\n"
                
                elif mode == "values":
                    if last_custom_was_llm_chunk:
                        yield f"data: {json.dumps({'type': 'newline'})}\n\n"
                        need_agent_prefix = True
                        last_custom_was_llm_chunk = False
                    last_values = chunk
            
            if last_custom_was_llm_chunk:
                yield f"data: {json.dumps({'type': 'newline'})}\n\n"
            
            # Get final state
            out = last_values if last_values is not None else state
            
            # Token usage
            pi, po, pt = _usage_from_callback(callback)
            if pi or po or pt:
                yield f"data: {json.dumps({'type': 'token_usage', 'input': pi, 'output': po, 'total': pt})}\n\n"
            
            # Handle final report and messages
            messages = out.get("messages", [])
            if messages:
                final_report = out.get("final_report")
                has_research_brief = out.get("research_brief") is not None
                
                # If research completed with final report
                if final_report and not out.get("_shown_final_report"):
                    for msg in messages:
                        if hasattr(msg, "content") and msg.content:
                            yield f"data: {json.dumps({'type': 'message', 'content': msg.content})}\n\n"
                    yield f"data: {json.dumps({'type': 'system', 'content': '根据报告创建训练任务：输入 /training 或 根据报告建任务'})}\n\n"
                
                # If no streaming happened, show last message
                elif not did_stream_llm:
                    last = messages[-1]
                    text = last.content if hasattr(last, "content") else str(last)
                    yield f"data: {json.dumps({'type': 'message', 'content': text})}\n\n"
                
                # Training proposal status
                if out.get("proposed_training") is not None:
                    yield f"data: {json.dumps({'type': 'system', 'content': '[--] 已列出参数，等待确认。回复 确认/运行 执行，或说明修改（如 epochs 20）；取消 则放弃。'})}\n\n"
                
                research_status = out.get("research_status") or "idle"
                if research_status in ("awaiting_user", "running"):
                    yield f"data: {json.dumps({'type': 'status', 'research_status': research_status})}\n\n"
            else:
                if not did_stream_llm:
                    yield f"data: {json.dumps({'type': 'message', 'content': '(无回复)'})}\n\n"
            
            yield "data: [DONE]\n\n"
            
        except Exception as e:
            logger.error(f"[Agent Chat] Error: {e}")
            import traceback
            traceback.print_exc()
            error_msg = f"Error: {e}"
            yield f"data: {json.dumps({'type': 'error', 'content': error_msg})}\n\n"
            yield "data: [DONE]\n\n"
    
    return StreamingResponse(
        stream_agent_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
