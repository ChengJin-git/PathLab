# PathLab 实验完成后可用于 paper draft 的素材清单

> 整理日期：2026-05-04
> 目标：在动手做 paper-gen agent 之前，先把"PathLab 完整跑完一次实验之后留下了什么"摸清楚——这就是 agent 的输入面。
> 范围：DB / zarr / 文件系统 / 现有 export 路径全部覆盖。
> 视角：从 paper draft 反推（Method / Dataset / Results / Figures / Tables / Supplementary），不是从代码反推。

---

## 0. TL;DR

PathLab 的一次完整实验（训练 + 推断 + 分析 + 可选外部验证）会在三个位置留下结构化数据：

| 位置 | 内容 | 谁产生 |
|------|------|--------|
| **PostgreSQL** | 任务配置、模型元数据、每张 WSI 的预测、训练日志、患者元信息、分割 GT（COCO） | gateway 写入 |
| **Zarr ZipStore** (`uploads/ai_results_bundles/{task_id}.zarr.zip`) | 每张 WSI 的 pred/probs/risk_score、MIL attention、Grad-CAM、分割 mask 等大数组 | trainer / inference 写入 |
| **文件系统** (`uploads/logs/analysis/{task_id}/`) | 测试集指标 summary、per-sample results、K-fold 拆解、bootstrap CI、4 张核心 PNG（confusion / ROC / loss / KM） | 分析路由生成 |

**对 paper draft 来说**：Method / Dataset / Results / 主表 / 4 张主图基本可以**自动填**；Ablation、calibration、per-fold ROC、failure case 是**当前缺的**——这些需要在 paper-gen agent 里要么自己补算，要么提示用户补做。

> 一句话：PaperOrchestra 那一套"experimental_log.md → manuscript"的输入侧——**PathLab 已经把 80% 的素材都存好了**。

---

## 1. 实验完成后的产物总览

```
PostgreSQL                               文件系统
├── training_tasks                       uploads/
│   ├── preprocessing_config (JSON)      ├── ai_results_bundles/
│   ├── model_config (JSON)              │   └── {task_id}.zarr.zip
│   ├── classes (JSON)                   │       ├── results/{wsi}/        (pred/probs/risk_score)
│   ├── status, progress                 │       ├── attention/{wsi}/      (MIL 注意力数组)
│   └── started_at / finished_at         │       ├── attention_raw/{wsi}/  (patch 级原始注意力)
├── trained_models                       │       ├── cam/{wsi}/            (Grad-CAM 数组)
│   ├── train_metrics (JSON)             │       └── pred_mask/{wsi}/      (分割 mask 数组)
│   ├── val_metrics (JSON)               │
│   ├── feature_extractor                ├── training/{task_id}/
│   └── aggregator                       │   └── metrics.json              (best ckpt 指标)
├── ai_results                           │
│   ├── pred / probs (JSON)              ├── models/{model_id}/
│   └── extra_metadata (zarr 指针)        │   └── *.pth, config.json
├── training_task_wsi                    │
│   ├── split: train/val/test/fold_N    ├── logs/analysis/{task_id}/
├── training_logs                        │   ├── summary.json              (★ 测试集主指标)
│   └── extra_data (epoch/loss/...)      │   ├── results.json              (★ 每样本预测)
├── wsi_slides                           │   ├── metrics_kfold.json        (★ 每折 + mean±std)
│   ├── case_id, label, age, gender      │   ├── bootstrap_ci.json         (★ 95% CI)
│   ├── source, split                    │   └── charts/
│   ├── event_time, event_status         │       ├── confusion_matrix.png  (★ 主图)
│   ├── mpp, magnification, vendor       │       ├── roc_curve.png         (★ 主图)
│   └── width, height, file_size         │       ├── loss_curve.png        (★ 主图)
└── segmentation_annotations             │       └── km_curve.png          (★ survival 主图)
    └── annotations (COCO)               │
                                         └── patch_coords/{wsi_id}.h5     (patch 坐标，重建 heatmap 用)
```

★ 标记的是**直接可以放进 paper 主体**的数据。

---

## 2. 按 paper 章节梳理可用素材

下表是给 paper-gen agent 用的核心映射：**每条 paper section / 每张图 / 每张表都标好了从哪里抽数据**。

### 2.1 Method 章节

