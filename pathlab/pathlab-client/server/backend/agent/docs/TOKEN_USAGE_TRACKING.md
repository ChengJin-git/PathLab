# Token 使用统计方案

## 一、需求分析

需要跟踪和统计所有 LLM API 调用的 token 使用量，包括：
- **输入 token** (`prompt_tokens`)
- **输出 token** (`completion_tokens`)  
- **总 token** (`total_tokens`)
- **按用户、会话、模型、时间等维度统计**

## 二、技术方案

### 2.1 数据库模型

**新建表：`llm_usage_logs`**

```python
class LLMUsageLog(Base):
    """LLM Token 使用记录表"""
    __tablename__ = "llm_usage_logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # 关联信息
    user_id = Column(String(255), index=True, default="default_user")
    conversation_id = Column(String(255), ForeignKey("chat_conversations.conversation_id"), index=True, nullable=True)
    
    # LLM 调用信息
    model = Column(String(255), nullable=False, index=True)  # 模型名称
    provider = Column(String(50), nullable=False, index=True)  # "openrouter", "vllm", "local", etc.
    base_url = Column(String(500))  # API base URL
    
    # Token 统计
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    
    # 调用类型（用于区分不同用途）
    call_type = Column(String(50), index=True)  # "chat", "research", "training", "parse_task", etc.
    
    # 元数据
    metadata = Column(JSON)  # 存储额外信息：messages数量、temperature、max_tokens等
    
    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # 关系
    conversation = relationship("ChatConversation", back_populates="usage_logs")
    
    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "model": self.model,
            "provider": self.provider,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "call_type": self.call_type,
            "created_at": self.created_at.isoformat() + 'Z' if self.created_at else None,
            "metadata": self.metadata,
        }
```

**在 `ChatConversation` 中添加关系：**
```python
usage_logs = relationship("LLMUsageLog", back_populates="conversation", cascade="all, delete-orphan")
```

### 2.2 Token 捕获机制

#### 方案 A：在响应解析时捕获（推荐）

OpenAI 兼容 API 在流式响应的**最后一条**会包含 `usage` 字段：

```json
{
  "choices": [...],
  "usage": {
    "prompt_tokens": 100,
    "completion_tokens": 50,
    "total_tokens": 150
  }
}
```

**修改 `stream_ai_response` 函数：**

```python
async def stream_ai_response(
    messages: List[Dict[str, str]],
    api_key: str = None,
    base_url: str = None,
    model: str = None,
    user_id: str = "default_user",
    conversation_id: str = None,
    call_type: str = "chat"
) -> AsyncIterator[str]:
    """Stream AI response and track token usage"""
    
    # ... 现有代码 ...
    
    usage_data = None  # 存储usage信息
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream(...) as response:
            response.raise_for_status()
            
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        # 在结束前保存usage
                        if usage_data:
                            await _save_usage_log(
                                db=db,  # 需要传入db session
                                user_id=user_id,
                                conversation_id=conversation_id,
                                model=llm_model,
                                provider="openrouter" if not is_local_service else "vllm",
                                base_url=llm_base_url,
                                usage=usage_data,
                                call_type=call_type,
                                metadata={"temperature": 0.7, "max_tokens": 2048}
                            )
                        yield "data: [DONE]\n\n"
                        break
                    try:
                        parsed = json.loads(data)
                        # 检查是否有usage字段（通常在最后一条）
                        if "usage" in parsed:
                            usage_data = parsed["usage"]
                        # 处理content
                        if "choices" in parsed and len(parsed["choices"]) > 0:
                            delta = parsed["choices"][0].get("delta", {})
                            if "content" in delta:
                                yield f"data: {json.dumps({'content': delta['content']})}\n\n"
                    except json.JSONDecodeError:
                        continue
```

#### 方案 B：使用 tiktoken 估算（备选）

如果 API 不返回 usage，可以用 `tiktoken` 估算：

```python
import tiktoken

def estimate_tokens(text: str, model: str = "gpt-4") -> int:
    """估算token数量"""
    try:
        encoding = tiktoken.encoding_for_model(model)
        return len(encoding.encode(text))
    except:
        # fallback: 简单估算（1 token ≈ 4 chars）
        return len(text) // 4
```

