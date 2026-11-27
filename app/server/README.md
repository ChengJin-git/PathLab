# PathLab Python backend

`server/` contains the Python services of the PathLab web application. `main.py` starts five
processes and the shared code lives in `backend/`. Installation is described in
[docs/installation.md](../../docs/installation.md).

## Processes

`main.py` starts the three HTTP services and two workers with `multiprocessing`, passes the service
URLs to each through environment variables and stops all of them when one exits unexpectedly.

| Process | Port | Responsibility |
| --- | --- | --- |
| Gateway | 6100 | Authentication, user management, and the public API for slides, datasets, tasks, results, chat, storage, settings and research |
| Preprocessing | 6101 | Slide metadata, images, thumbnails, DeepZoom tiles, heatmap helpers, ROI extraction and COCO export. Starts `PREPROCESSING_WORKERS` (default 4) workers, each recycled after `PREPROCESSING_MAX_REQUESTS` (default 500) requests to release native-library memory |
| AI | 6102 | Training, inference, feature extraction, and the aggregator and classifier registries |
| TaskWorker | — | Consumes task descriptors from Redis, owns the GPU queue, cancellation, runtime snapshots and training recovery |
| ResearchWorker | — | Supervises OpenCode research sessions, research concurrency and recovery, background article writing and durable conversation clean-up |

Ports come from `GATEWAY_PORT`, `PREPROCESSING_PORT` and `AI_PORT`. If `CUDA_VISIBLE_DEVICES` is
set it is respected; otherwise unhealthy GPUs are detected and excluded at start-up.

## Directory layout

```text
server/
├── main.py                 # starts the HTTP services and workers
├── requirements.txt        # pinned Python dependencies
├── requirements-test.txt   # test dependencies
├── requirements-sandbox-survival.txt  # scikit-survival for research sessions that need it
├── pytest.ini              # asyncio_mode = auto
├── tests/                  # backend tests (pytest)
├── gateway/                # public API, chat workspace, prompts
├── permissions/            # access-control reference
├── task_worker/            # Redis descriptor queue, GPU queue, recovery
└── backend/
    ├── ai/                 # models, trainers, inference
    ├── annotation/         # COCO conversion and label summaries
    ├── auth/               # accounts, roles, JWT sessions
    ├── autoresearch/       # research runtime, skills, literature, datasets, sandbox
    ├── common/             # configuration, Redis, task protocol, shared utilities
    ├── database/           # SQLAlchemy models, schema and repositories
    ├── preprocessing/      # whole-slide service
    ├── services/           # workspaces, data access, viewer objects, features, files, reports
    └── storage/            # storage inventory, migration and clean-up
```

## Task dispatch

The Gateway writes long-running training, inference, analysis and patch-extraction jobs as Redis
descriptors (`backend/common/task_dispatch.py`) and reads worker state through
`backend/common/task_runtime.py`. The GPU queue lives in `task_worker/task_queue.py` and is
initialised and recovered by the TaskWorker. A Gateway restart keeps the Redis progress of running
tasks; stale entries expire through TTLs and task completion.

The TaskWorker claims a descriptor into a processing list and acknowledges it once the handler has
dispatched it (not when the GPU job finishes). Failed dispatches are retried up to a limit and then
moved to a dead-letter queue. Cancellation first writes a short-lived durable key and then publishes
a pub/sub message. A job lock protects dispatch, and the GPU queue skips duplicate submissions of a
queued or running task. On start-up the TaskWorker moves descriptors left in the processing list
back to the pending queue before resuming persisted training.

`/queue` reports two kinds of counts: GPU queue counts (`running_count`, `pending_count`,
`queue_size`) and descriptor queue counts (`descriptor_pending_count`,
`descriptor_processing_count`, `descriptor_dlq_count`).

## Research sessions

The research API is served by the Gateway at `/research` (`/api/research` through nginx). The
ResearchWorker runs OpenCode in the Apptainer or Docker sandbox; experiments are queued to the
TaskWorker. Sessions, events and jobs are stored in the `auto_research_*` tables, OpenCode's own
state and experiment outputs on disk. Dataset download, literature retrieval and pathology templates
are shared with the rest of the platform. See [backend/autoresearch/README.md](backend/autoresearch/README.md).

## Runtime state

- **PostgreSQL** — metadata and application state.
- **Redis** — task queue, logs, progress and some caches.
- **Storage directory** — slides, feature caches, models, logs, annotations, research workspaces and
  derived files. Resolution order: `PATHLAB_UPLOADS_DIR` > `uploads_dir` saved in `storage.json`
  > `uploads/` in the system application-data directory.

Defaults are in `backend/common/config.py`, for example
`postgresql+asyncpg://pathlab:pathlab@localhost:5432/pathlab` and `redis://localhost:6379/0`.

