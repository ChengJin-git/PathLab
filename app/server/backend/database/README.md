# Database layer

The asynchronous SQLAlchemy data layer lives in `server/backend/database/`. `models.py` defines the
application models, `database.py` manages the engine and sessions, `current_schema.py` creates the
schema of a new database and checks the version of an existing one, and `repositories/` contains the
domain queries. The user model is in `backend/auth/models.py`.

## Tables

Table names follow `__tablename__` in `models.py`; the schema version is recorded in
`pathlab_schema_migrations`.

| Domain | Tables |
| --- | --- |
| Data and splits | `data_groups`, `datasets`, `dataset_tasks`, `wsi_slides`, `wsi_slide_user_splits`, `dataset_stats` |
| Training and inference | `ai_tasks`, `ai_results`, `training_tasks`, `training_task_wsi`, `trained_models`, `training_logs` |
| Workspaces, chat, files | `workspaces`, `chat_folders`, `chat_conversations`, `chat_messages`, `message_feedbacks`, `workbench_files`, `file_library_folders` |
| Assistant capabilities | `capability_entries`, `capability_installations` |
| Result analysis | `analysis_runs`, `result_sources`, `result_source_datasets`, `result_analyses`, `result_recipes`, `result_conversations` |
| Storage and export | `storage_tasks`, `export_tasks` |
| Viewer and labels | `viewer_regions`, `viewer_operations`, `segmentation_annotations`, `annotation_audit_logs` |
| Features | `feature_artifacts` |
| Articles | `manuscripts`, `manuscript_generations` |
| Research sessions | `auto_research_sessions`, `auto_research_experiments`, `auto_research_jobs`, `auto_research_events`, `knowhow_entries` |
| Accounts | `users` |

`users` extends FastAPI-Users with role, nickname, avatar, username, password digest, terms
acceptance, first activation time and contact e-mail. Sessions use `session_nonces`; the older
`session_nonce` column remains but is not used for authorisation.

## Datasets and provenance

- `Dataset` defines `data_type` and `aggregation_level`; `DatasetTask` stores the tasks a dataset
  supports. The five canonical task types are `wsi_classification`, `patch_classification`,
  `wsi_survival`, `patch_detection` and `patch_segmentation`.
- `DataGroup` only describes the type combination of a training task.
- `Dataset` stores owner, public flag, organ, description, parent dataset, free metadata, an edit
  revision and `acquisition_metadata`. Downloaded datasets keep the stable source ID, provider, URL,
  license, access attributes and registration record; `DatasetRepository.get_by_acquisition()`
  finds duplicates by owner and source identity, never by display name.
- `WSISlide.source` is the organ or tissue of origin; download provenance is in
  `associated_files.acquisition`. Label, case ID, follow-up time, event status and split are real
  columns. A censoring value of 0 and a follow-up time of 0 are valid values.
- Re-importing keeps manually corrected metadata, visibility and slide annotations; slides of the
  same case must agree on label, follow-up and split.
- Classification labels and survival outcomes use separate columns; COCO annotations are separated
  by `task_type`, so detection and segmentation do not overwrite each other. Label imports match
  original file names and can add a task or labels on their own.
- Model results belong to the owner of the task that produced them: administrators read all, other
  users only their own. Making a dataset public does not share models or results. Preprocessing's
  result-layer endpoints only accept short-lived requests signed by the Gateway.
- `WSISlideUserSplit` (unique on `(wsi_id, user_id)`) stores a user's own split on a public dataset.
- A dataset property update changes `Dataset`, `DatasetTask` and the necessary slide fields in one
  transaction and recomputes statistics when the aggregation level changes.
- `parent_dataset_id` records lineage and `created_by` the user who derived a dataset. Lineage does
  not grant access.

## Annotations

`ViewerRegion` stores interactive objects: slide, layer, owner, creator and last editor, revision,
geometry, label, task type and a deletion flag. Coordinates are level-0 pixels; rectangles and
polygons may be fractional and polygons may have holes. Deletions keep a tombstone revision.

`ViewerOperation` stores the operation ID, request fingerprint, user, slide and response.
Transaction locks on operations and objects protect concurrent writes; a retried operation returns
the original receipt and a stale object revision returns a conflict.

`SegmentationAnnotation` stores published COCO labels, separated by `source_dataset_id` and
`task_type`. `source` records viewer, import, upload or extraction and `status` is `finalized`.
`annotation_source` is derived: imports and uploads are `imported_gt`, viewer publications
`user_label`. Publication updates the selected objects by `viewer_region_id` and keeps existing
labels. See [VIEWER.md](../services/VIEWER.md).

## Features and result catalog