### 2.3 保存函数

**新建：`backend/database/repositories.py` 中添加：**

```python
class LLMUsageRepository:
    @staticmethod
    async def create_usage_log(
        db: AsyncSession,
        user_id: str,
        conversation_id: Optional[str],
        model: str,
        provider: str,
        base_url: Optional[str],
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        call_type: str = "chat",
        metadata: Optional[dict] = None
    ) -> LLMUsageLog:
        """创建token使用记录"""
        usage_log = LLMUsageLog(
            user_id=user_id,
            conversation_id=conversation_id,
            model=model,
            provider=provider,
            base_url=base_url,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            call_type=call_type,
            metadata=metadata or {}
        )
        db.add(usage_log)
        await db.commit()
        await db.refresh(usage_log)
        return usage_log
    
    @staticmethod
    async def get_user_usage_stats(
        db: AsyncSession,
        user_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        call_type: Optional[str] = None
    ) -> dict:
        """获取用户token使用统计"""
        query = db.query(LLMUsageLog).filter(LLMUsageLog.user_id == user_id)
        
        if start_date:
            query = query.filter(LLMUsageLog.created_at >= start_date)
        if end_date:
            query = query.filter(LLMUsageLog.created_at <= end_date)
        if call_type:
            query = query.filter(LLMUsageLog.call_type == call_type)
        
        logs = await db.execute(query)
        logs_list = logs.scalars().all()
        
        return {
            "total_calls": len(logs_list),
            "total_prompt_tokens": sum(log.prompt_tokens for log in logs_list),
            "total_completion_tokens": sum(log.completion_tokens for log in logs_list),
            "total_tokens": sum(log.total_tokens for log in logs_list),
            "by_model": {},  # 可按模型分组统计
            "by_call_type": {},  # 可按调用类型分组统计
        }
```

### 2.4 API 端点

**在 `gateway/routes/chat.py` 中添加：**

```python
@router.get("/usage/stats")
async def get_usage_stats(
    user_id: str = "default_user",
    start_date: Optional[str] = None,  # ISO format
    end_date: Optional[str] = None,
    call_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取token使用统计"""
    start = datetime.fromisoformat(start_date) if start_date else None
    end = datetime.fromisoformat(end_date) if end_date else None
    
    stats = await LLMUsageRepository.get_user_usage_stats(
        db, user_id, start, end, call_type
    )
    return stats

@router.get("/usage/logs")
async def get_usage_logs(
    user_id: str = "default_user",
    conversation_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """获取token使用记录列表"""
    query = db.query(LLMUsageLog).filter(LLMUsageLog.user_id == user_id)
    if conversation_id:
        query = query.filter(LLMUsageLog.conversation_id == conversation_id)
    query = query.order_by(LLMUsageLog.created_at.desc()).offset(skip).limit(limit)
    
    logs = await db.execute(query)
    return {
        "items": [log.to_dict() for log in logs.scalars().all()],
        "total": await db.execute(select(func.count()).select_from(LLMUsageLog).filter(LLMUsageLog.user_id == user_id))
    }
```

### 2.5 集成到现有调用

#### 修改 `chat_with_ai` 端点：

```python
@router.post("/chat")
async def chat_with_ai(
    req: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    # ... 现有代码 ...
    
    # 修改stream_with_persistence，传入user_id和conversation_id
    async def stream_with_persistence():
        full_response = ""
        async for chunk in stream_ai_response(
            messages, 
            api_key, 
            base_url, 
            model,
            user_id=req.user_id or "default_user",  # 新增
            conversation_id=req.conversation_id,  # 新增
            call_type="chat"  # 新增
        ):
            yield chunk
            # ... 现有代码 ...
    
    return StreamingResponse(...)
```

#### 修改 `stream_ai_response` 签名：

```python
async def stream_ai_response(
    messages: List[Dict[str, str]],
    api_key: str = None,
    base_url: str = None,
    model: str = None,
    user_id: str = "default_user",  # 新增
    conversation_id: str = None,  # 新增
    call_type: str = "chat",  # 新增
    db: Optional[AsyncSession] = None  # 新增，用于保存usage
) -> AsyncIterator[str]:
```

