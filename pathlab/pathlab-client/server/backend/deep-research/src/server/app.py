# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import asyncio
import json
import logging
import os
from typing import Annotated, Any, List, Optional, cast
from uuid import uuid4

# Load environment variables from .env file FIRST
# This must happen before checking DEBUG environment variable
from dotenv import load_dotenv
load_dotenv()

# Configure logging based on DEBUG environment variable
# This must happen early, before other modules are imported
_debug_mode = os.getenv("DEBUG", "").lower() in ("true", "1", "yes")
if _debug_mode:
    logging.getLogger("src").setLevel(logging.DEBUG)
    logging.getLogger("langchain").setLevel(logging.DEBUG)
    logging.getLogger("langgraph").setLevel(logging.DEBUG)

# Also log to file for easier debugging
_log_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "logs")
os.makedirs(_log_dir, exist_ok=True)
_file_handler = logging.FileHandler(os.path.join(_log_dir, "pathlab.log"), mode="a")
_file_handler.setFormatter(logging.Formatter("[%(asctime)s] [DeepResearch] [%(levelname)s] %(name)s - %(message)s"))
logging.getLogger().addHandler(_file_handler)
logging.getLogger().setLevel(logging.INFO)

from fastapi import FastAPI, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessageChunk, BaseMessage, ToolMessage
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command
try:
    from langgraph.checkpoint.mongodb import AsyncMongoDBSaver
except Exception:  # Optional dependency in some builds
    AsyncMongoDBSaver = None  # type: ignore[assignment]
try:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
except Exception:  # Optional dependency in some builds
    AsyncPostgresSaver = None  # type: ignore[assignment]
try:
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool
except Exception:  # Optional dependency in some builds
    dict_row = None  # type: ignore[assignment]
    AsyncConnectionPool = None  # type: ignore[assignment]

from src.config.configuration import get_recursion_limit
from src.config.loader import get_bool_env, get_int_env, get_str_env
from src.config.report_style import ReportStyle
from src.config.tools import SELECTED_RAG_PROVIDER
from src.citations import merge_citations
from src.utils.token_tracker import TokenUsageTracker
from src.graph.builder import build_graph_with_memory
from src.graph.checkpoint import chat_stream_message
from src.graph.stop_control import clear_stop, request_stop
from src.graph.utils import (
    build_clarified_topic_from_history,
    reconstruct_clarification_history,
)
from src.llms.llm import get_configured_llm_models
from src.prompt_enhancer.graph.builder import build_graph as build_prompt_enhancer_graph
from src.prose.graph.builder import build_graph as build_prose_graph
from src.rag.builder import build_retriever
from src.rag.milvus import load_examples as load_milvus_examples
from src.rag.qdrant import load_examples as load_qdrant_examples
from src.rag.retriever import Resource
from src.server.chat_request import (
    ChatRequest,
    EnhancePromptRequest,
    GenerateProseRequest,
    StopRequest,
)
from src.server.config_request import ConfigResponse
from src.server.mcp_request import MCPServerMetadataRequest, MCPServerMetadataResponse
from src.server.tool_events import (
    clear_thread_tool_events,
    drain_started_tool_events,
    mark_tool_finished,
    register_pending_tool_calls,
)
from src.server.mcp_utils import load_mcp_tools
from src.server.rag_request import (
    RAGConfigResponse,
    RAGResourceRequest,
    RAGResourcesResponse,
)
from src.utils.json_utils import sanitize_args
from src.utils.log_sanitizer import (
    sanitize_agent_name,
    sanitize_log_input,
    sanitize_thread_id,
    sanitize_tool_name,
    sanitize_user_content,
)
from src.pathlab import refresh_pathlab_cache

logger = logging.getLogger(__name__)

# Configure Windows event loop policy for PostgreSQL compatibility
# On Windows, psycopg requires a selector-based event loop, not the default ProactorEventLoop
if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

INTERNAL_SERVER_ERROR_DETAIL = "Internal Server Error"

# Global connection pools (initialized at startup if configured)
_pg_pool: Optional[AsyncConnectionPool] = None
_pg_checkpointer: Optional[Any] = None

# Global MongoDB connection (initialized at startup if configured)
_mongo_client: Optional[Any] = None
_mongo_checkpointer: Optional[Any] = None


from contextlib import asynccontextmanager


def _postgres_checkpoint_deps_available() -> bool:
    return (
        AsyncPostgresSaver is not None
        and AsyncConnectionPool is not None
        and dict_row is not None
    )


def _mongodb_checkpoint_deps_available() -> bool:
    return AsyncMongoDBSaver is not None


