# Auto Research Agent — Phase 1 后端方案

## Context

构建自动化病理研究 agent：研究问题 → 文献调研 → 实验设计 → 提交训练 → 等待完成 → 分析结果 → 迭代/报告。Phase 1 只做后端，不含前端。不生成代码，通过 PathLab API 执行实验。

**参考**：Karpathy AutoResearch（棘轮循环 + 单指标评估）、PantheonOS（代码进化 + 多 agent 团队）、Biomni（检索增强规划 + 代码执行 + Know-How Library）。

**核心借鉴**：
- AutoResearch 的 **ratchet loop**（改进就保留，否则丢弃）
- Biomni 的 **Skill Retriever**（从工具库检索最相关的组合）
- Biomni 的 **自适应规划**（执行中根据结果迭代修正计划）
- PantheonOS 的 **进化思想**（为 Phase 2 代码执行留接口）

## 架构

```
独立 LangGraph graph（不扩展 Deep Research）
复用: llm.py, search.py, crawl.py, pathlab.py tools, SSE 基础设施, checkpointer
新建: server/backend/auto_research/
```

### Graph 流程

```
START
  → coordinator          # 解析问题、检测语言、判断可行性
  → literature_review    # 搜索文献、提取方法和 benchmark
  → experiment_planner   # 检索可用资源 + 设计实验（Biomni 式 RAP）
  → human_review         # interrupt() 等用户审批
  → experiment_executor  # 提交训练任务到 PathLab API
  → experiment_monitor   # interrupt() 等训练完成（外部 poller resume）
  → results_analyzer     # 运行分析、构建对比表
  → iteration_router     # 判断：报告 or 迭代
      ├→ reporter → END  # 生成最终报告
      └→ experiment_planner（迭代：AutoResearch 式棘轮）
```

## 新建文件清单

全部在 `server/backend/auto_research/` 下（独立于 deep-research）：

```
server/backend/auto_research/
├── __init__.py
├── types.py          # AutoResearchState
├── nodes.py          # 9 个节点函数
├── builder.py        # build_auto_research_graph()
├── tools.py          # PathLab API 工具（submit_training, run_analysis 等）
├── monitor.py        # ExperimentMonitor（后台轮询训练状态 → resume graph）
├── prompts.py        # 各节点 system prompt
├── knowhow.py        # Know-How Library（病理学最佳实践检索）
└── server.py         # FastAPI 路由（可独立运行或嵌入 gateway）
```

Gateway / DB 相关：
```
server/gateway/routes/auto_research.py      # Gateway 代理（JWT 认证）
server/backend/database/models.py           # 追加 3 个 model
server/backend/database/repositories/auto_research.py  # CRUD + event replay
```

## 详细设计

### 1. types.py — State

```python
class AutoResearchState(MessagesState):
    # 身份
    locale: str
    research_question: str

    # 文献阶段
    literature_findings: list[dict]
    # [{title, url, methods: [{extractor, aggregator, dataset, metrics}], summary}]

    # 规划阶段
    available_resources: dict
    # {datasets: [...], extractors: [...], aggregators: [...], gpu_info: {...}}
    experiment_plan: list[dict]
    # [{id, name, dataset_id, extractor, aggregator, hyperparams, rationale}]
    plan_approved: bool

    # 执行阶段
    submitted_tasks: dict[str, dict]
    # {experiment_id: {training_task_id, config, status}}
    completed_results: list[dict]
    # [{experiment_id, training_task_id, metrics: {accuracy, auc, f1, ...}}]
    failed_results: list[dict]

    # 分析阶段
    comparison_table: dict    # {columns, rows, best_experiment_id}
    analysis_summary: str

    # 迭代控制（AutoResearch 棘轮）
    iteration: int            # 当前迭代轮次
    max_iterations: int       # 默认 3
    best_metric: float        # 棘轮基线（如最佳 AUC）
    best_experiment: dict     # 当前最优实验配置
    improvement_history: list[dict]  # [{iteration, experiment, metric, improved}]

    # 控制
    phase: str       # literature|planning|review|executing|monitoring|analyzing|routing|reporting
    stop_requested: bool
    final_report: str
```

### 2. nodes.py — 9 个节点

#### coordinator_node
- 解析 research_question，检测 locale
- 判断是否可行（有无相关数据集、GPU 是否可用）
- → literature_review

#### literature_review_node
**工具**: search（Tavily/Exa）、crawl
- 搜索与 research_question 相关的计算病理学论文
- 提取：用了什么 feature extractor、什么 aggregator、什么数据集、报告了什么指标
- 输出 literature_findings（3-5 篇关键论文的结构化摘要）
- → experiment_planner

