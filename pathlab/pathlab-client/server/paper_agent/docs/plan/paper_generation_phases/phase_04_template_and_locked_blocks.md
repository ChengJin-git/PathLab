# Phase 04 — Templates / Locked Blocks

## 目标

建立 MICCAI 和 Nature Scientific Reports 两套 LaTeX 模板，并实现 deterministic locked blocks。locked blocks 是 Section Writing Agent 的事实锁工具，不是第 6 个 agent。

## 输入

```text
evidence/evidence_lock.private.json
evidence/evidence_public.json
tables/*.tex
figures/manifest.json
template/style.json
```

## 输出

```text
locked_blocks/
├── dataset_block.tex
├── method_block.tex
├── results_block.tex
├── external_block.tex
└── metrics_macros.tex

templates/
├── miccai/
└── nature_scientific_reports/
```

## 代码范围

```text
pathlab_paper_agent/renderers/
├── locked_block_renderer.py
└── template_renderer.py

paper_generation/templates/
├── registry.json
├── miccai/
└── nature_scientific_reports/
```

## 实施步骤

1. 建 `templates/registry.json`。
2. 建 `templates/miccai/`：`llncs.cls`、`splncs04.bst`、`main.tex.j2`、`sections/*.tex.j2`、`style.json`。
3. 建 `templates/nature_scientific_reports/`：`main.tex.j2`、`sections/*.tex.j2`、`style.json`。
4. `locked_block_renderer.py` 生成 dataset / method / results / external blocks。
5. `metrics_macros.tex` 或 metric placeholder map 从 private lock 确定性生成。
6. `template_renderer.py` 支持按 template id 组装 paper shell。
7. 用 stub sections / stub locked blocks 跑通两个模板的 `latexmk`。

## 模板差异

| 模板 | Section 顺序 | 特殊要求 |
|---|---|---|
| MICCAI | abstract → intro → related work → methods → experiments → results → discussion → conclusion | LNCS、双盲、页数约束、refs 数量较少 |
| Nature SR | abstract → intro(+RW) → results → discussion → methods → data availability → author contributions | Methods 后置、单盲、Data Availability 必须有 |

## 验收标准

- 两个模板都能用 stub 内容编译出 PDF。
- locked blocks 100% deterministic，L1/L2 可 byte-identical 测试。
- locked blocks 中的数字来自 `evidence_lock.private.json`，final/export 中只保留脱敏 paper-facing blocks。
- Section Writing Agent 后续只能 `\input{locked_blocks/...}` 或使用 `{{m:...}}`，不能自由改写事实。

## 风险

- 不要把 private evidence 放进 final locked blocks。
- 不要让模板假设同一种 section ordering。
- 不要等 LLM 完成后才做 LaTeX 编译，模板环境要先测通。
