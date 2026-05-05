# Paper Agent 并行 Worktree 执行计划

> 当前基线 commit：`2c286e44 docs(paper): record refining stage commit hash in MIGRATIONS`  
> 适用范围：Wave 1 + 2A + 2B + 3 + 4A 已落地后，进入 Wave 4B = M11 Refinement Loop（单条 track）。  
> 注意：`docs/` 目录在当前 repo 里是 ignored，worktree 里不一定能看到 docs；所以其他 agent **优先读本文件**。

## 0. 先读这个结论

**已合并到 phase01**：

- Wave 1：M2 collector / M4 templates / M6a figures / M8a citations / M10a guards
- 跟在 Wave 1 后补做：M3 PHI scrub + evidence bundle
- Wave 2A：M5 locked blocks renderer + M7 outline agent (含 LLM provider 模块)
- Wave 2B：M6b plotting agent + M8b literature review agent
- Wave 3：M9 section writer + citation renderer
- Wave 4A：M10b LLM-output guards + M12a ZIP export 硬化（含 review polish）
- Wave 4A 后：refining stage 已经接进 pipeline dispatch（contract 占位），但 stage body 是 no-op，等 M11 填实

**Wave 4B 现在开一条 track**（不并行）：

- **M11 Refinement Loop** —— `agents/content_refinement_agent.py` + `stages/refining.py` 实体。AgentReview 风格 critic prompt（PathLab tuned 的 medical_accuracy / statistical_rigor / clinical_relevance / technical_novelty / presentation rubric），单调收敛接受准则（score 严格上升 OR 平局且子项无负退化），物理 snapshot 到 `drafts/snapshots/iter_{N}/`，物理 revert 回 `drafts/sections/`，最多 3 轮。Critic 调用 LLM，但 score 来自 M10a + M10b 的 GuardReport 加 critic 的 rubric 分数。

合完 M11 后下一步是 Wave 4C = M12b Regenerate API（依赖 M11 的 refinement loop entry）。

## 1. 当前 worktree 现状

### 1.1 Wave 4B active

| Track | Branch | Worktree | Agent 主要负责 |
|---|---|---|---|
| M11 Refinement Loop | `paper/m11-refinement` | `/Users/wangyihui/code/PathLab-worktrees/m11-refinement` | content_refinement_agent + stages/refining.py 真实 loop；critic LLM rubric + 单调收敛接受准则 + 物理 snapshot/revert + 最多 3 轮 |

起 worktree 命令（如果还没起）：

```bash
git -C /Users/wangyihui/code/PathLab worktree add -b paper/m11-refinement \
  /Users/wangyihui/code/PathLab-worktrees/m11-refinement paper-agent-phase01
```

### 1.2 历史 worktree（已合并，已清）

| Track | Branch | 合并 commit |
|---|---|---|
| M2 Collector | `paper/m2-collector` | `25ef559e` |
| M4 Templates | `paper/m4-templates` | `91d741e0` |
| M6a Figures | `paper/m6a-figures` | `1b63c762` |
| M8a Citations | `paper/m8a-citations` | `55e502a7` |
| M10a Guards | `paper/m10a-guards` | `736163fd` |
| M5 Locked Blocks | `paper/m5-locked-blocks` | `e5da8319` |
| M7 Outline Agent | `paper/m7-outline` | `1a9593b2` |
| M8b Literature Review | `paper/m8b-literature` | `db40f79c` |
| M6b Plotting | `paper/m6b-plotting` | `6f7bc75f` |
| M9 Section Writer | `paper/m9-sections` | `7cbb2f61` |
| M10b Claim/Consistency Guards | `paper/m10b-guards` | `31436967` |
| M12a ZIP Export 硬化 | `paper/m12a-export` | `2d592300` |

### 1.3 确认

```bash
git -C /Users/wangyihui/code/PathLab worktree list
```

所有活跃 worktree 都应该基于同一条主线 commit；当前为：

```text
2c286e44 docs(paper): record refining stage commit hash in MIGRATIONS
```

## 2. 给其他 agent 的开工流程

每个 agent 只做自己的 track。开工前先跑：

```bash
cd /Users/wangyihui/code/PathLab-worktrees/<worktree-name>
git status --short --branch
sed -n '1,260p' pathlab/pathlab-client/server/paper_agent/PARALLEL_WORKTREES.md

cd pathlab/pathlab-client/server/paper_agent
uv sync
uv run pytest -q
uv run ruff check src tests
```

如果测试通过，再开始实现。

如果需要读总设计文档，主目录里有：

```text
/Users/wangyihui/code/PathLab/docs/plan/paper_generation_agent_design.md
/Users/wangyihui/code/PathLab/docs/plan/paper_generation_phases/parallel_worktree_plan.md
```

但这些 docs 是 ignored 文件，其他 worktree 里可能不存在；工程操作以本文件为准。

## 3. 为什么先拆 stage module

Phase 01 scaffold 原来把所有 `_stage_*` 都放在：

```text
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/pipeline.py
```

这不适合并行，因为 M2 / M4 / M6 / M8 / M10 都会改同一个文件。现在已经拆成：

```text
src/pathlab_paper_agent/stages/
  collecting.py      # M2 collector entry point        ← 已落地（M2）
  evidence.py        # M3 PHI scrub + evidence lock     ← 已落地（M3 + M5 locked-block delegation）
  outlining.py       # M7 outline agent entry point     ← 已落地（M7）
  plotting.py        # M6 plotting entry point          ← 已落地（M6a generators + M6b orchestration）
  literature.py      # M8 literature/citation           ← 已落地（M8a deterministic + M8b LLM 编排）
  sections.py        # M9 section writer                ← 已落地（M9）
  validating.py      # M10 guards                       ← 已落地（M10a + M10b）
  refining.py        # M11 refinement loop              ← 已接 dispatch；scaffold no-op，M11 接手中
  rendering.py       # M4/M11 renderer entry point      ← 已落地（M4 + M5 per-template locked_blocks）
  exporting.py       # M11 bundle export entry point    ← 已落地（M4 ZIP export + M12a 硬化）
```

并行开发原则：

- `pipeline.py` 继续保持 thin orchestrator，只负责 stage dispatch、manifest 更新、错误处理。
- 各 track 优先在自己的 package 里加真实逻辑，再接到对应 `stages/*.py`。
- 不要把真实 collector / citation / validator / renderer 逻辑继续塞回 `pipeline.py`。
- M7 已经把 `agents/` 和 `llm/` 两个子包建好了，Wave 2B 的 M6b / M8b 在 `agents/` 里加各自模块即可，**不要新起根级别 package**。

**Locked blocks 状态**：M3 当时把 `locked_blocks/*.tex` 内嵌在 `evidence/bundle.py` 里（forward hook）。M5 已经把这部分逻辑迁到 `renderers/locked_block_renderer.py` + Jinja2 模板，并加了 byte-identical golden fixture。后续 milestone 改这块时**不要**让 golden 漂移；要扩字段就更新 fixture。

## 4. 每条 track 的写入边界

> **测试目录约定（所有 track 都要遵守）**：
> 每条 track 的测试放在 `paper_agent/tests/<track_name>/`，不要往
> `paper_agent/tests/` 根目录加 `test_*.py`。这避免 5 条 track 的测试文件名
> / fixtures 互撞。约定：
>
> ```
> paper_agent/tests/
> ├── conftest.py          # ★ contract 文件，main 协调；track 不直接改
> ├── collector/           # M2
> ├── templates/           # M4
> ├── figures/             # M6a
> ├── citations/           # M8a
> └── guards/              # M10a
> ```