@asynccontextmanager
async def lifespan(app):
    """
    Application lifecycle manager
    - Startup: Register asyncio exception handler and initialize global connection pools
    - Shutdown: Clean up global connection pools
    """
    global _pg_pool, _pg_checkpointer, _mongo_client, _mongo_checkpointer

    # ========== STARTUP ==========
    try:
        asyncio.get_running_loop()

    except RuntimeError as e:
        logger.warning(f"Could not register asyncio exception handler: {e}")

    # Initialize global connection pool based on configuration
    checkpoint_saver = get_bool_env("LANGGRAPH_CHECKPOINT_SAVER", False)
    checkpoint_url = get_str_env("LANGGRAPH_CHECKPOINT_DB_URL", "")

    if not checkpoint_saver or not checkpoint_url:
        logger.info("Checkpoint saver not configured, skipping connection pool initialization")
    else:
        # Initialize PostgreSQL connection pool
        if checkpoint_url.startswith("postgresql://"):
            if not _postgres_checkpoint_deps_available():
                logger.warning(
                    "PostgreSQL checkpoint dependencies are not available; "
                    "continuing without PostgreSQL checkpoint persistence."
                )
                _pg_pool = None
                _pg_checkpointer = None
            else:
                pool_min_size = get_int_env("PG_POOL_MIN_SIZE", 5)
                pool_max_size = get_int_env("PG_POOL_MAX_SIZE", 20)
                pool_timeout = get_int_env("PG_POOL_TIMEOUT", 60)

                connection_kwargs = {
                    "autocommit": True,
                    "prepare_threshold": 0,
                    "row_factory": dict_row,
                }

                logger.info(
                    f"Initializing global PostgreSQL connection pool: "
                    f"min_size={pool_min_size}, max_size={pool_max_size}, timeout={pool_timeout}s"
                )

                try:
                    _pg_pool = AsyncConnectionPool(
                        checkpoint_url,
                        kwargs=connection_kwargs,
                        min_size=pool_min_size,
                        max_size=pool_max_size,
                        timeout=pool_timeout,
                    )
                    await _pg_pool.open()

                    _pg_checkpointer = AsyncPostgresSaver(_pg_pool)
                    await _pg_checkpointer.setup()

                    logger.info("Global PostgreSQL connection pool initialized successfully")
                except Exception as e:
                    logger.error(f"Failed to initialize PostgreSQL connection pool: {e}")
                    _pg_pool = None
                    _pg_checkpointer = None
                    raise RuntimeError(
                        "Checkpoint persistence is explicitly configured with PostgreSQL, "
                        "but initialization failed. Application will not start."
                    ) from e

        # Initialize MongoDB connection pool
        elif checkpoint_url.startswith("mongodb://"):
            if not _mongodb_checkpoint_deps_available():
                raise RuntimeError(
                    "MongoDB checkpoint persistence is configured but "
                    "'langgraph.checkpoint.mongodb' is not available."
                )
            try:
                from motor.motor_asyncio import AsyncIOMotorClient

                # MongoDB connection pool settings
                mongo_max_pool_size = get_int_env("MONGO_MAX_POOL_SIZE", 20)
                mongo_min_pool_size = get_int_env("MONGO_MIN_POOL_SIZE", 5)

                logger.info(
                    f"Initializing global MongoDB connection pool: "
                    f"min_pool_size={mongo_min_pool_size}, max_pool_size={mongo_max_pool_size}"
                )

                _mongo_client = AsyncIOMotorClient(
                    checkpoint_url,
                    maxPoolSize=mongo_max_pool_size,
                    minPoolSize=mongo_min_pool_size,
                )

                # Create the MongoDB checkpointer using the global client
                _mongo_checkpointer = AsyncMongoDBSaver(_mongo_client)
                await _mongo_checkpointer.setup()

                logger.info("Global MongoDB connection pool initialized successfully")
            except ImportError:
                logger.error("motor package not installed. Please install it with: pip install motor")
                raise RuntimeError("MongoDB checkpoint persistence is configured but the 'motor' package is not installed. Aborting startup.")
            except Exception as e:
                logger.error(f"Failed to initialize MongoDB connection pool: {e}")
                raise RuntimeError(f"MongoDB checkpoint persistence is configured but could not be initialized: {e}")

    # ========== Initialize PathLab Data Cache ==========
    try:
        await refresh_pathlab_cache()
        logger.info("PathLab data cache initialized successfully")
    except Exception as e:
        logger.warning(f"Failed to initialize PathLab data cache: {e} (will use defaults)")

    # ========== YIELD - Application runs here ==========
    yield

    # ========== SHUTDOWN ==========
    # Close PostgreSQL connection pool
    if _pg_pool:
        logger.info("Closing global PostgreSQL connection pool")
        await _pg_pool.close()
        logger.info("Global PostgreSQL connection pool closed")

    # Close MongoDB connection
    if _mongo_client:
        logger.info("Closing global MongoDB connection")
        _mongo_client.close()
        logger.info("Global MongoDB connection closed")


app = FastAPI(
    title="Deep Research API",
    description="API for Deep Research",
    version="0.1.0",
    lifespan=lifespan,
)

# Add CORS middleware
# It's recommended to load the allowed origins from an environment variable
# for better security and flexibility across different environments.
allowed_origins_str = get_str_env("ALLOWED_ORIGINS", "http://localhost:3000")
allowed_origins = [origin.strip() for origin in allowed_origins_str.split(",")]

logger.info(f"Allowed origins: {allowed_origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,  # Restrict to specific origins
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],  # Use the configured list of methods
    allow_headers=["*"],  # Now allow all headers, but can be restricted further
)
# Load examples into RAG providers if configured
load_milvus_examples()
load_qdrant_examples()

in_memory_store = InMemoryStore()
graph = build_graph_with_memory()
default_graph_checkpointer = getattr(graph, "checkpointer", None)


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    # Check if MCP server configuration is enabled
    mcp_enabled = get_bool_env("ENABLE_MCP_SERVER_CONFIGURATION", False)

    logger.debug(f"get the request locale : {request.locale}")

    # Validate MCP settings if provided
    if request.mcp_settings and not mcp_enabled:
        raise HTTPException(
            status_code=403,
            detail="MCP server configuration is disabled. Set ENABLE_MCP_SERVER_CONFIGURATION=true to enable MCP features.",
        )

    thread_id = request.thread_id
    if thread_id == "__default__":
        thread_id = str(uuid4())

    return StreamingResponse(
        _astream_workflow_generator(
            request.model_dump()["messages"],
            thread_id,
            request.resources,
            request.max_plan_iterations,
            request.max_step_num,
            request.max_search_results,
            request.auto_accepted_plan,
            request.interrupt_feedback,
            request.mcp_settings if mcp_enabled else {},
            request.enable_background_investigation,
            request.enable_web_search,
            request.search_provider,
            request.report_style,
            request.enable_deep_thinking,
            request.enable_clarification,
            request.max_clarification_rounds,
            request.locale,
            request.voice_session_active,
            request.interrupt_before_tools,
            request.llm_override.model_dump() if request.llm_override else None,
            request.pathlab_auth_token,
        ),
        media_type="text/event-stream",
    )


@app.post("/api/chat/stop")
async def stop_chat(request: StopRequest):
    thread_id = request.thread_id
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id is required")

    request_stop(thread_id)
    checkpoint_updated = False
    try:
        state_config = {"configurable": {"thread_id": thread_id}}
        update_payload = {
            "stop_requested": True,
            "stop_reason": request.reason or "Stopped by user",
        }
        if hasattr(graph, "aupdate_state"):
            await graph.aupdate_state(state_config, update_payload)
            checkpoint_updated = True
        elif hasattr(graph, "update_state"):
            graph.update_state(state_config, update_payload)
            checkpoint_updated = True
    except Exception as e:
        safe_thread_id = sanitize_thread_id(thread_id)
        logger.warning(f"[{safe_thread_id}] Failed to update checkpointed stop flag: {e}")

    return {
        "thread_id": thread_id,
        "stop_requested": True,
        "checkpoint_updated": checkpoint_updated,
    }


