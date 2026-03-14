# P1 并行步骤执行 — 实现计划

> 基于 DeerFlow main-1.x 分析（DeerFlow 本身也是串行，并行为 PathLab 自有增强）

## 现状 vs 目标

```
当前（串行）:
research_team → conditional edge → researcher (step0) → research_team
                                 → researcher (step1) → research_team  ← 一次一个

目标（并行）:
research_team → Send × N → researcher (step0) ↘
                         → researcher (step1) → merge_results → research_team / planner
                         → analyst   (step2) ↗
```

## 文件改动清单

### 1. `types.py`

- 加 `merge_plans` 自定义 reducer（step-level merge，防止并行节点互相覆盖 current_plan）
- `current_plan` 类型注解改为 `Annotated[Plan | str | None, merge_plans]`
- 新增 `target_step_index: int = -1`（Send payload 指定执行哪个 step，-1 为串行兼容）
- import: `from typing import Annotated` + `import operator`

### 2. `builder.py`

- `continue_to_running_research_team` 改为返回 `list[Send]`（批量 dispatch）
- 读取 `max_parallel_steps`（默认 3）from config
- 注册 `merge_research_results` 节点
- 加 `route_after_merge` conditional edge（有剩余步骤 → research_team，否则 → planner）

### 3. `nodes.py`

- `_execute_agent_step`：当 `target_step_index >= 0` 时直接执行指定 step（不再搜索第一个）
- 返回 `goto` 改为：并行模式 → `merge_research_results`，串行模式 → `research_team`
- retry 分支同样按模式选 goto
- 新增 `merge_research_results_node`（pass-through，检查剩余步骤，决定 goto）

## 关键设计决策

| 问题 | 方案 |
|---|---|
| 并行节点都更新 current_plan 会覆盖 | `merge_plans` reducer：step-level merge，只覆写有值的 step |
| 哪个 step 该执行 | `target_step_index` via Send payload |
| retry 逻辑 | 不设 execution_res → merge 后仍为 incomplete → 下批次重试（自然兼容）|
| messages 并发合并 | `add_messages` reducer 已支持 |
| observations/citations 合并 | 各自 reducer（add_messages / operator.add）已支持 |
| vLLM 并发限制 | `max_parallel_steps` 默认 3，可配置 |

## 风险

- ANALYSIS 步骤依赖 RESEARCH 结果：planner 通常先排 RESEARCH 后排 ANALYSIS，默认 batch 截断可接受
- `merge_plans` 需深拷贝防副作用：用 `model_copy(deep=True)`
- SSE 流式事件交错：前端 store 已按 step 路由事件，理论兼容，需验证

## 实现顺序

1. `types.py`
2. `nodes.py`（先加 merge_research_results_node，再改 _execute_agent_step）
3. `builder.py`（最后接线）
4. 测试：单步骤（串行兼容）→ 多步骤并行 → 有 retry 的计划