| Paper 内容 | 数据来源 | 字段 |
|-----------|----------|------|
| 模型架构（feature extractor + aggregator） | DB `trained_models` | `feature_extractor` (e.g. CONCH/UNI/ResNet50), `aggregator` (e.g. ABMIL/CLAM/TransMIL) |
| 训练超参 | DB `training_tasks.model_config` | `learning_rate, epochs, optimizer, batch_size`（JSON）|
| 预处理 pipeline | DB `training_tasks.preprocessing_config` | `tile_size, stride, feature_extractor, feature_batch_size, use_gpu` |
| 类别定义 | DB `training_tasks.classes` 或 `trained_models.classes` | `["HSIL", "LSIL", "Normal"]` |
| 任务类型 | DB `training_tasks.group_id` → `data_groups` | `data_type` (wsi/patch), `aggregation_level` (file/case), `task_type` (classification/survival/segmentation) |
| 损失函数 | 见 trainer | wsi_survival 用 NLL survival loss (`backend/ai/tasks/wsi_survival/losses.py`) |
| 数据划分 | DB `training_task_wsi.split` | `train/val/test` 或 `fold_0..fold_K` |
| 训练时长 | DB `training_tasks.started_at` / `finished_at` | 直接相减 |

> 这一节基本上是**直接 JSON-to-Markdown 的转换**——paper-gen agent 只要把这些字段按句式模板填进 Method 就能写出"我们用了 X 模型，Y feature extractor，预处理用 256×256 tile，训了 50 epoch ..."。

### 2.2 Dataset 章节

| Paper 内容 | 数据来源 | 字段 |
|-----------|----------|------|
| 队列规模 | DB `dataset_stats` | `file_count, split_train_count, split_val_count, split_test_count` |
| 切片元信息 | DB `wsi_slides` 聚合 | `mpp` 平均值、`magnification` 分布、`vendor` 分布 |
| 患者人口学 | DB `wsi_slides` 聚合 | `age` (mean ± std)、`gender` 分布、`source`（器官 / 组织来源） |
| 标签分布 | DB `wsi_slides.label` 按 split 聚合 | per-class count |
| 生存数据 | DB `wsi_slides.event_time` / `event_status` | 中位随访时间、event 数 |
| 分级 / 分期 | DB `wsi_slides` extra fields | （需要确认 schema 是否含 stage/grade，PROJECT.md 里没列） |

> Dataset 章节最经典的"Table 1: Patient demographics"基本可以**完全自动填**。需要 agent 写一些 SQL 聚合：`GROUP BY split, label, gender` 这种。

### 2.3 Results 章节 — 主指标表

**WSI / Patch 分类**——主表（每行一个指标，列可以是 mean ± 95% CI）：

| 指标 | 数据来源 |
|------|----------|
| Accuracy | `analysis/summary.json` `metrics.accuracy` |
| Macro Precision / Recall / F1 / Specificity | `analysis/summary.json` `metrics.macro_*` |
| Weighted Kappa | `analysis/summary.json` `metrics.weighted_kappa` |
| AUC（二分类）/ AUC OvR（多分类）| `analysis/summary.json` `metrics.auc` |
| Per-class Precision/Recall/F1/Specificity | `analysis/summary.json` `class_metrics.{class}.*` |
| 95% CI | `analysis/bootstrap_ci.json` `{metric}.ci_lower / ci_upper` |
| K-fold mean ± std | `analysis/metrics_kfold.json` `aggregated.{metric}.{mean,std}` |

**WSI 生存**——主表：

| 指标 | 数据来源 |
|------|----------|
| Concordance Index (C-index) | `analysis/summary.json` `metrics.c_index` |
| Integrated Brier Score (IBS) | `analysis/summary.json` `metrics.integrated_brier_score` |
| 95% CI | `analysis/bootstrap_ci.json`（需确认是否覆盖 c_index） |
| 高/中/低风险组的中位生存时间 | 需要从 zarr `risk_score` + `wsi_slides.event_time/status` 现算 |

**Patch 分割**——主表：

| 指标 | 数据来源 |
|------|----------|
| mIoU | `analysis/summary.json` `metrics.miou` |
| Per-class IoU / Dice / Precision / Recall / F1 | `analysis/summary.json` `class_metrics.{class}.*` |
| Pixel accuracy | `analysis/summary.json` `metrics.accuracy` |

### 2.4 Results 章节 — 主图