def _validate_tool_call_chunks(tool_call_chunks):
    """Validate and log tool call chunk structure for debugging."""
    if not tool_call_chunks:
        return
    
    logger.debug(f"Validating tool_call_chunks: count={len(tool_call_chunks)}")
    
    indices_seen = set()
    tool_ids_seen = set()
    
    for i, chunk in enumerate(tool_call_chunks):
        index = chunk.get("index")
        tool_id = chunk.get("id")
        name = chunk.get("name", "")
        has_args = "args" in chunk
        
        logger.debug(
            f"Chunk {i}: index={index}, id={tool_id}, name={name}, "
            f"has_args={has_args}, type={chunk.get('type')}"
        )
        
        if index is not None:
            indices_seen.add(index)
        if tool_id:
            tool_ids_seen.add(tool_id)
    
    if len(indices_seen) > 1:
        logger.debug(
            f"Multiple indices detected: {sorted(indices_seen)} - "
            f"This may indicate consecutive tool calls"
        )


def _process_tool_call_chunks(tool_call_chunks):
    """
    Process tool call chunks with proper index-based grouping.
    
    This function handles the concatenation of tool call chunks that belong
    to the same tool call (same index) while properly segregating chunks
    from different tool calls (different indices).
    
    The issue: In streaming, LangChain's ToolCallChunk concatenates string
    attributes (name, args) when chunks have the same index. We need to:
    1. Group chunks by index
    2. Detect index collisions with different tool names
    3. Accumulate arguments for the same index
    4. Return properly segregated tool calls
    """
    if not tool_call_chunks:
        return []
    
    _validate_tool_call_chunks(tool_call_chunks)
    
    chunks = []
    chunk_by_index = {}  # Group chunks by index to handle streaming accumulation
    
    for chunk in tool_call_chunks:
        index = chunk.get("index")
        chunk_id = chunk.get("id")
        
        if index is not None:
            # Create or update entry for this index
            if index not in chunk_by_index:
                chunk_by_index[index] = {
                    "name": "",
                    "args": "",
                    "id": chunk_id or "",
                    "index": index,
                    "type": chunk.get("type", ""),
                }
            
            # Validate and accumulate tool name
            chunk_name = chunk.get("name", "")
            if chunk_name:
                stored_name = chunk_by_index[index]["name"]
                
                # Check for index collision with different tool names
                if stored_name and stored_name != chunk_name:
                    logger.warning(
                        f"Tool name mismatch detected at index {index}: "
                        f"'{stored_name}' != '{chunk_name}'. "
                        f"This may indicate a streaming artifact or consecutive tool calls "
                        f"with the same index assignment."
                    )
                    # Keep the first name to prevent concatenation
                else:
                    chunk_by_index[index]["name"] = chunk_name
            
            # Update ID if new one provided
            if chunk_id and not chunk_by_index[index]["id"]:
                chunk_by_index[index]["id"] = chunk_id
            
            # Accumulate arguments
            if chunk.get("args"):
                chunk_by_index[index]["args"] += chunk.get("args", "")
        else:
            # Handle chunks without explicit index (edge case)
            logger.debug(f"Chunk without index encountered: {chunk}")
            chunks.append({
                "name": chunk.get("name", ""),
                "args": sanitize_args(chunk.get("args", "")),
                "id": chunk.get("id", ""),
                "index": 0,
                "type": chunk.get("type", ""),
            })
    
    # Convert indexed chunks to list, sorted by index for proper order
    for index in sorted(chunk_by_index.keys()):
        chunk_data = chunk_by_index[index]
        chunk_data["args"] = sanitize_args(chunk_data["args"])
        chunks.append(chunk_data)
        logger.debug(
            f"Processed tool call: index={index}, name={chunk_data['name']}, "
            f"id={chunk_data['id']}"
        )
    
    return chunks


def _get_agent_name(agent, message_metadata, message_chunk=None):
    """Extract agent name from agent tuple."""
    agent_name = "unknown"
    if agent and len(agent) > 0:
        agent_name = agent[0].split(":")[0] if ":" in agent[0] else agent[0]
    else:
        agent_name = message_metadata.get("langgraph_node", "unknown")
    # Fallback to AIMessage.name when namespace and langgraph_node are missing.
    if agent_name == "unknown" and message_chunk is not None:
        chunk_name = getattr(message_chunk, "name", None)
        if chunk_name:
            agent_name = chunk_name
    return agent_name


def _create_event_stream_message(
    message_chunk, message_metadata, thread_id, agent_name
):
    """Create base event stream message."""
    content = message_chunk.content
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)

    # Use message_chunk.name as fallback when agent_name is unknown.
    effective_agent = agent_name
    if effective_agent == "unknown":
        chunk_name = getattr(message_chunk, "name", None)
        if chunk_name:
            effective_agent = chunk_name
    event_stream_message = {
        "thread_id": thread_id,
        "agent": effective_agent,
        "id": message_chunk.id,
        "role": "assistant",
        "checkpoint_ns": message_metadata.get("checkpoint_ns", ""),
        "langgraph_node": message_metadata.get("langgraph_node", ""),
        "langgraph_path": message_metadata.get("langgraph_path", ""),
        "langgraph_step": message_metadata.get("langgraph_step", ""),
        "content": content,
    }

    # Add optional fields
    if message_chunk.additional_kwargs.get("reasoning_content"):
        event_stream_message["reasoning_content"] = message_chunk.additional_kwargs[
            "reasoning_content"
        ]

    if message_chunk.response_metadata.get("finish_reason"):
        event_stream_message["finish_reason"] = message_chunk.response_metadata.get(
            "finish_reason"
        )

    return event_stream_message


def _create_interrupt_event(thread_id, event_data):
    """Create interrupt event."""
    interrupt = event_data["__interrupt__"][0]
    # Use the 'id' attribute (LangGraph 1.0+) instead of deprecated 'ns[0]'
    interrupt_id = getattr(interrupt, "id", None) or thread_id
    return _make_event(
        "interrupt",
        {
            "thread_id": thread_id,
            "id": interrupt_id,
            "agent": "planner",
            "role": "assistant",
            "content": interrupt.value,
            "finish_reason": "interrupt",
            "options": [
                {"text": "Edit plan", "value": "edit_plan"},
                {"text": "Start research", "value": "accepted"},
            ],
        },
    )


