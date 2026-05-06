# Phase 03 — PHI Scrub / Evidence Bundle

## 目标

把 Phase 02 的 raw collected evidence 转成 paper generation 的事实源：`experimental_log.md`、`evidence_lock.private.json`、`evidence_public.json`、tables 和 figures manifest。这个阶段是可信写作的地基。

## 输入

```text
evidence/raw_collected/*.json
inputs/idea.md
source task role mapping
```

`inputs/idea.md` 可以承载一个可选的、前端/调用方整理过的短对话 topic summary。不要传 raw chat；推荐用结构化块：

```md
[TOPIC_CONTEXT]
{
  "disease": "colorectal cancer",
  "clinical_endpoint": "microsatellite instability status",
  "prediction_target": "MSI vs MSS",
  "modality": "H&E whole-slide images",
  "task_type": "wsi_classification",
  "method_family": "multiple instance learning",
  "classes": ["MSI", "MSS"],
  "confidence": "high",
  "sources": ["pre_training_chat_summary"]
}
[/TOPIC_CONTEXT]
```

如果没有该块，Phase 03 只从 task / dataset / model evidence 做保守 topic hint，并标记 `needs_confirmation=true`。

## 输出

```text
evidence/
├── experimental_log.md
├── evidence_lock.private.json
├── evidence_public.json
├── topic_summary.public.json
├── dataset_summary.public.json
├── model_summary.public.json
└── analysis_summary.public.json

tables/
├── manifest.json
├── table_1_dataset.tex
├── table_2_main_results.tex
├── table_3_per_class.tex
├── table_4_ablation.tex
└── table_5_external_validation.tex

figures/
└── manifest.json
```

## 代码范围

```text
paper_generation/
├── phi_scrub.py
└── evidence/
    ├── experimental_log.py
    ├── evidence_lock.py
    ├── evidence_public.py
    ├── tables.py
    └── figures_manifest.py
```

## 实施步骤

1. `phi_scrub.py`：脱敏 case_id、文件名、机构、真实日期、患者标识符。
2. `evidence_lock.py`：生成 `evidence_lock.private.json`，保留真值和 provenance，仅后端 validator 可读。
3. `evidence_public.py`：从 private lock 派生脱敏 public evidence。
4. `topic.py`：从 `inputs/idea.md` 的 `[TOPIC_CONTEXT]` 或 Confirmed Topic Markdown 中解析 topic intent，并与 task / dataset / model evidence hints 合并；冲突时记录 `conflicts` 和 `needs_confirmation=true`。
5. `experimental_log.py`：生成 PaperOrchestra App. D.3 风格实验日志，并包含脱敏后的 `Topic Context` 小节。
6. `tables.py`：生成 cohort / split / main metric / per-class / ablation / external validation LaTeX 表。
7. `figures_manifest.py`：生成 figure manifest，标记 `ready` / `pending_generation` / `generated_by_paperbanana` / `requires_user_revision`。
8. 在 `manifest.json` 中为每个 artifact 标记 `visibility`。

## Private / Public 规则

- LLM 只能读：`experimental_log.md`、`evidence_public.json`、`tables/*.tex`、`figures/manifest.json`。
- `evidence_public.json.topic` 只能包含脱敏后的 topic intent / hints，不能包含 raw chat、message id、用户隐私或未脱敏路径。
- 后端 validator 才能读：`evidence_lock.private.json`。
- API 下载默认禁止 private artifact。
- export ZIP 永远不包含 private evidence。

## 验收标准

- `evidence_lock.private.json` 每个 metric / count / identifier 都有 provenance。
- `evidence_public.json` 不含真实 case_id、真实机构、原始路径、完整日期。
- `topic_summary.public.json` 能表达 disease / endpoint / modality / task_type / classes / confidence，并在冲突或缺失显式 topic 时标记 `needs_confirmation`。
- `experimental_log.md` 可单独给人阅读，并足够支持论文事实写作。
- `GET-files` 无法下载 private evidence。

## 风险

- PHI scrub 不完整会污染 LLM prompt。
- evidence_public 不能只是 private lock 改名，必须真正脱敏。
- private lock 不能进 ZIP / final / prompt / raw response。
