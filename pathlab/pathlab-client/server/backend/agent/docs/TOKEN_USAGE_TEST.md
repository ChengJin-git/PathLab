# Token 使用统计 - 本地测试实现

## ✅ 已实现功能

在 `backend/agent/__main__.py` REPL 中，每次对话后会显示本轮消耗的 token 数。

## 修改内容

### 1. `graph.py` - 添加 token 捕获

- **AgentState** 添加 `last_token_usage` 字段
- **`_chat_node`** 函数中：
  - 优先检查 `usage_metadata`（LangChain 标准化格式）
  - 备选检查 `response_metadata["token_usage"]`（OpenAI 原始格式）
  - 将 token usage 信息添加到 state 中

### 2. `__main__.py` - 显示 token 统计

- 在显示 Agent 回复后，检查 `out.get("last_token_usage")`
- 如果存在，打印格式：`[Token使用] 输入: X | 输出: Y | 总计: Z`

## 测试方法

### 1. 启动 REPL

```bash
cd pathlab/pathlab-client/server
uv run python -m backend.agent
```

### 2. 进行对话

```
You: 你好
Agent: 你好！有什么可以帮助你的吗？
[Token使用] 输入: 15 | 输出: 12 | 总计: 27
--------------------------------------------------
```

### 3. 验证 token 统计

- ✅ 如果 LLM API 返回了 token usage，会显示统计信息
- ⚠️ 如果 LLM API 没有返回（某些本地 vLLM 可能不支持），会显示调试信息（仅在开发环境）

## 注意事项

1. **API 支持**：
   - OpenAI 兼容 API（OpenRouter、vLLM 等）通常会在响应中包含 `usage` 字段
   - LangChain 的 `ChatOpenAI` 会自动解析并放入 `response_metadata` 或 `usage_metadata`
   - 如果 API 不支持，token 统计会显示为 0 或空

2. **调试模式**：
   - 开发环境下（`PATHLAB_ENV=development`），如果没有获取到 token usage，会打印调试信息
   - 帮助排查为什么没有获取到 token 数据

3. **下一步**：
   - 如果测试成功，可以继续实现：
     - 数据库存储（Phase 2）
     - 统计 API（Phase 3）
     - 前端展示（Phase 4）

## 示例输出

```
PathLab Agent (LangGraph) — 本地 vLLM
  URL:   http://localhost:8000/v1
  Model: default
  /quit 或 /q 退出，/clear 清空历史
  /research <问题> 深度研究；/training 或 根据报告建任务 创建训练（可接在 research 后）
--------------------------------------------------
You: 介绍一下病理学
Agent: 病理学是医学的一个分支，主要研究疾病的本质、发生机制和发展规律...
[Token使用] 输入: 25 | 输出: 150 | 总计: 175
--------------------------------------------------
```

## 故障排查

如果看不到 token 统计：

1. **检查 LLM API 是否返回 usage**：
   - 查看调试信息（开发环境）
   - 确认 API 是否支持 token usage 统计

2. **检查 LangChain 版本**：
   - 确保 `langchain-openai` 版本较新（支持 `usage_metadata`）

3. **手动测试**：
   ```python
   from langchain_openai import ChatOpenAI
   llm = ChatOpenAI(base_url="...", api_key="...", model="...")
   msg = llm.invoke([("user", "test")])
   print(msg.usage_metadata)
   print(msg.response_metadata)
   ```
