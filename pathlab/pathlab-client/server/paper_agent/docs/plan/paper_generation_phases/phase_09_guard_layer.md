# Phase 09 — Guard Layer

## 目标

实现 deterministic validation layer。Guard 不是最后装饰，而是 paper generation 的 hard gate：不通过则不得进入 final/export。

## 输入

```text
drafts/sections/*.tex
locked_blocks/*.tex
tables/*.tex
figures/manifest.json
citations/refs.bib
citations/selected_refs.json
citations/required_cites.json
evidence/evidence_lock.private.json
evidence/evidence_public.json
templates/{template}/style.json
```

## 输出

```text
validation/
├── metric_guard.json
├── claim_guard.json
├── identifier_guard.json
├── consistency_guard.json
├── citation_guard.json
├── figure_table_guard.json
├── latex_guard.json
├── latex_compile.log
└── warnings.md
```

## 代码范围

```text
paper_generation/validators/
├── metric_guard.py
├── claim_guard.py
├── identifier_guard.py
├── consistency_guard.py
├── citation_guard.py
├── latex_guard.py
└── figure_table_guard.py
```

## Guard 列表

| Guard | 检查 |
|---|---|
| Metric | 数字是否来自 private evidence / placeholder / locked block |
| Claim | 没有外部验证却写 external validation；没 baseline 却写 SOTA |
| Identifier | case_id、姓名、机构、真实路径泄露 |
| Consistency | val/test/external metric 串扰 |
| Citation | orphan cite、selected refs ≥90%、required cites 100% |
| LaTeX | braces/env/ref/cite，`latexmk` 编译通过 |
| Figure/Table | 正文引用、caption、manifest、LaTeX label 一致 |

## 实施步骤

1. `metric_guard.py`：placeholder-first，regex raw number 兜底。
2. `claim_guard.py`：关键词 + evidence flags。
3. `identifier_guard.py`：PHI / raw path / case_id 检测。
4. `consistency_guard.py`：按 split / analysis scope cross-check metric。
5. `citation_guard.py`：refs.bib selected-only、orphan-cite、required/selected coverage。
6. `latex_guard.py`：syntax sanity + `latexmk`。
7. `figure_table_guard.py`：manifest / label / caption /正文引用一致。
8. 聚合 `warnings.md`。

## 验收标准

- 每个 guard 都能独立运行。
- Guard report 机器可读，前端可展示。
- private evidence 只在后端 guard 内读取。
- 任一 hard gate fail 时 run 不进入 final/export。

## 风险

- 不要只做事后 regex；metric 应以 placeholder/render 机制预防为主。
- Citation coverage 要针对 selected_refs，不是 verified_pool。
- LaTeX 编译失败不能假装成功。