PathLab 已经把这 4 张 PNG 跑出来了，**paper 直接 `\includegraphics`**：

| 图 | 路径 | 适用任务 | paper 位置建议 |
|----|------|---------|----------------|
| Confusion matrix | `uploads/logs/analysis/{task_id}/charts/confusion_matrix.png` | classification | Results 主表附近 |
| ROC curve | `uploads/logs/analysis/{task_id}/charts/roc_curve.png` | binary / OvR multi-class | Results 主表附近 |
| Loss curve | `uploads/logs/analysis/{task_id}/charts/loss_curve.png` | 所有 | Method 末尾或 Supplementary |
| KM curve | `uploads/logs/analysis/{task_id}/charts/km_curve.png` | survival | Results 主图位 |

**额外可以即时合成的图**（zarr 数据 + 简单脚本）：

| 图 | 数据来源 | 现存？ |
|----|----------|--------|
| 切片级 attention heatmap overlay | zarr `attention/{wsi}` + `patch_coords/{wsi_id}.h5` + WSI thumbnail | ✅ Heatmap API 已有，[`gateway/routes/heatmap.py`] |
| Grad-CAM overlay | zarr `cam/{wsi}` | ✅ 数据有，前端 ResultsViewer 已展示 |
| 分割 mask overlay | zarr `pred_mask/{wsi}` | ✅ 数据有 |
| Top-k attended patches | zarr `attention/{wsi}` argsort + 切片 thumbnail crop | ⚠️ 数据有但需要新写脚本 |
| Per-fold ROC overlay | 需要从 zarr 重新算 fold-wise probs | ❌ 当前只存了 metrics_kfold.json，没有 fold-wise raw probs ROC（详见 §5） |
| Calibration plot (reliability diagram) | 需要从 zarr `probs` + ground truth 现算 | ❌ 当前没存（详见 §5） |

### 2.5 Results 章节 — 补充表（Supplementary）

| 内容 | 数据来源 |
|------|----------|
| 每张 WSI 的预测明细 | `analysis/results.json` 或 `ai_results` 表 |
| Top-N 自信 / 错误样本 | 从 `results.json` 按 `confidence` 排序 |
| 每折所有指标 | `analysis/metrics_kfold.json` `fold_0/1/.../K` |
| 完整 confusion matrix（数字版） | `summary.json.confusion_matrix` |
| Per-WSI risk score 分布（survival） | zarr `results/{wsi}.risk_score` |

### 2.6 External Validation（如果跑了）

外部验证是一个 `task_id` 以 `extval_` 开头的 TrainingTask，**和正常推断完全相同的 zarr + analysis 输出结构**。所以 paper 里"在外部数据集 X 上的泛化"段落可以**直接复用上面的所有 Results 章节模板**——只是 `task_id` 换成 extval 那个。

---

## 3. 按 4 种任务类型梳理"完整产物清单"

把上面的素材按任务类型重新切一刀，方便 paper-gen agent 在第一步就明确"这个 task 我能拿到什么"。

### 3.1 WSI Classification

```
完整产物 = {
  config: {
    preprocessing_config,                # tile_size, stride, feature_extractor...
    model_config,                        # aggregator, lr, epochs, optimizer...
    classes,                             # ["HSIL","LSIL","Normal"]
    feature_extractor,                   # "CONCH" / "UNI" / "ResNet50" / ...
    aggregator,                          # "ABMIL" / "CLAM" / "TransMIL" / ...
  },
  cohort: {
    splits: {train: N1, val: N2, test: N3},   # 或 fold_0..K
    demographics: {age, gender, source 分布},
    label_distribution: {per-split per-class},
  },
  per_wsi: [
    {                                    # 每张测试集 WSI 一条
      wsi_id, filename, case_id, label,
      pred, probs, confidence, correct,
      attention_weights: array,          # 从 zarr 读
      fold_key,                          # K-fold 时
    },
    ...
  ],
  metrics: {
    overall: {accuracy, macro_p/r/f1/specificity, weighted_kappa, auc},
    per_class: {class_i: {tp, fp, fn, tn, p, r, f1, specificity, support}},
    confusion_matrix,
    bootstrap_ci: {metric: {ci_lower, ci_upper}},   # 如果跑了
    kfold_aggregated: {metric: {mean, std}},        # 如果是 K-fold
  },
  charts: [confusion_matrix.png, roc_curve.png, loss_curve.png],
  training_curve: {
    epochs: [...], train_loss: [...], val_loss: [...]   # 从 training_logs 重建
  },
}
```