`FeatureArtifact` records feature files and optional coordinates: path, version, rows, dimension,
source and validation state, shared by the viewer, chat and research input preparation. `contract`
may be empty: missing historical weight versions are never guessed. Text localisation additionally
requires an explicit text encoder and alignment declaration
([FEATURE-ARTIFACTS.md](../services/FEATURE-ARTIFACTS.md)).

The per-slide result catalog is `ai_results_bundles/catalog.sqlite3` (SQLite WAL), kept in step with
the task ZIP bundles. It stores queryable summaries; access is still decided by the PostgreSQL
records.

## Workspaces and access

`Workspace` stores a dataset scope, permitted scan roots, enabled capabilities and connectors,
execution mode, archive state and version. `ChatConversation.workspace_id = NULL` means all
accessible resources. A workspace can only narrow access; candidate queries and cache hits re-check
the current owner and role.

`services/dataset_access.py` defines dataset access: owners and administrators read, write and
manage a dataset; public datasets are readable by every signed-in user.

Deleting a training task publishes a durable cancellation first, then commits the database deletion
and finally removes files. There is no global transaction across the database, Redis and disk.

## Research persistence

`auto_research_sessions.chat_conversation_id` links a session to its conversation and the unique
`chat_request_id` prevents duplicate creation; `conversation_id` is the native OpenCode session ID.

Deleting a conversation writes a `storage_tasks` record with `task_type=chat_delete`, marks research
as stopped, cancels queued jobs and makes related files unreadable in one transaction, then returns
`status=deleted` without waiting for processes or disk. The ResearchWorker stops writers, records a
clean-up manifest and deletes experiment outputs, models, reports, conversation attachments, research
files and database records. Independent file-library files, referenced files and source datasets are
kept. Failures and retry times stay in the record and clean-up resumes after a restart.

- `auto_research_sessions` — goal, state, phase, workspace and native-session location, recovery
  data, budget, plan and final result. The ResearchWorker resumes supervision from these records.
- `auto_research_jobs` — durable queue state, parameters and results of experiments, computations
  and downloads. Only real experiments are written to `auto_research_experiments` and count as
  experiment rounds.
- `auto_research_events` — monotonically numbered, replayable events, unique on
  `(session_id, sequence)`; the latest number is `auto_research_sessions.event_sequence`.
- Large data, models, code snapshots and OpenCode state are on disk; the database stores paths and
  summaries. Private native state is in `<uploads>/autoresearch/runtime/<id>/`, the downloadable
  workspace in `<uploads>/autoresearch/autoresearch_sessions/session_<id>/`.

`engine/store.py` writes sessions and jobs; `AutoResearchRepository` provides shared queries.

## Models and articles

`TrainingTask` and `TrainedModel` store real timings, configuration, class order and named metrics.
A research model can only be activated after it passes native-checkpoint or `pathlab-predictor-v1`
contract validation. `predictor.json` on disk records outputs, aggregation, preprocessing and weight
and adapter hashes; the database stores `inference_contract`. Result records point to Zarr 2 bundles;
large masks and attention arrays are not stored in the database.

`manuscripts` stores an immutable evidence snapshot, text, template (`conference` or `journal`),
language, state and an optimistic revision; `manuscript_generations` stores background writing state,
section checkpoints and the skill evidence used. Deleting an article does not delete experiments or
models.

## Initialisation, transactions and upgrades

On start-up the Gateway calls `database.py:init_db()`. An empty database is created from the ORM
models, indexes and built-in capabilities; an existing database must carry the version in
`current_schema.SCHEMA_VERSION` (currently `20261127_public_release`), otherwise start-up stops.

`workbench_files.storage_path` points to an independent file, `revision` is the content digest and
`source_revision` tracks changes to a research output. Folders only group files. Uploads and
generated documents are queued for indexing and are searchable once `indexed_revision` matches the
current revision ([FILE-LIBRARY.md](../services/FILE-LIBRARY.md)).

Application code uses `safe_session()` or an injected session and commits explicitly; exceptions
roll back. SSE status and log reads use `read_session()`: a read-only transaction with a five-second
statement timeout whose connection is returned before events are sent, Redis is awaited or the
stream sleeps. `get_db()` shares `safe_session()`'s close path, so cancellation also rolls back.
The pool keeps 20 connections with up to 10 overflow and a 10-second wait.

Back up the database and the whole storage root before moving or upgrading an installation.

## Related documents

[Backend](../README.md) · [Gateway](../../gateway/README.md) · [Storage](../storage/README.md) ·
[Research runtime](../autoresearch/README.md) · [Predictor contracts](../services/RESEARCH-PREDICTORS.md) ·
[Articles](../services/REPORTS.md) · [Moving an installation](../../../deploy/guides/MIGRATION.md)
