# PathScientist Model Registration TODO

## Problem

PathScientist can train a model and write run artifacts such as
`best_model.pth`, `metrics.json`, and external-test outputs, but the trained
model is not reliably visible as a normal PathLab trained model after the
session finishes.

The expected user-facing behavior is: after a successful non-quick-check
PathScientist training run, the model should appear in PathLab's trained-model
and training-task views, with enough metadata to reuse it for validation,
inference, heatmaps, and later PathLab workflows.

## Current Code To Reuse

Do not build a second registration system from scratch. There is already a
partial registration path in `server/gateway/pathscientist_persistence.py`:

- `_persist_session_state()` calls `_safe_register_pathlab_trained_model()` when
  a terminal session state is persisted.
- `_safe_register_pathlab_trained_model()` wraps failures and stores a
  `pathlab_model_registration` result in the persisted PathScientist state.
- `_register_pathlab_trained_model()` creates or updates:
  - `TrainingTask`
  - `TrainedModel`
  - a generated `DataGroup`
  - task feature symlinks under inferred `uploads/training/<task_id>/features`
  - WSI `feature_extracted` flags through `WSIRepository.bulk_update_feature_extracted()`
- Existing tests already cover parts of this behavior in
  `server/tests/test_auto_research_repository.py` and
  `server/tests/test_pathscientist_persistence_safety.py`.

The implementation work should first verify why this path is not enough in real
sessions, then patch the missing handoff points.

## Likely Gaps

1. Registration only runs when a terminal session state is persisted.
   If the final state is not persisted, persistence is delayed/dropped, or the
   session is interrupted after training but before final completion, the model
   never reaches PathLab tables.

2. Candidate selection requires a finalized full training run.
   `_validated_model_candidate()` rejects quick checks, external-test runs,
   failed runs, and entries without an existing `model_path`. If the ratchet
   entry does not include a durable `model_path`, registration returns
   `no_completed_training_model`.

3. The model artifact must survive workspace cleanup.
   `best_model.pth` should be copied or linked to a durable PathLab/PathScientist
   artifact path before registration stores `TrainedModel.model_path`.

4. The created task may not be fully equivalent to a normal PathLab training
   task.
   The current code creates `TrainingTask` and `TrainedModel`, but may not insert
   `TrainingTaskWSI` rows for the internal train/val/test slides. Some PathLab UI
   and inference flows rely on those rows to show counts, class labels, and data
   lineage.

5. Metrics are too loosely mapped.
   Internal test metrics, best validation metric, external metrics, model
   architecture, feature extractor, classes, dataset IDs, and split counts should
   be written into predictable fields in `model_config`, `preprocessing_config`,
   `train_metrics`, and `val_metrics` instead of depending on whatever the agent
   generated in `metrics.json`.

## Implementation Plan

### 1. Add a focused failing test for full session persistence

Create or extend tests under `server/tests/test_auto_research_repository.py`.

Build a fake terminal PathScientist state with:

- `status="completed"`, `stage="completed"`
- `best_run_id="run_a"`
- one full training `run_history` entry with `quick_check=false`, `committed=true`,
  `exit_code=0`, `run_kind="training"`, `model_path=<tmp>/best_model.pth`,
  internal metrics, dataset metadata, feature extractor, aggregator, classes,
  and split counts

Assert that `_persist_session_state()` or `_register_pathlab_trained_model()`
creates:

- one `TrainingTask` with status `completed`
- one `TrainedModel` with `model_path` pointing to an existing durable artifact
- registration result stored as `state["pathlab_model_registration"]`
- feature/task metadata in `preprocessing_config` and `model_config`

Run:

```bash
cd server
OPENHANDS_SUPPRESS_BANNER=1 backend/pathscientist/.venv/bin/python -m pytest \
  tests/test_auto_research_repository.py \
  tests/test_pathscientist_persistence_safety.py -q
```

### 2. Register immediately after a successful full training run finalizes

Keep terminal-state registration as a safety net, but add a more direct trigger
after the full training run is finalized and accepted by the ratchet.

Likely integration points:

- `server/backend/pathscientist/tools/ratchet.py`, after a successful
  non-external, non-quick-check commit has produced a finalized run entry.
