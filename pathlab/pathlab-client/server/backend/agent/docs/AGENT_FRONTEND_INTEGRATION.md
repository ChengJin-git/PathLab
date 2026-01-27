# Agent 前端集成方案

## 概述

将 LangGraph Agent 集成到前端 AI Chat 页面，替换现有的直接 LLM API 调用。

## 当前架构

### 后端
- **`gateway/routes/chat.py`**: 使用 `stream_ai_response()` 直接调用 LLM API
- **`backend/agent/graph.py`**: LangGraph agent，支持 chat/research/training 路由
- **`backend/agent/__main__.py`**: REPL 测试入口，使用 `astream()` 进行流式输出

### 前端
- **`AIChatPage.tsx`**: AI 聊天页面
- **`api.ts`**: `chatWithAI()` 函数，调用 `/chat` 端点，处理 SSE 流

## 集成方案

### 方案 1: 替换现有 stream_ai_response（推荐）

**优点**：
- 最小改动，保持现有 API 接口
- 前端无需修改
- 向后兼容

**实现步骤**：

1. **创建 `stream_agent_response()` 函数**（在 `chat.py` 中）
   ```python
   async def stream_agent_response(
       messages: List[Dict],
       user_data_context: str,
       conversation_id: Optional[str] = None,
       thread_id: Optional[str] = None,
       api_key: str = None,
       base_url: str = None,
       model: str = None
   ) -> AsyncIterator[str]:
       """
       使用 LangGraph Agent 进行流式响应。
       将 LangGraph 的 custom 事件转换为 SSE 格式。
       """
   ```

2. **消息格式转换**
   - 前端消息格式：`[{"role": "user", "content": "..."}]`
   - Agent 消息格式：`[HumanMessage(...), AIMessage(...)]`
   - 需要转换函数

3. **状态持久化**
   - 使用 `conversation_id` 作为 `thread_id`
   - 从数据库加载历史消息
   - 保存 agent state 到数据库（可选）

4. **流式事件处理**
   - `llm_chunk` → `{"content": "..."}` (SSE)
   - `status` → `{"type": "status", "stage": "...", "topic": "..."}` (SSE)
   - `search_result` → `{"type": "search_result", ...}` (SSE)
   - 其他 custom 事件 → 相应 SSE 格式

### 方案 2: 新增 `/chat/agent` 端点

**优点**：
- 保留现有 `/chat` 端点（向后兼容）
- 可以逐步迁移
- 可以 A/B 测试

**缺点**：
- 需要前端修改
- 维护两套代码

## 推荐实现（方案 1）

### 1. 修改 `chat.py` 添加 agent 支持

```python
# 在 chat.py 顶部添加导入
from backend.agent import create_agent, AgentState
from backend.agent.llm import get_llm
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.config import get_stream_writer

# 添加消息转换函数
def convert_messages_to_agent_format(messages: List[Dict]) -> List[BaseMessage]:
    """将前端消息格式转换为 LangChain 消息格式"""
    agent_messages = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if role == "user":
            agent_messages.append(HumanMessage(content=content))
        elif role == "assistant":
            agent_messages.append(AIMessage(content=content))
        elif role == "system":
            agent_messages.append(SystemMessage(content=content))
    return agent_messages

# 添加 agent 流式响应函数
async def stream_agent_response(
    messages: List[Dict],
    user_data_context: str,
    conversation_id: Optional[str] = None,
    api_key: str = None,
    base_url: str = None,
    model: str = None
) -> AsyncIterator[str]:
    """
    使用 LangGraph Agent 进行流式响应。
    """
    # 1. 转换消息格式
    agent_messages = convert_messages_to_agent_format(messages)
    
    # 2. 添加系统提示（包含用户数据上下文）
    if agent_messages and not isinstance(agent_messages[0], SystemMessage):
        system_prompt = f"""You are PathLab Agent...\n{user_data_context}"""
        agent_messages.insert(0, SystemMessage(content=system_prompt))
    
    # 3. 创建 agent state
    thread_id = conversation_id or f"chat_{uuid.uuid4().hex[:16]}"
    state: AgentState = {
        "messages": agent_messages,
        "research_status": None,
    }
    
    # 4. 配置 LLM（如果提供了 API key/base_url/model）
    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }
    
    # 如果提供了 LLM 配置，需要更新 get_llm() 或创建自定义 LLM
    # 这里可以扩展 api_keys 模块支持动态配置
    
    # 5. 创建 agent 并流式执行
    app = create_agent()
    full_response = ""
    
    async def stream_writer(event: dict):
        """将 custom 事件转换为 SSE 格式"""
        nonlocal full_response
        if event.get("type") == "llm_chunk":
            content = event.get("content", "")
            full_response += content
            yield f"data: {json.dumps({'content': content})}\n\n"
        elif event.get("type") == "status":
            yield f"data: {json.dumps({'type': 'status', 'stage': event.get('stage'), 'topic': event.get('topic')})}\n\n"
        # ... 其他事件类型
    
    # 6. 使用 astream 执行
    async for event in app.astream(state, config, stream_mode=["values", "custom"]):
        if isinstance(event, (list, tuple)) and len(event) >= 2:
            mode, chunk = event[0], event[1]
        else:
            mode, chunk = "values", event
        
        if mode == "custom":
            async for sse_chunk in stream_writer(chunk):
                yield sse_chunk
        elif mode == "values":
            # 处理最终状态
            pass
    
    yield "data: [DONE]\n\n"
    return full_response
```

