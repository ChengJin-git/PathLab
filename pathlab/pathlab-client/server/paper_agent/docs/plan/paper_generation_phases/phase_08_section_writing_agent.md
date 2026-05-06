# Phase 08 — Section Writing Agent

## 目标

实现 PaperOrchestra Step 4：Section Writing Agent。保留一次多模态 full-paper writing 的设计：读取 outline、figures、captions、refs、experimental log、intro/RW 草稿和 locked blocks，生成完整 `drafts/sections/*.tex`。

## 输入

```text
drafts/outline.json
drafts/intro_rw_draft/introduction.tex
drafts/intro_rw_draft/related_work.tex
citations/required_cites.json
citations/selected_refs.json
citations/refs.bib
evidence/experimental_log.md
locked_blocks/*.tex
tables/*.tex
figures/*.pdf|png
figures/captions.json
templates/{template}/style.json
```

## 输出

```text
drafts/sections/
├── abstract.tex
├── introduction.tex
├── related_work.tex
├── methods.tex
├── experiments.tex
├── results.tex
├── discussion.tex
└── conclusion.tex
```

## 代码范围

```text
paper_generation/agents/section_writing_agent.py
paper_generation/llm/prompts/section_writing.md
pathlab_paper_agent/renderers/metric_renderer.py
pathlab_paper_agent/renderers/citation_renderer.py
```

## Prompt 来源

- Base：PaperOrchestra Appendix F.4 Section Writing prompt。
- PathLab diff：locked blocks、metric placeholder、PHI blacklist、citation A2 contract。

## A2 契约

Section Writing Agent 可以润色 `intro_rw_draft` 的叙事，但必须遵守：

- 必须保留 `required_cites.json` 中的所有 `\cite{paperId}`。
- 不能新增 `selected_refs.json` 之外的引用；若需要新增，回到 Literature Review Agent verification。
- 最终编译和 guard 只看 `drafts/sections/`，不看 `drafts/intro_rw_draft/`。

## 写作约束

- 数字必须用 `{{m:metric_key}}` 或 locked block。
- 数据集 / 模型 / 实验设置必须 `\input{locked_blocks/...}`，不能自由改写。
- 引用先用 `[CITE:paperId]`，渲染阶段替换为 `\cite{paperId}`。
- 不得写 task_id / case_id / 真实路径 / 未脱敏机构名。
- 不得引入 `experimental_log.md` 之外的实验事实。

## 实施步骤

1. 组装多模态上下文：text + figures + captions + refs。
2. 调 LLM 生成所有 sections。
3. 做 schema / file completeness check。
4. `metric_renderer.py` 替换 metric placeholders。
5. `citation_renderer.py` 替换 cite placeholders。
6. 写 `drafts/sections/*.tex`。
7. 触发 Phase 09 guards。

## 验收标准

- 所有必需 section 都存在。
- `required_cites` 100% 保留。
- 所有 raw 数字要么来自 placeholder 替换，要么出现在 locked block。
- `methods.tex` / `results.tex` 包含 locked block 引用。
- 无 PHI 泄露。

## 风险

- LLM 可能删除引用、直接写真数字、改写 locked facts；这些必须由 post-processing 和 guards 拦住。
- Nature SR 和 MICCAI section ordering 不同，Section Writing Agent 必须读 `style.json`。