**注意**：由于 `stream_ai_response` 是生成器函数，不能直接使用 `db` session（session会在函数返回后关闭）。有两个解决方案：

**方案 1：在调用方保存（推荐）**
```python
# 在 chat_with_ai 中
usage_data = None
async def stream_with_persistence():
    nonlocal usage_data
    async for chunk in stream_ai_response(...):
        # 检查chunk是否包含usage信息
        if chunk.startswith("data: ") and "usage" in chunk:
            # 解析并保存usage_data
        yield chunk
    
    # 流结束后保存
    if usage_data:
        await LLMUsageRepository.create_usage_log(db, ...)
```

**方案 2：使用后台任务**
```python
# 在stream_ai_response中
if usage_data:
    # 使用asyncio.create_task或background task保存
    asyncio.create_task(_save_usage_async(usage_data, ...))
```

### 2.6 Research 流式调用的 Token 统计

对于 research 的流式调用，需要在 `deep_researcher` 的各个 LLM 调用点捕获 usage：

**修改 `deep_researcher.py` 中的 LLM 调用：**

```python
# 在每个使用 _base_llm_for_role 的地方，捕获usage
response = await _base_llm_for_role("research", config).ainvoke(messages)

# 检查response是否有usage属性（LangChain ChatOpenAI返回的AIMessage可能包含）
if hasattr(response, 'response_metadata') and 'token_usage' in response.response_metadata:
    usage = response.response_metadata['token_usage']
    await _save_research_usage(usage, call_type="research", ...)
```

或者使用 LangChain 的 callback：

```python
from langchain_core.callbacks import AsyncCallbackHandler

class TokenUsageCallback(AsyncCallbackHandler):
    def __init__(self, db, user_id, call_type):
        self.db = db
        self.user_id = user_id
        self.call_type = call_type
    
    async def on_llm_end(self, response, **kwargs):
        if hasattr(response, 'llm_output') and 'token_usage' in response.llm_output:
            usage = response.llm_output['token_usage']
            await LLMUsageRepository.create_usage_log(...)
```

## 三、实施步骤

### Phase 1: 基础功能
1. ✅ 创建 `LLMUsageLog` 数据库模型
2. ✅ 添加数据库迁移脚本
3. ✅ 实现 `LLMUsageRepository`
4. ✅ 修改 `stream_ai_response` 捕获 usage
5. ✅ 修改 `chat_with_ai` 保存 usage

### Phase 2: 统计API
6. ✅ 添加 `/usage/stats` 和 `/usage/logs` 端点
7. ✅ 实现按时间、模型、类型等维度统计

### Phase 3: Research集成
8. ✅ 在 research 流式调用中添加 token 统计
9. ✅ 在 training、parse_task 等其他调用点添加

### Phase 4: 前端展示
10. ✅ 在 Settings 页面显示总使用量
11. ✅ 在对话页面显示本次对话的 token 使用
12. ✅ 添加使用量趋势图表

## 四、注意事项

1. **流式响应中的 usage**：OpenAI 兼容 API 通常在**最后一条**消息中包含 usage，需要特殊处理
2. **并发保存**：多个并发请求时，确保数据库操作线程安全
3. **性能**：大量记录时考虑索引优化和分页查询
4. **隐私**：token 使用记录可能包含敏感信息（调用内容），考虑是否需要脱敏
5. **本地 LLM**：vLLM 等本地服务可能不返回 usage，需要估算或跳过

## 五、示例数据

```json
{
  "total_calls": 150,
  "total_prompt_tokens": 45000,
  "total_completion_tokens": 12000,
  "total_tokens": 57000,
  "by_model": {
    "qwen/qwen3-vl-235b-a22b-instruct": {
      "calls": 100,
      "tokens": 40000
    },
    "gpt-4": {
      "calls": 50,
      "tokens": 17000
    }
  },
  "by_call_type": {
    "chat": {"calls": 80, "tokens": 30000},
    "research": {"calls": 50, "tokens": 20000},
    "training": {"calls": 20, "tokens": 7000}
  }
}
```