#### experiment_planner_node
**工具**: ListDatasetsTool、GetTrainingOptionsTool、GetGPUInfoTool
- **Biomni 式检索增强规划**：先查可用资源（数据集、extractor、aggregator、GPU 状态），再结合文献设计实验
- 设计 2-4 个对比实验（不同 extractor×aggregator 组合）
- 输出 experiment_plan（JSON 格式，含每个实验的 rationale）
- 迭代轮次 > 0 时：分析上轮 comparison_table，决定调什么参数（**AutoResearch 棘轮**：只在有提升空间的方向探索）
- → human_review

#### human_review_node
- `interrupt("请审批实验计划")`
- 等待用户反馈：
  - `[ACCEPTED]` → experiment_executor
  - `[EDIT_PLAN] ...` → experiment_planner（带用户修改意见）
- **复用 deep research 的 human_feedback_node 模式**（Command(resume=...)）

#### experiment_executor_node
**工具**: SubmitTrainingTaskTool、GenerateSplitsTool
- 逐个提交实验到 PathLab：`POST /tasks/training`
- 记录 training_task_id 到 submitted_tasks
- → experiment_monitor

#### experiment_monitor_node
- `interrupt("等待训练完成")`
- **不阻塞 graph**，由外部 `ExperimentMonitor` 轮询训练状态
- Monitor 检测到所有任务完成/失败后，用 `Command(resume=...)` 恢复 graph
- 恢复时携带 completed_results / failed_results
- → results_analyzer

#### results_analyzer_node
**工具**: RunAnalysisTool、GetAnalysisResultsTool
- 对每个完成的实验运行分析（`POST /results/tasks/{task_id}/analysis`）
- 构建 comparison_table（多实验多指标对比）
- 更新 best_metric / best_experiment（**AutoResearch 棘轮**）
- → iteration_router

#### iteration_router_node
- LLM 判断是否继续迭代：
  - 达到 max_iterations → reporter
  - 所有实验都失败 → reporter（带失败分析）
  - 有改进空间且未收敛 → experiment_planner（下一轮迭代）
  - 用户 stop_requested → reporter
- → reporter 或 experiment_planner

#### reporter_node
- 基于 literature_findings + comparison_table + improvement_history 生成报告
- 报告结构：背景 → 方法 → 实验设计 → 结果对比 → 最优方案 → 结论
- 输出 final_report（Markdown）
- → END

### 3. tools.py — 8 个 PathLab API 工具

复用 `src/tools/pathlab.py` 的 BaseTool 模式（httpx 调用 Gateway API）：

| Tool | API | 用于节点 |
|------|-----|---------|
| `ListDatasetsTool` | `GET /wsi/datasets` | planner |
| `GetTrainingOptionsTool` | `GET /training/options` | planner |
| `GetGPUInfoTool` | `GET /gpu/info` | planner, coordinator |
| `SubmitTrainingTaskTool` | `POST /tasks/training` | executor |
| `GetTrainingStatusTool` | `GET /tasks/training/{id}` | monitor |
| `GenerateSplitsTool` | `POST /wsi/datasets/{id}/splits` | executor |
| `RunAnalysisTool` | `POST /results/tasks/{id}/analysis` | analyzer |
| `GetAnalysisResultsTool` | `GET /results/tasks/{id}/analysis` | analyzer |

认证：复用 `src/pathlab/api.py` 的 `_cache["auth_token"]` 模式。

### 4. monitor.py — ExperimentMonitor

```python
class ExperimentMonitor:
    """后台轮询训练状态，完成后 resume graph"""

    def register(self, thread_id: str, task_ids: list[str], graph, config):
        """注册需要监控的训练任务"""

    async def _poll_loop(self):
        """每 30s 轮询一次 GET /tasks/training/{task_id}"""
        # 所有任务完成/失败后：
        # 1. 收集 metrics
        # 2. graph.aupdate_state(config, {completed_results, failed_results})
        # 3. 触发 experiment_monitor_node resume: Command(resume="[COMPLETED]")
        # 4. 发射 SSE 事件（experiment_progress, experiment_completed）

    async def start(self):
        """启动后台轮询"""

    async def stop(self):
        """停止"""
```

SSE 事件在轮询过程中持续发射到 auto_research_events 表，前端可实时显示训练进度。

### 5. knowhow.py — 病理学 Know-How Library

受 Biomni 启发，预置领域知识帮助 planner 做更好的实验设计：

