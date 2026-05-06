# Paper Agent 并行 Worktree 执行计划

> 创建日期：2026-05-04  
> 当前基线 commit：`ca901bd3 chore(paper): split stages for parallel worktrees`  
> 适用范围：Phase 01 scaffold 已完成之后，多个 agent 并行实现真实 paper generation backend。

## 0. 先读这个结论

现在**需要开 worktree**。原因不是代码量大，而是 5 条 Day-1 track 会同时改 `server/paper_agent`，如果都在一个工作目录里做，很容易互相覆盖。

当前已经准备好 5 个独立 worktree，每个 worktree 对应一条分支和一个明确写入范围。其他 agent 开工时，直接进入对应 worktree，不要在主目录 `/Users/wangyihui/code/PathLab` 里改。

## 1. 当前已准备好的 worktree

| Track | Branch | Worktree | Agent 主要负责 |
|---|---|---|---|
| M2 Collector | `paper/m2-collector` | `/Users/wangyihui/code/PathLab-worktrees/m2-collector` | 从 PathLab DB / uploads 收集 task、dataset、split、model、analysis，产出 collector schema |
| M4 Templates | `paper/m4-templates` | `/Users/wangyihui/code/PathLab-worktrees/m4-templates` | MICCAI / Nature SR 模板、renderer、LaTeX compile、export bundle |
| M6a Figures | `paper/m6a-figures` | `/Users/wangyihui/code/PathLab-worktrees/m6a-figures` | empirical figure generators，mock data 单测，后续给 Plotting Agent 调用 |
| M8a Citations | `paper/m8a-citations` | `/Users/wangyihui/code/PathLab-worktrees/m8a-citations` | S2 / PubMed clients、verifier、ref selector、BibTeX generator、coverage gate |
| M10a Guards | `paper/m10a-guards` | `/Users/wangyihui/code/PathLab-worktrees/m10a-guards` | metric / identifier / latex / orphan-cite / coverage deterministic guards |

确认命令：

```bash
git -C /Users/wangyihui/code/PathLab worktree list
```

当前所有 worktree 都应该指向同一个基线：

```text
ca901bd3 chore(paper): split stages for parallel worktrees
```

## 2. 给其他 agent 的开工流程

每个 agent 只做自己的 track，按这个顺序启动：

```bash
cd /Users/wangyihui/code/PathLab-worktrees/<worktree-name>
git status --short --branch
cd pathlab/pathlab-client/server/paper_agent
uv sync
uv run pytest -q
uv run ruff check src tests
```

如果测试通过，再开始实现。每个 agent 开工前必须读：

```bash
sed -n '1,260p' pathlab/pathlab-client/server/paper_agent/PARALLEL_WORKTREES.md
```

注意：`docs/` 在当前 repo 里是 ignored，本地可读但不一定会出现在各个 worktree。真正给其他 agent 用的工程约束已经同步写在：

```text
pathlab/pathlab-client/server/paper_agent/PARALLEL_WORKTREES.md
```

如果需要读总设计文档，用主目录绝对路径：

```text
/Users/wangyihui/code/PathLab/pathlab/pathlab-client/server/paper_agent/docs/plan/paper_generation_agent_design.md
/Users/wangyihui/code/PathLab/pathlab/pathlab-client/server/paper_agent/pathlab/pathlab-client/server/paper_agent/docs/plan/paper_generation_phases/parallel_worktree_plan.md
```

## 3. 为什么先拆 stage module

Phase 01 scaffold 原来把所有 `_stage_*` 都放在：

```text
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/pipeline.py
```

这不适合并行，因为 M2 / M4 / M6 / M8 / M10 都会改同一个文件。现在已经拆成：

```text
src/pathlab_paper_agent/stages/
  collecting.py      # M2 collector entry point
  evidence.py        # M3 PHI scrub + evidence lock entry point
  outlining.py       # M7 outline agent entry point
  plotting.py        # M6 plotting entry point
  literature.py      # M8 literature/citation entry point
  sections.py        # M9 section writer entry point
  validating.py      # M10 guards entry point
  rendering.py       # M4/M11 renderer entry point
  exporting.py       # M11 bundle export entry point
```

并行开发原则：

- `pipeline.py` 继续保持 thin orchestrator，只负责 stage dispatch、manifest 更新、错误处理。
- 各 track 优先在自己的 package 里加真实逻辑，再接到对应 `stages/*.py`。
- 不要把真实 collector / citation / validator / renderer 逻辑继续塞回 `pipeline.py`。

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
pathlab/pathlab-client/server/paper_agent/docker/paper-latex/
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
你在 /Users/wangyihui/code/PathLab-worktrees/m2-collector 工作。只负责 paper agent 的 M2 Collector。先读 pathlab/pathlab-client/server/paper_agent/docs/plan/paper_generation_phases/parallel_worktree_plan.md 和 pathlab/pathlab-client/server/paper_agent/PARALLEL_WORKTREES.md。主要写 collector/ 和 stages/collecting.py，不要改其他 track 的 stage。实现后跑 uv run pytest -q 和 uv run ruff check src tests。
```

M4：

```text
你在 /Users/wangyihui/code/PathLab-worktrees/m4-templates 工作。只负责 M4 Templates / Renderer / LaTeX export。先读 parallel plan。主要写 templates/、renderers/、stages/rendering.py、stages/exporting.py、pathlab/pathlab-client/server/paper_agent/docker/paper-latex/。不要改 collector/citations/validators。实现后跑 paper_agent tests、ruff，并做一个 run-stage rendering/exporting smoke。
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

## 8. 合并顺序与 post-merge 回归

### 8.1 推荐合并顺序

```text
1. M2 Collector      ← 影响 M3 evidence schema，先合让下游有真 schema rebase
2. M4 Templates      ← 影响 locked blocks 和 renderer
3. M8a Citations     ← 与 M10a citation guard 有交集
4. M10a Guards
5. M6a Figures       ← 相对独立，可以后合
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

任何一条 worktree 因为新合入的改动而 pytest 挂掉，**阻塞下一条 track 的 merge**，让 track owner 先修。

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
