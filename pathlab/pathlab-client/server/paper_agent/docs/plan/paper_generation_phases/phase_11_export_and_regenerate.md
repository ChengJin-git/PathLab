# Phase 11 — Section Regenerate / Final Render / Export

## 目标

实现用户可用的最终交付：section-level regenerate、final template render、PDF 编译、dependency-closed ZIP export。

## 输入

```text
drafts/sections/*.tex
locked_blocks/*.tex
tables/*.tex
figures/*
citations/refs.bib
templates/{template}/
validation/*.json
```

## 输出

```text
final/{template}/
├── main.tex
├── sections/*.tex
├── locked_blocks/*.tex
├── tables/*.tex
├── refs.bib
├── figures/*
├── *.cls / *.bst
└── main.pdf

exports/{template}_bundle.zip
```

## 代码范围

```text
pathlab_paper_agent/renderers/
├── template_renderer.py
├── latex_compiler.py
└── zip_exporter.py

pathlab_paper_agent/api/routes.py
```

## 实施步骤

1. `template_renderer.py` 把 sections / locked blocks / refs / figures 复制到 `final/{template}/`。
2. 按 template style 渲染 `main.tex`。
3. `latex_compiler.py` 在隔离环境中跑 `latexmk`。
4. `zip_exporter.py` 打 dependency-closed bundle：`main.tex`、`sections/`、`locked_blocks/`、`tables/`、`refs.bib`、`figures/`、模板文件。
5. ZIP 打包后在临时目录解压并 dry-run compile。
6. 成功后开放 `GET /papers/{id}/export?template=...`。
7. 实现 `POST /papers/{id}/sections/{section}/regenerate`。

## Section-level regenerate

- 只能重生 public / narrative section。
- 默认允许：abstract、introduction、related_work、discussion、conclusion。
- 默认禁止直接重生：locked_blocks、private evidence。
- 重生后必须重跑 metric / claim / citation / latex / figure-table guard。
- 如果重生需要新增引用，必须回到 Literature Review Agent。

## Export 闭包规则

- ZIP 不包含 `evidence_lock.private.json`。
- ZIP 不包含 `drafts/intro_rw_draft/`。
- ZIP 不包含 raw prompt / raw response。
- ZIP 解压后必须能独立编译。
- `locked_blocks/` 是脱敏 paper-facing 版本。

## 验收标准

- MICCAI bundle 独立编译通过。
- Nature SR bundle 独立编译通过。
- `GET export` 返回 ZIP，而不是运行时目录裸路径。
- section regenerate 不破坏 required cites 和 metric placeholders。

## 风险

- final 目录缺 sections / locked_blocks 会导致 ZIP 无法编译。
- regenerate 可能引入新引用，必须回 citation verification。
- export 不能打包 private evidence。