```python
PATHOLOGY_KNOWHOW = [
    {
        "task": "MSI prediction",
        "recommended": {"extractor": "UNI2", "aggregator": "ABMIL"},
        "notes": "UNI2 在 CRC MSI 预测上 AUC 达 0.93（TCGA-CRC benchmark）"
    },
    {
        "task": "survival analysis",
        "recommended": {"extractor": "CONCH", "aggregator": "CLAM-SB"},
        "notes": "CONCH 病理专用预训练，survival 任务首选"
    },
    # ... 更多领域最佳实践
]

def retrieve_knowhow(research_question: str) -> list[dict]:
    """基于研究问题检索相关 know-how"""
```

experiment_planner 在规划前调用 `retrieve_knowhow()`，获得领域推荐作为参考。

### 6. prompts.py — 节点 Prompt

关键 prompt 设计：

**literature_review**: "你是计算病理学文献研究专家。搜索与'{research_question}'相关的最新论文，提取每篇论文使用的 feature extractor、aggregator、数据集和关键指标。输出结构化 JSON。"

**experiment_planner**: "你是实验设计专家。基于文献调研结果和可用资源，设计对比实验。\n\n可用资源：{available_resources}\n领域推荐：{knowhow}\n文献发现：{literature_findings}\n\n设计 2-4 个实验，每个包含 dataset_id, feature_extractor, aggregator, hyperparams, rationale。"

**iteration_router**: "分析实验结果：{comparison_table}\n当前最优：{best_experiment}（{best_metric}）\n已迭代 {iteration}/{max_iterations} 轮\n\n判断：1) 结果是否足够好？2) 是否有明确的改进方向？3) 是否应该停止？输出 CONTINUE 或 STOP + 理由。"

**reporter**: "生成学术风格的研究报告。包含：背景（research_question + 文献综述）、方法（实验设计及理由）、结果（comparison_table + 最优方案）、讨论（改进历史 + 局限性）、结论。"

### 7. builder.py — Graph 构建

```python
def build_auto_research_graph(checkpointer=None):
    graph = StateGraph(AutoResearchState)

    graph.add_node("coordinator", coordinator_node)
    graph.add_node("literature_review", literature_review_node)
    graph.add_node("experiment_planner", experiment_planner_node)
    graph.add_node("human_review", human_review_node)
    graph.add_node("experiment_executor", experiment_executor_node)
    graph.add_node("experiment_monitor", experiment_monitor_node)
    graph.add_node("results_analyzer", results_analyzer_node)
    graph.add_node("iteration_router", iteration_router_node)
    graph.add_node("reporter", reporter_node)

    graph.add_edge(START, "coordinator")
    graph.add_edge("coordinator", "literature_review")
    graph.add_edge("literature_review", "experiment_planner")
    graph.add_edge("experiment_planner", "human_review")
    graph.add_conditional_edges("human_review", route_after_review)
    # approved → executor, edit → planner
    graph.add_edge("experiment_executor", "experiment_monitor")
    graph.add_edge("experiment_monitor", "results_analyzer")
    graph.add_edge("results_analyzer", "iteration_router")
    graph.add_conditional_edges("iteration_router", route_iteration)
    # continue → planner, stop → reporter
    graph.add_edge("reporter", END)

    return graph.compile(checkpointer=checkpointer)
```

### 8. API Endpoints

**Auto Research 服务端** — `server/backend/auto_research/server.py`

