# PathLab Permission Baseline (Code-Backed)

This document summarizes the **current implemented permission model** in PathLab, with strict code references.

Scope includes:
- Role boundaries
- Feature access (upload/data management/training/internal validation/external validation/AI chat/annotation/AutoResearch PathScientist/admin settings)
- Dataset visibility and grant/revoke behavior
- Annotation (personal/shared/collaborator/finalize)
- Annotation-to-new-dataset closed loop
- Boundary and revocation semantics

---

## 1) Role Model and Core Capability

### 1.1 Roles in system
- Roles are fixed to `admin`, `pathologist`, `guest`: `pathlab/pathlab-client/server/backend/auth/models.py`.
- Valid role set: `VALID_ROLES = {admin, pathologist, guest}`: `pathlab/pathlab-client/server/backend/auth/models.py`.

### 1.2 GPU base capability
- `can_use_gpu()` is true only for admin/pathologist, false for guest: `pathlab/pathlab-client/server/backend/auth/models.py`.
- Explicit dependency `require_can_use_gpu` rejects non-GPU users: `pathlab/pathlab-client/server/backend/auth/dependencies.py`.

### 1.3 Admin-only capability
- Settings APIs require admin: `pathlab/pathlab-client/server/gateway/routes/settings.py`.
- `require_admin` helper: `pathlab/pathlab-client/server/backend/auth/dependencies.py`.

---

## 2) Frontend Route Gating vs Backend Enforcement

### 2.1 Frontend route gates
- `/settings` uses `requireAdmin`: `pathlab/pathlab-client/src/renderer/src/App.tsx`.
- `/task-setup` and `/results` use `requireGpu`: `pathlab/pathlab-client/src/renderer/src/App.tsx`, `pathlab/pathlab-client/src/renderer/src/App.tsx`.
- `/pathscientist`, `/pathscientist/new`, and `/pathscientist/sessions/:id` are protected AutoResearch / PathScientist routes: `pathlab/pathlab-client/src/renderer/src/App.tsx`.
- `ProtectedRoute` checks only login/admin/gpu flags and redirects accordingly: `pathlab/pathlab-client/src/renderer/src/components/ProtectedRoute.tsx`.

### 2.2 Backend is source-of-truth
- All sensitive operations are enforced server-side with permission checks in route handlers/helpers (examples in sections below).

---

## 3) Dataset/WSI Access and Ownership Rules

### 3.1 Dataset read access (`check_dataset_access_permission`)
Order of allow rules:
1. admin
2. dataset is public
3. owner
4. explicit `can_read` grant
5. ancestor collaboration (`can_collaborate` on ancestor dataset)

Code: `pathlab/pathlab-client/server/backend/auth/dependencies.py`.

### 3.2 Dataset write access (`check_dataset_write_permission`)
Allow rules:
1. admin
2. owner
3. direct `can_collaborate`
4. ancestor `can_collaborate`

Code: `pathlab/pathlab-client/server/backend/auth/dependencies.py`.

### 3.3 WSI access (`check_wsi_access_permission`)
Allow rules:
1. admin
2. dataset is public
3. WSI owner
4. explicit dataset `can_read`
5. ancestor collaboration

Code: `pathlab/pathlab-client/server/backend/auth/dependencies.py`.

### 3.4 Task visibility (`check_task_access_permission`)
- Admin can view all; non-admin must be task owner.
- This is the key basis for training/internal/external task visibility.

Code: `pathlab/pathlab-client/server/backend/auth/dependencies.py`.

---

## 4) Feature Access Matrix (Current Implementation)

## 4.1 Upload
- CSV upload endpoint: authenticated user (`current_active_user`): `pathlab/pathlab-client/server/gateway/routes/wsi_upload.py`.
- File upload endpoint: authenticated user: `pathlab/pathlab-client/server/gateway/routes/wsi_upload.py`.
- Path upload endpoint: authenticated user: `pathlab/pathlab-client/server/gateway/routes/wsi_upload.py`.
- Regression test verifies CSV route is no longer pathologist/admin-only: `pathlab/pathlab-client/server/tests/test_permission_closure_regressions.py`.

Conclusion: **guest can upload** (subject to downstream dataset/write validation logic where applicable).

