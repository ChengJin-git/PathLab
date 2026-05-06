# Phase 05 — Outline Agent

## 目标

实现 PaperOrchestra Step 1：Outline Agent。尽量保持 PaperOrchestra 原始 schema：`plotting_plan`、`macro_lit_search`、`micro_lit_clusters`、`section_plan`。PathLab 的 `claim_plan` 只能作为 extension，不能替代原始字段。

## 输入

```text
inputs/idea.md
evidence/experimental_log.md
evidence/evidence_public.json
  - topic: Phase 03 从 user_idea topic summary + locked evidence 得到的 paper-topic hint
figures/manifest.json
tables/manifest.json
templates/{template}/style.json
conference_guidelines.md
```

## 输出

```text
drafts/outline.json
```

## 代码范围

```text
paper_generation/agents/outline_agent.py
paper_generation/llm/prompts/outline.md
```

## Prompt 来源

- Base：PaperOrchestra Appendix F.1 Outline prompt。
- PathLab diff：注入 `style.json`、PHI 限制、PathLab `pathlab_extensions` 字段，以及 `evidence_public.topic` 作为 topic / related-work query 的主信号。
- Prompt 文件 frontmatter 必须写：`source_design: PaperOrchestra App. F.1`。

## 输出 schema

```json
{
  "plotting_plan": [],
  "macro_lit_search": [],
  "micro_lit_clusters": [],
  "section_plan": [],
  "pathlab_extensions": {
    "claim_plan": [],
    "table_plan": [],
    "guard_requirements": []
  }
}
```

## 实施步骤

1. 定义 `OutlineSchema` Pydantic model。
2. 编写 prompt，要求保留 PaperOrchestra 原始字段。
3. Prompt 明确要求：`evidence_public.topic` / `experimental_log.md` 的 Topic Context 用于确定 disease、endpoint、modality、method family 和 literature query；但实验事实仍只能来自 locked evidence。
4. 如果 `topic.needs_confirmation=true`，outline 和 lit search query 必须保持保守，不强行写死未确认 disease / endpoint。
5. 调 LLM 生成 outline。
6. 做 schema validation。
7. 做 conservative repair：只允许补缺失字段，不允许自由重写 evidence。
8. 将 outline 写入 `drafts/outline.json`，登记 manifest。

## 验收标准

- `outline.json` 必含 4 个 PaperOrchestra 原始字段。
- `plotting_plan` 能驱动 Plotting Agent。
- `macro_lit_search` / `micro_lit_clusters` 能驱动 Literature Review Agent。
- `macro_lit_search` / `micro_lit_clusters` 必须优先覆盖 `evidence_public.topic` 中确认的 disease、endpoint、modality 和 method family。
- `section_plan` 中有 citation hints 和 locked block 引用计划。
- 输出不含 PHI，不含 raw path，不含未脱敏 case_id。

## 风险

- 不要把 claim_plan 当 outline 主体。
- 不要把未确认 topic 写成确定结论；`needs_confirmation=true` 时必须让用户或后续 UI 介入确认。
- 不要让 Outline Agent 发明实验结果或新增不存在的 task。
- 不要在这个阶段做文献真实性判断；真实性在 Literature Review Agent 完成。
