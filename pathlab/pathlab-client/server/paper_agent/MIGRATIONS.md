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
