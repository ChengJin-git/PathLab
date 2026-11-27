# PathLab Gateway

The Gateway is the single public API of the PathLab web application. It handles authentication,
business logic, static files and the coordination with Preprocessing, AI and the TaskWorker; the
chat workspace and research sessions are served from here too.

## Start-up

Entry point `server/gateway/main.py` (FastAPI). On start-up the Gateway:

- initialises the database and Redis;
- keeps the Redis progress of running tasks (stale progress expires through TTLs and task completion);
- removes failed and cancelled tasks older than the retention period, keeping completed training runs;
- removes expired PDF caches;
- warms up, in the background, the embedding model and built-in knowledge used for training
  recommendations;
- registers all routers, mounts the built web client if present, and always mounts `/avatars`.

Chat queries resources on demand for the current workspace and question; the Gateway does not scan
all users' resources or build vectors at start-up. GPU detection, the task-queue runtime and
training recovery belong to the TaskWorker; the Gateway reads its runtime snapshots and heartbeats
from Redis.

## Task boundary and queue state

For long GPU jobs the Gateway enqueues descriptors, publishes cancellation requests and reports
status. `backend.common.task_dispatch` builds the Redis descriptors and writes them to the pending
queue; the TaskWorker claims, dispatches, acknowledges, retries and moves failures to a dead-letter
queue. Descriptors use three Redis lists (pending, processing, DLQ). Acknowledgement means the job
was dispatched, not that it finished. Cancellation writes a durable key and a pub/sub message; a
dispatch lock and task-ID de-duplication in the GPU queue prevent double submission. See
[task_worker/README.md](../task_worker/README.md).

`GET /queue` prefers the TaskWorker's runtime snapshot. `running_count`, `pending_count` and
`queue_size` describe the GPU queue; `descriptor_pending_count`, `descriptor_processing_count` and
`descriptor_dlq_count` describe the Redis descriptor queue.

## Response path of common page actions

- The dataset properties dialog uses `PATCH /wsi/datasets/{dataset_id}/properties`. With a revision
  check it changes name, task configuration, aggregation level, source, metadata and visibility in
  one transaction; task combinations are validated first and split statistics are recomputed when
  the aggregation level changes. Upload-source edits use the same endpoint.
- On success the client updates the card from the response and closes the dialog, then refreshes
  pages and filters in the background; on failure the draft is kept. Renaming or deleting tasks and
  submitting inference report success without waiting for list refreshes.
- Deleting a task publishes a durable cancellation and notification before deleting the database
  record; if publishing times out, the deletion is aborted. AI-service notification and file
  clean-up run afterwards in the background; `storage_cleanup.status=scheduled` does not mean the
  files are already gone.
- `DELETE /conversations/{id}` commits logical deletion, research cancellation and file
  invalidation and returns immediately. The ResearchWorker finishes the clean-up from a durable
  record and retries failures; this internal record does not appear in the storage progress list.
- Multi-task dataset creation and label appending are served by the `dataset_catalog` router;
  viewer objects, capabilities and local assistance by the `viewer` router.
- After a data change the cache revision is bumped through one Redis pipeline with a bounded wait.
  Progress is read in batches for current tasks only, falling back to database state when progress
  or runtime snapshots are unavailable.
- External-file availability is cached by inode, mtime and size and parsed snapshots are reused;
  lists read status in batches and parse JSON in a thread.

## Registered routers

`app_setup.py` registers these routers, each with and without the `/api` prefix:

`workspaces`, `auth`, `stats`, `dataset_catalog`, `viewer`, `wsi`, `wsi_upload`, `training`,
`ai_tasks`, `result_workbench`, `results`, `models`, `chat`, `storage`, `queue`, `asr`, `heatmap`,
`settings`, `gpu`, `annotation`, `training_options`, `autoresearch`, `reports`.

Together they cover:

- sign-in, user management, avatars;
- slide upload, lists, details and access checks;
- training tasks, AI tasks and the GPU queue;
- model management, results and report export;
- AI chat, conversation history, web search, PDF caching and vector search, feedback;
- workspaces with dataset scope, read-only mode and skill/connector restrictions;
- storage inventory, scanning, clean-up and configuration;
- GPU information, heatmaps, annotations and system settings;
- research sessions: creation, resume, stop, deletion, event replay, SSE and artifact download.

