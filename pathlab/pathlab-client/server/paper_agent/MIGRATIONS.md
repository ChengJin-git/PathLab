# Paper Agent Contract Migrations

> 5 条 track 并行开发期间，凡是改 `PARALLEL_WORKTREES.md` §5 列出的 contract 文件
> （`pipeline.py` thin form / `schemas.py` 字段 / `tests/conftest.py` /
> CLI / dev service / artifact layout / private/public 边界），**必须**
> 先在 main 改、登记到本文件、再让所有 worktree rebase 同步。
>
> 单纯加新模块（collector/、citations/、validators/...）或加新私有
> fixture 不需要登记。**只有动 contract 才登记**。

## 怎么写一条 entry

```markdown
## YYYY-MM-DD <短标题>

- **改了什么**：具体改的字段 / 路径 / 接口
- **为什么**：触发原因
- **影响哪些 track**：列出受影响的 worktree 名字
- **action 要求**：受影响 worktree 必须做什么（rebase / 改测试 / 改 prompt 等）
- **commit**: `<hash>`
```

每条 entry 写完后：

1. push 到 main / `paper-agent-phase01`。
2. 在每条受影响的 track 群里（或 issue 评论里）@track owner，让他们在自己 worktree 跑：
   ```bash
   git fetch origin
   git rebase origin/paper-agent-phase01
   uv run pytest -q
   ```
3. 任一 worktree pytest 挂掉，track owner 必须修；修完才能继续合后续 track。

---

## Migrations log

<!-- 按时间倒序加新条目；最近的在最上 -->

## 2026-05-04 phase03 public evidence download allowlist

- **改了什么**：`gateway.paper_generation.storage._ALLOWED_EXACT` 新增
  `evidence/dataset_summary.public.json`、`evidence/model_summary.public.json`、
  `evidence/analysis_summary.public.json`，配合 Phase 03 evidence stage 输出可下载的
  scrubbed public summaries。
- **为什么**：Phase 03 把 private evidence lock 派生为多个 LLM/public-facing evidence
  surfaces；这些文件不包含 private lock、raw paths、case identifiers 或 source mappings。
- **影响哪些 track**：Frontend artifact download / Phase 03 evidence tests。
- **action 要求**：下载 API 继续禁止 `evidence/evidence_lock.private.json` 和
  `evidence/raw_collected/*`；新增 public summaries 必须经过 PHI scrubber。
- **commit**: `TBD`

## 2026-05-04 m8a → sections stage 跨 §4 边界（intro_rw_draft hook）

- **改了什么**：`stages/sections.py` 内部加 `_section_text(...)`，让 introduction / related_work 在生成时**优先**读取 `drafts/intro_rw_draft/{introduction,related_work}.tex`（M8a 起草），不存在时 fallback 到原来的 scaffold 文本。
- **为什么**：M8a Literature Review Agent 的产物是 intro/RW 草稿；它必须能被下游 sections stage 读到。但 `stages/sections.py` 在 §4 写入边界里属于 M9 Section Writer 的领域，按规则 M8a 不应直接改。M9 worktree 还没启动 → 这是个非冲突的 forward hook。
- **影响哪些 track**：M9 Section Writer（启动后第一次 rebase 会拿到这个 hook，需要在 prompt 设计里假设 intro_rw_draft 文件可能已存在）。其它 track 不受影响。
- **action 要求**：M9 owner 启动 worktree 时阅读这条记录；如果 M9 想用别的方式接 intro_rw_draft，需先在 main 协调改回。
- **commit**: `0020e4a7` (在 paper/m8a-citations 上)，merge 进 phase01 时 commit hash 会变。

## 2026-05-04 baseline — initial worktree contract frozen

- **改了什么**：把 `pipeline.py` 拆成 thin orchestrator + `stages/*.py`；
  `schemas.py` 引入 `PaperRunArtifact` / `PaperRunDetail` / `PaperRunStage`
  完整枚举；`tests/` 强制按 track 分子目录；引入本 `MIGRATIONS.md`。
- **为什么**：5 条 Day-1 track 即将并行开干，需要 contract 边界稳定。
- **影响哪些 track**：所有 track（M2 / M4 / M6a / M8a / M10a）。
- **action 要求**：
  - 各 worktree 进入后跑 `git rebase origin/paper-agent-phase01`，确认 baseline 一致。
  - 各 worktree 把已有的 `tests/test_*.py`（如有）移到对应 `tests/<track_name>/`。
  - 不要在 worktree 里改 `schemas.py` 字段名/类型；只允许加新字段。
  - `pipeline.py` 的 dispatch 表只在 main 加；track 内只改对应 `stages/<self>.py`。
- **commit**: `ca901bd3 chore(paper): split stages for parallel worktrees`