def _process_initial_messages(message, thread_id):
    """Process initial messages and yield formatted events."""
    json_data = json.dumps(
        {
            "thread_id": thread_id,
            "id": "run--" + message.get("id", uuid4().hex),
            "role": "user",
            "content": message.get("content", ""),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    chat_stream_message(
        thread_id, f"event: message_chunk\ndata: {json_data}\n\n", "none"
    )


async def _process_message_chunk(message_chunk, message_metadata, thread_id, agent):
    """Process a single message chunk and yield appropriate events."""

    agent_name = _get_agent_name(agent, message_metadata, message_chunk)
    safe_agent_name = sanitize_agent_name(agent_name)
    safe_thread_id = sanitize_thread_id(thread_id)
    safe_agent = sanitize_agent_name(agent)
    logger.debug(f"[{safe_thread_id}] _process_message_chunk started for agent={safe_agent_name}")
    logger.debug(f"[{safe_thread_id}] Extracted agent_name: {safe_agent_name}")

    event_stream_message = _create_event_stream_message(
        message_chunk, message_metadata, thread_id, agent_name
    )

    if isinstance(message_chunk, ToolMessage):
        # Tool Message - Return the result of the tool call
        logger.debug(f"[{safe_thread_id}] Processing ToolMessage")
        tool_call_id = message_chunk.tool_call_id
        event_stream_message["tool_call_id"] = tool_call_id
        tool_status = getattr(message_chunk, "status", None)
        if tool_status:
            event_stream_message["tool_status"] = tool_status
        if event_stream_message.get("content") in (None, ""):
            logger.warning(
                f"[{safe_thread_id}] ToolMessage returned empty content | "
                f"tool={getattr(message_chunk, 'name', 'unknown')} | "
                f"tool_call_id={sanitize_log_input(tool_call_id or 'unknown', max_length=100)}"
            )
        
        # Validate tool_call_id for debugging
        if tool_call_id:
            safe_tool_id = sanitize_log_input(tool_call_id, max_length=100)
            logger.debug(f"[{safe_thread_id}] ToolMessage with tool_call_id: {safe_tool_id}")
            mark_tool_finished(thread_id, tool_call_id)
        else:
            logger.warning(f"[{safe_thread_id}] ToolMessage received without tool_call_id")
        
        logger.debug(f"[{safe_thread_id}] Yielding tool_call_result event")
        yield _make_event("tool_call_result", event_stream_message)
    elif isinstance(message_chunk, AIMessageChunk):
        # AI Message - Raw message tokens
        has_tool_calls = bool(message_chunk.tool_calls)
        has_chunks = bool(message_chunk.tool_call_chunks)
        logger.debug(f"[{safe_thread_id}] Processing AIMessageChunk, tool_calls={has_tool_calls}, tool_call_chunks={has_chunks}")
        
        if message_chunk.tool_calls:
            # AI Message - Tool Call (complete tool calls)
            safe_tool_names = [sanitize_tool_name(tc.get('name', 'unknown')) for tc in message_chunk.tool_calls]
            logger.debug(f"[{safe_thread_id}] AIMessageChunk has complete tool_calls: {safe_tool_names}")
            event_stream_message["tool_calls"] = message_chunk.tool_calls
            register_pending_tool_calls(
                thread_id,
                str(event_stream_message.get("id", "")),
                str(event_stream_message.get("agent", agent_name)),
                message_chunk.tool_calls,
            )
            
            # Process tool_call_chunks with proper index-based grouping
            processed_chunks = _process_tool_call_chunks(
                message_chunk.tool_call_chunks
            )
            if processed_chunks:
                event_stream_message["tool_call_chunks"] = processed_chunks
                safe_chunk_names = [sanitize_tool_name(c.get('name')) for c in processed_chunks]
                logger.debug(
                    f"[{safe_thread_id}] Tool calls: {safe_tool_names}, "
                    f"Processed chunks: {len(processed_chunks)}"
                )
            
            logger.debug(f"[{safe_thread_id}] Yielding tool_calls event")
            yield _make_event("tool_calls", event_stream_message)
        elif message_chunk.tool_call_chunks:
            # AI Message - Tool Call Chunks (streaming)
            chunks_count = len(message_chunk.tool_call_chunks)
            logger.debug(f"[{safe_thread_id}] AIMessageChunk has streaming tool_call_chunks: {chunks_count} chunks")
            processed_chunks = _process_tool_call_chunks(
                message_chunk.tool_call_chunks
            )
            
            # Emit separate events for chunks with different indices (tool call boundaries)
            if processed_chunks:
                prev_chunk = None
                for chunk in processed_chunks:
                    current_index = chunk.get("index")
                    
                    # Log index transitions to detect tool call boundaries
                    if prev_chunk is not None and current_index != prev_chunk.get("index"):
                        prev_name = sanitize_tool_name(prev_chunk.get('name'))
                        curr_name = sanitize_tool_name(chunk.get('name'))
                        logger.debug(
                            f"[{safe_thread_id}] Tool call boundary detected: "
                            f"index {prev_chunk.get('index')} ({prev_name}) -> "
                            f"{current_index} ({curr_name})"
                        )
                    
                    prev_chunk = chunk
                
                # Include all processed chunks in the event
                event_stream_message["tool_call_chunks"] = processed_chunks
                safe_chunk_names = [sanitize_tool_name(c.get('name')) for c in processed_chunks]
                logger.debug(
                    f"[{safe_thread_id}] Streamed {len(processed_chunks)} tool call chunk(s): "
                    f"{safe_chunk_names}"
                )
            
            logger.debug(f"[{safe_thread_id}] Yielding tool_call_chunks event")
            yield _make_event("tool_call_chunks", event_stream_message)
        else:
            # AI Message - Raw message tokens
            content_len = len(message_chunk.content) if isinstance(message_chunk.content, str) else 0
            logger.debug(f"[{safe_thread_id}] AIMessageChunk is raw message tokens, content_len={content_len}")
            yield _make_event("message_chunk", event_stream_message)


def extract_citations_from_event(event: Any, safe_thread_id: str = "unknown") -> list:
    """Extract all citations from event data using an iterative, depth-limited traversal."""
    # Only dict-based event structures are supported
    if not isinstance(event, dict):
        return []
    
    from collections import deque
    citations: list[Any] = []
    max_depth = 5  # Prevent excessively deep traversal
    max_nodes = 5000  # Safety cap to avoid pathological large structures
    
    # Queue holds (node_dict, depth) for BFS traversal
    queue: deque[tuple[dict[str, Any], int]] = deque([(event, 0)])
    nodes_visited = 0
    
    while queue:
        current, depth = queue.popleft()
        nodes_visited += 1
        if nodes_visited > max_nodes:
            logger.warning(
                f"[{safe_thread_id}] Stopping citation extraction after visiting "
                f"{nodes_visited} nodes to avoid performance issues"
            )
            break
        
        # Direct citations field at this level
        direct_citations = current.get("citations")
        if isinstance(direct_citations, list) and direct_citations:
            logger.debug(
                f"[{safe_thread_id}] Found {len(direct_citations)} citations at depth {depth}"
            )
            citations.extend(direct_citations)
            
        # Do not traverse deeper than max_depth
        if depth >= max_depth:
            continue
            
        # Check nested values (for updates mode)
        for value in current.values():
            if isinstance(value, dict):
                queue.append((value, depth + 1))
            # Also check if the value is a list of dicts (like Command updates)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        queue.append((item, depth + 1))
    return citations


async def _stream_graph_events(
    graph_instance, workflow_input, workflow_config, thread_id
):
    """Stream events from the graph and process them."""
    safe_thread_id = sanitize_thread_id(thread_id)
    logger.debug(f"[{safe_thread_id}] Starting graph event stream with agent nodes")
    
    # Track citations collected during research
    collected_citations = []
    # Track token usage from AIMessageChunk metadata
    token_tracker = TokenUsageTracker(thread_id=thread_id)
    
    try:
        event_count = 0
        last_state_update = None  # Track the last state update to get final citations
        clear_thread_tool_events(thread_id)
        
        async for agent, _, event_data in graph_instance.astream(
            workflow_input,
            config=workflow_config,
            stream_mode=["messages", "updates"],
            subgraphs=True,
        ):
            event_count += 1
            for started_event in drain_started_tool_events(thread_id):
                yield _make_event("tool_started", started_event)
            safe_agent = sanitize_agent_name(agent)
            logger.debug(f"[{safe_thread_id}] Graph event #{event_count} received from agent: {safe_agent}")
            
            if isinstance(event_data, dict):
                # Store the last state update for final citation extraction
                last_state_update = event_data
                
                # Log event keys for debugging (more verbose for citations debugging)
                event_keys = list(event_data.keys())
                
                # Check for citations in state updates (may be nested)
                new_citations = extract_citations_from_event(event_data, safe_thread_id)
                if new_citations:
                    # Accumulate citations across events instead of overwriting
                    # using merge_citations to avoid duplicates and preserve better metadata
                    collected_citations = merge_citations(collected_citations, new_citations)
                    # Key difference: replace string heuristic with actual extraction count for logging
                    logger.info(
                        f"[{safe_thread_id}] Event contains citations, "
                        f"keys: {event_keys}, count: {len(new_citations)}, total: {len(collected_citations)}"
                    )
                
                if "__interrupt__" in event_data:
                    logger.debug(
                        f"[{safe_thread_id}] Processing interrupt event: "
                        f"id={getattr(event_data['__interrupt__'][0], 'id', 'unknown') if isinstance(event_data['__interrupt__'], (list, tuple)) and len(event_data['__interrupt__']) > 0 else 'unknown'}, "
                        f"value_len={len(getattr(event_data['__interrupt__'][0], 'value', '')) if isinstance(event_data['__interrupt__'], (list, tuple)) and len(event_data['__interrupt__']) > 0 and hasattr(event_data['__interrupt__'][0], 'value') and hasattr(event_data['__interrupt__'][0].value, '__len__') else 'unknown'}"
                    )
                    yield _create_interrupt_event(thread_id, event_data)
                logger.debug(f"[{safe_thread_id}] Dict event without interrupt, skipping")
                continue

            message_chunk, message_metadata = cast(
                tuple[BaseMessage, dict[str, Any]], event_data
            )
            
            safe_node = sanitize_agent_name(message_metadata.get('langgraph_node', 'unknown'))
            safe_step = sanitize_log_input(message_metadata.get('langgraph_step', 'unknown'))
            logger.debug(
                f"[{safe_thread_id}] Processing message chunk: "
                f"type={type(message_chunk).__name__}, "
                f"node={safe_node}, "
                f"step={safe_step}"
            )

            # Capture token usage from AIMessageChunk
            # With stream_usage=True, usage data appears on the final chunk
            # in either usage_metadata or response_metadata
            if isinstance(message_chunk, AIMessageChunk):
                agent_name = _get_agent_name(agent, message_metadata, message_chunk)
                node_name = message_metadata.get("langgraph_node", "unknown")

                # Check usage_metadata (LangChain standard)
                # With stream_usage=True, vLLM sends a final chunk with usage_metadata
                # containing input_tokens, output_tokens, total_tokens
                # It can be a UsageMetadata object or a dict
                usage = getattr(message_chunk, "usage_metadata", None)
                if usage:
                    # Handle both dict and object formats
                    if isinstance(usage, dict):
                        input_tokens = usage.get("input_tokens", 0) or 0
                        output_tokens = usage.get("output_tokens", 0) or 0
                        total = usage.get("total_tokens", 0) or 0
                    else:
                        input_tokens = getattr(usage, "input_tokens", 0) or 0
                        output_tokens = getattr(usage, "output_tokens", 0) or 0
                        total = getattr(usage, "total_tokens", 0) or 0

                    if input_tokens > 0 or output_tokens > 0:
                        # Get model name from response_metadata if available
                        resp_meta = getattr(message_chunk, "response_metadata", {}) or {}
                        model_name = resp_meta.get("model_name", "")
                        # If this chunk doesn't have model_name, try to get from finish chunk
                        # (usage chunk comes AFTER finish chunk in stream)
                        token_tracker.record(
                            agent_name, node_name,
                            input_tokens, output_tokens, total,
                            model=model_name,
                            chunk_id=message_chunk.id or "",
                        )

            async for event in _process_message_chunk(
                message_chunk, message_metadata, thread_id, agent
            ):
                yield event

        for started_event in drain_started_tool_events(thread_id):
            yield _make_event("tool_started", started_event)
        
        # After streaming completes, try to get citations
        # First check if we collected any during streaming
        if not collected_citations and last_state_update:
            # Try to get citations from the last state update
            logger.debug(f"[{safe_thread_id}] No citations collected during streaming, checking last state update")
            collected_citations = extract_citations_from_event(last_state_update, safe_thread_id)
        
        # If still no citations, try to get from graph state directly
        if not collected_citations:
            try:
                # Get the current state from the graph using proper config
                state_config = {"configurable": {"thread_id": thread_id}}
                current_state = await graph_instance.aget_state(state_config)
                if current_state and hasattr(current_state, 'values'):
                    state_values = current_state.values
                    if isinstance(state_values, dict) and 'citations' in state_values:
                        collected_citations = state_values.get('citations', [])
                        logger.info(f"[{safe_thread_id}] Retrieved {len(collected_citations)} citations from final graph state")
            except Exception as e:
                logger.warning(
                    f"[{safe_thread_id}] Could not retrieve citations from graph state: {e}",
                    exc_info=True,
                )
        
        # Send collected citations as a separate event
        if collected_citations:
            logger.info(f"[{safe_thread_id}] Sending {len(collected_citations)} citations to client")
            yield _make_event("citations", {
                "thread_id": thread_id,
                "citations": collected_citations,
            })
        else:
            logger.debug(f"[{safe_thread_id}] No citations to send")
        
        # Send token usage summary as a separate event
        if token_tracker.has_data():
            usage_summary = token_tracker.get_summary()
            logger.info(
                f"[{safe_thread_id}] Token usage summary: "
                f"prompt={usage_summary['total_prompt_tokens']}, "
                f"completion={usage_summary['total_completion_tokens']}, "
                f"total={usage_summary['total_tokens']}, "
                f"calls={usage_summary['total_calls']}"
            )
            yield _make_event("token_usage", {
                "thread_id": thread_id,
                **usage_summary,
            })
        else:
            logger.debug(f"[{safe_thread_id}] No token usage data to send")
        
        logger.debug(f"[{safe_thread_id}] Graph event stream completed. Total events: {event_count}")
    except asyncio.CancelledError:
        # User cancelled/interrupted the stream - this is normal, not an error
        logger.info(f"[{safe_thread_id}] Graph event stream cancelled by user after {event_count} events")
        # Re-raise to signal cancellation properly without yielding an error event
        raise
    except Exception as e:
        logger.exception(f"[{safe_thread_id}] Error during graph execution")
        # Provide a user-readable error message (like the normal AI chat page does).
        # Include the exception summary so the user has actionable information.
        error_detail = str(e).strip()
        if len(error_detail) > 300:
            error_detail = error_detail[:300] + "..."
        user_error = (
            f"❌ **Research Error**\n\n"
            f"{error_detail}\n\n"
            f"Please try again. If the problem persists, check your AI service configuration."
        ) if error_detail else (
            "❌ **Research Error**\n\n"
            "An unexpected error occurred during research. Please try again."
        )
        yield _make_event(
            "error",
            {
                "thread_id": thread_id,
                "error": user_error,
            },
        )
    finally:
        clear_thread_tool_events(thread_id)


async def _astream_workflow_generator(
    messages: List[dict],
    thread_id: str,
    resources: List[Resource],
    max_plan_iterations: int,
    max_step_num: int,
    max_search_results: int,
    auto_accepted_plan: bool,
    interrupt_feedback: str,
    mcp_settings: dict,
    enable_background_investigation: bool,
    enable_web_search: bool,
    search_provider: Optional[str],
    report_style: ReportStyle,
    enable_deep_thinking: bool,
    enable_clarification: bool,
    max_clarification_rounds: int,
    locale: str = "en-US",
    voice_session_active: bool = False,
    interrupt_before_tools: Optional[List[str]] = None,
    llm_override: Optional[dict] = None,
    pathlab_auth_token: Optional[str] = None,
):
    safe_thread_id = sanitize_thread_id(thread_id)
    # Refresh PathLab data cache with the user's auth token so tools have
    # up-to-date dataset/model info for this request.
    if pathlab_auth_token:
        try:
            await refresh_pathlab_cache(token=pathlab_auth_token)
        except Exception as _cache_err:
            logger.warning(f"[{safe_thread_id}] PathLab cache refresh failed: {_cache_err}")
    # New run should clear stale stop signals from previous cancelled attempts.
    clear_stop(thread_id)
    safe_feedback = sanitize_log_input(interrupt_feedback) if interrupt_feedback else ""
    logger.debug(
        f"[{safe_thread_id}] _astream_workflow_generator starting: "
        f"messages_count={len(messages)}, "
        f"auto_accepted_plan={auto_accepted_plan}, "
        f"interrupt_feedback={safe_feedback}, "
        f"interrupt_before_tools={interrupt_before_tools}"
    )
    
    # Process initial messages
    logger.debug(f"[{safe_thread_id}] Processing {len(messages)} initial messages")
    for message in messages:
        if isinstance(message, dict) and "content" in message:
            safe_content = sanitize_user_content(message.get('content', ''))
            logger.debug(f"[{safe_thread_id}] Sending initial message to client: {safe_content}")
            _process_initial_messages(message, thread_id)

    logger.debug(f"[{safe_thread_id}] Reconstructing clarification history")
    clarification_history = reconstruct_clarification_history(messages)

    logger.debug(f"[{safe_thread_id}] Building clarified topic from history")
    clarified_topic, clarification_history = build_clarified_topic_from_history(
        clarification_history
    )
    latest_message_content = messages[-1]["content"] if messages else ""
    clarified_research_topic = clarified_topic or latest_message_content
    safe_topic = sanitize_user_content(clarified_research_topic)
    logger.debug(f"[{safe_thread_id}] Clarified research topic: {safe_topic}")

    # Prepare workflow input
    logger.debug(f"[{safe_thread_id}] Preparing workflow input")
    workflow_input = {
        "messages": messages,
        "plan_iterations": 0,
        "final_report": "",
        "current_plan": None,
        "observations": [],
        "auto_accepted_plan": auto_accepted_plan,
        "enable_background_investigation": enable_background_investigation,
        "research_topic": latest_message_content,
        "clarification_history": clarification_history,
        "clarified_research_topic": clarified_research_topic,
        "enable_clarification": enable_clarification,
        "max_clarification_rounds": max_clarification_rounds,
        "locale": locale,
        "voice_session_active": voice_session_active,
        "stop_requested": False,
        "stop_reason": "",
    }

    if not auto_accepted_plan and interrupt_feedback:
        logger.debug(f"[{safe_thread_id}] Creating resume command with interrupt_feedback: {safe_feedback}")
        resume_msg = f"[{interrupt_feedback}]"
        if messages:
            resume_msg += f" {messages[-1]['content']}"
        workflow_input = Command(
            resume=resume_msg,
            update={
                "voice_session_active": voice_session_active,
                "locale": locale,
            },
        )

    # Prepare workflow config
    logger.debug(
        f"[{safe_thread_id}] Preparing workflow config: "
        f"max_plan_iterations={max_plan_iterations}, "
        f"max_step_num={max_step_num}, "
        f"report_style={report_style.value}, "
        f"enable_deep_thinking={enable_deep_thinking}"
    )
    workflow_config = {
        "thread_id": thread_id,
        "resources": resources,
        "max_plan_iterations": max_plan_iterations,
        "max_step_num": max_step_num,
        "max_search_results": max_search_results,
        "mcp_settings": mcp_settings,
        "enable_web_search": enable_web_search,
        "search_provider": search_provider,
        "report_style": report_style.value,
        "enable_deep_thinking": enable_deep_thinking,
        "interrupt_before_tools": interrupt_before_tools,
        "recursion_limit": get_recursion_limit(),
        "llm_override": llm_override or {},
    }

    checkpoint_saver = get_bool_env("LANGGRAPH_CHECKPOINT_SAVER", False)
    checkpoint_url = get_str_env("LANGGRAPH_CHECKPOINT_DB_URL", "")
    
    logger.debug(
        f"[{safe_thread_id}] Checkpoint configuration: "
        f"saver_enabled={checkpoint_saver}, "
        f"url_configured={bool(checkpoint_url)}"
    )
    
    # Handle checkpointer if configured - prefer global connection pools
    if checkpoint_saver and checkpoint_url != "":
        # Try to use global PostgreSQL checkpointer first
        if checkpoint_url.startswith("postgresql://") and _pg_checkpointer:
            logger.info(f"[{safe_thread_id}] Using global PostgreSQL connection pool")
            graph.checkpointer = _pg_checkpointer
            graph.store = in_memory_store
            logger.debug(f"[{safe_thread_id}] Starting to stream graph events")
            async for event in _stream_graph_events(
                graph, workflow_input, workflow_config, thread_id
            ):
                yield event
            logger.debug(f"[{safe_thread_id}] Graph event streaming completed")
            return

        # Fallback to per-request PostgreSQL connection if global pool not available
        elif checkpoint_url.startswith("postgresql://"):
            if _postgres_checkpoint_deps_available():
                logger.info(f"[{safe_thread_id}] Global pool unavailable, creating per-request PostgreSQL connection")
                connection_kwargs = {
                    "autocommit": True,
                    "row_factory": dict_row,
                    "prepare_threshold": 0,
                }
                async with AsyncConnectionPool(
                    checkpoint_url, kwargs=connection_kwargs
                ) as conn:
                    checkpointer = AsyncPostgresSaver(conn)
                    await checkpointer.setup()
                    graph.checkpointer = checkpointer
                    graph.store = in_memory_store
                    logger.debug(f"[{safe_thread_id}] Starting to stream graph events")
                    async for event in _stream_graph_events(
                        graph, workflow_input, workflow_config, thread_id
                    ):
                        yield event
                    logger.debug(f"[{safe_thread_id}] Graph event streaming completed")
                return

            logger.warning(
                f"[{safe_thread_id}] PostgreSQL checkpoint dependencies unavailable; "
                "falling back to in-memory graph execution"
            )

        # Try to use global MongoDB checkpointer first
        elif checkpoint_url.startswith("mongodb://") and _mongo_checkpointer:
            logger.info(f"[{safe_thread_id}] Using global MongoDB connection pool")
            graph.checkpointer = _mongo_checkpointer
            graph.store = in_memory_store
            logger.debug(f"[{safe_thread_id}] Starting to stream graph events")
            async for event in _stream_graph_events(
                graph, workflow_input, workflow_config, thread_id
            ):
                yield event
            logger.debug(f"[{safe_thread_id}] Graph event streaming completed")
            return

        # Fallback to per-request MongoDB connection if global pool not available
        elif checkpoint_url.startswith("mongodb://"):
            if _mongodb_checkpoint_deps_available():
                logger.info(f"[{safe_thread_id}] Global pool unavailable, creating per-request MongoDB connection")
                async with AsyncMongoDBSaver.from_conn_string(
                    checkpoint_url
                ) as checkpointer:
                    graph.checkpointer = checkpointer
                    graph.store = in_memory_store
                    logger.debug(f"[{safe_thread_id}] Starting to stream graph events")
                    async for event in _stream_graph_events(
                        graph, workflow_input, workflow_config, thread_id
                    ):
                        yield event
                    logger.debug(f"[{safe_thread_id}] Graph event streaming completed")
                return

            logger.warning(
                f"[{safe_thread_id}] MongoDB checkpoint dependencies unavailable; "
                "falling back to in-memory graph execution"
            )

    if default_graph_checkpointer is not None:
        logger.info(
            f"[{safe_thread_id}] No usable persistent checkpointer configured; "
            "falling back to built-in in-memory checkpointer"
        )
        graph.checkpointer = default_graph_checkpointer
    else:
        logger.warning(
            f"[{safe_thread_id}] Graph has no built-in checkpointer; "
            "resume/edit-plan may be unavailable"
        )
        graph.checkpointer = None
    graph.store = in_memory_store
    logger.debug(f"[{safe_thread_id}] Starting to stream graph events")
    async for event in _stream_graph_events(
        graph, workflow_input, workflow_config, thread_id
    ):
        yield event
    logger.debug(f"[{safe_thread_id}] Graph event streaming completed")


def _make_event(event_type: str, data: dict[str, any]):
    if data.get("content") == "":
        data.pop("content")
    # Ensure JSON serialization with proper encoding
    try:
        json_data = json.dumps(data, ensure_ascii=False)

        finish_reason = data.get("finish_reason", "")
        chat_stream_message(
            data.get("thread_id", ""),
            f"event: {event_type}\ndata: {json_data}\n\n",
            finish_reason,
        )

        return f"event: {event_type}\ndata: {json_data}\n\n"
    except (TypeError, ValueError) as e:
        logger.error(f"Error serializing event data: {e}")
        # Return a safe error event
        error_data = json.dumps({"error": "Serialization failed"}, ensure_ascii=False)
        return f"event: error\ndata: {error_data}\n\n"


@app.post("/api/prose/generate")
async def generate_prose(request: GenerateProseRequest):
    try:
        sanitized_prompt = request.prompt.replace("\r\n", "").replace("\n", "")
        logger.info(f"Generating prose for prompt: {sanitized_prompt}")
        workflow = build_prose_graph()
        events = workflow.astream(
            {
                "content": request.prompt,
                "option": request.option,
                "command": request.command,
                "locale": request.locale,
            },
            stream_mode="messages",
            subgraphs=True,
        )
        return StreamingResponse(
            (f"data: {event[0].content}\n\n" async for _, event in events),
            media_type="text/event-stream",
        )
    except Exception as e:
        logger.exception(f"Error occurred during prose generation: {str(e)}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_ERROR_DETAIL)


@app.post("/api/prompt/enhance")
async def enhance_prompt(request: EnhancePromptRequest):
    try:
        sanitized_prompt = request.prompt.replace("\r\n", "").replace("\n", "")
        logger.info(f"Enhancing prompt: {sanitized_prompt}")

        # Convert string report_style to ReportStyle enum
        report_style = None
        if request.report_style:
            try:
                # Handle both uppercase and lowercase input
                style_mapping = {
                    "ACADEMIC": ReportStyle.ACADEMIC,
                    "POPULAR_SCIENCE": ReportStyle.POPULAR_SCIENCE,
                    "NEWS": ReportStyle.NEWS,
                    "SOCIAL_MEDIA": ReportStyle.SOCIAL_MEDIA,
                    "STRATEGIC_INVESTMENT": ReportStyle.STRATEGIC_INVESTMENT,
                }
                report_style = style_mapping.get(
                    request.report_style.upper(), ReportStyle.ACADEMIC
                )
            except Exception:
                # If invalid style, default to ACADEMIC
                report_style = ReportStyle.ACADEMIC
        else:
            report_style = ReportStyle.ACADEMIC

        workflow = build_prompt_enhancer_graph()
        final_state = workflow.invoke(
            {
                "prompt": request.prompt,
                "context": request.context,
                "report_style": report_style,
                "locale": request.locale,
            }
        )
        return {"result": final_state["output"]}
    except Exception as e:
        logger.exception(f"Error occurred during prompt enhancement: {str(e)}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_ERROR_DETAIL)


@app.post("/api/mcp/server/metadata", response_model=MCPServerMetadataResponse)
async def mcp_server_metadata(request: MCPServerMetadataRequest):
    """Get information about an MCP server."""
    # Check if MCP server configuration is enabled
    if not get_bool_env("ENABLE_MCP_SERVER_CONFIGURATION", False):
        raise HTTPException(
            status_code=403,
            detail="MCP server configuration is disabled. Set ENABLE_MCP_SERVER_CONFIGURATION=true to enable MCP features.",
        )

    try:
        # Set default timeout for this endpoint (configurable via env)
        timeout = get_int_env("MCP_DEFAULT_TIMEOUT_SECONDS", 60)

        # Use custom timeout from request if provided
        if request.timeout_seconds is not None:
            timeout = request.timeout_seconds

        # Get sse_read_timeout from request if provided
        sse_read_timeout = request.sse_read_timeout

        # Load tools from the MCP server using the utility function
        tools = await load_mcp_tools(
            server_type=request.transport,
            command=request.command,
            args=request.args,
            url=request.url,
            env=request.env,
            headers=request.headers,
            timeout_seconds=timeout,
            sse_read_timeout=sse_read_timeout,
        )

        # Create the response with tools
        response = MCPServerMetadataResponse(
            transport=request.transport,
            command=request.command,
            args=request.args,
            url=request.url,
            env=request.env,
            headers=request.headers,
            tools=tools,
        )

        return response
    except Exception as e:
        logger.exception(f"Error in MCP server metadata endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_ERROR_DETAIL)


@app.get("/api/rag/config", response_model=RAGConfigResponse)
async def rag_config():
    """Get the config of the RAG."""
    return RAGConfigResponse(provider=SELECTED_RAG_PROVIDER)


@app.get("/api/rag/resources", response_model=RAGResourcesResponse)
async def rag_resources(request: Annotated[RAGResourceRequest, Query()]):
    """Get the resources of the RAG."""
    retriever = build_retriever()
    if retriever:
        return RAGResourcesResponse(resources=retriever.list_resources(request.query))
    return RAGResourcesResponse(resources=[])


MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS = {".md", ".txt"}


def _sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal attacks."""
    # Extract only the base filename, removing any path components
    basename = os.path.basename(filename)
    # Remove any null bytes or other dangerous characters
    sanitized = basename.replace("\x00", "").strip()
    # Ensure filename is not empty after sanitization
    if not sanitized or sanitized in (".", ".."):
        return "unnamed_file"
    return sanitized


@app.post("/api/rag/upload", response_model=Resource)
async def upload_rag_resource(file: UploadFile):
    # Validate filename exists
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required for upload")

    # Sanitize filename to prevent path traversal
    safe_filename = _sanitize_filename(file.filename)

    # Validate file extension
    _, ext = os.path.splitext(safe_filename.lower())
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Only {', '.join(ALLOWED_EXTENSIONS)} files are allowed.",
        )

    # Read content with size limit check
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Cannot upload an empty file")
    if len(content) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB.",
        )

    retriever = build_retriever()
    if not retriever:
        raise HTTPException(status_code=500, detail="RAG provider not configured")
    try:
        return retriever.ingest_file(content, safe_filename)
    except NotImplementedError:
        raise HTTPException(
            status_code=501, detail="Upload not supported by current RAG provider"
        )
    except ValueError as exc:
        # Invalid user input or unsupported file content; treat as a client error
        logger.warning("Invalid RAG resource upload: %s", exc)
        raise HTTPException(
            status_code=400,
            detail="Invalid RAG resource. Please check the file and try again.",
        )
    except RuntimeError as exc:
        # Internal error during ingestion; log and return a generic server error
        logger.exception("Runtime error while ingesting RAG resource: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to ingest RAG resource due to an internal error.",
        )


@app.get("/api/config", response_model=ConfigResponse)
async def config():
    """Get the config of the server."""
    return ConfigResponse(
        rag=RAGConfigResponse(provider=SELECTED_RAG_PROVIDER),
        models=get_configured_llm_models(),
    )


@app.post("/api/pathlab/refresh-cache")
async def refresh_pathlab_data_cache():
    """
    Manually refresh the PathLab data cache (datasets and models).
    Call this after uploading new datasets or training new models
    to update the information available to the AI assistant.
    """
    try:
        await refresh_pathlab_cache()
        return {"status": "success", "message": "PathLab data cache refreshed successfully"}
    except Exception as e:
        logger.error(f"Failed to refresh PathLab cache: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to refresh cache: {str(e)}")