## 4.2 Data management (rename/type/data-level/source/delete/update metadata)
- Dataset operations generally require owner/admin via `require_owner=True` on `get_dataset_with_access`: examples at `pathlab/pathlab-client/server/gateway/routes/wsi.py`, `pathlab/pathlab-client/server/gateway/routes/wsi.py`, `pathlab/pathlab-client/server/gateway/routes/wsi.py`, `pathlab/pathlab-client/server/gateway/routes/wsi.py`.
- WSI delete/update metadata require owner/admin: `pathlab/pathlab-client/server/gateway/routes/wsi.py`, `pathlab/pathlab-client/server/gateway/routes/wsi.py`.

## 4.3 Training
- Create training task: authenticated user endpoint: `pathlab/pathlab-client/server/gateway/routes/training.py`.
- Enforced checks:
  - access to each selected WSI (`_has_wsi_training_access`): `pathlab/pathlab-client/server/gateway/routes/training.py`, `pathlab/pathlab-client/server/gateway/routes/training.py`
  - homogeneous `(task_type, data_type, aggregation_level)` across selected datasets: `pathlab/pathlab-client/server/gateway/routes/training.py`
  - request task/data type must match dataset contracts: `pathlab/pathlab-client/server/gateway/routes/training.py`
  - GPU permission check by dataset for non-GPU users: `pathlab/pathlab-client/server/gateway/routes/training.py`
- Task list/detail filtered by owner unless admin via `get_user_id_filter` and ownership checks: `pathlab/pathlab-client/server/gateway/routes/training.py`, `pathlab/pathlab-client/server/gateway/routes/training.py`, `pathlab/pathlab-client/server/backend/auth/dependencies.py`.
- **Rerun** (failed or cancelled training tasks):
  - Frontend shows the rerun button for both `failed` and `cancelled` task statuses: `pathlab/pathlab-client/src/renderer/src/pages/TaskDetailPage.tsx`.
  - Non-admin rerun: submits a new task owned by the current user; `rerun_from_task_id` is not sent. All standard permission checks (WSI access, GPU) apply to the requester.
  - Admin rerun: frontend passes `rerun_from_task_id = source_task_id`; backend sets `effective_task_owner_user_id = source_task.user_id` so the new task is owned by the **original task's user**, not the admin: `pathlab/pathlab-client/server/gateway/routes/training.py`. Admin bypasses per-WSI access checks and GPU permission checks during submission.
  - `rerun_from_task_id` is silently ignored if the caller is not admin (backend gate: `user.is_admin() and req.rerun_from_task_id`): `pathlab/pathlab-client/server/gateway/routes/training.py`.

## 4.4 Internal validation (implemented as task analysis flow)
- Internal validation trigger is `POST /results/tasks/{task_id}/analysis`: `pathlab/pathlab-client/server/gateway/routes/results.py`.
- Enforced checks:
  - `_get_task_with_access` (owner/admin visibility): implemented in `pathlab/pathlab-client/server/gateway/routes/analysis_utils.py` and imported by `pathlab/pathlab-client/server/gateway/routes/results.py`
  - dataset-level access check for non-admin users: even if a pathologist's role grants GPU capability, `run_task_analysis` additionally verifies `check_dataset_access_permission`; revoked dataset access returns HTTP 403 before the task is queued: `pathlab/pathlab-client/server/gateway/routes/results.py`
  - `_require_task_gpu_permission` for analysis execution path: implemented in `pathlab/pathlab-client/server/gateway/routes/analysis_utils.py` and invoked by `pathlab/pathlab-client/server/gateway/routes/results.py`
- Analysis visibility:
  - `GET /results/tasks/{task_id}/analysis` filters non-admin to analyses submitted by that user: `pathlab/pathlab-client/server/gateway/routes/results.py`, `pathlab/pathlab-client/server/gateway/routes/results.py`.
- Frontend behaviour on revoked dataset:
  - `AnalysisConfigCard` catches HTTP 403 from `run_task_analysis` and shows a localised toast; the task remains visible (read-only), only new analysis submissions are blocked: `pathlab/pathlab-client/src/renderer/src/components/chat/AnalysisConfigCard.tsx`.
  - i18n key: `chatComponents.analysisConfig.datasetAccessRevoked` (en-US / zh-CN / zh-HK): `pathlab/pathlab-client/src/renderer/src/locales/en-US.json`.