### 3.2 WSI Survival

和 classification 共享 config / cohort / charts / training_curve 部分，主要差别：

```
{
  per_wsi: [
    {
      wsi_id, case_id,
      risk_score, event_time, event_status,    # 真值 + 预测
      surv_probs: [...], bin_edges: [...],     # 时间分箱生存概率
      attention_weights: array,
      fold_key,
    },
  ],
  metrics: {
    c_index, integrated_brier_score,
    bootstrap_ci, kfold_aggregated,
  },
  charts: [km_curve.png, loss_curve.png],
}
```

> **生存任务的特别价值**：可以**自动做 Cox 回归式风险分层**——按 `risk_score` 中位数（或三分位）切分高/低/中风险组，再做 KM curve。**这是临床论文最常见的图之一**，但 PathLab 当前可能没自动算分层后的 log-rank p-value——需要 paper-gen agent 自己接 lifelines 算。

### 3.3 Patch Classification

和 WSI classification 类似，差别：
- 没有 attention（聚合是 patch 级，不是 MIL）；改成 **Grad-CAM** 存在 zarr `cam/`
- Per-WSI 改成 per-patch
- `wsi_slides.data_type = 'patch'`

### 3.4 Patch Segmentation

```
{
  config: {
    preprocessing_config, model_config (含 backbone / decoder),
    classes,
  },
  ground_truth: {                        # COCO 格式存在 DB
    annotations: { images, annotations, categories }
  },
  per_image: [
    {
      image_id,
      pred_mask: array (H, W),           # zarr `pred_mask/`
      cam: array (H, W),                 # zarr `cam/`
      metrics: { class_i: {iou, dice}, miou }
    },
  ],
  metrics: {
    overall: {accuracy, miou, macro_f1},
    per_class: {class_i: {iou, dice, p, r, f1}},
  },
  charts: [loss_curve.png],              # 通常没有 confusion matrix / ROC
}
```

> **分割任务的 Figure 主图是定性可视化**：选若干样例，并排展示 [WSI / GT mask / pred mask / Grad-CAM]。这个 paper-gen agent 需要自动从 zarr `pred_mask` 拼合，**当前 PathLab 没有现成的 4-panel 拼图脚本**。

---

## 4. 写一个 PaperOrchestra 风格的 `experimental_log.md`

把上面所有信息按 PaperOrchestra (App. D.3) 的格式整理出来，**就是 paper-gen agent 的输入**。下面是一个具体的伪示例（用 WSI classification 任务）：

```markdown
# Experimental Log — task_id: train-20260504-abc123

## Setup
- Task type: wsi_classification
- Aggregation level: file
- Feature extractor: CONCH (frozen)
- Aggregator: ABMIL
- Tile size: 256×256, stride: 256, mpp filter: 0.5
- Optimizer: AdamW, lr=1e-4, weight_decay=0.05
- Epochs: 50, batch_size: 1 (slide-level)
- Train/val/test split: 320 / 80 / 100 WSIs
- Hardware: 1× A100, training time: 3h 42m

## Cohort (Table 1 candidate)
| Split | N WSIs | N cases | Age (mean±std) | Female | HSIL | LSIL | Normal |
|-------|-------:|--------:|---------------:|-------:|-----:|-----:|-------:|
| train | 320 | 287 | 52.3 ± 12.1 | 100% | 110 | 95 | 115 |
| val   | 80  | 73  | 51.8 ± 11.7 | 100% | 28  | 25  | 27  |
| test  | 100 | 92  | 53.1 ± 12.8 | 100% | 35  | 30  | 35  |

## Results — Main Table
| Metric              |  Test   | 95% CI         |
|---------------------|--------:|----------------|
| Accuracy            | 0.892   | [0.840, 0.940] |
| Macro F1            | 0.881   | [0.827, 0.928] |
| Macro AUC (OvR)     | 0.962   | [0.938, 0.981] |
| Weighted Kappa      | 0.832   | [0.760, 0.895] |

### Per-class (Test)
| Class  | P     | R     | F1    | Specificity | Support |
|--------|------:|------:|------:|------------:|--------:|
| HSIL   | 0.91  | 0.94  | 0.92  | 0.95        | 35      |
| LSIL   | 0.86  | 0.83  | 0.84  | 0.93        | 30      |
| Normal | 0.89  | 0.89  | 0.89  | 0.94        | 35      |

### Confusion Matrix
[[33 1 1] [3 25 2] [1 3 31]]

## Qualitative observations
- Top attention 的 patch 高度集中于鳞状上皮基底层 / 异型核区域
- 误分类多发生在 LSIL ↔ HSIL 边界
- 当病灶 < 1% 切片面积时性能下降明显（confidence < 0.6 的样本占测试集 7%）

## Figures (paths)
- figures/confusion_matrix.png  ← uploads/logs/analysis/{task_id}/charts/confusion_matrix.png
- figures/roc_curve.png         ← uploads/logs/analysis/{task_id}/charts/roc_curve.png
- figures/loss_curve.png        ← uploads/logs/analysis/{task_id}/charts/loss_curve.png
- figures/heatmap_top.png       ← 需要从 zarr attention 重建（heatmap API）
```

