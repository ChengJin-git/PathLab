# Phase 02 — Deterministic Collector

## 目标

实现完全不依赖 LLM 的 collector，把已完成 PathLab 实验链路中的 task、dataset、split、model、analysis、external validation、qualitative artifact 收集为结构化 evidence schema。

## 输入

- `source_task_ids`
- `source_analysis_ids` 或 `latest`
- task role：`main` / `baseline` / `ablation_*` / `external_validation`
- PathLab DB / uploads / analysis 文件

## 输出

```text
evidence/raw_collected/
├── task_summary.json
├── dataset_summary.json
├── split_summary.json
├── model_summary.json
├── analysis_summary.json
├── external_validation_summary.json
└── qualitative_summary.json
```

这些 raw collected 文件默认 private，后续 Phase 03 再做 PHI scrub 和 public/private 分离。

## 代码范围

```text
paper_generation/collector/
├── task.py
├── dataset.py
├── split.py
├── model.py
├── analysis.py
├── external_validation.py
├── qualitative.py
└── role_dispatcher.py
```

## 实施步骤

1. `task.py`：读取 `TrainingTask` 元信息、`preprocessing_config`、`model_config`、`classes`、状态、时间戳。
2. `dataset.py`：读取 data group / dataset / WSI slide，统计 WSI 数、case 数、label 分布、cohort 字段。
3. `split.py`：读取 `TrainingTaskWSI`，统计 train / val / test / fold 分布。
4. `model.py`：读取 `TrainedModel`，记录 checkpoint、config、feature extractor、aggregator、train/val metrics。
5. `analysis.py`：定位 latest 或指定 analysis，读取 `summary.json`、`results.json`、charts。
6. `external_validation.py`：识别外部验证 task，归一化为同一 analysis schema。
7. `qualitative.py`：收集 heatmap / CAM / thumbnail / mask / zarr bundle 的可用性，不直接大规模复制图像。
8. `role_dispatcher.py`：按 role tag 组织 main / baseline / ablation / extval。
9. 所有 collector 输出 Pydantic schema，不输出 prose。

## 支持任务类型

- `wsi_classification`
- `wsi_survival`
- `patch_classification`
- `patch_segmentation`

## 验收标准

- 单 task main run 可以完整收集 task / dataset / split / model / analysis。
- 多 task role tags 可以生成 baseline / ablation 分组。
- 没有 analysis 时明确返回 missing evidence，不让后续 agent 编造。
- collector 输出稳定、可序列化、可测试。

## 风险

- 不要在 collector 里写 narrative。
- 不要让 collector 做 PHI 脱敏以外的“解释”。
- 不要假设每个 task 都有 external validation 或 qualitative artifact。