## 4.5 External validation
- Entry: `POST /results/external-validation`: `pathlab/pathlab-client/server/gateway/routes/results.py`.
- Enforced checks:
  - model ownership/task access (`_require_task_access`): `pathlab/pathlab-client/server/gateway/routes/results.py`
  - target dataset access (`_has_external_validation_dataset_access`): `pathlab/pathlab-client/server/gateway/routes/results.py`, `pathlab/pathlab-client/server/gateway/routes/results.py`
  - dataset GPU permission: `pathlab/pathlab-client/server/gateway/routes/results.py`
  - model/dataset compatibility (`data_type/task_type/aggregation_level/labels/features`): `pathlab/pathlab-client/server/gateway/routes/results.py`
- Auto-triggers post-inference analysis, but task visibility still follows owner/admin model: `pathlab/pathlab-client/server/gateway/routes/inference_external_validation.py`, `pathlab/pathlab-client/server/gateway/routes/inference_external_validation.py`.
- **Rerun** (failed or cancelled external validation tasks):
  - Frontend shows the rerun button for both `failed` and `cancelled` task statuses: `pathlab/pathlab-client/src/renderer/src/pages/TaskDetailPage.tsx`.
  - Non-admin rerun: submits a new external validation owned by the current user; `rerun_from_task_id` is not sent. All standard permission checks (model access, dataset access, GPU) apply to the requester.
  - Admin rerun: frontend passes `rerun_from_task_id = source_task_id`; backend sets `effective_task_owner_user_id = source_task.user_id` so the new task is owned by the **original task's user**, not the admin: `pathlab/pathlab-client/server/gateway/routes/results.py`. All permission checks (model, dataset, GPU) are still evaluated against the **requesting admin user**, not the effective owner.
  - `rerun_from_task_id` is silently ignored if the caller is not admin (backend gate: `user.is_admin() and req.rerun_from_task_id`): `pathlab/pathlab-client/server/gateway/routes/results.py`.

## 4.6 AI chat
- Chat page is protected by login route guard (`/dashboard`): `pathlab/pathlab-client/src/renderer/src/App.tsx`.

## 4.7 Admin settings
- Backend admin-only for get/update/check-vllm/check-asr operations: `pathlab/pathlab-client/server/gateway/routes/settings.py`, `pathlab/pathlab-client/server/gateway/routes/settings.py`, `pathlab/pathlab-client/server/gateway/routes/settings.py`, `pathlab/pathlab-client/server/gateway/routes/settings.py`.

## 4.8 AutoResearch / PathScientist
- Added on `2026-06-23`; PathScientist is the implementation codename for the AutoResearch user feature.
- Frontend routes are protected by login at `/pathscientist`, `/pathscientist/new`, and `/pathscientist/sessions/:id`: `pathlab/pathlab-client/src/renderer/src/App.tsx`.
- Gateway exposes PathScientist under both `/pathscientist/...` and `/api/pathscientist/...` because `app_setup.py` registers each router directly and again with `/api` prefix: `pathlab/pathlab-client/server/gateway/app_setup.py`.
- Session management endpoints require `current_active_user`; non-admin access is limited to sessions owned by that user: `pathlab/pathlab-client/server/gateway/routes/pathscientist.py`.
- Dataset mounts supplied to a PathScientist session are resolved through PathLab dataset access checks before being passed into the runtime: `pathlab/pathlab-client/server/gateway/routes/pathscientist.py`.
- Artifact download and SSE event endpoints use PathScientist-specific short-lived access tokens because browser download/event-stream clients cannot always attach normal headers: `pathlab/pathlab-client/server/gateway/routes/pathscientist.py`.
- Compact history is indexed in `auto_research_sessions`, `auto_research_experiments`, and `auto_research_events`; full workspace/artifact state remains on disk under the configured PathScientist base directory: `pathlab/pathlab-client/server/backend/database/models.py`.

---

## 5) Dataset Visibility, Grants, and Revocation