### M2 Collector agent

工作目录：

```bash
cd /Users/wangyihui/code/PathLab-worktrees/m2-collector
```

主要写：

```text
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/collector/
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/stages/collecting.py
pathlab/pathlab-client/server/paper_agent/tests/collector/
tests/paper_generation/fixtures/wsi_classification_minimal/   ← M2 还负责造 fixture
```

不要主要改：`stages/literature.py`、`stages/rendering.py`、`stages/validating.py`。

目标：

- 支持 `wsi_classification` / `wsi_survival` / `patch_classification` / `patch_segmentation` 的 collector schema。
- 读 PathLab DB / uploads，收集 task、dataset、split、model、analysis、external validation、qualitative evidence。
- 没有 analysis 时输出 missing evidence，不允许后续 agent 编造。
- 继续产出 `inputs/source_tasks.json`、`inputs/source_analyses.json`、`inputs/idea.md`。
- **造 fixture**：从一次真实 PathLab `wsi_classification` task 缩样到 30 条 WSI，存到 `tests/paper_generation/fixtures/wsi_classification_minimal/`。这件事**最早做最划算**——做 fixture 时会直接揭穿 collector schema 假设错的地方。

### M4 Templates agent

工作目录：

```bash
cd /Users/wangyihui/code/PathLab-worktrees/m4-templates
```

主要写：

```text
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/templates/
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/renderers/
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/stages/rendering.py
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/stages/exporting.py
pathlab/pathlab-client/server/paper_agent/tests/templates/
pathlab/pathlab-client/docker/paper-latex/
```

目标：

- MICCAI / LNCS 和 Nature Scientific Reports 两套模板 skeleton。
- 每个模板有 `style.json`，后续 agents 按 style 控制 section order / tone / constraints。
- `final/{template}/main.tex`、`main.pdf` 可生成。
- `exports/{template}_bundle.zip` dependency-closed，不能包含 private evidence。

### M6a Figures agent

工作目录：

```bash
cd /Users/wangyihui/code/PathLab-worktrees/m6a-figures
```

主要写：

```text
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/plotting/
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/stages/plotting.py
pathlab/pathlab-client/server/paper_agent/tests/figures/
```

目标：

- 先做 deterministic empirical generators，不依赖 LLM。
- 每个 generator 接收结构化 evidence/mock data，输出 `figures/*.{pdf,png}` 和 manifest entry。
- Figure 1 conceptual diagram 先保留 `requires_user_revision` 或 `user_provided`；PaperBanana adapter 是 M6c，不阻塞 v1。

### M8a Citations agent

工作目录：

```bash
cd /Users/wangyihui/code/PathLab-worktrees/m8a-citations
```

主要写：

```text
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/citations/
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/stages/literature.py
pathlab/pathlab-client/server/paper_agent/tests/citations/
```

目标：

- S2 / PubMed clients。
- title / abstract / venue / year verifier。
- selected refs、required cites、BibTeX generator。
- `citations/coverage_report.json`，给 M10a citation guard 使用。
- 注意 Literature Review Agent 本体是 M8b；M8a 只做 deterministic citation chain。

### M10a Guards agent

工作目录：

```bash
cd /Users/wangyihui/code/PathLab-worktrees/m10a-guards
```

主要写：

```text
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/validators/
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/stages/validating.py
pathlab/pathlab-client/server/paper_agent/tests/guards/
```

目标：

- metric guard：论文数字必须来自 evidence lock，允许受控 rounding。
- identifier guard：禁止 case ID、医院名、原始路径、疑似 PHI 泄露。
- latex guard：编译前静态检查明显错误。
- citation guard：orphan cite、coverage、missing bib key。
- 输出 `validation/*.json` 和 `validation/warnings.md`。

### M5 Locked Blocks Renderer agent (Wave 2A)

工作目录：

```bash
cd /Users/wangyihui/code/PathLab-worktrees/m5-locked-blocks
```

主要写：

```text
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/renderers/locked_block_renderer.py
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/templates/locked_blocks/   ← Jinja2 模板（MICCAI / Nature SR 各一组）
pathlab/pathlab-client/server/paper_agent/tests/locked_blocks/
tests/paper_generation/fixtures/wsi_classification_minimal/golden/deterministic/locked_blocks/*.tex
```

目标：

- 把 M3 在 `evidence/bundle.py` 里的 `_render_locked_blocks` / `_render_metrics_macros` / `_render_tables` 三段搬到 `renderers/locked_block_renderer.py`，做成 Jinja2 模板化的 `LockedBlockRenderer`。
- 模板感知：MICCAI 顺序（intro→methods→experiments→results→discussion）vs Nature SR 顺序（intro→results→discussion→methods）。M5 只负责让不同模板挑不同的 .tex 模板；section 顺序由 M9 处理。
- byte-identical golden：固化当前 fixture 跑出来的 `locked_blocks/*.tex` 作为回归参考。
- 不依赖 LLM。
- 注意 metrics_macros.tex 已经因为 M3 review 修过 LaTeX 命令名 bug（`_latex_cmd_key` letters-only），M5 重构必须保留这个不变量。

不要改：`stages/literature.py` / `stages/sections.py` / `stages/validating.py` / `stages/rendering.py` / `collector/` / `citations/` / `validators/` / `evidence/phi.py` 的 PHI 逻辑（M3 owned；只允许把 `_render_*` 函数的调用点 swap 为 `LockedBlockRenderer`）。

### M7 Outline Agent (Wave 2A, 第一条 LLM track)

工作目录：

```bash
cd /Users/wangyihui/code/PathLab-worktrees/m7-outline
```

主要写：

```text
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/llm/                  ← 第一次建 LLM provider 模块
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/agents/               ← 第一次建 agents/ 目录
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/agents/outline_agent.py
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/stages/outlining.py   ← 替掉现在的 hardcoded scaffold
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/prompts/outline_v1.txt
pathlab/pathlab-client/server/paper_agent/tests/outline/                                ← LLM 全部 mock
```

目标：

- LLM provider（`llm/`）：httpx 客户端，三档 env override `PAPER_GEN_LLM_BASE_URL` / `_API_KEY` / `_MODEL` → vLLM 内网 → OpenRouter 兜底；reasoning 模型（gpt-5.5）必须 stream 并把 SSE chunks 聚合。
- Outline Agent：单次 LLM 调用，输入装配 experimental_log（M3）+ inputs/idea.md + 模板 style.json（M4）+ figures/manifest.json（M6a），输出 `drafts/outline.json`。
- **PHI 双保险**：装配 prompt 前再过一次 `PhiScrubber`（evidence/phi.py），任何 raw_paths / case_id / 机构名进 prompt 必须 hard fail。
- outline.json schema 必须能通过 §13.1 `outline_schema.json` 断言：`plotting_plan` / `macro_lit_search` / `micro_lit_clusters` / `section_plan` 四个 PaperOrchestra 字段 + PathLab `pathlab_extensions`。
- prompt 来源：PaperOrchestra App. F.1（按 PathLab WSI 场景改写）。
- CI 不能跑真实 LLM，全部 mock。

不要改：`schemas.py` / `pipeline.py` dispatch / `tests/conftest.py`（contract）；`collector/` / `evidence/` / `citations/` / `validators/` / `renderers/`；其他 `stages/*.py`。新建 `llm/` 和 `agents/` 不属于 contract，可以直接做。

