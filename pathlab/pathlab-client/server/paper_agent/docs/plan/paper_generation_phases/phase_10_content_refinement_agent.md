# Phase 10 — Content Refinement Agent

## 目标

实现 PaperOrchestra Step 5：Content Refinement Agent。使用 AgentReview-style critic，最多 3 轮，单调收敛接受准则，不提升则物理 revert。

## 输入

```text
drafts/sections/*.tex
final draft main.tex
validation/*.json
validation/warnings.md
templates/{template}/style.json
```

## 输出

```text
drafts/sections/*.tex
# 可能被 refinement 修改后的版本

drafts/snapshots/
├── iter_0/sections/*.tex
├── iter_1/sections/*.tex
└── iter_2/sections/*.tex
```

## 代码范围

```text
paper_generation/agents/content_refinement_agent.py
paper_generation/llm/prompts/content_refinement.md
paper_generation/llm/prompts/critic_review.md
```

## Prompt 来源

- Base：PaperOrchestra Appendix F.5 Refinement prompt。
- PathLab diff：医学/病理 rubric、PHI guard、locked block 不可改、required cites 不可删。

## 迭代逻辑

```text
for iter in 1..3:
  snapshot(drafts/sections -> drafts/snapshots/iter_N)
  review = critic(full_draft)
  refined = revise(full_draft, review)
  new_review = critic(refined)

  if new_review.overall > review.overall:
      accept
  elif new_review.overall == review.overall and net_subaxis_delta >= 0:
      accept
  else:
      revert snapshot
      break

  rerun all guards
```

## Critic rubric

- `medical_accuracy`
- `statistical_rigor`
- `clinical_relevance`
- `technical_novelty`
- `presentation`

## 不可修改内容

- `locked_blocks/*.tex`
- metric placeholder keys
- `required_cites`
- BibTeX keys
- figure/table labels
- PHI scrubbed identifiers

## 验收标准

- 最多 3 轮。
- 每轮都有 physical snapshot。
- 不满足单调收敛则真实 revert。
- 每轮后重跑 guard。
- refinement 不会修改 private evidence 或 locked blocks。

## 风险

- 不要让 LLM 自己决定“已经更好”。必须用 critic score gate。
- 不要 in-memory revert，要真实文件级 revert。
- 不要让 refinement 修 guard 失败时绕过 guard。