## 5.1 Visibility model
- Dataset has `is_public` and `parent_dataset_id` fields (hierarchy support): `pathlab/pathlab-client/server/backend/database/models.py`.
- Public datasets are globally readable (authenticated users), private require owner/admin/grant logic via access checks in dependencies.

## 5.2 Grant model
- Grant dimensions: `can_read`, `can_collaborate`, `can_use_gpu`: `pathlab/pathlab-client/server/gateway/routes/wsi_grants.py`.
- The public `POST /datasets/{dataset_id}/grants` endpoint always forces `can_read=True, can_collaborate=False, can_use_gpu=False`; the `can_collaborate` dimension is set separately via the collaborator add endpoint, and `can_use_gpu` is only accessible through the internal `_grant_or_renew_permission` helper.
- Guest cannot receive GPU grants:
  - runtime guard in `_grant_or_renew_permission`: `pathlab/pathlab-client/server/gateway/routes/wsi_grants.py`
  - test coverage: `pathlab/pathlab-client/server/tests/test_permission_policy_updates.py`.
- `check_dataset_gpu_permission` behaviour: if `user.can_use_gpu()` is true (admin/pathologist), return immediately; otherwise **always** consult `DatasetGrantRepository.has_valid_gpu` for all roles including guest. There is no separate `is_guest()` short-circuit — the DB query is the sole gate: `pathlab/pathlab-client/server/backend/auth/dependencies.py`. The net result for guest is unchanged (no GPU grant is ever stored for a guest), but the code path is now uniform.

## 5.3 Revoke model and side effects
- Single revoke endpoint: `DELETE /datasets/{dataset_id}/grants/{target_user_id}`: `pathlab/pathlab-client/server/gateway/routes/wsi_grants.py`.
- Batch revoke endpoint: `POST /datasets/{dataset_id}/grants/batch-revoke`: `pathlab/pathlab-client/server/gateway/routes/wsi_grants.py`.
- Revoke side effects include:
  - find affected running tasks using dataset WSIs: `pathlab/pathlab-client/server/gateway/routes/wsi_grants.py`
  - notify AI service to revoke permission on running tasks: `pathlab/pathlab-client/server/gateway/routes/wsi_grants.py`
  - cascade revoke on child datasets: `pathlab/pathlab-client/server/gateway/routes/wsi_grants.py`
  - audit log entries: `pathlab/pathlab-client/server/gateway/routes/wsi_grants.py`.
- Cross-process revocation (in-process tasks): `_notify_ai_service_permission_revocation` now calls `_local_revoke(task_id)` (via `backend.ai.permission_revocation.revoke_task_permission`) **before** the HTTP call to the AI service. This ensures that external-validation tasks running in the same Gateway process are interrupted even if the HTTP round-trip has not yet completed: `pathlab/pathlab-client/server/gateway/routes/wsi_grants.py`, `pathlab/pathlab-client/server/gateway/routes/wsi_grants.py`.
- In-flight external-validation checkpoint locations: tasks check `is_permission_revoked(task_id)` at the following points and raise `PermissionRevokedException` if revoked:
  - `_run_external_validation_patch_segmentation`: after PATCHING 10 (`pathlab/pathlab-client/server/gateway/routes/inference_external_validation.py`) and after inference thread returns before DB save (`pathlab/pathlab-client/server/gateway/routes/inference_external_validation.py`). `clear_revocation(task_id)` is called in `finally`.
  - `_run_external_validation_patch_classification`: after PATCHING 10 (`pathlab/pathlab-client/server/gateway/routes/inference_external_validation.py`) and after inference thread returns before DB save (`pathlab/pathlab-client/server/gateway/routes/inference_external_validation.py`). `clear_revocation(task_id)` is called in `finally`.
  - `_run_external_validation` (survival / main body): after PATCHING 0 (`pathlab/pathlab-client/server/gateway/routes/inference_external_validation.py`) and before TRAINING 35 (`pathlab/pathlab-client/server/gateway/routes/inference_external_validation.py`).

## 5.4 Public->private transition side effect
- When visibility switches public->private, non-owner running training tasks on that dataset can be stopped: `pathlab/pathlab-client/server/gateway/routes/wsi_grants.py`.

---

## 6) Annotation Permission Model

