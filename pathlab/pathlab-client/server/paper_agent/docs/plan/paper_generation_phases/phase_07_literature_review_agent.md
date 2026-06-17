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

## BibTeX 生成修复计划

> 2026-05-13 调研结论：不要让 LLM 直接生成 `.bib`。Zotero / Better BibTeX /
> JabRef / Citation.js / Manubot 的共同模式是先维护结构化引用 metadata，再用
> deterministic exporter 输出 BibTeX；有 DOI 时可以用 Crossref / DOI content
> negotiation 获取 canonical BibTeX，但必须缓存并保留 PathLab 自己的稳定 citekey。

### 当前实现问题

- `bib_generator.py` 当前总是输出 `@article`，会议论文会被错误写成 journal article。
- `venue` 总是映射为 `journal`，对 MICCAI / CVPR / NeurIPS / ICML 等会议应改成
  `booktitle`。
- 统一转义 `{` / `}` 会破坏 title capitalization protection，例如 `{CRC}`、
  `{MSI}`、`{H&E}`、`{WSI}`。
- `url` / `doi` 目前和普通文本走同一套 LaTeX escape，容易破坏 identifier。
- `CitationCandidate.raw` 中的 OpenAlex / Semantic Scholar / PubMed metadata 转成
  `CitationReference` 后大多丢失，BibTeX 阶段只能靠 `venue` 猜类型和字段。

### Phase 1：本地 renderer 先稳定

- 改造 `citations/bib_generator.py`，让 renderer deterministic、无网络依赖。
- 推断 BibTeX entry type：
  - PubMed / journal-like venue：`@article` + `journal`。
  - MICCAI / CVPR / ICCV / ECCV / NeurIPS / ICML / ICLR / AAAI / IJCAI 等：
    `@inproceedings` + `booktitle`。
  - arXiv / preprint：`@misc` 或 `@article` + `eprint` / `archivePrefix`。
- 字段输出按类型选择：`journal` 只给 article，`booktitle` 只给 conference。
- `url` / `doi` 使用专门 escaping；普通文本保留 balanced braces。
- title 自动保护医学和 ML 常见大写词：`CRC`、`MSI`、`MSS`、`H&E`、`WSI`、`AI`
  等，避免 BibTeX style 把大小写降掉。

### Phase 2：补齐 metadata 流向

- 扩展 `CitationReference` 或新增 normalized bib metadata 字段：
  `entry_type`、`journal`、`booktitle`、`volume`、`number`、`pages`、`publisher`、
  `arxiv_id`、`publication_type`。
- 在 `semantic_scholar.py`、`pubmed.py`、`openalex.py` 中尽量提取已有字段。
- 从 `CitationCandidate` 到 `CitationReference` 时不要丢掉 BibTeX 渲染所需字段。
- `selected_refs.json` 继续作为引用 truth source；`refs.bib` 只能从它派生。

### Phase 3：测试和验证

- 在 `tests/citations/` 增加 BibTeX renderer 测试：
  - journal reference 输出 `@article` + `journal`。
  - MICCAI / CVPR reference 输出 `@inproceedings` + `booktitle`。
  - `CRC` / `MSI` / `H&E` / `WSI` title 大小写被保护。
  - existing braces 不被错误 escape。
  - DOI / URL 不被错误转义。
  - empty refs 输出安全注释。
- 如果后续允许增加轻量依赖，可用 `bibtexparser` 或 `pybtex` 做 parse
  validation；否则先用单测 + LaTeX compile guard 兜底。

### Phase 4：DOI canonical BibTeX（二期）

- 有 DOI 时请求 `https://doi.org/{doi}`，header 使用
  `Accept: application/x-bibtex`。
- 成功后缓存 canonical BibTeX，并把 entry key 替换成 PathLab stable key。
- 请求失败、格式不合法或 metadata 不完整时 fallback 到本地 renderer。
- 该步骤不能阻塞本地生成，也不能让 compile 阶段临时依赖联网。

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
