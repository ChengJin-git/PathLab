# Configuration

PathLab reads its server configuration from environment variables, normally set in
`app/server/.env` (copied from `app/server/.env.example`). `deploy/start.sh`, `deploy/hot-reload.sh`
and the systemd template load this file. Per-installation settings that administrators change at
run time — language models, Hugging Face access, captcha — are stored through **Settings → General**
and do not need environment variables.

No credentials are shipped with PathLab. Every key below is empty or a placeholder until you set it.

## Required

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://pathlab:pathlab@localhost:5432/pathlab` | PostgreSQL connection. URL-encode special characters in the password. |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | Redis for the task queue, progress and caches. |
| `JWT_SECRET` | random per start | Signs login sessions. Set a stable random value (`openssl rand -hex 32`); otherwise every restart signs all users out. |
| `DEFAULT_ADMIN_PASSWORD` | random, printed once | Password of the `admin` account created on the first start of an empty database. |

## Network and ports

| Variable | Default | Purpose |
| --- | --- | --- |
| `GATEWAY_PORT` | `6100` | Public API (behind nginx at `/api/`). |
| `PREPROCESSING_PORT` | `6101` | Slide tiles and thumbnails (`/preprocessing/`). |
| `AI_PORT` | `6102` | Training and inference service (`/ai/`). |
| `PATHLAB_BIND_HOST` | `0.0.0.0` | Interface the HTTP services listen on. Use `127.0.0.1` when nginx runs on the same host. |
| `APP_SALT` | `PathLab2024SecureSalt` | Salt mixed into the time-limited password hash the browser sends at sign-in. Set your own value and build the client with the same `VITE_APP_SALT`; stored passwords are not affected. |

## Storage

| Variable | Default | Purpose |
| --- | --- | --- |
| `PATHLAB_UPLOADS_DIR` | value saved in Settings, else the system application-data directory | Root for slides, patches, features, models, results, research workspaces and model checkpoints (`extractor_checkpoints/`). Use an absolute path outside the repository. Administrators can migrate it later in **Settings → Storage**. |
| `MAX_UPLOAD_SIZE` | 10 GiB | Largest single upload, in bytes. |
| `PATHLAB_PATH_MAP` | `{}` | JSON map from host path prefixes to the paths the services see, for slides registered from shared file systems. |

## Compute

| Variable | Default | Purpose |
| --- | --- | --- |
| `CUDA_VISIBLE_DEVICES` | all healthy GPUs | Restrict the GPUs PathLab uses. Without it, devices that fail a start-up probe are excluded. |
| `PREPROCESSING_WORKERS` | `4` | Worker processes serving tiles. |
| `PREPROCESSING_MAX_REQUESTS` | `500` | Requests after which a tile worker is recycled. |
| `SLIDE_CACHE_SIZE`, `DZG_CACHE_SIZE` | `8`, `16` | Open slides and tile generators cached per worker. |
| `PATHLAB_RAG_CPU_THREADS` | `4` | CPU threads for the retrieval embedding model. |
| `PDF_VECTOR_EMBEDDING_DEVICE` | automatic | Device for PDF embeddings (`cpu` or `cuda`). |

## Models and external services

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `OPENROUTER_MODEL` | empty, `https://openrouter.ai/api/v1`, — | Fallback language-model settings when none are saved in **Settings → General**. Any OpenAI-compatible endpoint works. |
| `HF_ENDPOINT` | `https://huggingface.co` | Hugging Face mirror for model downloads. The access token is set in Settings. |
| `HF_HOME` | `~/.cache/huggingface` | Cache for retrieval and OCR models. |
| `PATHLAB_KNOWLEDGE_PAPERS_DIR` | `server/gateway/knowledge/chat/papers` | Optional papers used for training recommendations (see the README in that directory). |
| `PATHLAB_OCR_MODEL_DIR` | prepared by `deploy/prepare-ocr.py` | OCR model location. |
| `PATHLAB_PREVIEW_SOFFICE` | `soffice` on `PATH` | LibreOffice binary for document previews. |
| `PATHLAB_CONTACT_EMAIL` | empty | Contact address of the installation, shown on the sign-in legal pages and in the password dialog ("the administrator of this installation" when empty), and sent to NCBI, Crossref and Unpaywall when articles are fetched. Unpaywall lookups are skipped while empty. |
| `SEMANTIC_SCHOLAR_API_KEY`, `PATHLAB_SERPAPI_KEY` | empty | Optional higher-rate literature and web search. |
| `KAGGLE_USERNAME`, `KAGGLE_KEY`, `GDC_TOKEN` | empty | Optional credentials for downloading public datasets from Kaggle and the NCI GDC. |