## 6.1 Shared annotation access
- `can_access_shared` allows only admin / dataset owner / explicit collaborator grant.
- Public dataset status does not grant shared annotation access by itself.

Code: `pathlab/pathlab-client/server/backend/auth/annotation_permissions.py`.
Test: `pathlab/pathlab-client/server/tests/test_permission_policy_updates.py`.

## 6.2 Personal annotation access
- Route-level owner/admin restriction for dataset-scoped personal operations via `_require_personal_annotation_owner`: `pathlab/pathlab-client/server/gateway/routes/annotation.py`, `pathlab/pathlab-client/server/gateway/routes/annotation.py`.
- Repository-level access guard for personal drafts via `get_with_permission` owner/admin-only behavior: `pathlab/pathlab-client/server/backend/database/repositories/annotation.py`.

## 6.3 Shared finalize
- Only owner/admin can finalize shared annotation into GT: `pathlab/pathlab-client/server/gateway/routes/annotation.py`.
- Finalize writes `label_{dataset_id}` as `status=finalized`, then removes shared draft: `pathlab/pathlab-client/server/gateway/routes/annotation.py`, `pathlab/pathlab-client/server/gateway/routes/annotation.py`.

## 6.4 Collaborator management
- Add/remove collaborator requires owner/admin (`can_finalize`): `pathlab/pathlab-client/server/gateway/routes/annotation.py`, `pathlab/pathlab-client/server/gateway/routes/annotation.py`.
- Removing collaborator cascades child-dataset collaborator revoke behavior and emits collaboration revocation events (`access_revoked`, `force_disconnect`): `pathlab/pathlab-client/server/gateway/routes/annotation.py`, `pathlab/pathlab-client/server/gateway/routes/annotation.py`, `pathlab/pathlab-client/server/gateway/routes/annotation.py`.

## 6.5 Annotation source semantics
- `annotation_source` is a **derived read-only field** computed at query time; it is never stored as a column.
- Value is `"imported_gt"` when the effective annotation record was imported externally (mask GT import flow), `"user_label"` when it originated from user-drawn or finalized shared annotation.
- Derivation logic lives in `GET /annotation/datasets/{dataset_id}/labels` and `GET /annotation/datasets/{dataset_id}/summary`: `pathlab/pathlab-client/server/gateway/routes/annotation.py`, `pathlab/pathlab-client/server/gateway/routes/annotation.py`.
- `SegmentationAnnotation.to_dict()` also exposes `annotation_source` per-record for the WSI-viewer GT overlay: `pathlab/pathlab-client/server/backend/database/models.py`.
- Frontend `AnnotationSource` type mirrors the two values: `pathlab/pathlab-client/src/renderer/src/api/annotation.ts`.

---

## 7) Data Type / Task Type / Aggregation Constraints

## 7.1 Segmentation hard contract
- Constants define segmentation contract as `task_type=segmentation`, `data_type=patch`, `aggregation_level=file`: `pathlab/pathlab-client/server/gateway/utils.py`.
- Contract validator exists: `ensure_segmentation_contract`: `pathlab/pathlab-client/server/gateway/utils.py`.
- Dataset-level validator wrapper: `ensure_dataset_segmentation_contract`: `pathlab/pathlab-client/server/gateway/utils.py`.

## 7.2 Training consistency constraints
- All selected datasets for one training job must share same `(task_type, data_type, aggregation_level)`: `pathlab/pathlab-client/server/gateway/routes/training.py`.
- Requested `task_type`/`data_type` must match resolved dataset contracts: `pathlab/pathlab-client/server/gateway/routes/training.py`.

## 7.3 Dataset updates constrained by task type
- Segmentation dataset cannot switch aggregation to `case`: `pathlab/pathlab-client/server/gateway/routes/wsi.py`.
- Segmentation WSIs reject image-level label updates: `pathlab/pathlab-client/server/gateway/routes/wsi.py`.

---

## 8) Annotation -> New Dataset Closed Loop

## 8.1 Extraction entry
- Entry endpoint is `POST /annotation/extract`: `pathlab/pathlab-client/server/gateway/routes/annotation.py`.
- Supports dataset-scope extraction from effective annotations (GT + overlay): `pathlab/pathlab-client/server/gateway/routes/annotation.py`.

