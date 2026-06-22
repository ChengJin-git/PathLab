# PathScientist Code Agent — Implementation Plan

> Date: 2026-04-03
> Last updated: 2026-04-03 Phase 1 done + Phase 2 SDK audit

## 1. Architecture

基于 OpenHands V1 SDK，LLM 驱动 ratchet 流程（非硬编码状态机）。

```
OpenHands SDK Agent (LLM loop + tool dispatch)
    │
    ├── SDK 内置: TerminalTool, FileEditorTool (含 str_replace), ThinkTool, FinishTool
    ├── SDK 能力: LLMSummarizingCondenser (历史压缩), StuckDetector (死循环检测)
    │
    ├── 自定义 Tools:
    │     RunExperimentTool    → workspace 执行脚本，收集 metrics
    │     ValidateScriptTool   → 语法 + 安全检查
    │     RatchetCommitTool    → git commit 改进
    │     RatchetRevertTool    → git revert 失败
    │     GetMetricsTool       → 读取实验结果
    │     GetWorkspaceInfoTool → workspace 状态
    │
    ├── Runtime:
    │     Workspace           → SDK LocalWorkspace + git ratchet
    │     script_safety       → regex + AST 安全分析
    │
    ├── Domain: skills, templates, extractors (已有)
    └── Prompts: system_prompt.j2 (ratchet workflow)
```

## 2. 已完成

| 文件 | 状态 | 说明 |
|------|------|------|
| `config.py` | ✅ | PathScientistConfig dataclass, from_env() |
| `agent.py` | ✅ | create_agent() + create_conversation(), Condenser + StuckDetector |
| `run.py` | ✅ | CLI 入口, argparse |
| `runtime/workspace.py` | ✅ | 基于 SDK LocalWorkspace, git ratchet (commit/revert/baseline) |
| `runtime/script_safety.py` | ✅ | regex + AST 安全检查 |
| `tools/run_experiment.py` | ✅ | workspace.run_script() 执行, 收集 metrics |
| `tools/validate_script.py` | ✅ | 语法/入口/metrics/safety 检查 |
| `tools/ratchet.py` | ✅ | RatchetCommitTool + RatchetRevertTool |
| `tools/metrics.py` | ✅ | MetricsTracker + GetMetricsTool |
| `tools/workspace_info.py` | ✅ | 文件列表 + git history + 当前脚本 |
| `prompts/system_prompt.j2` | ✅ | ratchet workflow 指导 |
| `structured_output.py` | ✅ | JSON 提取, strip_thinking, Pydantic 验证 |
| `domain/skills/` | ✅ | SkillRegistry, Skill dataclass, YAML 加载 |
| `domain/templates/` | ✅ | classification, survival, feature_extraction + extractors + aggregators |
| `.venv/` | ✅ | Python 3.12 + openhands-sdk v1.16.1 + openhands-tools + torch(cpu) |

### Phase 1 测试结果

| 测试 | 状态 | 结果 |
|------|------|------|
| Smoke test (简单任务) | ✅ | Qwen3.5-397B, 6 步完成 ratchet 循环 |
| Skill 集成 (MIL classification) | ✅ | 加载 template → 修改路径 → 执行 → AUC=0.75 on mock data |

## 3. 待完成

### Phase 2: 增强 agent 能力

#### ~~Task 5: Error classification~~ → 需要自建

SDK 只有原始 `AgentErrorEvent`，没有错误分类。需从旧代码迁移。

**实现方案**:
- 创建 `pathscientist/error_classifier.py`
- 从 `auto_research_old/code_agent.py` 迁移 `_classify_error()` (12 种错误类型)
- 在 `RunExperimentTool` 的 observation 里加入结构化错误分类 + 修复建议
- 12 种类型: ImportError, CUDA_OOM, ShapeMismatch, DeviceMismatch, FileNotFound, TypeError, ValueError, KeyError, SyntaxError, AttributeError, PermissionError, Timeout
- 每种类型附带修复 hint（如 CUDA_OOM → "reduce batch_size, use gradient checkpointing"）