## Research sessions

| Variable | Default | Purpose |
| --- | --- | --- |
| `PATHLAB_PYTHON` | detected | Python interpreter used by the deploy scripts. |
| `PATHLAB_OPENCODE_BIN` | `~/.opencode/bin/opencode` | OpenCode binary (pinned to `opencodeVersion` in `app/package.json`). |
| `AUTORESEARCH_SANDBOX_IMAGE` | `~/.local/share/PathLab/sandbox/pathlab-sandbox.sif` | Apptainer image for generated code. |
| `APPTAINER_BIN` | `apptainer` on `PATH` | Apptainer binary. |
| `AUTORESEARCH_SANDBOX` | `auto` | `auto`/`apptainer`, or `local` to skip the sandbox (development only; code runs unisolated on the host). |
| `AUTORESEARCH_SANDBOX_CGROUPS` | `auto` | Apply cgroup resource limits to sandboxed jobs. |
| `PATHLAB_SANDBOX_BACKEND` | `apptainer` | Set to `docker` to use Docker. |
| `PATHLAB_DOCKER_IMAGE`, `PATHLAB_DOCKER_MEMORY`, `PATHLAB_DOCKER_CPUS`, `PATHLAB_DOCKER_BIN` | `pathlab/sandbox:1.0.8-r3-cpu`, —, —, `docker` | Docker sandbox image and limits. Build the image from `deploy/sandbox/Dockerfile`. |
| `PATHLAB_RESEARCH_MAX_PENDING`, `PATHLAB_RESEARCH_MAX_PENDING_PER_USER` | `100`, `8` | Queue limits for research sessions. |
| `PATHLAB_RESEARCH_POLISH_MODEL` | `gpt-6-luna` | Model used to polish research briefs; set it to a model your endpoint serves. |
| `AUTORESEARCH_RAG_EMBEDDING_BASE_URL`, `AUTORESEARCH_RAG_EMBEDDING_API_KEY` | empty | Optional remote embedding service for literature retrieval. |

Optional per-tool credentials for the research agent (PubMed, Unpaywall, image generation) are
read from `<storage>/autoresearch/credentials/skills.env`; see
`app/deploy/research-skills.env.example`.

## Web client build

Set these in `app/src/renderer/.env.production` (example: `app/src/renderer/.env.example`) before
`npm run build`. With nginx in front, the defaults (same host, standard ports) or the relative paths
below are typical.

| Variable | Purpose |
| --- | --- |
| `VITE_BASE_PATH` | URL prefix the app is served under (default `/`). |
| `VITE_API_BASE`, `VITE_PREPROCESSING_BASE`, `VITE_AI_BASE` | Service URLs, e.g. `/api`, `/preprocessing`, `/ai`. |
| `VITE_APP_SALT` | Must equal the server's `APP_SALT`. |

## Settings stored in the database

Administrators configure these in **Settings → General**; they apply immediately and take
precedence over the fallback environment variables:

- Language model: endpoint, API key and model for chat and research (OpenAI-compatible, OpenRouter,
  DashScope or a local vLLM server).
- Hugging Face token for gated checkpoints. PathLab does not redistribute model weights; each
  installation downloads them from the publishers with its own token after accepting their
  licenses.
- Exa web-search key, local speech-recognition server.
- Turnstile or Tencent captcha for the sign-in page.
