# PathLab Agent (LangGraph)

简易对话 agent，**默认只连本地 vLLM**，用于本地测试。模型：`Qwen/Qwen3-235B-A22B-Instruct-2507`。

## 环境（uv）

```bash
cd pathlab/pathlab-client/server

uv sync

# 默认即为本地 vLLM，可直接运行（若已 export VLLM_URL / VLLM_KEY 可省略）
export VLLM_URL="http://localhost:8000/v1"
export VLLM_KEY="sk-pathlab"

uv run python -m backend.agent
```

或一行（使用默认 URL/Key）：

```bash
cd server && uv run python -m backend.agent
```

## API Key 与配置

统一由 `api_keys` 模块读取：环境变量 或 `backend/agent/.env`（导入时用 python-dotenv 加载，不覆盖已有变量）。模板见 `api_keys.env.example`。

```bash
# 方式一：复制模板后编辑（勿提交 .env）
cp api_keys.env.example .env

# 方式二：export
export VLLM_URL="http://localhost:8000/v1"
export VLLM_KEY="sk-pathlab"
```

## 环境变量（均为可选，有默认值）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| VLLM_URL | `http://localhost:8000/v1` | vLLM 的 base URL |
| VLLM_KEY | `sk-pathlab` | API Key |
| VLLM_MODEL | `Qwen/Qwen3-235B-A22B-Instruct-2507` | 模型名 |
| VLLM_MAX_TOKENS | `8192` | 单次回复最大 token 数 |

## REPL

- 输入内容 → 调 LLM 并打印回复
- `/quit` 或 `/q`：退出
- `/clear`：清空对话历史
- **`/research <问题>`**：深度研究（open_deep_research：Tavily 搜索 + 多轮推理 + 报告）。需在 `.env` 或环境中配置 `TAVILY_API_KEY`；模型用 `VLLM_*`（本地 vLLM）或云模型（如 `OPENAI_API_KEY`）。