可独立运行或嵌入 gateway 进程：

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/auto-research/start` | POST | 接收 {research_question, max_iterations?, locale?}，创建 session + thread，启动 graph |
| `/api/auto-research/{session_id}/stream` | GET | SSE 事件流（cursor-based replay，复用 research_job_events 模式） |
| `/api/auto-research/{session_id}/approve` | POST | 用户审批计划：{feedback: "accepted" \| "edit_plan", message?} → Command(resume=...) |
| `/api/auto-research/{session_id}/stop` | POST | 设置 stop_requested |
| `/api/auto-research/{session_id}` | GET | 获取会话状态 |
| `/api/auto-research/sessions` | GET | 列出用户的所有会话 |

**Gateway 代理** — `server/gateway/routes/auto_research.py`

JWT 认证代理（复用 `research_chat.py` 的代理模式）。

### 9. Database Schema

追加到 `server/backend/database/models.py`：

**AutoResearchSession** — session_id, user_id, research_question, phase, status, thread_id, experiment_plan(JSON), best_metric, best_experiment(JSON), comparison_results(JSON), final_report, current_iteration, max_iterations, created_at, updated_at

**AutoResearchExperiment** — id, session_id(FK), experiment_name, training_task_id, dataset_id, feature_extractor, aggregator, hyperparams(JSON), status, metrics(JSON), analysis_id, iteration, created_at

**AutoResearchEvent** — id, session_id(FK), event_type, event_data(JSON), sequence, created_at。Index: (session_id, sequence)

Repository: `repositories/auto_research.py`（复用 `research_job.py` 的 `append_events_batch` + `get_events_after` cursor replay 模式）

### 10. SSE Event Protocol

```
phase_change         — {"phase": "literature", "message": "..."}
agent_thinking       — {"agent": "planner", "message": "..."}
literature_finding   — {"title", "url", "methods", "summary"}
resources_discovered — {"datasets": [...], "extractors": [...]}
knowhow_retrieved    — {"task", "recommended", "notes"}
plan_created         — {"experiments": [...], "requires_approval": true}
plan_approved        — {"approved": true}
experiment_submitted — {"experiment_id", "training_task_id", "config"}
experiment_progress  — {"experiment_id", "progress", "epoch", "status"}
experiment_completed — {"experiment_id", "metrics"}
experiment_failed    — {"experiment_id", "error"}
analysis_complete    — {"comparison_table"}
ratchet_update       — {"best_metric", "best_experiment", "improved": true/false}
iteration_decision   — {"decision": "continue"|"stop", "reason", "iteration"}
report_generated     — {"report": "# ..."}
end                  — {"status": "completed"|"failed"}
```

## Implementation Order

| Sprint | 内容 | 文件 |
|--------|------|------|
| 1 | types.py + knowhow.py + prompts.py + tools.py（8 个 PathLab 工具） | server/backend/auto_research/ 基础模块 |
| 2 | nodes.py 前半（coordinator, literature_review, experiment_planner, human_review） + builder.py 骨架 | graph 文献+规划链路 |
| 3 | nodes.py 后半（executor, monitor, analyzer, iteration_router, reporter）+ monitor.py | graph 执行+分析链路 |
| 4 | DB schema + repository + API endpoints（deep-research server + gateway 代理） | 持久化 + 接口 |
| 5 | 端到端测试：curl 发请求 → 走完整流程 | 集成验证 |

## 复用清单

| 文件 | 复用什么 |
|------|---------|
| `src/llms/llm.py` | get_llm_by_type, 模型配置 |
| `src/tools/search.py` | 搜索工具 |
| `src/tools/crawl.py` | 网页爬取 |
| `src/tools/pathlab.py` | BaseTool 模式 + _cache["auth_token"] + build_tool_result() |
| `src/pathlab/api.py` | httpx 调用 Gateway API 的模式 |
| `src/graph/types.py` | MessagesState 继承模式 |
| `src/graph/nodes.py` | human_feedback_node 的 interrupt()/Command(resume=...) 模式 |
| `src/graph/builder.py` | StateGraph + checkpointer 模式 |
| `src/server/app.py` | SSE streaming + _create_interrupt_event 模式 |
| `src/config/configuration.py` | Configuration dataclass + from_runnable_config 模式 |
| `gateway/routes/research_chat.py` | Gateway 代理 + event buffer + _normalize_thread_id |
| `database/repositories/research_job.py` | append_events_batch + get_events_after cursor replay |

## Verification

1. `python -c "from backend.auto_research.builder import build_auto_research_graph; print('OK')"` — graph 构建成功
2. `curl -X POST /api/auto-research/start -d '{"research_question":"CRC MSI 预测最好的方法"}'` → 返回 session_id
3. `curl /api/auto-research/{id}/stream` → SSE 流：phase_change → literature_finding → plan_created
4. `curl -X POST /api/auto-research/{id}/approve -d '{"feedback":"accepted"}'` → 训练任务出现在 `/tasks/training`
5. 训练完成后 monitor 自动 resume graph → analysis_complete → ratchet_update
6. iteration_router 判断后 → 迭代或报告
7. 最终 report_generated 事件包含完整 Markdown 报告
8. `curl -X POST /api/auto-research/{id}/stop` → 优雅停止（不取消已提交训练）

---

## Phase 2 升级路线

Phase 1 验证核心流程跑通后，以下方向可逐步升级：

### P2.1 代码执行层（AutoResearch 式）

Phase 1 只能调 PathLab 已有 API（固定的 extractor×aggregator 组合）。Phase 2 加入代码沙箱，agent 能写自定义代码：

- **自定义分析脚本**：统计检验（t-test, Wilcoxon）、画 ROC 曲线、Kaplan-Meier 生存曲线、热力图
- **自定义训练脚本**：写 PyTorch 训练循环、设计新网络结构、自定义 loss function
- **Karpathy 棘轮升级**：agent 直接修改 `train.py`（而非调 API 参数），每次改进 git commit，失败 git reset
- **实现方式**：新增 `code_executor_node`，内部启动 Docker 沙箱（参考 OpenHands），执行 agent 生成的 Python 代码

**新增 State 字段**：
```python
code_artifacts: list[dict]   # [{filename, content, execution_result}]
sandbox_id: str              # Docker 容器 ID
```

**新增节点**：`code_executor_node`（替代或并行于 experiment_executor）

### P2.2 Know-How Library → RAG 升级

Phase 1 是硬编码的 20-30 条最佳实践。Phase 2 升级为向量检索 RAG：

- **自动提取**：从 PubMed/bioRxiv 论文中自动提取"方法→数据集→指标"三元组
- **向量化**：用 sentence-transformers 嵌入存入 Milvus/Qdrant（PathLab 已有这两个依赖）
- **检索**：experiment_planner 查询时用语义检索替代关键词匹配
- **持续学习**：每次实验完成后，将{方法, 数据集, 指标}自动入库，Know-How 越用越丰富

**复用**：`deep-research/src/rag/` 已有 Milvus 和 Qdrant provider

### P2.3 并行实验（Swarm 模式）

Phase 1 线性执行（单 GPU 限制）。Phase 2 支持并行：

- **多 GPU 并行提交**：experiment_executor 同时提交多个训练任务，monitor 并行监控
- **PantheonOS 式 Swarm**：多个 agent 分别探索不同方向（一个调 extractor，一个调 aggregator，一个调 hyperparams），结果汇聚
- **实现方式**：LangGraph 的 `Send()` API 将任务分发到并行子图

**Graph 变化**：
```
experiment_executor → [parallel_monitor_1, parallel_monitor_2, ...] → results_aggregator
```

### P2.4 Biomni 式自适应规划

Phase 1 的 planner 一次性设计 2-4 个实验。Phase 2 支持动态调整：

- **实时感知**：monitor 汇报训练中间指标（如 epoch 10 的 loss 趋势），planner 可以提前决定"这个实验没戏，换方向"
- **early stopping 触发**：如果某实验 loss 明显不收敛，自动终止并将资源给下一个
- **资源感知调度**：根据 GPU VRAM 和队列深度动态调整实验并发数

### P2.5 PantheonOS 式代码进化（Evolve）

最高级形态 — agent 不只是调参，还能改进算法本身：

- **进化框架**：遗传算法驱动，population 是不同版本的训练代码
- **变异操作**：LLM 修改代码（改网络结构、改 loss、改优化器逻辑）
- **选择操作**：跑实验 → 按指标排序 → 保留 top-k → 交叉变异 → 下一代
- **目标**：超越人类设计的 baseline（如 PantheonOS 对 Harmony 的进化）

### P2.6 论文生成

Phase 1 生成 Markdown 报告。Phase 2 升级为学术论文：

- **LaTeX 模板**：预置 CVPR/MICCAI/Nature Medicine 模板
- **图表自动生成**：code_executor 生成 matplotlib/seaborn 图表，嵌入论文
- **参考文献管理**：literature_findings 自动格式化为 BibTeX
- **AI Scientist 式审稿**：reporter 生成论文后，用另一个 LLM 做 peer review，反馈修改

### P2.7 前端 UI

独立规划，大致方向：
- **三面板布局**：PhaseTimeline（左）+ ActivityFeed（中）+ ExperimentDashboard（右）
- **PlanReviewModal**：展示实验计划，支持拖拽调整、修改参数
- **ComparisonTable**：实时多实验指标对比
- **ReportViewer**：Markdown 渲染 + 导出 PDF

### 升级优先级建议

| 优先级 | 升级项 | 理由 |
|--------|--------|------|
| P0（紧跟 Phase 1） | P2.7 前端 UI | 没有前端无法使用 |
| P1（高价值） | P2.1 代码执行 | 突破 API 参数空间限制 |
| P1（高价值） | P2.2 Know-How RAG | 让 planner 更智能 |
| P2（增强） | P2.3 并行实验 | 多 GPU 时效率提升 |
| P2（增强） | P2.4 自适应规划 | 减少无效实验 |
| P3（前沿） | P2.5 代码进化 | 需要 P2.1 先完成 |
| P3（前沿） | P2.6 论文生成 | 需要 P2.1 先完成 |
