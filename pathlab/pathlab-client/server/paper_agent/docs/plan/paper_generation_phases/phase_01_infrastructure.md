# Phase 01 — Infrastructure / Run Management

## 目标

建立 paper generation 的运行基础设施：DB run 记录、运行目录、基础 API、CPU/LLM queue、LaTeX 编译环境。这个阶段不接 LLM、不做真实论文生成，只保证任务可以被创建、跟踪、取消、查询和编译 hello-world LaTeX。

## 输入

- 用户请求：`POST /papers`
- 可选 `task_id` / `template_id`
- PathLab 配置：uploads 根目录、数据库连接、任务队列配置

## 输出

```text
uploads/paper_generation/{paper_id}/
├── manifest.json
├── config.json
├── inputs/
├── evidence/
├── tables/
├── locked_blocks/
├── figures/
├── citations/
├── drafts/
├── validation/
├── final/
└── exports/
```

## 代码范围

```text
pathlab/pathlab-client/server/gateway/paper_generation/routes.py      # thin frontend bridge
pathlab/pathlab-client/server/backend/database/repositories/paper_generation.py
pathlab/pathlab-client/server/task_worker/jobs/paper_generation.py
pathlab/pathlab-client/server/paper_agent/docker/paper-latex/

pathlab/pathlab-client/server/paper_agent/                 # uv 独立环境
├── pyproject.toml
├── uv.lock
├── .python-version
└── src/pathlab_paper_agent/
    ├── cli.py                      # run / run-stage / serve
    ├── dev_server.py               # 开发期 standalone FastAPI
    ├── api/routes.py               # /papers implementation
    ├── pipeline.py
    ├── schemas.py
    └── storage.py

pathlab/pathlab-client/src/renderer/src/api/papers.ts          # 前端 API client 预留
pathlab/pathlab-client/src/renderer/src/pages/PaperGenerationPage.tsx
pathlab/pathlab-client/src/renderer/src/pages/PaperRunDetailPage.tsx
```

## 实施步骤

1. 新增 `paper_generation_runs` 表或 repository prototype。
2. 新增 `PaperGenerationConfig` / `PaperGenerationRun` / `PaperGenerationStatus` schema。
3. 创建 `uploads/paper_generation/{paper_id}/` 目录骨架。
4. 写入初始 `config.json` 和 `manifest.json`。
5. 增加基础 API：
   - `POST /papers`
   - `GET /papers`
   - `GET /papers/{paper_id}`
   - `DELETE /papers/{paper_id}`
   - `GET /papers/{paper_id}/files/{path}` shell
6. `GET-files` 先实现 allowlist + path normalization：拒绝 `..`、绝对路径、symlink escape、未登记 artifact。
7. 接入 CPU/LLM worker queue，明确 `requires_gpu=false`。
8. 建 `pathlab/pathlab-client/server/paper_agent/docker/paper-latex/`，跑通 hello-world `latexmk`。
9. 建 `server/paper_agent/` uv 独立环境：
   - `uv init --package --python 3.12`
   - 提交 `pyproject.toml` / `uv.lock` / `.python-version`
   - 不提交 `.venv/`
   - 暴露 CLI：`pathlab-paper-agent run --paper-id ...`
   - 暴露逐阶段命令：`pathlab-paper-agent run-stage --paper-id ... --stage collecting`
   - 暴露开发服务：`pathlab-paper-agent serve --host 127.0.0.1 --port 6200`
10. TaskWorker 先用 subprocess 调 CLI，不把 paper agent 依赖塞进 Gateway 进程。
11. 前端预留接口：
   - 新增 `src/renderer/src/api/papers.ts`
   - `api/index.ts` 导出 `papers`
   - 新增 `/papers` 和 `/papers/:paper_id` 页面壳
   - `ToolsPage` 加 Paper Generator 入口卡片
   - 详情页先用 polling 查询 `GET /papers/{id}`

## 开发期 standalone service

Phase 01 就要保证 paper agent 可以不通过 Electron / Gateway 单独启动：

```bash
cd pathlab/pathlab-client/server/paper_agent
uv sync
uv run pathlab-paper-agent serve \
  --host 127.0.0.1 \
  --port 6200 \
  --uploads-dir "$PATHLAB_UPLOADS_DIR"
```

dev service 的接口保持 Gateway `/papers` contract 的最小子集：

```text
GET  /health
POST /papers
GET  /papers/{paper_id}
POST /papers/{paper_id}/stages/{stage}:run
GET  /papers/{paper_id}/files?path=...
```

这样可以按阶段测试：

```bash
curl http://127.0.0.1:6200/health
curl -X POST http://127.0.0.1:6200/papers
curl -X POST http://127.0.0.1:6200/papers/paper_dev_001/stages/collecting:run
curl -X POST http://127.0.0.1:6200/papers/paper_dev_001/stages/building_evidence:run
```

注意：dev service 只用于构建和联调；产品里仍然是 Gateway 创建 run、TaskWorker subprocess 执行 `pathlab-paper-agent run`。

## Manifest 状态机

```text
created
collecting
building_evidence
outlining
plotting
literature_review
section_writing
validating
refining
rendering
exporting
completed
failed
cancelled
```

## 验收标准

- `POST /papers` 返回 `paper_id`，并创建完整目录骨架。
- `GET /papers/{paper_id}` 能返回当前阶段、错误信息、artifact 列表。
- `GET-files` 默认只能下载 public artifact，private artifact 返回 403。
- 前端能调用 `POST /papers`，创建后跳转 `/papers/{paper_id}` 并轮询状态。
- 前端 artifact 列表只显示 `visibility=public && downloadable=true` 的文件。
- `server/paper_agent/` 能 `uv sync`，并能 `uv run pathlab-paper-agent --help`。
- `server/paper_agent/` 能单独 `uv run pathlab-paper-agent serve --port 6200`，`GET /health` 返回 ok。
- `run-stage` 能执行 stub stage，并更新 `manifest.json.current_stage` / `stage_history`。
- TaskWorker 能用 `uv run --project server/paper_agent ...` 启动 paper agent CLI。
- CPU worker 能消费 paper job，不占用 GPU queue。
- LaTeX container 能独立编译 hello-world PDF。

## 风险

- 不要把 paper job 塞进训练 GPU queue。
- 不要把 `GET-files` 写成裸文件服务器。
- 不要把 `evidence_lock.private.json` 这类 private artifact 暴露给前端。