> 这套 markdown 和 PaperOrchestra 期望的 `experimental_log.md` 格式高度兼容——agent 只需要把 PathLab 数据按这个 schema 序列化就行。

---

## 5. 关键 gap：paper 需要但 PathLab 当前没有

按"补全成本"从低到高排：

### 5.1 补全成本低（agent 内部现算即可）

| Gap | 说明 | 补全方式 |
|-----|------|----------|
| **C-index 95% CI** | summary.json 里有 c_index 但 bootstrap_ci.json 是否覆盖未确认 | agent 用 lifelines / scipy 自己 bootstrap 1000 次 |
| **Per-fold ROC overlay** | metrics_kfold.json 只存了聚合指标，没存 fold-wise 概率 | agent 直接读 zarr `results/{wsi}/` 用 `fold_key` 分组重画 |
| **风险分层 KM curve + log-rank p** | 当前只画总体 KM | agent 读 zarr 的 risk_score → 中位数切分 → lifelines `KaplanMeierFitter` + `logrank_test` |
| **Calibration plot (reliability diagram)** | 没存 | agent 读 `analysis/results.json` 的 probs + label → bin 后画 |
| **Top-k attended patches 拼图** | 数据全在 zarr | agent 读 attention → argsort → 用 preprocessing API 取 patch thumbnail 拼 |
| **分割定性可视化 4-panel** | 数据全在 zarr | agent 读 pred_mask + 用 preprocessing API 取 WSI thumbnail + COCO GT |
| **Patient-level demographics 聚合表** | wsi_slides 表里都有原始字段 | agent 写 SQL agg 即可 |

> 这一类 gap **不需要改 PathLab**，paper-gen agent 自己解决。

### 5.2 补全成本中等（需要在 PathLab 加保存逻辑）

| Gap | 影响的 paper 位置 | 建议 |
|-----|-------------------|------|
| **Per-epoch 完整 train/val 曲线** | Method 末尾 / Supplementary loss curve | training_logs 现在有 epoch 字段但需要确认能完整重建训练曲线；如不能，agent 应该接受"只能从 metrics.json 拿到 best ckpt 单点"的现状 |
| **Per-fold loss curve** | Supplementary | 需要 trainer 在 K-fold 模式下分 fold 写 log |
| **Failure case 自动标记** | Discussion / Limitations | 简单做法：在 analysis 阶段把 `confidence < 0.5` 或 `correct == false` 的 wsi_id 列入一个 `failure_cases.json` |
| **Per-stratum 子组指标** | "性能在不同年龄/性别/器官上" | 需要 analysis 路由支持按 `wsi_slides` 字段做 group-by 重算指标 |

### 5.3 补全成本高（架构层面欠缺，paper 第一版可以先不要）

| Gap | 说明 |
|-----|------|
| **Ablation 自动比较** | PathLab 一次只跑一个 task；想要"我们做了 ablation 1/2/3"必须用户**自己手动跑多次 task 然后告诉 agent 哪几个是同一组 ablation**。这是产品功能层面的缺失，不是数据层面 |
| **Multiple model comparison（同任务不同 backbone）** | 同上——属于 task 间比较，需要 agent 自己接受多个 task_id 列表作为输入 |
| **Bayesian uncertainty / MC Dropout** | 模型本身需要修改才能产出，paper-gen agent 只能跳过这部分 |
| **Subgroup fairness（AUC by age/gender）** | 同 §5.2 的 per-stratum，需要新分析路由 |

