# PathLab backend modules

`server/backend/` holds the code shared by all server processes, the implementations of the two
internal FastAPI services (Preprocessing and AI) and the research runtime.

```text
backend/
├── ai/               # training, inference, models
├── auth/             # user model, JWT / FastAPI-Users configuration
├── common/           # configuration, Redis, task protocol and snapshots, chat cache, utilities
├── database/         # SQLAlchemy models, sessions, repositories
├── annotation/       # COCO conversion and label summaries
├── autoresearch/     # research runtime, experiment orchestration, persistence, sandbox, skill templates
├── preprocessing/    # whole-slide info, images, DeepZoom, tiles, heatmaps
├── services/         # workspaces, data access, viewer, features, files, articles
└── storage/          # storage inventory, migration, clean-up
```

## Preprocessing service

Entry point: `backend/preprocessing/main.py`.

- Slide health checks and metadata
- Full images, thumbnails, DeepZoom descriptors and tiles
- Heatmap helpers (`heatmap_routes.py`) and their preview cache
- ROI extraction from annotations, and COCO caches written to `uploads/annotations/*_coco.json`

The Gateway enforces user and result access; Preprocessing's result-layer endpoints only accept
short-lived requests signed by the Gateway.

## AI service

Entry point: `backend/ai/main.py`, with two routers, `routes/training.py` and `routes/inference.py`.

- Starting, tracking and reading training runs
- Inference and analysis helpers
- Registries for feature extractors, aggregators and classifiers, and the shared training pipeline

## Annotation helpers

`backend/annotation/` provides `coco_utils.py` (COCO export) and `summary_cache.py` (dataset label
summaries). Interactive annotations are saved as `ViewerRegion` objects by
`services/viewer_annotations.py`, with idempotent receipts in `ViewerOperation`. The viewer's SSE
stream announces object changes and re-checks access every two seconds.

## Research runtime

`backend/autoresearch/` is called by the Gateway's research router to create, resume, stop and
export research sessions:

- The ResearchWorker supervises native OpenCode sessions in the sandbox, with messages, pause and
  resume.
- Dataset acquisition from public sources, workspace preparation and artifact archiving.
- Literature retrieval and RAG, domain skills and templates, experiment summaries and know-how
  records.
- Session state, commands, event sequences and jobs in PostgreSQL; OpenCode state, input views and
  experiment snapshots on disk.
- Sandbox image build, scientific skill packages, reusable predictor adapters and article
  generation.

See [autoresearch/README.md](autoresearch/README.md).

## Shared infrastructure

### Authentication

- User model: `auth/models.py`; FastAPI-Users configuration: `auth/users.py`.
- Sessions use JWTs and the user's `session_nonces`. The older single `session_nonce` column is kept
  in the schema but not used for authorisation.

### Database

- ORM models: `database/models.py`; repositories: `database/repositories/__init__.py`;
  initialisation: `database/init_db.py`.
- `current_schema.py` creates a new database and checks the schema version of an existing one. See
  [database/README.md](database/README.md).

### Redis and configuration

- Configuration: `common/config.py`.
- `progress_store.py` reads task progress in batches; `task_runtime.py` reads bounded runtime
  snapshots and callers fall back to persisted state on failure.
- Trainers write progress with `progress_store.set_progress(task_id, progress)`; training logs are
  written to `logs/training/{task_id}/training.log`.
- `ai/classifiers/checkpoint.py` loads patch classifier heads (`classifier_head.pth`, linear, MLP or
  attention, per fold) for inference, external validation and chat image inference.
- `common/analysis_state.py` tracks analysis tasks; `common/service_health.py` checks the services a
  worker depends on.
- `chat_context_cache.py` keeps a shared revision for workspace context and invalidates it through a
  Redis pipeline; access is re-checked before a cached result is used.
- `Config.configure_service_ports()` updates in-memory configuration and environment variables
  before child processes start, so every process sees the same service URLs.
- GPU, slide and split helpers: `common/gpu_utils.py`, `slide_utils.py`, `split_generation.py`.
- Global settings (language models, Hugging Face, DashScope, Exa, vLLM, local speech recognition,
  Turnstile and Tencent captcha) are written by `common/settings_store.py` to `storage.json` in the
  application-data directory. The public settings endpoint only returns the selected captcha
  provider and its public site key.
- `Config.get_uploads_dir()` resolves the storage root: `PATHLAB_UPLOADS_DIR`, then `storage.json`,
  then the application-data directory.

### Storage

- `storage/manager.py` (entry point), `stats_mixin.py`, `orphan_mixin.py`, `migration.py`.
- `storage/external_availability.py` reads the last known availability of external files and reuses
  parsed snapshots per file version. See [storage/README.md](storage/README.md).

### Workspaces, data and research outputs

- `services/workspaces.py` — workspace dataset scope, task constraints and capability catalog. A
  workspace can only narrow existing access.
- `services/dataset_access.py` — owners and administrators read, write and manage a dataset; public
  datasets are readable by every signed-in user.
- `services/dataset_catalog.py` — validates multi-task dataset configuration; the Gateway updates
  properties or appends labels in one transaction.
- `services/research_prediction.py` — prediction contracts for classification, survival, detection
  and segmentation research models; `ai/research_predictor_worker.py` loads them in the sandbox and
  `predictor.json` records output order, aggregation, preprocessing and file hashes.
- `services/manuscripts.py`, `manuscript_writer.py`, `report_export.py` — evidence snapshots,
  background writing, versioned editing and Word/LaTeX export.
- `services/articles/` (`identity`, `document`, `sources`, `reader`) and `services/web_search.py` —
  article identity, structure, download, CPU reading and web search, usable from chat and research
  without importing the Gateway.
- `services/feature_inventory.py` and `ai/feature_contracts.py` — registered features and their
  version, embedding space and optional text encoder.
- `services/viewer_*.py` — viewer objects, reference labels, local assistance, feature search and
  text providers ([services/VIEWER.md](services/VIEWER.md)).
- `services/chat_deletion.py` — logical conversation deletion; the ResearchWorker removes files and
  records from a durable clean-up record.
- `ai/result_store.py` (ZIP result bundles and locks) and `ai/result_catalog.py` (SQLite WAL
  catalog); result lists never open content files.

## Boundaries

- Interactive objects live in `viewer_regions`; published COCO labels in `segmentation_annotations`,
  separated by task type.
- `common/config.py` creates the storage sub-directories (`avatars`, `coordinates`, `masks`,
  `features`, `ai_results_bundles`, `training`, `models`, `extractor_checkpoints`, `logs`,
  `wsi_files`, `metadata`, `progress`, …).
- Long-running jobs execute in `server/task_worker/`; `backend/ai/` provides the task
  implementations.
- The research API is served by the Gateway; the ResearchWorker recovers from the sessions,
  commands, jobs and events stored in the database.

## Related documents

[Server](../README.md) · [Gateway](../gateway/README.md) · [Research runtime](autoresearch/README.md) ·
[Database](database/README.md) · [Storage](storage/README.md)