### 2. 修改 `/chat` 端点

```python
@router.post("/chat")
async def chat_with_ai(
    req: ChatRequest,
    request: Request,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    # ... 现有的用户数据上下文获取逻辑 ...
    
    # 选择使用 agent 还是直接 LLM
    use_agent = request.headers.get("X-Use-Agent", "true").lower() == "true"
    
    if use_agent:
        # 使用 agent
        async def stream_with_persistence():
            full_response = ""
            async for chunk in stream_agent_response(
                messages=req.messages,
                user_data_context=user_data_context,
                conversation_id=req.conversation_id,
                api_key=api_key,
                base_url=base_url,
                model=model
            ):
                yield chunk
                # 提取 content 用于持久化
                if chunk.startswith("data: ") and chunk != "data: [DONE]\n\n":
                    try:
                        data = json.loads(chunk[6:])
                        if "content" in data:
                            full_response += data["content"]
                    except:
                        pass
            
            # 保存响应
            if req.conversation_id and full_response:
                # ... 保存逻辑 ...
    else:
        # 使用原有逻辑
        async def stream_with_persistence():
            # ... 原有 stream_ai_response 逻辑 ...
```

### 3. 状态持久化（可选）

如果需要跨会话保持 agent state：

```python
# 在数据库中存储 agent state
class AgentStateStore:
    @staticmethod
    async def save_state(db: AsyncSession, conversation_id: str, state: dict):
        # 将 state 序列化为 JSON 存储
        
    @staticmethod
    async def load_state(db: AsyncSession, conversation_id: str) -> Optional[dict]:
        # 从数据库加载 state
```

## 前端适配（可选）

如果需要支持 agent 的特殊事件：

```typescript
// 在 api.ts 中扩展事件处理
interface AgentEvent {
  type: 'content' | 'status' | 'search_result' | 'search_hit'
  content?: string
  stage?: string
  topic?: string
  snippet?: string
}

// 在 AIChatPage.tsx 中处理不同类型的事件
function handleAgentEvent(event: AgentEvent) {
  switch (event.type) {
    case 'content':
      // 显示 LLM 输出
      break
    case 'status':
      // 显示状态提示（如"正在搜索..."）
      break
    case 'search_result':
      // 显示搜索结果
      break
  }
}
```

## 实施步骤

1. **Phase 1: 基础集成**
   - 实现 `stream_agent_response()` 函数
   - 实现消息格式转换
   - 修改 `/chat` 端点支持 agent 模式
   - 测试基本聊天功能

2. **Phase 2: 工具支持**
   - 确保 PathLab tools 正常工作
   - 测试 `list_wsi`, `list_datasets` 等工具调用
   - 处理工具调用的错误

3. **Phase 3: 高级功能**
   - 支持 research 子图（`/research` 命令）
   - 支持 training 子图（训练任务创建）
   - 状态持久化（跨会话）

4. **Phase 4: 优化**
   - 性能优化
   - 错误处理增强
   - 前端 UI 增强（显示工具调用、状态等）

## 注意事项

1. **LLM 配置**：Agent 使用 `backend.agent.llm.get_llm()`，需要确保与前端传入的配置一致
2. **认证**：Agent tools 需要 JWT token，已在 `pathlab.py` 中实现
3. **错误处理**：Agent 执行可能失败，需要优雅降级
4. **性能**：Agent 可能比直接 LLM 调用慢（因为有工具调用），需要优化

## 测试建议

1. 测试基本聊天
2. 测试工具调用（list_wsi, list_datasets）
3. 测试 research 功能（`/research` 命令）
4. 测试 training 功能（创建训练任务）
5. 测试错误处理（网络错误、工具错误等）
6. 测试状态持久化（conversation_id）