## 8.2 Access and mode checks during extraction
- Shared extraction requires shared-access check (`can_access_shared`): `pathlab/pathlab-client/server/gateway/routes/annotation.py`.
- Every referenced WSI rechecked via `get_wsi_with_access`: `pathlab/pathlab-client/server/gateway/routes/annotation.py`.

## 8.3 Inheritance into new dataset payload
- When extraction is sourced from an existing dataset, payload carries:
  - `source_dataset_id`
  - `parent_dataset_id = source_dataset_id`
  - inherited `is_public` from parent dataset

Code: `pathlab/pathlab-client/server/gateway/routes/annotation.py`.

## 8.4 Finalization as closed-loop stabilization
- Shared finalize persists GT into finalized record and removes draft, stabilizing produced annotation state before downstream extraction: `pathlab/pathlab-client/server/gateway/routes/annotation.py`, `pathlab/pathlab-client/server/gateway/routes/annotation.py`, `pathlab/pathlab-client/server/gateway/routes/annotation.py`.

## 8.5 Extraction audit: promoted_to_training_reference
- When extraction succeeds, a `promoted_to_training_reference` audit event is written to `permission_audit_logs` recording the source annotation ID and new dataset ID.
- This closes the data loop traceability: the audit log links the annotation that was promoted to a training dataset.

Code: `pathlab/pathlab-client/server/gateway/routes/annotation.py`.

---

## 9) Boundary Conditions and Safety Handling

## 9.1 Revocation vs historical artifacts
- Annotation cleanup by dataset/user intentionally deletes only `draft` records; finalized records remain.
- This preserves historical outputs after permission revocation.

Code: `pathlab/pathlab-client/server/backend/database/repositories/annotation.py`.

## 9.2 Shared edit concurrency
- Shared upsert supports version-based conflict handling (`expected_version`) with force override only for owner/admin flows.

Code: `pathlab/pathlab-client/server/backend/database/repositories/annotation.py`.

## 9.3 Empty finalize guard
- Shared finalize rejects empty annotations unless `force=true`: `pathlab/pathlab-client/server/gateway/routes/annotation.py`.

## 9.4 Label deletion guard with active training
- Label delete endpoint (`DELETE /annotation/datasets/{dataset_id}/labels`) blocks when active training tasks exist: `pathlab/pathlab-client/server/gateway/routes/annotation.py`.
- Note: the guard is system-wide — any active training task (regardless of dataset) will block deletion.

## 9.5 Task access and analysis visibility boundary
- Task analysis endpoints require task access checks; non-admin analysis listing is further filtered to analyses submitted by current user.

Code: `pathlab/pathlab-client/server/gateway/routes/results.py`, `pathlab/pathlab-client/server/gateway/routes/results.py`.

---

## 10) Tests that Anchor Current Permission Behavior

### Existing anchors
- Guest cannot gain GPU via dataset grant (no valid DB grant → denied): `pathlab/pathlab-client/server/tests/test_permission_policy_updates.py`.
- Shared annotation requires explicit collaborator even for public dataset: `pathlab/pathlab-client/server/tests/test_permission_policy_updates.py`.
- Non-owner cannot read personal draft via repository permission API: `pathlab/pathlab-client/server/tests/test_permission_policy_updates.py`.
- Dataset/WSI access ancestor grant logic: `pathlab/pathlab-client/server/tests/test_permission_logic.py`, `pathlab/pathlab-client/server/tests/test_permission_logic.py`.
- Upload CSV route gate is authenticated-user (guest-capable) regression check: `pathlab/pathlab-client/server/tests/test_permission_closure_regressions.py`.

