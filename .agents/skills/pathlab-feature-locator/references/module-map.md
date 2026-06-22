# PathLab Module Map

Use this after `feature-index.md` when a feature requires module boundary details.

## Main Package

`pathlab/pathlab-client/` aggregates Electron, React, Python sidecar, tests, and deployment.

- Edit package scripts/build resources in `package.json`.
- Edit Electron/Vite build entries in `electron.vite.config.ts`.
- Edit Python sidecar startup in `server/main.py`.
- Edit frontend test matching in `vitest.config.ts`.

## Electron Main

`src/main/` owns desktop lifecycle, deep-link login, IPC, embedded PostgreSQL / Redis, and Python sidecar startup.

- `index.ts`: `handleDeepLink(url)`, `createWindow()`, `ipcMain.handle(...)`.
- `sidecar-manager.ts`: `startPythonSidecar(extraEnv?)`, service port parsing.
- `services-manager.ts`: `startEmbeddedServices()`, embedded DB/Redis behavior.

## Electron Preload

`src/preload/index.ts` exposes safe desktop APIs to renderer.

- `BackendServicePorts`: Gateway / Preprocessing / AI port type.
- `api`: contextBridge-exposed object.
- Edit `api` for new native file, directory, auth callback, port, or external link capabilities.

## Renderer App

`src/renderer/src/` contains React routes, pages, components, contexts, API clients, utilities, and locales.

- `main.tsx`: initialize API config, router/provider root.
- `App.tsx`: main routes and protected routes.
- `config.ts`: `initializeApiConfig()`, `updateApiBase()`.
- `contexts/AuthContext.tsx`: `AuthProvider`.
- `contexts/backgroundTask/`: training, analysis, storage task SSE and actions.
- `pages/`: page-level workflows such as `NewTaskPage`, `WSIViewerPage`, `ResultsViewerPage`, `StorageManagementPage`.
- `components/`: reusable business and UI components.

## Renderer API Clients

`src/renderer/src/api/` wraps Gateway / Preprocessing / AI HTTP calls.

- `client.ts`: common request/error handling.
- `auth.ts`, `users.ts`: login, registration, profile, admin user management, maintenance mode.
- `wsi.ts`: WSI/dataset list, details, upload, CSV/COCO templates, metadata.
- `training.ts`, `trainingOptions.ts`: training tasks, models, options.
- `queue.ts`: GPU queue status, concurrency, cancellation.
- `results.ts`, `analysis.ts`, `batchInference.ts`: results, analysis, external validation, batch/independent inference.
- `annotation.ts`, `grants.ts`: annotation, collaboration, presence, grants.
- `chat.ts`, `feedback.ts`: AI chat, conversations, patch inference, feedback.
- `storage.ts`: storage stats, migration, scan, orphan cleanup, background storage tasks.
- `settings.ts`, `stats.ts`, `heatmap.ts`: settings, dashboard stats, heatmap/thumbnail URLs.

## Python Sidecar

`server/` is not one FastAPI app. `server/main.py` starts Gateway, Preprocessing, AI, and TaskWorker.

- `main()`: choose ports, set service discovery env, start processes.
- `run_service(app_module, port, name, ...)`: run uvicorn child service.
- `run_task_worker()`: start no-port worker.
- `_detect_and_exclude_bad_gpus()`: GPU visibility handling.

## Gateway

`server/gateway/` owns public API, auth, aggregation, static resources, and task descriptor enqueueing.

- `main.py`: Gateway FastAPI app entry.
- `app_setup.py`: `include_api_routers(app)`, `mount_static_routes(app, renderer_dist?)`.
- `startup.py`: DB/Redis startup cleanup and prewarm.
- `task_dispatch.py`: `enqueue_task_descriptor(...)`.
- `task_queue.py`: queue runtime types and shared scheduling definitions.
- `routes/auth.py`: auth, users, maintenance, avatars.
- `routes/wsi.py`, `routes/wsi_upload.py`: WSI/dataset list and upload/registration.
- `routes/training.py`: training task creation, list, logs, models.
- `routes/results.py`: results, analysis, external validation, batch/independent inference, export.
- `routes/queue.py`: queue status and cancellation.
- `routes/storage.py`, `routes/storage_tasks.py`, `routes/storage_scan.py`: storage stats/tasks/scan.
- `routes/annotation.py`: annotation drafts, labels, collaboration, presence, audit.
- `routes/chat.py`: AI chat and stream responses.

## TaskWorker

`server/task_worker/` owns background execution of Redis descriptors.

