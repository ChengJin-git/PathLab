# Phase 12 — Testing / Fixtures / Release Gate

## 目标

建立可回归的 paper generation 测试体系。核心不是“能跑一次”，而是每次改 collector、prompt、template、guard 后都知道有没有破坏可信性。

## Fixture 目录

```text
tests/paper_generation/fixtures/
├── wsi_classification_minimal/
├── wsi_classification_kfold/
├── wsi_classification_with_extval/
├── wsi_classification_ablation/
├── wsi_survival_minimal/
├── patch_classification_minimal/
└── patch_segmentation_minimal/
```

## 单个 fixture 结构

```text
wsi_classification_minimal/
├── task_record.json
├── trained_model.json
├── wsi_slides.csv
├── analysis/
│   ├── summary.json
│   ├── results.json
│   ├── bootstrap_ci.json
│   └── charts/*.png
└── golden/
    ├── deterministic/
    │   ├── experimental_log.md
    │   ├── evidence_lock.private.json
    │   ├── evidence_public.json
    │   ├── tables/*.tex
    │   └── locked_blocks/*.tex
    ├── outline_schema.json
    ├── citation_constraints.json
    └── section_constraints.json
```

## 测试层级

| 层 | 验证什么 | 是否调用 LLM |
|---|---|---|
| L1 | collector + evidence 与 golden 严格一致 | 否 |
| L2 | locked blocks + tables 与 golden 严格一致 | 否 |
| L3 | LaTeX 编译、ZIP 解压编译、PDF 元信息 | 否 |
| L4 | 5 agents 输出满足 schema / constraints / guards | 是 |

## 实施步骤

1. Phase 01-03 时先做 `wsi_classification_minimal`。
2. 每支持一个 task type，补一个 fixture。
3. `pytest` 实现 L1/L2/L3 自动测试。
4. L4 做手动或 nightly 测试，避免 CI 常规调用 LLM。
5. 每个 prompt 改动必须跑对应 L4。
6. 每个 template 改动必须跑 L3。
7. 每个 collector / evidence 改动必须跑 L1/L2。

## Release gate

v1 release 必须满足：

- 7 个 fixture 都能过 L1/L2/L3。
- 至少 `wsi_classification_minimal` 完整过 L4。
- 两个模板都能输出 dependency-closed ZIP。
- private evidence 无法通过 API 下载。
- selected refs / required cites coverage 全部达标。
- metric guard / PHI guard / latex guard 全部 hard gate 生效。

## 风险

- 没 fixture 就无法判断 prompt 和 template 改动是否退化。
- LLM 输出不稳定，所以 L4 只能测约束满足，不能 byte-identical。
- 测试 fixture 必须脱敏，不能把真实 PHI 放进 repo。
