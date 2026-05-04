# Paper Agent 并行 Worktree 执行计划

> 当前基线 commit：`a1cd831e docs(paper/m3): record M3 commit hash in MIGRATIONS.md`  
> 适用范围：Phase 01 scaffold + Wave 1 已落地后，多 agent 并行实现 paper generation backend 后续 milestone。  
> 注意：`docs/` 目录在当前 repo 里是 ignored，worktree 里不一定能看到 docs；所以其他 agent **优先读本文件**。

## 0. 先读这个结论

**Wave 1 已合并**（M2 collector / M4 templates / M6a figures / M8a citations / M10a guards），紧跟着 **M3 PHI scrub + evidence bundle** 也已落 phase01。原 5 个 Wave 1 worktree 全部 stale，建议清掉。

**Wave 2A 现在开两条并行 track**：

- **M5 Locked Blocks Renderer** —— 把 M3 内嵌的 `_render_locked_blocks` 搬出来，做成模板感知的 Jinja2 renderer。纯确定性，不依赖 LLM。
- **M7 Outline Agent** —— 第一条 LLM track；要顺手把 LLM provider 模块（httpx + 三档 env override + streaming）建起来。

两条 track 写入文件零交集，可同时跑。后续 Wave 2B = M6b + M8b 都依赖 M7，所以 M7 越早合并越好。

## 1. 当前 worktree 现状

### 1.1 Wave 2 active

| Track | Branch | Worktree | Agent 主要负责 |
|---|---|---|---|
| M5 Locked Blocks | `paper/m5-locked-blocks` | `/Users/wangyihui/code/PathLab-worktrees/m5-locked-blocks` | 把 M3 emit 的 `locked_blocks/*.tex` 抽出来做成 Jinja2 + template-aware renderer，建 byte-identical golden fixture |
| M7 Outline Agent | `paper/m7-outline` | `/Users/wangyihui/code/PathLab-worktrees/m7-outline` | LLM provider 模块 + Outline Agent（PaperOrchestra App. F.1）+ outline.json schema validate |

起 worktree 命令（如果还没起）：

```bash
git -C /Users/wangyihui/code/PathLab worktree add -b paper/m5-locked-blocks \
  /Users/wangyihui/code/PathLab-worktrees/m5-locked-blocks paper-agent-phase01

git -C /Users/wangyihui/code/PathLab worktree add -b paper/m7-outline \
  /Users/wangyihui/code/PathLab-worktrees/m7-outline       paper-agent-phase01
```

### 1.2 Wave 1（已合并，worktree 可清）

| Track | Branch | 合并 commit |
|---|---|---|
| M2 Collector | `paper/m2-collector` | `25ef559e` |
| M4 Templates | `paper/m4-templates` | `91d741e0` |
| M6a Figures | `paper/m6a-figures` | `1b63c762` |
| M8a Citations | `paper/m8a-citations` | `55e502a7` |
| M10a Guards | `paper/m10a-guards` | `736163fd` |

清理（合完之后可以直接做）：

```bash
cd /Users/wangyihui/code/PathLab
for w in m2-collector m4-templates m6a-figures m8a-citations m10a-guards; do
  git worktree remove --force "/Users/wangyihui/code/PathLab-worktrees/$w" 2>/dev/null
  git branch -D "paper/$w" 2>/dev/null
done
```

### 1.3 确认

```bash
git -C /Users/wangyihui/code/PathLab worktree list
```

所有活跃 worktree 都应该基于同一条主线 commit；当前为：

```text
a1cd831e docs(paper/m3): record M3 commit hash in MIGRATIONS.md
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
  evidence.py        # M3 PHI scrub + evidence lock     ← 已落地（M3，含 minimal locked_blocks 输出）
  outlining.py       # M7 outline agent entry point     ← 现在是 hardcoded scaffold，M7 接手
  plotting.py        # M6 plotting entry point          ← scaffold
  literature.py      # M8 literature/citation           ← 已落地（M8a deterministic 部分）
  sections.py        # M9 section writer                ← scaffold + intro_rw_draft hook
  validating.py      # M10 guards                       ← 已落地（M10a deterministic guards）
  rendering.py       # M4/M11 renderer entry point      ← 已落地（M4）
  exporting.py       # M11 bundle export entry point    ← 已落地（M4 ZIP export）
```

并行开发原则：

- `pipeline.py` 继续保持 thin orchestrator，只负责 stage dispatch、manifest 更新、错误处理。
- 各 track 优先在自己的 package 里加真实逻辑，再接到对应 `stages/*.py`。
- 不要把真实 collector / citation / validator / renderer 逻辑继续塞回 `pipeline.py`。

**M3 临时领地**（M5 启动后归还）：M3 在 `evidence/bundle.py` 里同时生成了 `locked_blocks/*.tex` 和 `tables/*.tex`。这是 forward hook，本应是 M5 的范围。M5 启动时把这部分逻辑搬到 `renderers/locked_block_renderer.py` 即可，不需要登记 MIGRATIONS（不动公开 contract surface）。

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

**Wave 2A（当前）**：

```text
1. M5 Locked Blocks Renderer ← 先合：M9 / M11 都要 byte-identical locked blocks
2. M7 Outline Agent          ← 后合：合完立即解锁 Wave 2B = M6b + M8b
```

两条 track 写入零交集，可以同时跑；merge 顺序只是给下游的 unblock 节奏建议，谁先完成谁先 merge 也行。

**Wave 2B（M7 合后再开）**：

```text
1. M6b Plotting Agent        ← 读 outline.plotting_plan 编排 M6a generators
2. M8b Literature Review     ← 读 outline.macro_lit_search/micro_lit_clusters，调 M8a chain
```

**Wave 3（M5 + M6b + M8b 合后）**：

```text
M9 Section Writer → M10b LLM-output guards → M11 Refinement Loop → M12 Regenerate + ZIP
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