Routers are only assembled in `app_setup.py`; `routes/__init__.py` has no side effects.

## Supporting modules in `routes/`

Besides the routers, `routes/` contains modules used by them:

- Inference: `inference_external_validation.py`, `inference_wsi_survival.py`,
  `inference_patch_segmentation.py`, `inference_patch_classification.py`,
  `inference_wsi_classification.py` (called by `results`), `inference_batch.py` (batch inference on
  unlabelled datasets, scheduled as `BATCH_INFERENCE`), and the shared `inference_base.py`.
- Research image prediction: `inference_research_images.py` reuses sandbox adapters to store
  standard patch classification and segmentation results.
- Analysis: `classification_analysis.py`, `segmentation_analysis.py`, `survival_analysis.py`,
  `external_validation_analysis.py`, `analysis_utils.py`, `analysis_metrics.py`; cross-process
  analysis state is in `backend/common/analysis_state.py`.
- Chat: `chat_pdf.py` (authorised image route), `chat_pdf_vectorstore.py`, `chat_feedback.py`,
  `chat_patch_inference.py`, `chat_training_recommendation.py`, `chat_conversation.py`,
  `chat_llm_client.py`, `chat_model_selector.py`; context and capability loading in `gateway/chat/`.
  Article reading, source identification, document structure and download are in
  `backend/services/articles/`, CPU parsing in `backend/services/pdf_cpu.py`, source numbering in
  `gateway/chat/article_sources.py`.
- Access: `access_control.py` (ownership and admin assertions).
- Training options: `training_options.py` (`/training/options`).
- Runtime: `transformers_runtime.py`.
- Storage: `storage_scan.py`, `storage_tasks.py`.
- Dataset visibility: `dataset_visibility.py` (making a dataset private stops other users' training
  on it).
- Image candidates: `image_recommendations.py` (bounded results filtered by workspace, label,
  prediction and model).

External data availability for training and inference is decided in `gateway/data_availability.py`.

## Authentication

Code: `routes/auth.py` and `backend/auth/`.

- FastAPI-Users with a JWT strategy. `/auth/jwt/login` is disabled; clients sign in through
  `/auth/secure-login`, which receives a time-limited password hash instead of the password.
- `session_nonces` per user allow sessions to be revoked; the older `session_nonce` column is only
  kept in the schema.
- Sign-out, profile updates, avatar upload, access requests reviewed by administrators.
- Maintenance mode, a paginated user list and batch activation, deactivation and deletion for
  administrators.

## Viewer and annotation routes

