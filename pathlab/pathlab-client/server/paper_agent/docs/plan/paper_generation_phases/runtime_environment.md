# Paper Generation Runtime Environment

> 创建日期：2026-05-04  
> 目标：说明 PathLab Paper Generation Agent 在开发、桌面打包、服务器部署三种场景下的运行环境。

## 1. 总体原则

Paper generation 的**产品形态**不应该做成独立重型服务。它应该复用 PathLab 当前 sidecar 架构：

```text
Electron / Browser
      │
      ├── src/renderer/src/api/papers.ts
      ├── /papers
      └── /papers/:paper_id
      │
      ▼
Gateway FastAPI              # POST /papers, GET /papers/{id}, files/export
      │
      ▼
Redis descriptor queue
      │
      ▼
TaskWorker                   # paper_generation job, requires_gpu=false
      │
      ├── PostgreSQL          # task/model/dataset metadata
      ├── uploads/            # analysis artifacts + paper_generation/{paper_id}
      ├── LLM provider         # OpenRouter / local / Vertex
      ├── Citation APIs        # Semantic Scholar / PubMed
      └── LaTeX backend        # docker / tectonic / system latexmk
```

核心要求：

- Paper job 走 CPU/LLM 队列，`requires_gpu=false`，不占 GPU training queue。
- Gateway 只做 API 和 descriptor 入队，不在请求生命周期里跑 LLM / LaTeX。
- TaskWorker 执行 paper pipeline，阶段性写 `manifest.json`。
- LaTeX 编译隔离运行，不污染 PathLab Python 环境。
- LLM 只读脱敏 public artifact；private evidence 只给后端 validator。

开发期例外：`server/paper_agent/` 必须能**单独启动**，方便逐阶段调试 collector、evidence、outline、plotting、literature、section writing、refinement。这个 standalone service 只作为开发入口，不替代最终 Gateway / TaskWorker 集成。

## 2. 开发环境推荐

### 2.1 必需组件

| 组件 | 用途 | 推荐开发方式 |
|---|---|---|
| Python sidecar | Gateway / TaskWorker / collector / agents | 复用 `server/main.py` |
| PostgreSQL | PathLab DB / paper run records | Electron embedded 或本地 Postgres |
| Redis | task descriptor queue / runtime status | Electron embedded 或本地 Redis |
| uploads | 运行时 artifact | `Config.get_uploads_dir()` 默认路径 |
| LaTeX | 编译 MICCAI / Nature SR PDF | Docker `texlive/texlive` 或 Tectonic |
| LLM provider | Outline / Lit / Section / Refinement | OpenRouter 默认，provider 抽象 |
| 网络 | S2 / PubMed / LLM | Citation 和 LLM 阶段需要 |

### 2.1.1 前端接口预留

运行环境里必须同时预留前端 API client 和页面入口，避免后端先做完但 UI 接不上：

```text
src/renderer/src/api/papers.ts
src/renderer/src/pages/PaperGenerationPage.tsx
src/renderer/src/pages/PaperRunDetailPage.tsx
```

路由：

```text
/papers
/papers/:paper_id
```

v1 前端不需要完整编辑器，但至少要支持：

- 创建 paper run。
- 轮询 run 状态和 current stage。
- 显示 validation summary / warnings。
- 只展示 public downloadable artifacts。
- 下载 final ZIP。
- 后续 Phase 11 开放 section regenerate。

详细 contract 见 [`frontend_interface.md`](frontend_interface.md)。

### 2.2 推荐本地启动方式

在 `pathlab/pathlab-client/` 下：

```bash
cp .env.example .env
# 按需填 INTERNAL_API_KEY / JWT_SECRET / DATABASE_URL / OpenRouter fallback 等

# Electron 开发模式：会通过 sidecar-manager 拉起 Python sidecar
npm run dev
```

如果只调 Python sidecar，可用固定端口模式：

```bash
cd pathlab/pathlab-client
export PATHLAB_DEBUG=1
export GATEWAY_PORT=6100
export PREPROCESSING_PORT=6101
export AI_PORT=6102
python server/main.py
```

固定端口模式下：

```text
Gateway       http://127.0.0.1:6100
Preprocessing http://127.0.0.1:6101
AI            http://127.0.0.1:6102
TaskWorker    no HTTP port
```

