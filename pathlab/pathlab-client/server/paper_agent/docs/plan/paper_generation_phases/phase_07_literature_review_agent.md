# Phase 07 — Literature Review Agent

## 目标

实现 PaperOrchestra Step 3：Literature Review Agent。它不是单纯查 BibTeX，而是完成检索、API 验证、引用选择、Intro / Related Work 草稿。PathLab 增强 PubMed 和医学/病理关键词，但保留 PaperOrchestra 的核心 citation guard 思路。

## 输入

```text
drafts/outline.json
  - macro_lit_search
  - micro_lit_clusters
  - section_plan[*].citation_hints
templates/{template}/style.json
submission_cutoff_date
```

## 输出

```text
citations/
├── discovery_pool.json
├── verified_pool.json
├── selected_refs.json
├── required_cites.json
├── refs.bib
└── coverage_report.json

drafts/intro_rw_draft/
├── introduction.tex
└── related_work.tex
```

## 代码范围

```text
paper_generation/agents/literature_review_agent.py
paper_generation/citations/
├── semantic_scholar.py
├── pubmed.py
├── verifier.py
├── ref_selector.py
├── bib_generator.py
├── coverage_gate.py
└── orphan_cite_gate.py
paper_generation/llm/prompts/literature_query.md
paper_generation/llm/prompts/literature_draft.md
```

## Prompt 来源

- Base：PaperOrchestra Appendix F.3 Literature Review prompt。
- PathLab diff：PubMed + OpenAlex query、病理关键词、template max refs、submission cutoff。

## Citation 三层结构

| 文件 | 含义 | 是否全部进正文 |
|---|---|---|
| `verified_pool.json` | S2/PubMed/OpenAlex 校验通过的可信候选池 | 否 |
| `selected_refs.json` | 本文最终选择的引用集合 | ≥90% 要出现在终稿正文 |
| `required_cites.json` | 每个 macro/micro cluster 的核心引用 | 100% 要出现在终稿正文 |

## 实施步骤

1. 用 LLM 从 outline 生成 search queries。
2. 对 macro / micro queries 做并发 discovery。
3. 对候选标题跑 S2 / PubMed / OpenAlex verification：Levenshtein ≥ 0.7、year cutoff、dedup by paperId / DOI / PMID / OpenAlex id。
4. 生成 `verified_pool.json`。
5. `ref_selector.py` 从 verified pool 中选择 `selected_refs` 和 `required_cites`。
6. `bib_generator.py` 生成 `refs.bib`。
7. LLM 起草 `drafts/intro_rw_draft/introduction.tex` 和 `related_work.tex`。
8. coverage gate 检查 selected / required 引用覆盖。

## 验收标准

- 不存在未 verified 的 bib entry。
- `refs.bib` 只来自 `selected_refs.json`。
- `selected_refs` ≥90% 被 intro/RW 或后续终稿正文引用。
- `required_cites` 100% 必须被 Section Writing Agent 保留。
- `drafts/intro_rw_draft/` 不参与编译，只作为 Section Writing Agent 输入素材。

## 风险

- 不要把 verified pool 全量写进 refs.bib。
- 不要让 Section Writing Agent 新增 selected_refs 之外的引用。
- PubMed / S2 rate limit 要区分 discovery 并发和 verification 串行。