---

## 6. 给 paper-gen agent 的输入接口建议

基于上面的盘点，建议 agent 第一步是一个数据 gathering 函数：

```python
def gather_experiment_artifacts(
    task_ids: list[str],              # 一个或多个 task；多个用于 ablation/comparison
    include_external_validation: bool = True,
    bootstrap_n: int = 1000,          # agent 自己补的 CI 用
) -> ExperimentBundle:
    """
    Returns a single bundle that contains everything paper-gen needs.
    """
```

`ExperimentBundle` 的 schema 建议：

```python
@dataclass
class ExperimentBundle:
    # 元信息
    task_ids: list[str]
    task_type: Literal["wsi_classification", "wsi_survival", "patch_classification", "patch_segmentation"]
    primary_task_id: str              # ablation 时这是"主"那个

    # Method 章节素材
    config: dict                      # preprocessing_config + model_config + classes 合并
    feature_extractor: str
    aggregator: str
    training_runtime_seconds: float

    # Dataset 章节素材
    cohort: CohortStats               # split / demographics / label distribution
    coco_ground_truth: dict | None    # 仅 segmentation

    # Results 主体
    per_sample_results: list[SampleResult]   # 从 analysis/results.json + zarr
    metrics: MetricsBundle                    # summary.json + bootstrap_ci.json + kfold
    confusion_matrix: np.ndarray | None       # classification only
    survival_data: SurvivalBundle | None      # survival only

    # Figures（已存在的 + 即时生成的）
    existing_charts: dict[str, Path]          # confusion / roc / loss / km PNG 路径
    derived_charts: dict[str, np.ndarray | Path]  # agent 自己生成的：calibration / per-fold-ROC / 4-panel ...

    # Heatmap 数据（按需读取）
    attention_data: dict[str, np.ndarray]    # wsi_id → attention (lazy)
    cam_data: dict[str, np.ndarray]          # wsi_id → Grad-CAM (lazy)
    pred_masks: dict[str, np.ndarray]        # wsi_id → mask (lazy, segmentation)

    # External validation (如果有)
    external_validation: ExperimentBundle | None    # 递归同结构

    # Failure cases（agent 自己挑的）
    failure_cases: list[SampleResult]
```

**实现要点**：
- 大数组（attention / cam / pred_mask）**lazy load**——访问时再从 zarr 读，避免 bundle 大到塞不下 prompt。
- 所有数字字段**确保从 source-of-truth 读**：metric 必须从 `summary.json` / `metrics_kfold.json` / `bootstrap_ci.json`，**绝不允许 LLM 重新算或近似**。这就是 PaperOrchestra 的"数字从 log 拷贝、不让 LLM 算"原则。
- Schema 字段命名直接对齐 paper section——让 agent 的 prompt 能直接 `bundle.cohort.demographics.female_pct` 这样取。

---

## 7. 第一版 paper-gen agent 的最小可行集

参考 PaperOrchestra 5-agent 架构，按 PathLab 现状做的优先级建议：

### Phase 1（第一版，2 周可做）

只支持 **WSI classification + 单 task（无 ablation）+ 无外部验证** 的场景：

**输入**：
- `task_id`（已完成的 training+analysis）
- 用户写的 `idea.md`（动机、方法描述、结论假设）
- 投稿模板（CVPR / MICCAI / Nature CommMed）

**复用 PathLab 已有的数据**：
- ✅ Method：从 `training_tasks.preprocessing_config / model_config` 直接生成
- ✅ Dataset：从 `wsi_slides` SQL 聚合 + `dataset_stats`
- ✅ Main metrics：`summary.json` + `bootstrap_ci.json`
- ✅ Figures：confusion matrix / ROC / loss curve PNG 直接 includegraphics
- ⚠️ Heatmap 主图：调 PathLab 的 heatmap API 生成 1-2 张展示

**Agent 自己加的**（PathLab 没存的）：
- Calibration plot（agent 内部 matplotlib）
- Top-k attention patches 拼图（调 preprocessing API）
- Failure cases 列表（按 confidence 排序）
- Literature review（Semantic Scholar API + Levenshtein 校验，仿 PaperOrchestra）

**故意不支持**：
- ❌ Ablation（用户得自己提供多个 task_id 的 mapping 才行——v2 再做）
- ❌ Cross-task comparison（同上）
- ❌ Per-stratum 子组分析（需要改 analysis 路由——v2）