**旧代码参考**: `auto_research_old/code_agent.py` lines 67-133

#### ~~Task 6: Quick check 两阶段~~ → Prompt 改进即可

`RunExperimentTool` 已支持 `quick_check` 参数。SDK 没有原生 dry-run 机制。

**实现方案**:
- 在 `prompts/system_prompt.j2` 里强化引导：先 `quick_check=true`，通过后再 `quick_check=false`
- 在 smoke test 验证 LLM 确实先跑 quick check
- **不需要写新代码**，只改 prompt

#### ~~Task 7: Diff mode editing~~ → **跳过，SDK 已有**

SDK `FileEditorTool` 的 `str_replace` 命令已经完整实现了增量编辑：
- 精确字符串匹配 + strip fallback
- 返回 before/after diff
- 多次匹配检测（报错要求唯一）
- undo_edit 支持
- SDK 默认 system prompt 已有使用示例

**不需要任何工作。**

#### Task 8: 环境上下文注入 → 需要自建（用 SDK AgentContext 框架）

SDK 有 `AgentContext.system_message_suffix` 注入机制，但没有 GPU/包/路径检测内容。

**实现方案**:
- 创建 `pathscientist/context.py`，包含 `RuntimeContextProvider`
- 检测并注入: GPU 信息、已安装包、数据挂载路径、common/ 库能力
- 通过 `AgentContext(system_message_suffix=...)` 注入 agent
- 更新 `agent.py` 中 `create_agent()` 传入 context

**SDK 接入点**: `Agent(agent_context=AgentContext(system_message_suffix="..."))` 

### Phase 3: 与 PathLab 平台集成

#### Task 9: SSE 事件流
- SDK `LocalConversation` 支持 `on_event` callback
- 将 callback 接入现有的 `AutoResearchEvent` 表
- 前端可以实时看到 agent 的每一步操作

#### Task 10: Session 管理
- 将 agent 运行绑定到 `AutoResearchSession`
- SDK `LocalConversation` 支持 persistence_dir 用于恢复
- 支持 stop/resume, 多 session 并发

#### Task 11: API 端点
- `POST /api/pathscientist/start` → 创建 session + 启动 agent
- `GET /api/pathscientist/{session_id}/stream` → SSE 事件流
- `POST /api/pathscientist/{session_id}/stop` → 停止 agent
- `GET /api/pathscientist/{session_id}` → session 状态

### Phase 4: 高级能力

#### Task 12: 文献知识注入
- 将 literature findings 和 knowhow 注入 system prompt
- 可通过 SDK `AgentContext.skills` 机制实现（knowledge skill with triggers）
- 让 agent 参考文献方法来修改代码

#### Task 13: Evidence 收集
- 每次 ratchet_commit 时记录: 代码 diff, metrics, logs
- SDK `LocalConversation` 的 event history 天然记录了所有操作
- 为后续 paper writer 提供 evidence 数据

#### Task 14: Paper writer agent
- 新的 agent（或同一个 agent 的 finish 阶段）
- 基于 evidence 生成 report.md / paper.md

## 4. SDK 复用清单

| SDK 模块 | 如何使用 | 状态 |
|---|---|---|
| `Agent` | 核心 agent loop | ✅ 已用 |
| `LLM` | LLM 调用 | ✅ 已用 |
| `Tool/ToolDefinition/Action/Observation` | Tool 协议 | ✅ 已用 |
| `TextContent` | LLM 消息格式 | ✅ 已用 |
| `register_tool` | Tool 注册 | ✅ 已用 |
| `LocalWorkspace` + `CommandResult` | 命令执行、文件操作 | ✅ 已用 |
| `LLMSummarizingCondenser` | 长对话自动压缩 | ✅ 已用 |
| `LocalConversation` + `StuckDetector` | agent 运行 + 死循环检测 | ✅ 已用 |
| `TerminalTool` | shell 命令 | ✅ 已用 |
| `FileEditorTool` (含 str_replace) | 文件编辑 + 增量 diff | ✅ 已用，**替代了旧 diff mode** |
| `ThinkTool` | agent 推理 | ✅ 已用 |
| `FinishTool` | 任务完成 | ✅ 已用 |
| `AgentContext` | 环境上下文注入框架 | 🔜 Phase 2 Task 8 |
| `on_event` callback | SSE 事件流 | 🔜 Phase 3 Task 9 |
| `persistence_dir` | Session 持久化 | 🔜 Phase 3 Task 10 |
| `AgentContext.skills` | 文献知识注入 | 🔜 Phase 4 Task 12 |