### Revocation and GPU-grant anchors (`test_permission_revocation_fixes.py`)
- `check_dataset_gpu_permission` reaches `has_valid_gpu` DB query for all `can_use_gpu()=False` users: `test_gpu_permission_reaches_has_valid_gpu_when_can_use_gpu_false`.
- Pathologist (role-level GPU) never hits DB in `check_dataset_gpu_permission`: `test_gpu_permission_pathologist_never_hits_db`.
- Non-GPU user without a valid DB grant is denied: `test_gpu_permission_denied_when_no_grant_and_can_use_gpu_false`.
- `_notify_ai_service_permission_revocation` marks task revoked in-process before HTTP call succeeds: `test_notify_revocation_marks_task_revoked_in_process`.
- Local revoke fires even when HTTP call to AI service fails: `test_notify_revocation_marks_task_even_when_http_fails`.
- `run_task_analysis` raises HTTP 403 when dataset access has been revoked: `test_run_task_analysis_raises_403_when_dataset_access_revoked`.
- Admin bypasses dataset access check in `run_task_analysis`: `test_run_task_analysis_admin_skips_dataset_access_check`.
- `revoke_task_permission` / `clear_revocation` lifecycle: `test_revoke_marks_task_and_clear_removes_it`, `test_revoke_affects_only_named_task`, `test_clear_revocation_is_idempotent`.
- `PermissionRevokedException` is an `Exception` subclass: `test_permission_revoked_exception_is_exception_subclass`.

---

## 11) Practical Summary (Current State)

- **Guest**: can upload and access permitted/public data; cannot perform GPU-required flows (training/external validation/internal analysis requiring GPU), cannot access admin settings. Authenticated guests can open PathScientist routes, but any dataset mounts still go through normal dataset access checks and downstream GPU work remains subject to the relevant execution/runtime constraints. `check_dataset_gpu_permission` no longer has a dedicated `is_guest()` short-circuit — the DB query (`has_valid_gpu`) is the uniform gate, which still returns false for guest because no GPU grant is ever stored for guest accounts.
- **Pathologist**: can use GPU flows and non-admin product functions under dataset/task ownership/grant boundaries. Role-level `can_use_gpu()` bypasses the DB grant check, but `run_task_analysis` now enforces an additional `check_dataset_access_permission` check so that a revoked dataset grant blocks new analysis submissions even for pathologists.
- **Admin**: full access, plus global settings and grant/revoke controls. Admin bypasses the dataset access check in `run_task_analysis`.

**Revocation semantics for in-flight tasks**: on grant revocation the system (a) performs a local in-process revoke synchronously, then (b) notifies the AI service over HTTP. In-flight external-validation tasks across all three paths (patch-segmentation, patch-classification, survival) check `is_permission_revoked` at multiple checkpoints and abort before committing results to the database.

**Analysis submission after revocation**: the dataset and its tasks remain visible to the user. Only new analysis submissions are blocked; the frontend shows a user-friendly toast (`datasetAccessRevoked`) instead of a raw error.

Key architectural point: permissions are a combination of **role capability** + **resource ownership/grants** + **task visibility ownership**.

---

## 12) Registered Routers Not Covered in Sections 1–11

Gateway registers 18 top-level routers. The following are authenticated-user-only (require `current_active_user`) unless noted:

| Router | Auth level | Notes |
|---|---|---|
| `stats` | authenticated user | Storage/usage stats for the current user's own data; admin sees all |
| `gpu` | authenticated user | GPU queue status; read-only |
| `heatmap` | `get_user_from_header_or_param` | Image endpoints accept token via `Authorization` header **or** `?token=` query param (see Section 13.2) |
| `models` | authenticated user | Trained-model list/detail filtered by ownership (same `get_user_id_filter` pattern as training); delete requires owner/admin |
| `ai_tasks` | authenticated user | AI task list filtered to current user unless admin |
| `training_options` | authenticated user | Read-only endpoint returning available extractor/aggregator options; no ownership logic |
| `asr` | `?token=` query param (WebSocket) | See Section 13.3 for dedicated auth path |
| `pathscientist` | authenticated user for session management; PathScientist access token for SSE/download | AutoResearch session owner/admin boundary; artifact/SSE token is minted from an authenticated session |

`wsi_grants` is not a top-level router but an auxiliary module included by the `wsi` router. Grant creation (`POST /datasets/{dataset_id}/grants`) requires the caller to be **admin only** (`require_admin` dependency): `pathlab/pathlab-client/server/gateway/routes/wsi_grants.py`. Dataset owners without admin role cannot create grants through this endpoint.

Current top-level router registration lives in `server/gateway/app_setup.py`; update this section from that file rather than from route filenames alone, because several `routes/*.py` modules are support modules imported by top-level routers.