### M6b Plotting Agent (Wave 2B)

工作目录：

```bash
cd /Users/wangyihui/code/PathLab-worktrees/m6b-plotting
```

主要写：

```text
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/agents/plotting_agent.py
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/stages/plotting.py     ← 替掉现在的 scaffold
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/prompts/plotting_caption_v1.txt
pathlab/pathlab-client/server/paper_agent/tests/plotting/
```

目标：

- 读 `drafts/outline.json` 的 `plotting_plan`，按每条 item 派遣到 M6a 的 generator（已落 `plotting/` 模块）。
- `backend == "deterministic_plotting"` → 调对应 generator 出 `figures/<id>.{pdf,png}`。
- `backend == "paperbanana"` → 默认 fallback 成 `requires_user_revision`（M6c 还没做，主流水线不阻塞）。
- `backend == "user_revision"` → 在 manifest 里标 `status: user_provided`。
- 每张图调一次短 LLM 调用生成 caption（不要长篇叙事），模板写在 `prompts/plotting_caption_v1.txt`。
- 写最终 `figures/manifest.json`：`status` / `source` / `generator` / `caption` / `kind`。
- 没图能编出 `manifest.figures` 缺失的 figure；所有 figure 必须可追溯到 evidence + outline 一条 plan item。
- LLM 全部 mock，CI 不打真客户端（沿用 M7 的 `_NoNetworkOutlineLLMClient` 思路另起一个 `_NoNetworkPlottingLLMClient`，或共用 `OpenAICompatibleLLMClient` + monkeypatch http_client）。

不要改：`schemas.py` / `pipeline.py` dispatch / `tests/conftest.py`（contract）；`collector/` / `evidence/` / `citations/` / `validators/` / `renderers/`；其他 `stages/*.py`；`plotting/` 里 M6a 的 generator 实现（M6b 是 orchestration 层，按 plan 调 generator，不动 generator 本身）。`agents/outline_agent.py` 也不要改。

### M8b Literature Review Agent (Wave 2B)

工作目录：

```bash
cd /Users/wangyihui/code/PathLab-worktrees/m8b-literature
```

主要写：

```text
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/agents/literature_review_agent.py
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/stages/literature.py    ← M8a 已写过，M8b 改成走 agent flow
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/prompts/lit_search_v1.txt
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/prompts/intro_rw_draft_v1.txt
pathlab/pathlab-client/server/paper_agent/tests/literature/
```

目标：

- 读 `drafts/outline.json` 的 `macro_lit_search` + `micro_lit_clusters`。
- LLM 调用 1：把 outline 的查询条目展开成具体的 S2 / PubMed 搜索查询（每条 query ≤ 一句话，主题清晰）。
- 调 M8a 的 `citations/semantic_scholar.py` / `pubmed.py` / `verifier.py` / `ref_selector.py` / `bib_generator.py` / `coverage_gate.py` —— 当 library 用，**不要重新实现**。
- 默认 10 路并发 web search，verifier 串行（QPS 限制）。
- 输出 `selected_refs.json` / `required_cites.json` / `citations/refs.bib` / `citations/coverage_report.json` —— coverage_gate 必须 ≥ 90%，不达标 hard fail。
- LLM 调用 2：用 selected_refs 起草 `drafts/intro_rw_draft/introduction.tex` 和 `drafts/intro_rw_draft/related_work.tex`，每篇引用必须出现在 `selected_refs.json` 内。M8a 已经把 `stages/sections.py` 接成 `intro_rw_draft` → sections 的 forward hook（见 MIGRATIONS 2026-05-04 m8a 那条），M8b 只填内容、不动 hook。
- prompt 来源：PaperOrchestra App. F.3。
- 网络 client（S2 / PubMed / LLM）必须可 mock，测试默认不联外网。
- A2 契约：M8b 起的 intro_rw_draft 是稿，**M9 Section Writer 可以润色**，但不能删掉 `required_cites.json` 里的任何 `\cite{paperId}`，也不能新增 `selected_refs.json` 之外的引用。

不要改：`schemas.py` / `pipeline.py` dispatch / `tests/conftest.py`（contract）；`collector/` / `evidence/` / `validators/` / `renderers/`；其他 `stages/*.py`（含 `sections.py` 现有的 intro_rw_draft hook）；`citations/*.py` 的内部实现（按现有 API 当 library 用，需要新功能就先在 main 协调）。`agents/outline_agent.py` 也不要改。

### M9 Section Writing Agent (Wave 3, 终稿正文)

工作目录：

```bash
cd /Users/wangyihui/code/PathLab-worktrees/m9-sections
```

主要写：

```text
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/agents/section_writing_agent.py
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/stages/sections.py            ← 替掉 scaffold + intro_rw_draft hook
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/renderers/citation_renderer.py ← 新建
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/prompts/section_writing_v1.txt
pathlab/pathlab-client/server/paper_agent/tests/sections/
```

目标：

