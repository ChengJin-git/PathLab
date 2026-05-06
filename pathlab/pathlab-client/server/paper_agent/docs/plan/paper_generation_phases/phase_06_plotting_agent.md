# Phase 06 — Plotting Agent

## 目标

实现 PaperOrchestra Step 2：Plotting Agent。它同时处理 empirical plots 和 conceptual diagrams。PathLab 的 empirical plots 由确定性脚本画图；Figure 1 等 conceptual diagrams 走 PaperBanana-style 子流水线。

## 输入

```text
drafts/outline.json
evidence/experimental_log.md
evidence/evidence_lock.private.json
figures/manifest.json
analysis JSON / zarr bundle / heatmap API
templates/{template}/style.json
```

## 输出

```text
figures/
├── manifest.json
├── figure_1_overview.png|pdf
├── figure_2_confusion.pdf
├── figure_3_roc.pdf
├── figure_5_calibration.pdf
└── ...
figures/captions.json
```

## 代码范围

```text
paper_generation/agents/plotting_agent.py
paper_generation/plotting/
├── chart_passthrough.py
├── calibration_plot.py
├── per_fold_roc.py
├── km_stratified.py
├── failure_cases_panel.py
├── heatmap_examples.py
├── seg_qualitative_4panel.py
├── grad_cam_examples.py
└── paperbanana_adapter.py
```

## 实施步骤

1. 读取 `outline.plotting_plan`。
2. 对 `ready` charts：copy / convert PathLab analysis chart 到 paper figures。
3. 对 `pending_generation` empirical plots：调用 deterministic plotting generator。
4. 对 conceptual diagrams：调用 `paperbanana_adapter.py`：
   - Retriever
   - Planner
   - Stylist
   - Visualizer
   - Critic
5. Critic 通过则标记 `generated_by_paperbanana`。
6. Critic 不通过或 backend 不可用则标记 `requires_user_revision`，不静默通过。
7. 生成 captions。
8. 更新 `figures/manifest.json`。

## 修复计划：复用 PathLab 已生成分析图

当前 PathLab gateway 的结果分析已经会在 `summary.json.chart_paths` 里记录
ROC、confusion matrix、loss curve、KM curve 等 PNG/PDF。Phase 06 不应优先重画
这些图，而应先把它们作为 locked evidence artifact 复用：

1. Plotting stage 启动时读取 Phase 02/03 收集到的 selected
   `analysis_summary.chart_paths`。
2. 只接受已经存在的 `.png` / `.jpg` / `.jpeg` / `.pdf`；跳过不存在或非图像
   artifact。
3. 把可复用图复制到当前 paper run 内部的
   `figures/source_charts/`，文件名只保留安全 chart kind，不暴露原始 upload
   path、task id 或 analysis id。
4. 为每张图写一个 `evidence/plot_data/pathlab_chart_*.json`，内容只包含
   run-relative `source_path` 和 chart kind。
5. 自动生成一个 `chart_passthrough` plotting plan；如果 outline 已经要求 ROC/KM
   等同类图，则用 passthrough plan 替换原 deterministic generator，避免再次
   画图。
6. Plotting Agent 仍通过 `chart_passthrough.py` 复制到最终 `figures/*.png|pdf`
   并生成 caption；`figures/manifest.json` 只暴露最终 figure path，不暴露原始
   analysis path。
7. 只有 PathLab 没有现成图时，才回退到 calibration / per-fold ROC / KM 等
   deterministic generator。

## 验收标准

- 至少支持 calibration、per-fold ROC、failure cases、heatmap examples。
- PathLab 已经生成的 `chart_paths` 会被自动复制并通过 `chart_passthrough`
  注册成 ready figure，不额外重画。
- Figure 1 默认走 PaperBanana-style 流程，而不是 user_provided 占位。
- 每张图都有 source、generator、caption、status、template sizing 信息。
- empirical plots 的数字都可追溯到 evidence，不由 LLM 写像素级数字。

## 风险

- Conceptual diagram 最容易连错边，必须有 Critic gate 和人工复核状态。
- 不要让 LLM 直接生成 metric 图中的数值。
- 大图复制和 zarr 读取要注意运行时体积。