## 5. 自研清单

| 模块 | 原因 | 状态 |
|---|---|---|
| `runtime/script_safety.py` | Python 脚本级 regex+AST, SDK 的 SecurityAnalyzer 是 action 级别 | ✅ 已有 |
| `structured_output.py` | JSON 提取 + strip_thinking + Pydantic retry, SDK 没有 | ✅ 已有 |
| `config.py` | 业务配置 | ✅ 已有 |
| `tools/ratchet.py` | git commit/revert ratchet 语义, SDK git 只有 read-only | ✅ 已有 |
| `tools/run_experiment.py` | 实验执行 + metrics 收集 | ✅ 已有 |
| `tools/validate_script.py` | 脚本验证 | ✅ 已有 |
| `tools/metrics.py` | 实验 metrics 追踪 | ✅ 已有 |
| `tools/workspace_info.py` | workspace 状态查询 | ✅ 已有 |
| `error_classifier.py` | 12 种错误分类 + 修复 hint, SDK 没有 | 🔜 Phase 2 Task 5 |
| `context.py` | GPU/包/路径检测, SDK 只有框架 | 🔜 Phase 2 Task 8 |
| `domain/` | skills, templates, extractors | ✅ 已有 |

## 6. 执行优先级

```
Phase 1 (让 agent 跑起来):                          ✅ 已完成
  Task 1 (SDK 安装) ✅
  Task 2 (Smoke test) ✅ — Qwen3.5, 6 步完成 ratchet
  Task 3 (真实 LLM) ✅ — 合并到 Task 2
  Task 4 (Skill 集成) ✅ — MIL classification AUC=0.75

Phase 2 (增强能力):                                  🔜 进行中
  Task 8 (环境上下文) → 用 SDK AgentContext 注入
  Task 5 (Error classification) → 自建分类器
  Task 6 (Quick check prompt) → 改 prompt 即可
  Task 7 (Diff mode) → 跳过，SDK FileEditorTool 已有

Phase 3 (平台集成):
  Task 9 (SSE 事件流) → SDK on_event callback
  Task 10 (Session 管理) → SDK persistence_dir
  Task 11 (API 端点) → FastAPI routes

Phase 4 (高级能力):
  Task 12 (文献注入) → SDK AgentContext.skills
  Task 13 (Evidence) → SDK event history
  Task 14 (Paper writer) → 新 agent
```

## 7. 验证标准

- Phase 1 ✅: agent 能在 local workspace 跑完 ratchet 循环 + skill 集成
- Phase 2: agent 有结构化错误恢复 + 环境感知 + quick check 习惯
- Phase 3: 前端能看到 agent 实时状态, 能 start/stop
- Phase 4: 一次 session 能生成 report + paper draft

## 8. 测试方法

```bash
# 激活环境
cd /project/vcompath/storage/ywangrm/PathLab/pathlab/pathlab-client/server/backend/pathscientist
source .venv/bin/activate

# 简单任务 smoke test
cd /project/vcompath/storage/ywangrm/PathLab/pathlab/pathlab-client/server
PYTHONPATH=backend python pathscientist_tests/test_smoke_agent.py

# Skill 集成 test
PYTHONPATH=backend python pathscientist_tests/test_smoke_skill.py
```

LLM 配置: `openai/Qwen/Qwen3.5-397B-A17B-FP8` @ `http://dgx-52.cm.cluster:8000/v1` (key: `sk-pathlab`)