- **一次多模态 LLM 调用**装配整篇 sections。输入：`drafts/outline.json`（M7）+ `drafts/intro_rw_draft/{introduction,related_work}.tex`（M8b）+ `figures/manifest.json`（M6b）+ `citations/{refs.bib,selected_refs.json,required_cites.json}`（M8b）+ `locked_blocks/*.tex`（M3+M5）+ 可选 `tables/*.tex`。
- **强制占位符**：metric → `{{m:metric_key}}`，引用 → `[CITE:paperId]`。LLM **不能**直接写数字，**不能**直接 `\cite{}`。
- **A2 引用契约**（设计 §10.M9）：可以润色 M8b 起的 intro_rw_draft 文风；但不能删掉 `required_cites.json` 里的任何 paperId，也不能引用 `selected_refs.json` 之外的 paperId。
- 输出全套 `drafts/sections/*.tex`（含 introduction / related_work 终稿 / methods / experiments / results / discussion / conclusion / abstract — 由 outline 的 section_plan 决定具体集合）。
- 跑完 LLM 后接两个 renderer：`renderers/metric_renderer.py`（M10a 已交，把 `{{m:...}}` 替成 evidence_lock 数字）+ 新建 `renderers/citation_renderer.py`（把 `[CITE:paperId]` 替成 `\cite{paperId}`）。两个 renderer 都是确定性，不接 LLM。
- 合规：M10a deterministic guards（metric / identifier / latex / citation）必须 100% 通过。
- prompt 来源：PaperOrchestra App. F.4（按 PathLab 场景改写）。
- LLM client mock 用 M7 同样 pattern：`_NoNetworkSectionWritingLLMClient` + `PAPER_GEN_LLM_ALLOW_NETWORK_IN_TESTS=1` 显式 opt-in。CI 不跑真实 LLM。
- Exit criterion (§13.1)：fixture → 完整 sections/*.tex；M10a 全过；section_constraints.json 断言（占位符数量、`\input{locked_blocks/...}` 数量、`\cite{}` 数量等）。

不要改：`schemas.py` / `pipeline.py` dispatch / `tests/conftest.py`（contract）；`collector/` / `evidence/` / `citations/` 内部实现；`agents/{outline_agent,plotting_agent,literature_review_agent}.py`；`llm/`；其他 `stages/*.py`；`renderers/{template_renderer,latex_compiler,zip_exporter,locked_block_renderer}.py`（只许新建 `citation_renderer.py`）；`validators/`（M10a 已落地，guard 跑在 stages/validating.py）。**`stages/sections.py` 现有的 intro_rw_draft 优先逻辑**保留语义（intro/related_work 优先读 M8b 的草稿），M9 只是把它整合进新的 agent flow。

### M10b Claim/Consistency Guards (Wave 4A)

工作目录：

```bash
cd /Users/wangyihui/code/PathLab-worktrees/m10b-guards
```

主要写：

```text
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/validators/claim_guard.py
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/validators/consistency_guard.py
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/stages/validating.py     ← 接入新 guard 的 dispatch
pathlab/pathlab-client/server/paper_agent/tests/guards/                                    ← 与 M10a 共用目录，新文件 test_m10b_*.py
```

目标：

- **claim_guard**：扫 `drafts/sections/*.tex`，检测 keyword 集合（`external validation` / `independent cohort` / `generalization to`；`outperforms` / `state-of-the-art` / `SOTA` / `significantly` / `statistically significant`；`real world deployment` 等）。从 `evidence_lock.private.json` **派生** flag —— `has_external_validation = bool(evidence_lock["external_validation"])`、`has_baseline = any(model.role == "baseline" for model in source_tasks)`、`has_statistical_test = any("ci_" in metric_key or "p_value" in metric_key for metric_key in evidence_lock["metrics"])`。当正文有 keyword 但 evidence 不支持时 hard fail；GuardReport 报 fail + 列出具体 section + keyword + 缺什么 evidence。
- **consistency_guard**：检测段落串扰 —— test section 段落里出现写明 "validation" / "val" 上下文的数字、external section 段落里出现写明 internal cohort 的数字。实现可以走 metric_renderer 反向：先把 evidence_lock 的 metric 按 task / split 索引；再扫每个 section 的 `\metricXxx` macro 引用，看是否落在该 section 应该引用的 task/split 子集里。
- 输出沿 M10a 的格式：每条 guard 写 `validation/<guard>.json` + 汇总 `validation/warnings.md`。
- 不接 LLM —— 这两个 guard 是确定性的关键词检测 + evidence_lock cross-reference。

不要改：`schemas.py` / `pipeline.py` dispatch / `tests/conftest.py`（contract）；`collector/` / `evidence/` / `citations/` / `renderers/` / `agents/` / `llm/`；其他 `stages/*.py`；M10a 已交的 `validators/{metric,identifier,latex,citation,common}_guard.py`、`validators/common.py`（沿用 `GuardReport` / `tex_files_under` / `rel_to_run` 等 helper）。

### M12a ZIP Export 硬化 (Wave 4A)

工作目录：

```bash
cd /Users/wangyihui/code/PathLab-worktrees/m12a-export
```

主要写：

```text
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/renderers/zip_exporter.py    ← 扩，不重写
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/renderers/bundle_validator.py ← 新建
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/stages/exporting.py          ← 扩
pathlab/pathlab-client/server/paper_agent/tests/exporting/                                     ← 新建（M12a 自己的测试目录）
```

目标：

- **dependency-closed bundle**：每个 template 各打一个 ZIP，含 `main.tex`、`refs.bib`（M8b）、所有 `.cls` / `.bst`（M4 模板下）、`figures/*.{pdf,png}`（M6b ready 的）、`locked_blocks/*.tex`（M3+M5）、`tables/*.tex`、`README.md`。**不能含**任何 `evidence_lock.private.json` / `raw_collected/` / `intro_rw_draft/`（保 §5.3 数据契约）。
- **post-extract dry-run latexmk**：bundle 打完后解压到临时目录 → 进 `pathlab/pathlab-client/docker/paper-latex/` container（M4 已建）跑 `latexmk -dvi=0 -ps=0 -pdf -interaction=nonstopmode`。返回码非零 → bundle 标 `downloadable=False`，错误日志摘要写进 `validation/warnings.md`。
- **双模板 main.pdf 编译**：MICCAI 和 Nature SR 的 `final/{template}/main.pdf` 都得编译成功。M4 已有 `latex_compiler.py`，调它即可。
- 测试用 fixture：`tests/paper_generation/fixtures/wsi_classification_minimal/` 喂完一遍 evidence/locked_blocks/figures/sections，跑 export stage，断言 ZIP 内容树 + dry-run 通过 + main.pdf 出文件。
- 没有 LLM —— 纯 packaging + 编译验证。

不要改：`schemas.py` / `pipeline.py` dispatch / `tests/conftest.py`（contract）；`collector/` / `evidence/` / `citations/` / `validators/`；其他 `stages/*.py`；`agents/` / `llm/`；M4 的 `renderers/template_renderer.py` / `renderers/latex_compiler.py` 内部实现（按现有 API 调）；M5 的 `renderers/locked_block_renderer.py`。**M11 territory（refinement_loop）和 M12b territory（regenerate API）严格不动**，留给后续 wave。

### M11 Refinement Loop (Wave 4B)

工作目录：

```bash
cd /Users/wangyihui/code/PathLab-worktrees/m11-refinement
```

主要写：

```text
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/agents/content_refinement_agent.py
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/stages/refining.py        ← 替掉 no-op scaffold
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/prompts/refinement_critic_v1.txt
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/prompts/refinement_revise_v1.txt
pathlab/pathlab-client/server/paper_agent/tests/refinement/                                  ← 新建测试目录
```

目标：

- **Critic LLM 调用** 用 PaperOrchestra App. F.5 风格的 rubric，PathLab tuned：`medical_accuracy` / `statistical_rigor` / `clinical_relevance` / `technical_novelty` / `presentation`，每项 0-5 整数 + 一句话理由 + overall 总分。
- **Revise LLM 调用** 给出当前 sections + critic 反馈，让 LLM 重写需要修的章节。**保留 M9 的占位符约束**：metric 必须 `{{m:...}}`，引用必须 `[CITE:paperId]`。**保留 M9 A2 cite 契约**。重写后跑 M9 的 `citation_renderer` + M10a 的 `metric_renderer` 收尾。
- **物理 snapshot**：每次接受重写，先把 `drafts/sections/*.tex` copy 到 `drafts/snapshots/iter_{N}/sections/` 再 overwrite。`paths.snapshots_dir` 已经在 `PaperRunPaths` 里。
- **物理 revert**：score 退步或 critic 维度有负向退化时，**不接受**新版 → 把 `iter_{N-1}` 的内容 copy 回 `drafts/sections/` （即 revert）。manifest 标 `refining/iter_{N}/status: rejected`。
- **单调收敛接受准则**（设计文档 §10 M11）：score 严格上升 → 接受；score 平局 → 每个子项不能负退化才接受；score 下降 → 拒绝。
- **最多 3 轮**。第 3 轮无论结果都停。
- **score 来源是 hybrid**：M10a + M10b 的 GuardReport（每条 fail → 总分扣分；critical 严重的扣得多）+ critic LLM 的 5 个 rubric 分。critic 不能凭空给高分覆盖 guard fail —— 任何 guard fail 直接 force reject 该轮重写。
- **最终产出**：`drafts/sections/*.tex`（最优一轮的内容）+ `drafts/snapshots/iter_*/`（每轮快照）+ `validation/refinement_log.json`（每轮 score / 接受/拒绝原因）。
- LLM 全部 mock，CI 不跑真实调用，沿 M7 的 `_NoNetworkLLM` pattern + `PAPER_GEN_LLM_ALLOW_NETWORK_IN_TESTS=1` 显式 opt-in。

不要改：`schemas.py` / `pipeline.py` dispatch / `tests/conftest.py`（contract，**已在 main 协调好 refining 的 dispatch 占位**，不要再改）；`collector/` / `evidence/` / `citations/` / `validators/`；其他 `stages/*.py`；`renderers/`（按 M5 / M9 / M10a 现有 API 调）；`agents/` 其他 agent（不要改 outline / plotting / literature / section_writing）；`llm/`。

## 5. 所有 agent 都必须保留的 contract

这些是 **contract 文件**：worktree 里**不要直接改**，必须先在 main 协调，
登记到 `paper_agent/MIGRATIONS.md`，然后所有 worktree rebase 同步。

### 5.1 接口契约

- **CLI**：`pathlab-paper-agent run`、`run-stage`、`scaffold`、`serve` —— 名称和参数。
- **Dev service**：`GET /health`、`POST /papers`、`GET /papers/{paper_id}`、`POST /papers/{paper_id}/stages/{stage}:run` —— 路径和 schema。
- **TaskWorker 边界**：生产通过 subprocess 调 paper agent；subprocess argv 和 stdout/stderr 协议不变。
- **PaperOrchestra 5-agent 边界**：PathLab 的 collector / PHI / evidence / guard 是外围增强，不要改散 5 个 agent 的职责。

### 5.2 文件契约（多 track 都读的源文件）

以下文件被多条 track 读取，**改它们 = 改其他 track 的输入**：

- **`src/pathlab_paper_agent/pipeline.py`** —— thin orchestrator，只做 stage dispatch + manifest 更新 + 错误处理。
  - track 内允许的：在 stages/<自己>.py 加新返回字段。
  - track 不允许的：改 dispatch 表、改 manifest 写入逻辑、把真实业务塞回 pipeline.py。
  - 真要加新 stage / 改 dispatch 必须走 main 协调。
- **`src/pathlab_paper_agent/schemas.py`** —— Pydantic models（PaperConfig / PaperManifest / PaperRunArtifact / PaperRunStage / TaskRole 等）。
  - 允许：在 worktree 里**新增**字段（向后兼容）。
  - 禁止：重命名字段、改字段类型、删字段、改 enum 值。这种改动必须走 main 协调。
- **`tests/conftest.py`** —— 全局 fixture（`db_session` / `paper_run_paths` / `mock_evidence` 等）。
  - 加新全局 fixture 必须走 main 协调。worktree 内的 fixture 放各自 `tests/<track_name>/conftest.py`。

### 5.3 数据契约

- **Artifact layout**：`inputs/`、`evidence/`、`locked_blocks/`、`drafts/`、`figures/`、`citations/`、`validation/`、`final/`、`exports/` —— 目录名和层级。
- **Private/public 边界**：`evidence_lock.private.json`、raw prompts、raw responses、source mappings 不能进入前端下载和 export ZIP。
- **`manifest.artifact_index`**：每个 artifact 的 status / visibility / downloadable / label / content_type 的 enum 值集合稳定；只允许新增 status 值，不允许改语义。

### 5.4 Contract 改动流程

如果你确实需要改上面任何一项：

1. 不要在自己 worktree 直接动手。先在 main（或一个独立的 `paper/contract-<name>` 分支）改。
2. 在 `paper_agent/MIGRATIONS.md` 加一条记录（日期、改了什么、为什么、影响哪些 track）。
3. 主分支 commit + push 后，所有 worktree 跑 `git fetch && git rebase origin/<base>`。
4. 每条受影响 track 在自己的 worktree 跑一次 `uv run pytest -q`，确认仍然绿。

## 6. 单阶段 smoke test

开发中不要每次都跑完整 pipeline，可以只跑自己的 stage：

```bash
cd /Users/wangyihui/code/PathLab-worktrees/<name>/pathlab/pathlab-client/server/paper_agent

uploads=/tmp/pathlab-paper-dev
paper_id=paper_dev_001

uv run pathlab-paper-agent scaffold \
  --paper-id "$paper_id" \
  --uploads-dir "$uploads"

uv run pathlab-paper-agent run-stage \
  --paper-id "$paper_id" \
  --stage collecting \
  --uploads-dir "$uploads"
```

常用 stage 名：

```text
collecting
building_evidence
outlining
plotting
literature_review
section_writing
validating
rendering
exporting
```

完整 smoke：

```bash
uv run pathlab-paper-agent run \
  --paper-id "$paper_id" \
  --uploads-dir "$uploads"
```

Standalone service：

```bash
uv run pathlab-paper-agent serve \
  --host 127.0.0.1 \
  --port 6201 \
  --uploads-dir /tmp/pathlab-paper-dev
```

## 7. 推荐给每个 Codex agent 的任务提示

M2：

```text
你在 /Users/wangyihui/code/PathLab-worktrees/m2-collector 工作。只负责 paper agent 的 M2 Collector。先读 pathlab/pathlab-client/server/paper_agent/PARALLEL_WORKTREES.md。主要写 collector/ 和 stages/collecting.py，不要改其他 track 的 stage。实现后跑 uv run pytest -q 和 uv run ruff check src tests。
```

M4：

```text
你在 /Users/wangyihui/code/PathLab-worktrees/m4-templates 工作。只负责 M4 Templates / Renderer / LaTeX export。先读 pathlab/pathlab-client/server/paper_agent/PARALLEL_WORKTREES.md。主要写 templates/、renderers/、stages/rendering.py、stages/exporting.py、docker/paper-latex/。不要改 collector/citations/validators。实现后跑 paper_agent tests、ruff，并做一个 run-stage rendering/exporting smoke。
```

M6a：

```text
你在 /Users/wangyihui/code/PathLab-worktrees/m6a-figures 工作。只负责 M6a empirical figure generators。主要写 plotting/ 和 stages/plotting.py。先用 mock evidence 做 deterministic figure tests，不接 LLM，不做 PaperBanana。实现后跑 tests/ruff。
```

M8a：

```text
你在 /Users/wangyihui/code/PathLab-worktrees/m8a-citations 工作。只负责 M8a deterministic citation chain。主要写 citations/ 和 stages/literature.py。实现 S2/PubMed client、verifier、ref selector、BibTeX、coverage report。网络 API 需要可 mock，测试默认不依赖外网。
```

M10a：

```text
你在 /Users/wangyihui/code/PathLab-worktrees/m10a-guards 工作。只负责 M10a deterministic guards。主要写 validators/ 和 stages/validating.py。实现 metric/identifier/latex/citation guards，测试用 mock evidence 和 tex。不要接 LLM review/refinement。
```

---

**Wave 2A**：

M5 Locked Blocks Renderer：

```text
你在 /Users/wangyihui/code/PathLab-worktrees/m5-locked-blocks 工作。只负责 M5 deterministic locked blocks renderer。先按顺序读：(1) pathlab/pathlab-client/server/paper_agent/PARALLEL_WORKTREES.md（§4 M5 边界 + §5 contract），(2) pathlab/pathlab-client/server/paper_agent/MIGRATIONS.md（特别是 2026-05-04 phase03 那条），(3) /Users/wangyihui/code/PathLab/docs/plan/paper_generation_agent_design.md 的 M5 段。

任务：把 M3 内嵌在 evidence/bundle.py 的 _render_locked_blocks / _render_metrics_macros / _render_tables 三段搬到新建的 renderers/locked_block_renderer.py，做成 Jinja2 模板化的 LockedBlockRenderer。模板感知 MICCAI vs Nature SR（M5 只挑模板，section 顺序由 M9 处理）。建 byte-identical golden fixture 在 tests/paper_generation/fixtures/wsi_classification_minimal/golden/deterministic/locked_blocks/。**保留** M3 review 修过的 \\newcommand letters-only 不变量。

主要写 renderers/locked_block_renderer.py、templates/locked_blocks/、tests/locked_blocks/。不要改 schemas.py / pipeline.py / conftest.py / 其他 stages / collector / citations / validators / evidence/phi.py。完成后跑 uv run pytest -q 和 uv run ruff check src tests。纯确定性，不接 LLM。
```

M7 Outline Agent（第一条 LLM track）：

```text
你在 /Users/wangyihui/code/PathLab-worktrees/m7-outline 工作。只负责 M7 Outline Agent。这是 paper-agent 第一条 LLM track，LLM provider 模块由你来建。先按顺序读：(1) pathlab/pathlab-client/server/paper_agent/PARALLEL_WORKTREES.md（§4 M7 边界 + §5 contract），(2) pathlab/pathlab-client/server/paper_agent/MIGRATIONS.md，(3) /Users/wangyihui/code/PathLab/docs/plan/paper_generation_agent_design.md 的 M7 段、§5.4.8 prompt 模板、§13.1 outline_schema.json 断言，(4) PaperOrchestra App. F.1（项目 docs/research/ 下 paper_generation_research.md 有摘要）。

任务：(1) 起 LLM provider 模块 src/pathlab_paper_agent/llm/，httpx 客户端 + 三档 env override（PAPER_GEN_LLM_BASE_URL / _API_KEY / _MODEL → vLLM 内网 → OpenRouter 兜底），reasoning 模型必须 stream + 聚合 SSE。(2) 起 agents/ 目录 + agents/outline_agent.py，单次 LLM 调用，输入 experimental_log + idea + style.json + figures/manifest.json，输出 drafts/outline.json（PaperOrchestra App. F.1 schema：plotting_plan / macro_lit_search / micro_lit_clusters / section_plan + PathLab pathlab_extensions）。(3) **PHI 双保险**：装配 prompt 前过 PhiScrubber，任何 raw_paths / case_id / 机构名 hard fail。(4) 替掉 stages/outlining.py 现在的 hardcoded scaffold。

主要写 llm/、agents/、stages/outlining.py、prompts/outline_v1.txt、tests/outline/。不要改 schemas.py / pipeline.py / conftest.py / collector / evidence / citations / validators / renderers / 其他 stages。tests/outline/ 全部 mock LLM，CI 不跑真实调用。完成后跑 uv run pytest -q 和 uv run ruff check src tests。
```

---

**Wave 2B**：

M6b Plotting Agent：

```text
你在 /Users/wangyihui/code/PathLab-worktrees/m6b-plotting 工作。只负责 M6b Plotting Agent（M6a 的 orchestration 层）。先按顺序读：(1) pathlab/pathlab-client/server/paper_agent/PARALLEL_WORKTREES.md（§4 M6b 边界 + §5 contract），(2) pathlab/pathlab-client/server/paper_agent/MIGRATIONS.md，(3) /Users/wangyihui/code/PathLab/docs/plan/paper_generation_agent_design.md 的 M6b 段、§5.4.6 plotting prompt 模板、§13.1 figures_manifest.json 断言。

任务：(1) 起 src/pathlab_paper_agent/agents/plotting_agent.py（agents/ 已经在 M7 建好），读 drafts/outline.json 的 plotting_plan，按 backend 字段派遣：deterministic_plotting → 调 plotting/ 下对应 M6a generator 出 figures/<id>.{pdf,png}；paperbanana → fallback 到 requires_user_revision（M6c 暂未实装，主流水线不阻塞）；user_revision → manifest 标 status=user_provided。(2) 每张图调一次短 LLM 写 caption（不要长篇叙事），prompt 在 prompts/plotting_caption_v1.txt。(3) 写最终 figures/manifest.json：figure_id / status / source / generator / kind / caption。(4) 替掉 stages/plotting.py 现在的 scaffold，走 agent flow。

主要写 agents/plotting_agent.py、stages/plotting.py、prompts/plotting_caption_v1.txt、tests/plotting/。不要改 schemas.py / pipeline.py / conftest.py / collector / evidence / citations / validators / renderers；不要改 plotting/ 里 M6a 的 generator 实现（按 plan 调，不动 generator 本身）；不要改 agents/outline_agent.py 或 llm/。tests/plotting/ 全部 mock LLM，CI 不跑真实调用。完成后跑 uv run pytest -q 和 uv run ruff check src tests。
```

M8b Literature Review Agent：

```text
你在 /Users/wangyihui/code/PathLab-worktrees/m8b-literature 工作。只负责 M8b Literature Review Agent。先按顺序读：(1) pathlab/pathlab-client/server/paper_agent/PARALLEL_WORKTREES.md（§4 M8b 边界 + §5 contract），(2) pathlab/pathlab-client/server/paper_agent/MIGRATIONS.md（特别是 2026-05-04 m8a→sections 那条 forward hook），(3) /Users/wangyihui/code/PathLab/docs/plan/paper_generation_agent_design.md 的 M8b 段、§5.4.7 literature prompt 模板、§13.1 citation_constraints.json 断言，(4) PaperOrchestra App. F.3。

任务：(1) 起 src/pathlab_paper_agent/agents/literature_review_agent.py。(2) 读 drafts/outline.json 的 macro_lit_search + micro_lit_clusters，第 1 次 LLM 调用把每条展开成具体 S2/PubMed 查询。(3) 把 M8a 的 citations/ 模块当 library 调（semantic_scholar / pubmed / verifier / ref_selector / bib_generator / coverage_gate / orphan_cite_gate），10 路并发搜索 + 串行 verify + selected_refs/required_cites 选定 + refs.bib 生成 + coverage_report.json（≥ 90% 不达标 hard fail）。(4) 第 2 次 LLM 调用用 selected_refs 起草 drafts/intro_rw_draft/{introduction,related_work}.tex，每篇引用必须出现在 selected_refs.json 内。M8a 已经把 stages/sections.py 接成 intro_rw_draft → sections 的 forward hook（见 MIGRATIONS）；M8b 只填内容，不动 hook。(5) 替掉 stages/literature.py 现在的 M8a 占位，走 agent flow。

主要写 agents/literature_review_agent.py、stages/literature.py、prompts/lit_search_v1.txt、prompts/intro_rw_draft_v1.txt、tests/literature/。不要改 schemas.py / pipeline.py / conftest.py / collector / evidence / validators / renderers / 其他 stages（含 sections.py）；不要改 citations/ 内部实现（按现有 API 当 library 用，需要新功能就先在 main 协调）；不要改 agents/outline_agent.py 或 llm/。tests/literature/ 全部 mock LLM + S2 + PubMed，CI 不跑真实外网调用。完成后跑 uv run pytest -q 和 uv run ruff check src tests。
```

---

**Wave 3**：

M9 Section Writing Agent：

```text
你在 /Users/wangyihui/code/PathLab-worktrees/m9-sections 工作。只负责 M9 Section Writing Agent。这是 v1 主线最重的一条 LLM track —— 一次多模态 LLM 调用装配整篇正文。先按顺序读：(1) pathlab/pathlab-client/server/paper_agent/PARALLEL_WORKTREES.md（§4 M9 边界 + §5 contract），(2) pathlab/pathlab-client/server/paper_agent/MIGRATIONS.md，(3) /Users/wangyihui/code/PathLab/docs/plan/paper_generation_agent_design.md 的 M9 段、§5.5.1 placeholder rendering、§13.1 section_constraints.json 断言，(4) PaperOrchestra App. F.4。

任务：(1) 起 src/pathlab_paper_agent/agents/section_writing_agent.py，单次多模态 LLM 调用装配整篇 sections。输入：drafts/outline.json + drafts/intro_rw_draft/{introduction,related_work}.tex（M8b）+ figures/manifest.json（M6b）+ citations/{refs.bib,selected_refs.json,required_cites.json}（M8b）+ locked_blocks/*.tex（M3+M5）。(2) **强制占位符语法**：metric → {{m:metric_key}}，引用 → [CITE:paperId]。LLM 不能直接写数字、不能直接 \cite{}。(3) **A2 引用契约**：可润色 intro_rw_draft 文风，但不能删 required_cites.json 里任何 paperId，不能新增 selected_refs.json 之外的 paperId。(4) 接两个 renderer 收尾：renderers/metric_renderer.py（M10a 已交，{{m:...}} → evidence_lock 数字）+ 新建 renderers/citation_renderer.py（[CITE:paperId] → \cite{paperId}）。(5) 替掉 stages/sections.py 现有的 scaffold + intro_rw_draft hook，走 agent flow（intro/RW 优先读 M8b draft 这条语义保留）。(6) M10a deterministic guards（metric / identifier / latex / citation）必须 100% 通过。

主要写 agents/section_writing_agent.py、stages/sections.py、renderers/citation_renderer.py、prompts/section_writing_v1.txt、tests/sections/。不要改 schemas.py / pipeline.py / conftest.py / collector / evidence / citations / validators / 其他 stages / agents 里其他 agent / llm/ / renderers 里其他 renderer。tests/sections/ 全部 mock LLM，CI 不跑真实调用，沿用 M7 的 _NoNetworkLLM pattern + PAPER_GEN_LLM_ALLOW_NETWORK_IN_TESTS=1 显式 opt-in。完成后跑 uv run pytest -q 和 uv run ruff check src tests。
```

---

**Wave 4A**：

M10b Claim/Consistency Guards：

```text
你在 /Users/wangyihui/code/PathLab-worktrees/m10b-guards 工作。只负责 M10b LLM-output guards。先按顺序读：(1) pathlab/pathlab-client/server/paper_agent/PARALLEL_WORKTREES.md（§4 M10b 边界 + §5 contract），(2) pathlab/pathlab-client/server/paper_agent/MIGRATIONS.md，(3) /Users/wangyihui/code/PathLab/docs/plan/paper_generation_agent_design.md 的 M10b 段、§11 设计误区列表（claim guard 那条）。

任务：(1) 起 src/pathlab_paper_agent/validators/claim_guard.py。扫 drafts/sections/*.tex，检测 keyword（external validation / independent cohort / generalization to / outperforms / state-of-the-art / SOTA / significantly / statistically significant / real world deployment 等）。从 evidence_lock.private.json **派生** has_external_validation / has_baseline / has_statistical_test 三个 flag（不要让 M3 加新字段，从已有结构派生：has_external_validation = bool(evidence_lock["external_validation"])，has_baseline = 任一 source_task role=="baseline"，has_statistical_test = metrics 含 ci_/p_value）。当正文有 keyword 但 evidence 不支持时 hard fail。(2) 起 src/pathlab_paper_agent/validators/consistency_guard.py，检测段落串扰（test 段出现 val/external 数字、external 段出现 internal 数字）。可走 metric_renderer 反向：把 evidence_lock 的 metric 按 task/split 索引，扫每个 section 的 \metricXxx macro，看是否落在该 section 应引用的 task/split 子集里。(3) 接进 stages/validating.py，在 M10a 4 个 guard 之后跑 claim 和 consistency。每条 guard 写 validation/<guard>.json + 汇总 validation/warnings.md（沿 M10a 现有格式）。

主要写 validators/claim_guard.py、validators/consistency_guard.py、stages/validating.py、tests/guards/test_m10b_*.py。不要改 schemas.py / pipeline.py / conftest.py / collector / evidence / citations / renderers / agents / llm / 其他 stages；不要改 M10a 已交的 validators/{metric,identifier,latex,citation,common}_guard.py 内部实现（沿用 GuardReport / tex_files_under / rel_to_run 等 helper）。完成后跑 uv run pytest -q 和 uv run ruff check src tests。不接 LLM —— 这两个 guard 是确定性的关键词检测 + evidence_lock cross-reference。
```

M12a ZIP Export 硬化：

```text
你在 /Users/wangyihui/code/PathLab-worktrees/m12a-export 工作。只负责 M12a ZIP export 硬化（dependency-closed bundle + dry-run latexmk + 双模板 main.pdf 编译）。先按顺序读：(1) pathlab/pathlab-client/server/paper_agent/PARALLEL_WORKTREES.md（§4 M12a 边界 + §5 contract），(2) pathlab/pathlab-client/server/paper_agent/MIGRATIONS.md，(3) /Users/wangyihui/code/PathLab/docs/plan/paper_generation_agent_design.md 的 M12 段、§3.7 文件 allowlist、§5.3 私有/公开数据契约。**注意 M12 整体被拆成 M12a 和 M12b**：你只做 M12a（packaging + 编译验证），不要碰 regenerate API（那是 M12b，要等 M11 refinement_loop）。

任务：(1) 扩 src/pathlab_paper_agent/renderers/zip_exporter.py，每个模板各打一个 dependency-closed ZIP，含 main.tex / refs.bib / 全部 .cls .bst（M4 模板下）/ figures/*.{pdf,png}（M6b ready 的）/ locked_blocks/*.tex（M3+M5）/ tables/*.tex / README.md。**禁止**含 evidence_lock.private.json / raw_collected/ / intro_rw_draft/（保数据契约）。(2) 新建 src/pathlab_paper_agent/renderers/bundle_validator.py：bundle 打完后解压到临时目录，进 pathlab/pathlab-client/docker/paper-latex/ container（M4 已建）跑 latexmk -dvi=0 -ps=0 -pdf -interaction=nonstopmode。返回码非零 → bundle 标 downloadable=False，错误日志摘要写进 validation/warnings.md。(3) 双模板 final/{template}/main.pdf 编译成功（调 M4 已有的 latex_compiler.py）。(4) 扩 stages/exporting.py，在 M4 已有 export 流程后挂上 dependency-closure 检查 + dry-run validate + manifest 标记 downloadable。(5) 测试用 fixture wsi_classification_minimal/，端到端跑 export，断言 ZIP 内容树 + dry-run 通过 + main.pdf 出文件 + 不含 private 资料。

主要写 renderers/zip_exporter.py、renderers/bundle_validator.py、stages/exporting.py、tests/exporting/。不要改 schemas.py / pipeline.py / conftest.py / collector / evidence / citations / validators / agents / llm / 其他 stages；不要改 M4 的 renderers/template_renderer.py / renderers/latex_compiler.py 内部实现（按现有 API 调）；不要改 M5 的 renderers/locked_block_renderer.py。**M11 territory（agents/refinement_agent.py 等）和 M12b territory（POST regenerate 路由）严格不动**。完成后跑 uv run pytest -q 和 uv run ruff check src tests。不接 LLM —— 纯 packaging + 编译验证。
```

---

**Wave 4B**：

M11 Refinement Loop：

```text
你在 /Users/wangyihui/code/PathLab-worktrees/m11-refinement 工作。只负责 M11 Refinement Loop。这是 v1 主线倒数第二条 LLM track —— critic-driven 多轮重写循环。先按顺序读：(1) pathlab/pathlab-client/server/paper_agent/PARALLEL_WORKTREES.md（§4 M11 边界 + §5 contract），(2) pathlab/pathlab-client/server/paper_agent/MIGRATIONS.md（特别是 2026-05-05 refining stage scaffold 那条 —— pipeline dispatch 已经接好，你只填 stage body），(3) /Users/wangyihui/code/PathLab/docs/plan/paper_generation_agent_design.md 的 M11 段 + §10 + §11 设计误区里"refinement loop 不能无限循环改到好"那条，(4) PaperOrchestra App. F.5。

任务：(1) 起 src/pathlab_paper_agent/agents/content_refinement_agent.py。一轮里两次 LLM 调用：critic（5 个 PathLab tuned rubric 维度，每项 0-5 整数 + 一句话理由 + overall）→ revise（拿 critic 反馈重写需要修的章节）。revise 必须保留 M9 的占位符约束（{{m:...}} + [CITE:paperId]）和 A2 cite 契约（不能删 required_cites，不能加 selected_refs 之外）。(2) 替掉 stages/refining.py 的 no-op scaffold，跑 ≤ 3 轮 critic→revise→guards→accept/revert 循环。(3) **物理 snapshot**：每次接受重写前先 copy drafts/sections/* 到 drafts/snapshots/iter_{N}/sections/。(4) **物理 revert**：拒绝时把上一轮 snapshot copy 回 drafts/sections/。(5) **单调收敛**：score 严格上升 → 接受；平局 → 每个子项不能负退化才接受；下降 → 拒绝。(6) **score 是 hybrid**：M10a + M10b 的 GuardReport（fail 直接 force reject 该轮）+ critic 的 5 维 rubric 总分。(7) revise 后跑 M9 的 citation_renderer + M10a 的 metric_renderer 收尾。(8) 写 validation/refinement_log.json 记录每轮 score / 接受/拒绝原因 + iter snapshot 清单。

主要写 agents/content_refinement_agent.py、stages/refining.py、prompts/refinement_critic_v1.txt、prompts/refinement_revise_v1.txt、tests/refinement/。不要改 schemas.py / pipeline.py / conftest.py（contract — main 已经协调好 refining dispatch 占位）；不要改 collector / evidence / citations / validators / renderers 的内部实现（按现有 API 调）；不要改 agents/ 其他 agent / llm/ / 其他 stages。tests/refinement/ 全部 mock LLM，沿用 M7 的 _NoNetworkLLM pattern + PAPER_GEN_LLM_ALLOW_NETWORK_IN_TESTS=1 显式 opt-in；至少要有：score 上升接受、score 持平且无负退化接受、score 下降拒绝物理 revert、guard fail force reject 这四条 test。完成后跑 uv run pytest -q 和 uv run ruff check src tests。
```

## 8. 合并顺序与 post-merge 回归

### 8.1 推荐合并顺序

**Wave 1（已完成）**：

```text
1. M2 Collector      ← 已合（commit 25ef559e）
2. M4 Templates      ← 已合（commit 91d741e0）
3. M8a Citations     ← 已合（commit 55e502a7）
4. M10a Guards       ← 已合（commit 736163fd）
5. M6a Figures       ← 已合（commit 1b63c762）
6. M3 PHI + Evidence ← 已合（commit a87b3f83，phase01 内补做）
```

**Wave 2A（已完成）**：

```text
1. M5 Locked Blocks Renderer ← 已合（commit e5da8319）
2. M7 Outline Agent          ← 已合（commit 1a9593b2）
```

**Wave 2B（已完成）**：

```text
1. M8b Literature Review     ← 已合（commit db40f79c，先合给 M9 早早解锁）
2. M6b Plotting Agent        ← 已合（commit 6f7bc75f）
```

**Wave 3（已完成）**：

```text
1. M9 Section Writer         ← 已合（commit 7cbb2f61）
```

**Wave 4A（已完成）**：

```text
1. M10b Claim/Consistency Guards ← 已合（commit 31436967）
2. M12a ZIP Export 硬化          ← 已合（commit 2d592300）
```

**Wave 4B（当前）**：

```text
1. M11 Refinement Loop          ← 单条 track；用 M10a + M10b 的 guard 当 score 输入
```

**Wave 4C（M11 合后）**：

```text
M12b Section Regenerate API   ← 单条 track；POST /papers/{id}/sections/{name}/regenerate，重跑 guards + refinement
```

**Optional / 可滑出 v1**：

```text
M6c PaperBanana adapter       ← 完全独立，任何时候插队都行；如果 v1 deadline 紧就留到 v1.1
```

### 8.2 单条 track merge 前的本地 check

```bash
cd /Users/wangyihui/code/PathLab-worktrees/<name>/pathlab/pathlab-client/server/paper_agent
uv run pytest -q
uv run ruff check src tests
```

### 8.3 合并回主分支

```bash
cd /Users/wangyihui/code/PathLab
git switch paper-agent-phase01
git merge --no-ff paper/<branch-name>
```

`--no-ff` 让每条 track 的提交集合保留为一个 merge commit，方便 `git revert -m 1 <merge_sha>` 整组撤回。

### 8.4 ★ Post-merge 回归扫荡（必须做）

每条 track merge 进 main 后，**在合下一条 track 之前**：

```bash
# 一键脚本：对所有未合并 worktree rebase 并跑测试
for w in m2-collector m4-templates m6a-figures m8a-citations m10a-guards; do
  if [ -d "/Users/wangyihui/code/PathLab-worktrees/$w" ]; then
    echo "=== $w ==="
    cd "/Users/wangyihui/code/PathLab-worktrees/$w"
    git fetch origin
    git rebase origin/paper-agent-phase01 || { echo "rebase fail in $w"; break; }
    cd pathlab/pathlab-client/server/paper_agent
    uv run pytest -q || echo "PYTEST FAIL in $w"
  fi
done
```

任何一条 worktree 因为新合入的改动而 pytest 挂掉，**阻塞下一条 track 的 merge**，让 hat track 的 owner 先修。

### 8.5 冲突保护优先级

如果 merge 冲突，优先保护这些（按重要性）：

1. private evidence 不外泄（§5.3）
2. CLI / dev service / TaskWorker subprocess contract（§5.1）
3. `schemas.py` 字段不被重命名/改类型（§5.2）
4. `pipeline.py` thin orchestrator 形态（§5.2）
5. `manifest.artifact_index` 的 status / visibility 枚举值不被改语义（§5.3）

### 8.6 整组 rollback

如果某条 track merge 进去后才发现下游问题（M2 之后才发现 schema 漏了字段、或 M10a 之后才发现 guard 误判合法 draft），用：

```bash
git revert -m 1 <merge_commit_sha>     # 整组回滚那条 track
```

然后：
1. 在 `MIGRATIONS.md` 登记 rollback 原因
2. 让 track owner 在自己 worktree 里修，重新走一遍 merge 流程