- `server/backend/pathscientist/orchestrator/runner.py`, where finalized runs
  are appended to `state.run_history` and external steps are advanced.
- `server/gateway/pathscientist_persistence.py`, preferably as the single place
  that writes PathLab DB rows.

The direct trigger should still be idempotent. Re-running registration for the
same `session_id + run_id` must update the same `TrainingTask` and `TrainedModel`
instead of creating duplicates.

### 3. Guarantee a durable model path before registration

Before writing `TrainedModel.model_path`, make sure the model artifact is outside
any workspace path that can be reverted or cleaned.

Recommended layout:

```text
<pathscientist_base>/artifacts/models/<session_id>/<run_id>/best_model.pth
<pathscientist_base>/artifacts/models/<session_id>/<run_id>/metrics.json
<pathscientist_base>/artifacts/models/<session_id>/<run_id>/run_metadata.json
```

Registration should store the durable `best_model.pth` path, not a transient
workspace `output/runs/<run_id>/best_model.pth` path, unless that path is already
known to be durable.

### 4. Populate PathLab lineage fields

Extend `_register_pathlab_trained_model()` or a helper it calls so it records:

- `TrainingTask.task_name`: concise PathScientist title plus run id
- `TrainingTask.task_description`: original prompt, session id, run id
- `TrainingTask.preprocessing_config`: feature root, extractor, dataset IDs,
  split counts, source `pathscientist`
- `TrainingTask.model_config`: architecture, aggregator, model path, config path,
  class list, metric name/value, quick-check false
- `TrainingTask.classes`: class labels from labels/splits/metrics metadata
- `TrainedModel.train_metrics`: training/best-validation summary
- `TrainedModel.val_metrics`: internal test metrics plus external metrics if
  available

If `TrainingTaskWSI` rows are required by PathLab views, insert them from the
internal split manifest using the same `(task_id, wsi_id, split)` convention as
`TrainingTaskRepository.create()`.

### 5. Include external validation linkage without making it the main model

External test runs should not create a second trained model. Instead, attach
external results to the same training task/model metadata:

- `external_test_history`
- external dataset id/name
- external run id
- external metrics
- path to external predictions/report artifacts

Keep the primary `TrainedModel.model_path` from the internal full training run.

### 6. Surface registration failure clearly

If registration fails, the session should still complete, but the final state and
UI should expose a clear warning:

```json
{
  "pathlab_model_registration": {
    "registered": false,
    "reason": "...",
    "session_id": "...",
    "run_id": "..."
  }
}
```

Do not silently swallow failures as only a backend log line.

## Acceptance Criteria

- A successful full PathScientist training run creates or updates exactly one
  `TrainingTask` and one `TrainedModel`.
- Quick-check runs and external-test runs do not create trained models.
- Re-persisting the same completed session is idempotent.
- `TrainedModel.model_path` points to an existing durable `best_model.pth`.
- PathLab model/task list APIs can see the new task/model for the correct user.
- Internal test metrics are visible as the model's main classification metrics.
- External metrics are attached as external validation metadata, not mistaken for
  the internal score.
- The persisted PathScientist session contains `pathlab_model_registration` with
  `registered=true`, `training_task_id`, `model_id`, and `model_path`.

## Verification Commands

Run focused unit tests:

```bash
cd server
OPENHANDS_SUPPRESS_BANNER=1 backend/pathscientist/.venv/bin/python -m pytest \
  tests/test_auto_research_repository.py \
  tests/test_pathscientist_persistence_safety.py \
  tests/test_pathscientist_routes.py -q
```

After an end-to-end web session finishes, verify the database:

```sql
select task_id, task_name, status, user_id, model_config
from training_tasks
where task_id like 'pathscientist_%'
order by updated_at desc
limit 5;

select model_id, task_id, model_name, model_path, feature_extractor, aggregator
from trained_models
where model_id like 'pathscientist_%'
order by updated_at desc
limit 5;
```

## Notes

- Keep all database writes in the Gateway/backend process. The generated agent
  code should not write directly to PathLab tables.
- Keep registration best-effort from the session perspective, but make failures
  visible to users and logs.
- Do not let external validation overwrite the trained model record.
- Keep model registration separate from dataset/feature registration, but reuse
  existing feature registration metadata when available.