如果不是通过 Electron embedded services 启动，需要自己准备 PostgreSQL 和 Redis，并保证：

```bash
DATABASE_URL=postgresql+asyncpg://pathlab:pathlab@localhost:5432/pathlab
REDIS_URL=redis://localhost:6379/0
```

### 2.3 Paper agent 单独启动方式

构建阶段需要支持两类独立启动：

```bash
cd pathlab/pathlab-client/server/paper_agent
uv sync

# 1) 单次 CLI 执行：最接近 TaskWorker 生产调用方式
uv run pathlab-paper-agent run \
  --paper-id paper_dev_001 \
  --uploads-dir "$PATHLAB_UPLOADS_DIR" \
  --config "$PATHLAB_UPLOADS_DIR/paper_generation/paper_dev_001/config.json"

# 2) 开发 HTTP service：方便 curl/Postman/前端逐步测试
uv run pathlab-paper-agent serve \
  --host 127.0.0.1 \
  --port 6200 \
  --uploads-dir "$PATHLAB_UPLOADS_DIR"
```

开发 service 至少暴露这些接口：

```text
GET  /health
POST /papers
GET  /papers/{paper_id}
POST /papers/{paper_id}/stages/{stage}:run
GET  /papers/{paper_id}/files?path=...
```

约束：

- `serve` 只用于开发和集成测试；生产仍由 Gateway 暴露 `/papers`，TaskWorker 用 subprocess 调 `run`。
- `serve` 和 Gateway 使用同一套 pipeline / schemas / validators，不能维护两份业务逻辑。
- 前端 v1 默认连 Gateway；需要单独调试时可把 paper API base URL 临时指到 `http://127.0.0.1:6200`。
- `GET /files` 即使在 dev service 里也必须执行 public allowlist、路径归一化、private artifact 403。

## 3. Paper Generation 新增环境变量

建议新增这些配置，全部有默认值，避免影响现有训练链路：

```bash
# Feature flag
PATHLAB_PAPER_GENERATION_ENABLED=1

# Queue / concurrency
PAPER_REQUIRES_GPU=false
PAPER_MAX_CONCURRENT_RUNS=1
PAPER_CITATION_MAX_CONCURRENT_RUNS=1
PAPER_LATEX_MAX_WORKERS=2
PAPER_RUN_RETENTION_DAYS=30

# Artifact safety
PAPER_ALLOW_PRIVATE_ARTIFACT_DOWNLOAD=0
PAPER_KEEP_LLM_RAW_IO=0
PAPER_EXPORT_PRIVATE_EVIDENCE=0

# LLM provider
PAPER_LLM_PROVIDER=openrouter
PAPER_LLM_MODEL=google/gemini-2.5-pro
PAPER_LLM_VISION_MODEL=google/gemini-2.5-pro
PAPER_LLM_TIMEOUT_SECONDS=180
PAPER_LLM_MAX_RETRIES=2

# Citation APIs
SEMANTIC_SCHOLAR_API_KEY=
PUBMED_EMAIL=
PUBMED_API_KEY=
OPENALEX_API_KEY=
OPENALEX_MAILTO=
PAPER_SUBMISSION_CUTOFF_DATE=2026-05-04

# LaTeX backend
PAPER_LATEX_BACKEND=docker       # docker | tectonic | system
PAPER_LATEX_DOCKER_IMAGE=texlive/texlive:latest
PAPER_LATEX_TIMEOUT_SECONDS=180
```

说明：

- OpenRouter API key 应优先走 PathLab Settings；`.env` 只作为开发 fallback。
- `PAPER_KEEP_LLM_RAW_IO=0` 是默认安全值，避免 raw prompt / response 泄露 PHI。
- `PAPER_ALLOW_PRIVATE_ARTIFACT_DOWNLOAD=0` 在产品环境必须保持关闭。


## 4. uv 独立环境策略

可以，而且我建议 **paper agent 用 uv 管一个独立 Python 环境**，但不要把 Gateway 本身拆出去。推荐形态是：

```text
Gateway / TaskWorker 仍然跑在 PathLab 主 sidecar 环境
        │
        └── TaskWorker 用 subprocess 调 paper agent CLI
              │
              └── server/paper_agent/.venv 由 uv 管理
```

这样做的好处：

