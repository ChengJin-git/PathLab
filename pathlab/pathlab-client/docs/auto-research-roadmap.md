---
name: auto-research-roadmap
description: Auto Research Agent roadmap - Phase 2 (code execution + enhanced planning) and Phase 3 (code evolution + paper generation). Dependencies and timeline.
type: project
---

# Auto Research Agent — Phase 2 & 3 Roadmap

## Phase 2：代码执行 + 增强规划

Phase 1 的限制：只能调 PathLab API 预设参数（17 extractor × 8 aggregator），无法自定义分析或训练逻辑。

### P2.1 代码执行沙箱
**目标**：agent 能写并执行 Python 代码

- Docker 沙箱执行环境（参考 OpenHands CodeAct）
- 新增 `code_executor_node`，与 experiment_executor 并行
- 支持的代码类型：
  - 统计分析：t-test, Wilcoxon, bootstrap CI
  - 可视化：ROC 曲线, Kaplan-Meier, confusion matrix, heatmap
  - 数据预处理：特征选择, 降维, 数据增强
  - 自定义训练：PyTorch 训练脚本, 自定义 loss, 新网络结构
- Karpathy 棘轮集成：agent 修改 train.py → 跑 → git commit/reset

**依赖**：Phase 1 完成
**预估**：3-4 周

### P2.2 Know-How RAG
**目标**：从论文自动提取最佳实践，替代硬编码

- 从 PubMed/bioRxiv 提取 {方法, 数据集, 指标} 三元组
- sentence-transformers 嵌入 → Milvus/Qdrant 向量库（已有依赖）
- experiment_planner 语义检索替代关键词匹配
- 闭环学习：每次实验完成后自动入库

**依赖**：Phase 1 完成，复用 deep-research/src/rag/
**预估**：2 周

### P2.3 并行实验
**目标**：多 GPU 并行跑实验

- experiment_executor 同时提交多个训练任务
- monitor 并行监控多个任务
- LangGraph Send() API 分发到并行子图
- 资源感知调度：根据 GPU VRAM 和队列深度动态调整并发数

**依赖**：Phase 1 完成，多 GPU 环境
**预估**：2 周

### P2.4 自适应规划
**目标**：实验过程中动态调整计划

- monitor 汇报训练中间指标（epoch N 的 loss 趋势）
- planner 可提前终止无效实验（early stopping）
- 将释放的资源分配给新实验
- 需要改 monitor → planner 的反馈通道

**依赖**：P2.3 并行实验
**预估**：1-2 周

### P2.5 前端 UI
**目标**：可视化操作界面

- 三面板布局：PhaseTimeline + ActivityFeed + ExperimentDashboard
- PlanReviewModal：拖拽调整实验计划
- ComparisonTable：实时多实验指标对比
- ReportViewer：Markdown 渲染 + 导出 PDF
- 路由：/auto-research/:sessionId

**依赖**：Phase 1 API 稳定
**预估**：3-4 周

---

## Phase 3：进化 + 论文生成

Phase 2 的限制：agent 写代码但没有系统化的搜索策略；报告是 Markdown 不是论文。

### P3.1 代码进化（PantheonOS Evolve）
**目标**：遗传算法驱动的代码进化，超越人类 baseline

- Population：不同版本的训练代码/模型结构
- 变异：LLM 修改代码（改网络层、改 loss、改优化策略）
- 选择：按指标排序 → top-k 保留 → 交叉变异 → 下一代
- 进化历史可视化：family tree of code versions
- 目标：在特定任务上超越人类手工调优的 SOTA

**依赖**：P2.1 代码执行沙箱
**预估**：4-6 周

### P3.2 学术论文生成
**目标**：自动生成可投稿的学术论文

- LaTeX 模板：CVPR, MICCAI, Nature Medicine 格式
- 图表自动生成：code_executor 生成 matplotlib 图 → 嵌入论文
- 参考文献：literature_findings → BibTeX 自动格式化
- AI 审稿：第二个 LLM 做 peer review（AI Scientist 模式）
- 迭代修改：根据审稿意见自动修改论文
- 输出：LaTeX source + compiled PDF

**依赖**：P2.1 + P2.2 + Phase 1 reporter
**预估**：3-4 周

### P3.3 多 agent 协作（Swarm）
**目标**：多个 agent 并行探索不同研究方向

- PantheonOS 式团队模式：
  - Agent A 探索 extractor 选择
  - Agent B 探索 aggregator + hyperparams
  - Agent C 探索数据增强策略
- Mixture-of-Agents 汇聚：多 agent 输出合成最优方案
- 分布式执行：NATS 或 Redis 消息总线

**依赖**：P2.3 并行实验 + P2.1 代码执行
**预估**：4-6 周

### P3.4 跨平台数据获取
**目标**：agent 自动从外部平台获取数据集

- 调用 Phase 1 的 dataset_download 服务（HuggingFace, Kaggle, GEO, Zenodo）
- 自动注册到 PathLab Dataset
- 文献中提到的数据集 → 自动搜索 → 下载 → 注册 → 用于实验
- 需要 TCGA/GDC API 支持（dbGaP 认证）

**依赖**：dataset_download 服务 + Phase 1
**预估**：2-3 周

---

## 整体时间线

```
Phase 1（后端核心）         ████████████████████  4-5 周
Phase 2.5（前端 UI）        ░░░░████████████████  3-4 周
Phase 2.1（代码执行）       ░░░░░░░░████████████  3-4 周
Phase 2.2（Know-How RAG）   ░░░░░░░░░░██████      2 周
Phase 2.3（并行实验）       ░░░░░░░░░░░░████      2 周
Phase 2.4（自适应规划）     ░░░░░░░░░░░░░░██      1-2 周
Phase 3.1（代码进化）       ░░░░░░░░░░░░░░░░████████  4-6 周
Phase 3.2（论文生成）       ░░░░░░░░░░░░░░░░░░██████  3-4 周
Phase 3.3（多 agent）       ░░░░░░░░░░░░░░░░░░░░████  4-6 周
Phase 3.4（跨平台数据）     ░░░░░░░░░░░░░░░░██████    2-3 周
```

关键里程碑：
- M1：Phase 1 完成 → 可以用 curl 跑完整的 文献→实验→分析→报告 流程
- M2：P2.5 前端完成 → 用户可以在浏览器里操作
- M3：P2.1 代码执行完成 → 突破 API 参数空间限制
- M4：P3.1 代码进化完成 → 具备超越人类 baseline 的能力