### Phase 2 扩展点

按价值排序：
1. 加生存任务（核心方法已经有，主要是模板差异）
2. 加 ablation/comparison（关键是 task_id 列表的语义打标——是 backbone 对比？还是 hyperparam sweep？）
3. 加 per-stratum 子组分析（需要在 PathLab 后端加个 analysis 路由）
4. 加分割任务（4-panel 拼图脚本 + 分割 paper 模板）

---

## 8. 实施清单（动手前的 checklist）

在 `paper-gen/` 目录下开第一版前，按这个顺序做：

- [ ] **跑通一次完整 PathLab WSI classification 任务**，把上面提到的所有 artifact 路径**亲自验证一遍存在**（特别是 zarr 内部结构和 analysis JSON 的具体字段）——避免 agent 写到一半发现某字段名不对。
- [ ] **写 `gather_experiment_artifacts()` 函数**（§6）的最小版本，只覆盖 WSI classification 单 task。先确保 `bundle.metrics.accuracy` 能从代码取到正确数字。
- [ ] **写一个"实验日志 markdown 渲染器"**：`bundle → experimental_log.md`，验证它符合 PaperOrchestra App. D.3 格式。
- [ ] **写 4 个补图脚本**：calibration / per-fold ROC / top-k attention / failure cases。
- [ ] **复用 [Ar9av/PaperOrchestra](https://github.com/Ar9av/PaperOrchestra) 的 5 个 agent skill**，把 inputs 接口对齐到 `bundle`。
- [ ] **把 `literature-review-agent` 的 Semantic Scholar 校验链原封不动搬过来**（Levenshtein + 时间截断 + ≥ 90% 强制引用率）。
- [ ] **为病理领域接 PubMed / 临床指南检索**——这是 PathLab 场景独有的，PaperOrchestra 默认不覆盖。

---

## 9. 关键文件索引（动手时直接跳）

| 关心什么 | 文件 |
|----------|------|
| 训练任务表 schema | `pathlab/pathlab-client/server/backend/database/models.py:745-830` |
| 训好的模型表 schema | `pathlab/pathlab-client/server/backend/database/models.py:863-938` |
| 推断结果表 schema | `pathlab/pathlab-client/server/backend/database/models.py:436-485` |
| WSI 元信息表 schema | `pathlab/pathlab-client/server/backend/database/models.py:192-372` |
| 训练日志表 schema | `pathlab/pathlab-client/server/backend/database/models.py:941-995` |
| 分割标注（COCO）schema | `pathlab/pathlab-client/server/backend/database/models.py:1067-1145` |
| Zarr 结果存储（25 KB 全是这个的实现） | `pathlab/pathlab-client/server/backend/ai/result_store.py` |
| 各任务 trainer | `pathlab/pathlab-client/server/backend/ai/tasks/{wsi_classification,wsi_survival,patch_classification,patch_segmentation}/trainer.py` |
| 生存指标计算 | `pathlab/pathlab-client/server/backend/ai/tasks/wsi_survival/losses.py` |
| K-fold 指标聚合 | `pathlab/pathlab-client/server/backend/ai/tasks/training_utils.py:156-250` |
| 分析 / chart 生成路由 | `pathlab/pathlab-client/server/gateway/routes/analysis_metrics.py` |
| 外部验证分析路由 | `pathlab/pathlab-client/server/gateway/routes/external_validation_analysis.py` |
| Heatmap API | `pathlab/pathlab-client/server/gateway/routes/heatmap.py` |
| 现有 export（CSV/JSON/MD） | `pathlab/pathlab-client/src/renderer/src/pages/ReportGeneratorPage.tsx:43-100` |
| 现有 results 展示 | `pathlab/pathlab-client/src/renderer/src/pages/ResultsViewerPage.tsx:20-140` |

---

## 10. 引用本文的位置 / 关联文档

- [`paper-generation-survey.md`](paper-generation-survey.md) — 论文自动生成的全景综述（PathLab 借鉴部分指向 C 类）
- [`paperorchestra.md`](paperorchestra.md) — PaperOrchestra 详解（特别是 §11 PathLab 5-agent 重映射，本文是它的"输入侧"详化）
- [`llm4papers.md`](llm4papers.md) — 最细颗粒度 LLM 写作辅助参考实现