---

## 13) Auth Mechanisms Not Covered Above

### 13.1 User Registration Flow

Self-service registration and administrator account creation are intentionally separate:

| Endpoint | Resulting state | Allowed roles | Notes |
|---|---|---|---|
| `POST /auth/register` | disabled (HTTP 410) | none | Public direct registration is blocked; use request-access instead |
| `POST /auth/request-access` | `is_active=False` (admin must activate) | `guest` | Self-service access request with educational email validation |
| `POST /auth/users` | `is_active=True` (immediately usable) | `admin`, `pathologist`, `guest` | Admin-only direct account creation; email is optional and no application emails are sent |

Only admin can create or elevate a user to `pathologist` or `admin` role (via `POST /auth/users` or `AdminUserUpdate`).

Default admin account: created on first run when no users exist (`backend/database/database.py:327`). Password is taken from `DEFAULT_ADMIN_PASSWORD` env var. The unified backend launcher (`server/main.py`) defaults that env var to `admin` unless the operator provides a different value.

**Email notifications** (triggered by `gateway/email_notifications.py` via `send_templated_email`):

| Event | Recipient | Trigger |
|---|---|---|
| `new_user_registration_notice` | applicant's `registration_email` | immediately after `POST /auth/request-access` succeeds |
| `admin_new_user_registration_notice` | admin `admin_notify_email` setting | same as above (admin alert) |
| `account_activated` | applicant's `registration_email` | when admin activates a previously inactive user via `AdminUserUpdate(is_active=True)` |

Email delivery is fire-and-forget (`asyncio.create_task`). If `registration_email` is absent or `admin_notify_email` is not configured, the corresponding notification is silently skipped. Email templates are configurable via the `email_templates` global setting.

### 13.2 Token-in-URL Pattern (SSE and Image Endpoints)

Server-Sent Events and browser-loaded image/tile/heatmap URLs cannot set `Authorization` headers. These endpoints accept the JWT via a `?token=` query parameter:

- SSE streams: training logs, results logs, storage task progress (`get_user_from_token_param`)
- Image/tile/heatmap URLs: `get_user_from_header_or_param` (prefers `Authorization: Bearer`, falls back to `?token=`)

Both helpers call the same `_get_user_from_jwt` internally, which enforces the active `session_nonces` set (legacy `session_nonce` is only kept for schema compatibility): `backend/auth/dependencies.py:315`.

Security implication: tokens in URLs appear in server access logs and browser history. These endpoints are intentionally short-lived resource fetches; the JWT lifetime is the same as all other endpoints.

### 13.3 ASR WebSocket Auth

`GET /asr/realtime` (WebSocket) accepts `?token=` because WebSocket handshakes cannot carry `Authorization` headers in browser environments.

Auth path: `gateway/routes/asr.py:249` calls `_get_user_from_jwt(token, db)` from `backend/auth/dependencies.py`, which enforces full JWT validation against the current `session_nonces` list. A token invalidated by a new login on another device is rejected at this endpoint identically to all REST endpoints.

### 13.4 JWT Configuration

`JWT_SECRET` is read from the environment at startup (`backend/auth/users.py:37`). If unset, a new random secret is generated each run, invalidating all existing sessions on restart. **Production deployments must set `JWT_SECRET` as a persistent environment variable.**

JWT lifetime is controlled by `Config.JWT_LIFETIME_SECONDS`.

### 13.5 CORS Policy

All three services currently use `allow_origins=["*"]`. For web deployment mode, Gateway's CORS should be restricted to the known frontend origin. The Preprocessing and AI services are internal-only (listen on localhost); they do not need CORS middleware.

### 13.6 `/auth/jwt/login` Status

The standard FastAPI-Users login route (`POST /auth/jwt/login`) is actively blocked by an override route registered before `include_router`, ensuring FastAPI's first-match routing returns HTTP 405 before the FastAPI-Users handler can run: `pathlab/pathlab-client/server/gateway/routes/auth.py`. The only functional login path is `POST /auth/secure-login`, which validates a client-side SHA-256 hashed password and optionally enforces Turnstile: `pathlab/pathlab-client/server/gateway/routes/auth.py`.