`routes/viewer.py` manages interactive objects, capabilities and search; `routes/annotation.py`
manages published labels, extraction and audit.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/viewer/slides/{wsi_id}/context` | Slide, neighbouring slides, personal/team/manage permissions |
| `GET/POST` | `/viewer/slides/{wsi_id}/regions` | Viewport or cursor queries; object writes with revision and operation ID |
| `POST` | `/viewer/slides/{wsi_id}/regions/selection` | Refresh selected objects and deletion tombstones |
| `GET` | `/viewer/slides/{wsi_id}/events` | Change stamps; access is re-checked every two seconds |
| `POST` | `/viewer/slides/{wsi_id}/reference-labels` | Publish selected objects as labels, keeping other labels |
| `GET` | `/viewer/slides/{wsi_id}/capabilities` | Available features and installed prompt models |
| `POST` | `/viewer/slides/{wsi_id}/assist`, `/search`, `/assistant` | Local assistance, feature search, slide assistant |
| `GET` | `/annotation/wsi/{wsi_id}/labels`, `/label-thumbnail` | Published labels and thumbnails per task |
| `GET` | `/annotation/datasets/{dataset_id}/summary` | Label summary |
| `POST` | `/annotation/extract` | Extract ROIs from saved objects into a new dataset with recorded lineage |
| `GET` | `/annotation/audit`, `/audit/export` | Annotation audit |

Switching between personal and team layers does not copy objects. Writes, undo and publication check
the current revision; idempotent retries return the original receipt. Editing the team layer and
publishing labels require dataset management rights (owner or administrator). See
[VIEWER.md](../backend/services/VIEWER.md) and [FEATURE-ARTIFACTS.md](../backend/services/FEATURE-ARTIFACTS.md).

Heatmap lists read the SQLite result catalog and result ownership without scanning bundles; content
is read from Preprocessing through short-lived signed requests.

## Chat and speech

- `POST /chat` receives the message, workspace, expert, enabled skills and connectors, execution
  mode and voice state. Models and credentials come from the platform settings.
- The model interprets negation, corrections, confirmations and topic changes; `LOAD_CAPABILITY`
  only requests extra reads when facts or protocols are missing.
- `GET /wsi/recommendations` returns bounded, access-checked candidates for image cards.
- WebSocket `/asr/realtime` proxies a cloud or local speech-recognition service after
  authentication.
- SSE parses upstream HTTP errors and in-stream errors and records stage timings; rate limits are
  reported, not shown as empty replies.

Cards, confirmations, history and option rules are described in [chat/README.md](chat/README.md).

## Storage routes

`routes/storage.py` provides `/storage/disk-space`, `/storage/check-upload-space`, `/storage/config`,
`/storage/migrate` and `/storage/migration/status`, and is combined with `storage_tasks.py` and
`storage_scan.py`. The storage inventory is described in [storage/README.md](../backend/storage/README.md).

## Research routes

`routes/autoresearch.py` uses the `/research` prefix (browser: `/api/research`); the pages are
`/autoresearch/new` and `/autoresearch/sessions/:id`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/research/configuration` | Capabilities, models, budget defaults and built-in skills |
| `POST` | `/research/polish-goal` | Polish a research brief without creating a session |
| `POST` | `/research/skills/import`, `/research/skills/upload` | Import a complete skill package and preview resources and compatibility |
| `GET/POST` | `/research/sessions` | List or create sessions |
| `GET/DELETE` | `/research/sessions/{id}` | Details, or durable deletion with background stop and clean-up |
| `POST` | `/research/sessions/{id}/messages` | Add an instruction |
| `POST` | `/research/sessions/{id}/pause`, `/resume`, `/continue`, `/stop` | Pause, resume, continue optimising, stop |
| `POST` | `/research/sessions/{id}/access-token` | Short-lived token for SSE and downloads |
| `GET` | `/research/sessions/{id}/events` | Replay events by sequence (SSE) |
| `GET` | `/research/sessions/{id}/files`, `/download` | Artifact preview and archive |
| `GET` | `/research/sessions/{id}/runs/{run_id}/download` | Archive of one experiment |

All endpoints require the administrator or pathologist role and are filtered by owner. SSE keeps
re-checking role, token expiry and ownership. See [autoresearch/README.md](../backend/autoresearch/README.md).

## Articles and models

The `reports` router provides evidence sources, article lists, background generation and
continuation, versioned editing, polishing and export (page `/reports`, API `/reports/documents`;
see [REPORTS.md](../backend/services/REPORTS.md)). Research artifacts that fail contract validation
cannot be activated for inference through the API.

## Static files

- `/avatars` → `uploads/avatars`
- `/images`, `/assets` → the built web client, if present
- `/datasets`, `/upload` → the single-page app entry

## Gateway modules

| Module | Purpose |
| --- | --- |
| `main.py` | FastAPI application, lifespan and router registration |
| `dependencies.py` | Shared dependencies (logging, `.env` loading, helpers) |
| `models.py` | Pydantic request and response models |
| `utils.py` | Helpers such as segmentation/COCO contract validation |
| `pipeline.py` | AI training/inference pipeline helpers |
| `scan_sessions.py` | Directory scan sessions (TTL cache used by `storage_scan`) |
| `app_setup.py` | Router registration and static mounts |
| `startup.py` | Start-up and shutdown orchestration |
| `workspace_access.py` | Workspace scope and execution limits enforced independently of prompts |
| `chat/` | Chat context, capability loading and protocol helpers |
| `knowledge/` | Built-in knowledge and the training-recommendation RAG directory |
| `prompts/` | Prompts and workflow contracts for the controller |

Shared task descriptors, status snapshots, task types and the chat context cache are in
`backend/common/task_dispatch.py`, `task_runtime.py`, `task_types.py` and `chat_context_cache.py`.
The GPU queue is in `task_worker/task_queue.py`; some training and analysis functions in
`gateway/pipeline.py` are lazily reused by the worker, which owns their execution.

## Related documents

[Server](../README.md) · [Backend](../backend/README.md) · [Database](../backend/database/README.md) ·
[Storage](../backend/storage/README.md) · [Chat workspace](chat/README.md)
