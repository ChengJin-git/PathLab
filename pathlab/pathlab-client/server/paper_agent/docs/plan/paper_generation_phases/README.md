# PathLab Paper Generation Agent 分阶段实施计划

> 创建日期：2026-05-04  
> 来源：`pathlab/pathlab-client/server/paper_agent/docs/plan/paper_generation_agent_design.md`  
> 原则：Agent 设计尽量照搬 PaperOrchestra 5-agent pipeline；PathLab 只在 evidence / PHI / guard / 模板 / 医学场景层增强。

## 阶段总览

| 阶段 | 文件 | 目标 | 是否依赖 LLM |
|---|---|---|---|
| Phase 01 | [`phase_01_infrastructure.md`](phase_01_infrastructure.md) | 建立 run、目录、DB、API、CPU queue、LaTeX 编译基础设施 | 否 |
| Phase 02 | [`phase_02_collector.md`](phase_02_collector.md) | 收集 task / dataset / split / model / analysis / extval / qualitative evidence | 否 |
| Phase 03 | [`phase_03_phi_and_evidence.md`](phase_03_phi_and_evidence.md) | PHI scrub、experimental log、private/public evidence、tables、figures manifest | 否 |
| Phase 04 | [`phase_04_template_and_locked_blocks.md`](phase_04_template_and_locked_blocks.md) | MICCAI / Nature SR 模板、locked blocks、可编译占位稿 | 否 |
| Phase 05 | [`phase_05_outline_agent.md`](phase_05_outline_agent.md) | PaperOrchestra-style Outline Agent，输出原始 outline schema | 是 |
| Phase 06 | [`phase_06_plotting_agent.md`](phase_06_plotting_agent.md) | Empirical plots + PaperBanana-style conceptual diagrams | 部分 |
| Phase 07 | [`phase_07_literature_review_agent.md`](phase_07_literature_review_agent.md) | Literature Review Agent：检索、验证、选引用、Intro/RW 草稿 | 是 |
| Phase 08 | [`phase_08_section_writing_agent.md`](phase_08_section_writing_agent.md) | Section Writing Agent：单次多模态生成 full-paper sections | 是 |
| Phase 09 | [`phase_09_guard_layer.md`](phase_09_guard_layer.md) | Metric / claim / identifier / consistency / citation / latex / figure-table guards | 否 |
| Phase 10 | [`phase_10_content_refinement_agent.md`](phase_10_content_refinement_agent.md) | Content Refinement Agent：AgentReview-style 单调收敛循环 | 是 |
| Phase 11 | [`phase_11_export_and_regenerate.md`](phase_11_export_and_regenerate.md) | Section-level regenerate、final render、dependency-closed ZIP export | 部分 |
| Phase 12 | [`phase_12_testing_and_release.md`](phase_12_testing_and_release.md) | 7 个 fixture、L1-L4 测试、发布验收 | 部分 |
| Frontend Contract | [`frontend_interface.md`](frontend_interface.md) | 前端 API client、页面入口、状态轮询、artifact 下载、section regenerate | 部分 |
| Runtime | [`runtime_environment.md`](runtime_environment.md) | 开发/桌面/服务器运行环境、LaTeX backend、CPU queue、环境变量 | 部分 |
| Parallel Worktrees | [`parallel_worktree_plan.md`](parallel_worktree_plan.md) | 多 agent 并行开发 worktree、分支、写入边界、测试和合并流程 | 否 |

## 推荐执行顺序

```text
P01 Infrastructure
  ├── P02 Collector
  │     └── P03 PHI + Evidence
  │           └── P04 Templates + Locked Blocks
  │                 ├── P05 Outline Agent
  │                 │     ├── P06 Plotting Agent
  │                 │     └── P07 Literature Review Agent
  │                 │           └── P08 Section Writing Agent
  │                 │                 └── P09 Guard Layer
  │                 │                       └── P10 Content Refinement Agent
  │                 │                             └── P11 Export + Regenerate
  │                 └── P12 Testing runs across all phases
```

## 第一周并行起步建议

第一周不要等所有前置都完成，建议并行启动 5 条线：

1. **P01 Infrastructure**：DB / run dir / API shell / `server/paper_agent` uv 环境 / standalone `serve` / `run-stage` / scaffold export。
2. **Frontend Contract**：先放 `api/papers.ts`、`/papers`、`/papers/:paper_id` 页面壳，能创建 run 和轮询状态。
3. **P03 Fixture + PHI 起步**：抽一个真实 `wsi_classification` task 做最小 fixture。
4. **P04 Template shell**：MICCAI + Nature SR 两个模板先编译通过。
5. **P07 Citation deterministic prototype**：先写 S2 / PubMed / verifier / ref selector，不等 LLM。

当前实现已经有 deterministic scaffold 能跑完整 stage 顺序并产出 public/private artifact、`final/*/main.tex` 和 ZIP。注意这只是**契约 scaffold**，不能把它等同于真实 P02/P03/P04/P07/P08/P09/P11 完成；后续并行工作应逐步替换各 stage 的内部实现，而不改变 CLI / manifest / frontend contract。

## 阶段间硬约束

- LLM 只能读取脱敏材料：`experimental_log.md`、`evidence_public.json`、`tables/*.tex`、`figures/manifest.json`、`selected_refs` / `refs.bib`。
- 后端 validator 才能读取 `evidence_lock.private.json`。
- `drafts/intro_rw_draft/` 是 Literature Review Agent 草稿区，不参与编译和 guard。
- `drafts/sections/` 是 Section Writing Agent 终稿区，编译和 guard 只看这里。
- ZIP export 必须 dependency-closed，解压后独立 `latexmk` 通过。