- paper agent 的 LLM / citation / plotting / LaTeX 辅助依赖不会污染 PathLab 主训练环境。
- 后续升级 paper agent prompt、文献检索、plotting 包时风险更小。
- TaskWorker 和 paper agent 通过 `paper_id + uploads/paper_generation/{paper_id}/manifest.json` 做文件协议，耦合低。

推荐目录：

```text
pathlab/pathlab-client/server/paper_agent/
├── pyproject.toml
├── uv.lock
├── .python-version
├── README.md
├── src/pathlab_paper_agent/
│   ├── __init__.py
│   ├── cli.py                    # pathlab-paper-agent run / run-stage / serve
│   ├── dev_server.py             # dev-only FastAPI app, reuses pipeline
│   ├── pipeline.py
│   ├── schemas.py
│   ├── storage.py
│   ├── collector/
│   ├── evidence/
│   ├── agents/
│   ├── plotting/
│   ├── citations/
│   ├── validators/
│   └── renderers/
└── tests/
```

初始化命令建议：

```bash
cd pathlab/pathlab-client/server
mkdir -p paper_agent/src/pathlab_paper_agent
cd paper_agent

uv init --package --python 3.11
uv add pydantic fastapi "uvicorn[standard]" jinja2 httpx openai redis sqlalchemy asyncpg numpy pandas matplotlib scikit-learn pillow python-dotenv
uv add --dev pytest pytest-asyncio ruff mypy
```

TaskWorker 调用方式：

```bash
uv run --project pathlab/pathlab-client/server/paper_agent \
  pathlab-paper-agent run \
  --paper-id paper_xxx \
  --uploads-dir "$PATHLAB_UPLOADS_DIR" \
  --config uploads/paper_generation/paper_xxx/config.json
```

`pyproject.toml` 里暴露 CLI：

```toml
[project.scripts]
pathlab-paper-agent = "pathlab_paper_agent.cli:main"
```

### 4.1 启动 / 集成方式

| 方式 | 做法 | 优点 | 缺点 | 建议 |
|---|---|---|---|---|
| In-process package | paper_generation 代码直接被 Gateway / TaskWorker import | 简单、无 subprocess | 依赖污染主 sidecar，PyInstaller 更重 | 不推荐作为长期形态 |
| uv CLI | `uv run pathlab-paper-agent run --paper-id ...` | 最接近生产 worker，可单步复现任务 | 不方便手动点接口 | 必须支持 |
| uv dev service | `uv run pathlab-paper-agent serve --port 6200` | 可单独启动，方便 curl/Postman/前端联调 | 只能作为开发入口，不能变成第二套后端 | 必须支持开发期 |
| uv subprocess | TaskWorker 调 `uv run --project server/paper_agent ...` | 环境隔离、容易升级、失败边界清晰 | 需要处理 subprocess 状态和打包 | 推荐生产集成 |

### 4.2 开发 / 部署差异

- **开发环境**：可以依赖本机 `uv`，使用 `uv sync` / `uv run`。
- **服务器部署**：安装阶段执行 `uv sync --frozen`，运行时使用固定 `.venv`。
- **Electron 桌面打包**：不能假设用户机器有 `uv`。应在 build 阶段把 paper agent 环境打进 sidecar，或把 paper agent CLI 用 PyInstaller / standalone venv 打包。

也就是说：**uv 是构建和环境管理工具，不一定是最终用户运行时依赖**。

### 4.3 与 PathLab 主后端的关系

paper agent 独立 venv 仍然可以复用 PathLab 代码，但要显式处理 import 边界：

- 推荐短期：TaskWorker 把必要的 `paper_id`、uploads 路径、DB URL 写进 config，paper agent CLI 自己读 DB / 文件。
- 如果需要 import `server/backend/...`，TaskWorker 启动 subprocess 时设置 `PYTHONPATH=pathlab/pathlab-client/server`，并保证 uv env 里安装兼容依赖。
- 更长期：把共享 DB schema / config 抽成可安装 package，paper agent 用 editable dependency 引入。

### 4.4 uv 环境文件是否进 git

- 提交：`pyproject.toml`、`uv.lock`、`.python-version`。
- 不提交：`.venv/`、`.pytest_cache/`、LLM raw logs、private evidence。
- CI / 部署使用：`uv sync --frozen`。


## 5. LaTeX 编译环境