- `main.py`: `TaskWorkerRuntime`, heartbeat, cancellation subscription, shutdown.
- `handlers.py`: `_register()`, `dispatch_descriptor(descriptor)`.
- `recovery.py`: `resume_interrupted_tasks()`.
- `runtime_status.py`: `publish_runtime_status(queue)`.
- `jobs/training.py`: `run_training_pipeline()`.
- `jobs/inference.py`: batch/independent inference wrappers.
- `jobs/analysis.py`: analysis execution.
- `jobs/chat_patch.py`: chat patch inference execution.

## Backend Common

`server/backend/common/` contains shared backend infrastructure.

- `config.py`: `Config`, default ports, DB/Redis, uploads, global settings.
- `redis_client.py`: `get_redis()`, key helpers.
- `port_utils.py`: `find_free_port()`, `announce_port(port, service_name)`.
- `gpu_utils.py`: GPU health, VRAM, `select_optimal_gpu_for_task()`.
- `progress_store.py`: Redis progress/task owner storage.
- `slide_utils.py`, `file_types.py`: WSI/patch recognition and slide loading helpers.
- `split_generation.py`: classification/survival/segmentation splits.

## Database And Auth

`server/backend/database/` owns SQLAlchemy async access.

- `database.py`: async engine/session.
- `models.py`: business ORM models such as `Dataset`, `WSISlide`, `TrainingTask`, `TrainedModel`,
  `AIResult`, `AnalysisRun`, `SegmentationAnnotation`, `DatasetGrant`, `PermissionAuditLog`.
- `repositories/`: business repositories including training task, annotation, and grant repositories.
- `migrate_task_taxonomy.py`: task taxonomy/data group migration.

`server/backend/auth/` owns user model and auth dependencies.

- `models.py`: `User`.
- `users.py`: FastAPI-Users setup and JWT/auth backend.
- `schemas.py`: user schemas.
- `dependencies.py`: `current_active_user`, `require_admin`.

## Preprocessing

`server/backend/preprocessing/` is an internal FastAPI service for WSI image operations.

- `main.py`: `health()`, `get_wsi_info(wsi_id)`, `get_thumbnail(...)`, `get_dzi(...)`,
  `get_tile(...)`, `extract_regions(...)`, `_extract_segmentation_dataset(...)`.
- `heatmap_routes.py`: heatmap helpers.
- `slide_cache.py`: slide handle cache and release behavior.

## AI

`server/backend/ai/` owns training, inference, models, and registries.

- `main.py`: AI FastAPI app.
- `routes/training.py`: WSI classification, WSI survival, patch classification, patch segmentation training endpoints.
- `routes/inference.py`: `run_inference_pipeline()`.
- `extractors/registry.py`: `get_extractor()`, `list_extractors()`, `register_extractor()`.
- `aggregators/`: MIL aggregators such as ABMIL, CLAM, DSMIL, DTFD, MeanMIL, MaxMIL, TransMIL.
- `classifiers/`: classifier base classes and registry.
- `tasks/`: `WSIClassificationTrainer`, `WSISurvivalTrainer`, `PatchClassificationTrainer`, `SegmentationTrainer`.

## Annotation Helpers

`server/backend/annotation/` supports annotation workflows but is not an independent service.

- `coco_utils.py`: COCO export helpers.
- `summary_cache.py`: `build_dataset_annotation_summary_cache()`,
  `rebuild_dataset_annotation_summary_cache()`, `build_effective_summary_from_cache()`.
- `pubsub.py`: collaboration event broadcast.
- `presence_pubsub.py`: presence broadcast.

## Storage

`server/backend/storage/` owns filesystem storage statistics, migration, orphan detection, and cleanup.

- `manager.py`: `StorageManager`.
- `stats_mixin.py`: `StorageStatsMixin`.
- `orphan_mixin.py`: `StorageOrphanMixin`.
- `migration.py`: `MigrationManager`.

## Deploy

`deploy/` owns fixed-port Web deployment and operations.

- `start.sh`: cleanup old processes, install dependencies, build frontend, start fixed-port backend, health check.
- `hot-reload.sh`: frontend/backend/gateway/preprocessing/ai/all hot reload.
- `nginx/`: HTTPS and HTTP-only reverse proxy templates.
- `systemd/pathlab.service`: service template.

Important env vars: `PATHLAB_DEBUG=1`, `GATEWAY_PORT=6100`, `PREPROCESSING_PORT=6101`,
`AI_PORT=6102`, `CUDA_VISIBLE_DEVICES`.