The research sandbox backend is selected with `PATHLAB_SANDBOX_BACKEND` (Apptainer by default,
Docker optional). Built-in training can also use Apple MPS through `backend/common/accelerator.py`
when the services run on macOS for development.

## Implementation notes

- `DatasetTask` keeps several task types and their labels on one dataset. Dataset read access and
  model/result ownership are checked separately; see [DATASETS.md](backend/services/DATASETS.md).
- `viewer_regions` and `viewer_operations` provide object revisions, idempotent edits and deletion
  tombstones; the team layer is edited by the dataset owner or an administrator
  ([VIEWER.md](backend/services/VIEWER.md)).
- `feature_artifacts` registers extracted features for reuse by the viewer, chat and research
  ([FEATURE-ARTIFACTS.md](backend/services/FEATURE-ARTIFACTS.md)).
- `ai_results_bundles/catalog.sqlite3` is a lightweight result catalog; result layers are read on
  demand.
- Deleting a conversation commits its hidden, cancelled and file-invalidated state before returning;
  the ResearchWorker stops writers, removes files and retries failures.
- Dataset properties are updated atomically through one PATCH endpoint with server-side checks of
  ownership, task types and data types ([gateway/README.md](gateway/README.md)).
- Task lists and SSE read Redis progress in batches; deleting a task always publishes cancellation
  first.
- Chat retrieves bounded candidates within the workspace scope and loads model, training, analysis
  and literature protocols on demand. Errors from external model services are reported, not
  swallowed as empty replies.
- Research models are integrated through the task contracts in `services/research_prediction.py`
  and run in the sandbox; outputs are stored per task type in Zarr 2.
- A cancelled or failed terminal state in an AI response stops the pipeline at one boundary, so a
  successful HTTP status is never mistaken for a successful training run.
- Dataset acquisition validates complete metadata, reuses known source identities, prepares
  annotations and registers the data; missing items are returned with the receipt.

## Tests

Backend tests use pytest, pytest-asyncio and httpx.

```bash
pip install -r requirements-test.txt
python -m pytest tests/ -q --ignore=tests/test_ai_extractors_pretrained.py
python -m pytest backend/autoresearch/tests/ -q      # research data and template packages
python -m pytest tests/test_ai_extractors_pretrained.py -v   # needs a GPU and a Hugging Face token
```

Tests that use PostgreSQL read `DATABASE_URL` and run in temporary schemas;
`PATHLAB_TEST_POSTGRES_URL` enables the asyncpg cancellation test. Real-sandbox and GPU tests are
enabled by explicit switches in their files; a skipped test is not a pass.

Tests are grouped by behaviour (see `tests/test_*.py`):

- Configuration and runtime: `test_config.py`, `test_settings.py`, `test_queue_config.py`,
  `test_gateway_*`, `test_gpu_*`, `test_service_health.py`, `test_module_boundaries.py`,
  `test_main_processes.py`
- Accounts and access: `test_auth_*`, `test_current_schema.py`, `test_permission_*`
- File library and retrieval: `test_file_library*.py`, `test_chat_workbench.py`, `test_chat_deletion.py`
- Data and viewer: `test_dataset_catalog_and_result_privacy.py`, `test_manual_upload_contract.py`,
  `test_viewer_*.py`, `test_annotation_workflow.py`
- Task taxonomy and scheduling: `test_task_taxonomy.py`, `test_*_task_taxonomy.py`, `test_training_*`,
  `test_resume_tasks.py`
- Storage: `test_storage_*`, `test_uploads_boundary.py`, `test_dataset_repository_namespacing.py`
- Workspaces and mutations: `test_mutation_responsiveness.py`, `test_workspace_*.py`,
  `test_image_recommendations.py`
- Research: `test_research_*.py`, `test_autoresearch_routes.py`, `test_acquisition_metadata.py`,
  `test_builtin_research_skills.py`, and `backend/autoresearch/tests/`
- Results and inference: `test_ai_result_store*.py`, `test_*analysis*.py`, `test_batch_inference.py`,
  `test_validation_dataset.py`, `test_patching_stage.py`
- Model smoke tests: `test_ai_models.py`, `test_fm_segmentation_decoders.py`,
  `test_ai_extractors_pretrained.py`

Design notes:

- Tests use temporary directories, synthetic data and controlled dependencies.
- Route tests mount a single router on a bare FastAPI app, override the auth dependencies and call
  it through `httpx.AsyncClient(transport=ASGITransport(...))`, without a real database, Redis or GPU.
- Configuration tests reset `Config`'s global-settings cache before and after each test.
- Pretrained-model tests share a module-level model cache across parametrised cases.
- `HF_TOKEN` is read from `server/.env` (not committed) by `conftest.py`.

## Related documents

[Permissions](permissions/README.md) · [Gateway](gateway/README.md) ·
[Backend modules](backend/README.md) · [Research runtime](backend/autoresearch/README.md) ·
[Database](backend/database/README.md) · [Storage](backend/storage/README.md)