### 5.1 开发 / 服务器优先：Docker

优点：隔离、可复现、不污染主机。

```text
pathlab/pathlab-client/server/paper_agent/docker/paper-latex/
├── Dockerfile
└── compile.sh
```

Dockerfile 建议：

```dockerfile
FROM texlive/texlive:latest
RUN apt-get update && apt-get install -y make perl ghostscript poppler-utils && rm -rf /var/lib/apt/lists/*
WORKDIR /work
ENTRYPOINT ["latexmk"]
```

编译方式：

```bash
docker run --rm \
  -v uploads/paper_generation/{paper_id}/final/miccai:/work \
  texlive/texlive:latest \
  -pdf -interaction=nonstopmode -halt-on-error main.tex
```

### 5.2 桌面用户 fallback：Tectonic

很多 Electron 桌面用户没有 Docker。打包版建议支持：

```bash
PAPER_LATEX_BACKEND=tectonic
```

优点：单二进制、比完整 TeX Live 小。缺点：首次编译可能下载依赖，模板兼容性要测试。

### 5.3 最小实现建议

- Phase 01 先做 Docker backend。
- Phase 11 前补 Tectonic fallback。
- `latex_compiler.py` 抽象为：`DockerLatexBackend` / `TectonicBackend` / `SystemLatexmkBackend`。

## 6. TaskWorker 运行方式

Paper job 应作为 TaskWorker job，而不是 Gateway 内同步执行。

建议 descriptor：

```json
{
  "task_type": "paper_generation",
  "paper_id": "paper_xxx",
  "requires_gpu": false,
  "queue": "cpu_llm",
  "payload": {
    "source_task_ids": ["task_xxx"],
    "templates": ["miccai", "nature_scientific_reports"]
  }
}
```

TaskWorker 执行时：

1. claim descriptor。
2. 更新 `manifest.json.current_stage`。
3. 执行 collector / evidence / agents / guards / export。
4. 定期发布 runtime status。
5. 成功 ack；失败写 `validation/warnings.md` 和 `manifest.error`。

## 7. 网络访问

需要网络的阶段：

| 阶段 | 网络用途 |
|---|---|
| Outline Agent | LLM API |
| Plotting Agent | 概念图 backend / VLM critic，取决于 provider |
| Literature Review Agent | LLM query generation、Semantic Scholar、PubMed |
| Section Writing Agent | LLM API，可能 vision input |
| Content Refinement Agent | LLM critic / revise |

不需要网络的阶段：

- Infrastructure
- Collector
- PHI + Evidence
- Locked Blocks
- Deterministic Guards
- LaTeX compile（Docker image 已存在时）

## 8. 开发验收命令

```bash
# Python 依赖
cd pathlab/pathlab-client
pip install -r server/requirements.txt
pip install -r server/requirements-test.txt

# 后端测试，不跑预训练 GPU 测试
python -m pytest server/tests/ -v -k "not pretrained"

# 前端测试
npm run test:run

# Sidecar 固定端口启动
PATHLAB_DEBUG=1 python server/main.py

# LaTeX backend smoke
mkdir -p /tmp/pathlab-paper-latex-smoke
cat >/tmp/pathlab-paper-latex-smoke/main.tex <<'TEX'
\\documentclass{article}
\\begin{document}
PathLab paper generation smoke test.
\\end{document}
TEX

docker run --rm -v /tmp/pathlab-paper-latex-smoke:/work texlive/texlive:latest \
  -pdf -interaction=nonstopmode -halt-on-error main.tex
```

## 9. 推荐落地顺序

1. 先让现有 PathLab sidecar 正常跑起来。
2. 增加 `paper_generation` feature flag 和 run 目录。
3. 增加 CPU/LLM paper job descriptor，不碰 GPU queue。
4. 跑通 LaTeX Docker smoke。
5. 再接 collector / evidence。
6. 最后接 LLM agent 和 citation 网络。

## 10. 最重要的运行时禁忌

- 不要在 Gateway request 内同步跑 LLM 或 LaTeX。
- 不要让 paper job 占 GPU queue。
- 不要把 private evidence 暴露到 API / ZIP / LLM prompt。
- 不要假设用户机器有 Docker；桌面版要准备 Tectonic fallback。
- 不要把 raw LLM prompt / response 默认持久化。
