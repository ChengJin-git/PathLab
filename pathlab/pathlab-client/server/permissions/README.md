# PathLab Permission Baseline (Code-Backed)

This document summarizes the **current implemented permission model** in PathLab, with strict code references.

Scope includes:
- Role boundaries
- Feature access (upload/data management/training/internal validation/external validation/AI chat/annotation/admin settings)
- Dataset visibility and grant/revoke behavior
- Annotation (personal/shared/collaborator/finalize)
- Annotation-to-new-dataset closed loop
- Boundary and revocation semantics

---

## 1) Role Model and Core Capability

### 1.1 Roles in system
- Roles are fixed to `admin`, `pathologist`, `guest`: `pathlab/pathlab-client/server/backend/auth/models.py:120`.
- Valid role set: `VALID_ROLES = {admin, pathologist, guest}`: `pathlab/pathlab-client/server/backend/auth/models.py:124`.

### 1.2 GPU base capability
- `can_use_gpu()` is true only for admin/pathologist, false for guest: `pathlab/pathlab-client/server/backend/auth/models.py:137`.
- Explicit dependency `require_can_use_gpu` rejects non-GPU users: `pathlab/pathlab-client/server/backend/auth/dependencies.py:36`.

### 1.3 Admin-only capability
- Settings APIs require admin: `pathlab/pathlab-client/server/gateway/routes/settings.py:103`.
- `require_admin` helper: `pathlab/pathlab-client/server/backend/auth/dependencies.py:17`.

---

## 2) Frontend Route Gating vs Backend Enforcement

### 2.1 Frontend route gates
- `/settings` uses `requireAdmin`: `pathlab/pathlab-client/src/renderer/src/App.tsx:42`.
- `/task-setup` and `/results` use `requireGpu`: `pathlab/pathlab-client/src/renderer/src/App.tsx:43`, `pathlab/pathlab-client/src/renderer/src/App.tsx:48`.
- `ProtectedRoute` checks only login/admin/gpu flags and redirects accordingly: `pathlab/pathlab-client/src/renderer/src/components/ProtectedRoute.tsx:21`.

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

Code: `pathlab/pathlab-client/server/backend/auth/dependencies.py:127`.

### 3.2 Dataset write access (`check_dataset_write_permission`)
Allow rules:
1. admin
2. owner
3. direct `can_collaborate`
4. ancestor `can_collaborate`

Code: `pathlab/pathlab-client/server/backend/auth/dependencies.py:161`.

### 3.3 WSI access (`check_wsi_access_permission`)
Allow rules:
1. admin
2. dataset is public
3. WSI owner
4. explicit dataset `can_read`
5. ancestor collaboration

Code: `pathlab/pathlab-client/server/backend/auth/dependencies.py:85`.

### 3.4 Task visibility (`check_task_access_permission`)
- Admin can view all; non-admin must be task owner.
- This is the key basis for training/internal/external task visibility.

Code: `pathlab/pathlab-client/server/backend/auth/dependencies.py:282`.

---

## 4) Feature Access Matrix (Current Implementation)

## 4.1 Upload
- CSV upload endpoint: authenticated user (`current_active_user`): `pathlab/pathlab-client/server/gateway/routes/wsi_upload.py:151`.
- File upload endpoint: authenticated user: `pathlab/pathlab-client/server/gateway/routes/wsi_upload.py:356`.
- Path upload endpoint: authenticated user: `pathlab/pathlab-client/server/gateway/routes/wsi_upload.py:817`.
- Regression test verifies CSV route is no longer pathologist/admin-only: `pathlab/pathlab-client/server/tests/test_permission_closure_regressions.py:245`.

Conclusion: **guest can upload** (subject to downstream dataset/write validation logic where applicable).

## 4.2 Data management (rename/type/data-level/source/delete/update metadata)
- Dataset operations generally require owner/admin via `require_owner=True` on `get_dataset_with_access`: examples at `pathlab/pathlab-client/server/gateway/routes/wsi.py:814`, `pathlab/pathlab-client/server/gateway/routes/wsi.py:868`, `pathlab/pathlab-client/server/gateway/routes/wsi.py:995`, `pathlab/pathlab-client/server/gateway/routes/wsi.py:1073`.
- WSI delete/update metadata require owner/admin: `pathlab/pathlab-client/server/gateway/routes/wsi.py:1238`, `pathlab/pathlab-client/server/gateway/routes/wsi.py:1312`.

## 4.3 Training
- Create training task: authenticated user endpoint: `pathlab/pathlab-client/server/gateway/routes/training.py:243`.
- Enforced checks:
  - access to each selected WSI (`_has_wsi_training_access`): `pathlab/pathlab-client/server/gateway/routes/training.py:50`, `pathlab/pathlab-client/server/gateway/routes/training.py:318`
  - homogeneous `(task_type, data_type, aggregation_level)` across selected datasets: `pathlab/pathlab-client/server/gateway/routes/training.py:360`
  - request task/data type must match dataset contracts: `pathlab/pathlab-client/server/gateway/routes/training.py:370`
  - GPU permission check by dataset for non-GPU users: `pathlab/pathlab-client/server/gateway/routes/training.py:381`
- Task list/detail filtered by owner unless admin via `get_user_id_filter` and ownership checks: `pathlab/pathlab-client/server/gateway/routes/training.py:493`, `pathlab/pathlab-client/server/gateway/routes/training.py:708`, `pathlab/pathlab-client/server/backend/auth/dependencies.py:49`.
- **Rerun** (failed or cancelled training tasks):
  - Frontend shows the rerun button for both `failed` and `cancelled` task statuses: `pathlab/pathlab-client/src/renderer/src/pages/TaskDetailPage.tsx`.
  - Non-admin rerun: submits a new task owned by the current user; `rerun_from_task_id` is not sent. All standard permission checks (WSI access, GPU) apply to the requester.
  - Admin rerun: frontend passes `rerun_from_task_id = source_task_id`; backend sets `effective_task_owner_user_id = source_task.user_id` so the new task is owned by the **original task's user**, not the admin: `pathlab/pathlab-client/server/gateway/routes/training.py:280`. Admin bypasses per-WSI access checks and GPU permission checks during submission.
  - `rerun_from_task_id` is silently ignored if the caller is not admin (backend gate: `user.is_admin() and req.rerun_from_task_id`): `pathlab/pathlab-client/server/gateway/routes/training.py:280`.

## 4.4 Internal validation (implemented as task analysis flow)
- Internal validation trigger is `POST /results/tasks/{task_id}/analysis`: `pathlab/pathlab-client/server/gateway/routes/results.py:6034`.
- Enforced checks:
  - `_get_task_with_access` (owner/admin visibility): `pathlab/pathlab-client/server/gateway/routes/results.py:6057`, `pathlab/pathlab-client/server/gateway/routes/analysis_helpers.py:80`
  - dataset-level access check for non-admin users: even if a pathologist's role grants GPU capability, `run_task_analysis` additionally verifies `check_dataset_access_permission`; revoked dataset access returns HTTP 403 before the task is queued: `pathlab/pathlab-client/server/gateway/routes/results.py:6067`
  - `_require_task_gpu_permission` for analysis execution path: `pathlab/pathlab-client/server/gateway/routes/results.py:6084`, `pathlab/pathlab-client/server/gateway/routes/analysis_helpers.py:102`
- Analysis visibility:
  - `GET /results/tasks/{task_id}/analysis` filters non-admin to analyses submitted by that user: `pathlab/pathlab-client/server/gateway/routes/results.py:5926`, `pathlab/pathlab-client/server/gateway/routes/results.py:5994`.
- Frontend behaviour on revoked dataset:
  - `AnalysisConfigCard` catches HTTP 403 from `run_task_analysis` and shows a localised toast; the task remains visible (read-only), only new analysis submissions are blocked: `pathlab/pathlab-client/src/renderer/src/components/chat/AnalysisConfigCard.tsx`.
  - i18n key: `chatComponents.analysisConfig.datasetAccessRevoked` (en-US / zh-CN / zh-HK): `pathlab/pathlab-client/src/renderer/src/locales/en-US.json`.

## 4.5 External validation
- Entry: `POST /results/external-validation`: `pathlab/pathlab-client/server/gateway/routes/results.py:3034`.
- Enforced checks:
  - model ownership/task access (`_require_task_access`): `pathlab/pathlab-client/server/gateway/routes/results.py:3079`
  - target dataset access (`_has_external_validation_dataset_access`): `pathlab/pathlab-client/server/gateway/routes/results.py:3099`, `pathlab/pathlab-client/server/gateway/routes/results.py:142`
  - dataset GPU permission: `pathlab/pathlab-client/server/gateway/routes/results.py:3108`
  - model/dataset compatibility (`data_type/task_type/aggregation_level/labels/features`): `pathlab/pathlab-client/server/gateway/routes/results.py:3115`
- Auto-triggers post-inference analysis, but task visibility still follows owner/admin model: `pathlab/pathlab-client/server/gateway/routes/results.py:5721`, `pathlab/pathlab-client/server/gateway/routes/results.py:5781`.
- **Rerun** (failed or cancelled external validation tasks):
  - Frontend shows the rerun button for both `failed` and `cancelled` task statuses: `pathlab/pathlab-client/src/renderer/src/pages/TaskDetailPage.tsx`.
  - Non-admin rerun: submits a new external validation owned by the current user; `rerun_from_task_id` is not sent. All standard permission checks (model access, dataset access, GPU) apply to the requester.
  - Admin rerun: frontend passes `rerun_from_task_id = source_task_id`; backend sets `effective_task_owner_user_id = source_task.user_id` so the new task is owned by the **original task's user**, not the admin: `pathlab/pathlab-client/server/gateway/routes/results.py:3055`. All permission checks (model, dataset, GPU) are still evaluated against the **requesting admin user**, not the effective owner.
  - `rerun_from_task_id` is silently ignored if the caller is not admin (backend gate: `user.is_admin() and req.rerun_from_task_id`): `pathlab/pathlab-client/server/gateway/routes/results.py:3055`.

## 4.6 AI chat
- Chat page is protected by login route guard (`/dashboard`): `pathlab/pathlab-client/src/renderer/src/App.tsx:39`.

## 4.7 Admin settings
- Backend admin-only for get/update/check-vllm operations: `pathlab/pathlab-client/server/gateway/routes/settings.py:103`, `pathlab/pathlab-client/server/gateway/routes/settings.py:117`, `pathlab/pathlab-client/server/gateway/routes/settings.py:154`.

---

## 5) Dataset Visibility, Grants, and Revocation

## 5.1 Visibility model
- Dataset has `is_public` and `parent_dataset_id` fields (hierarchy support): `pathlab/pathlab-client/server/backend/database/models.py:149`.
- Public datasets are globally readable (authenticated users), private require owner/admin/grant logic via access checks in dependencies.

## 5.2 Grant model
- Grant dimensions: `can_read`, `can_collaborate`, `can_use_gpu`: `pathlab/pathlab-client/server/gateway/routes/wsi_grants.py:53`.
- The public `POST /datasets/{dataset_id}/grants` endpoint always forces `can_read=True, can_collaborate=False, can_use_gpu=False` (lines 426–428); the `can_collaborate` dimension is set separately via the collaborator add endpoint, and `can_use_gpu` is only accessible through the internal `_grant_or_renew_permission` helper.
- Guest cannot receive GPU grants:
  - runtime guard in `_grant_or_renew_permission`: `pathlab/pathlab-client/server/gateway/routes/wsi_grants.py:73`
  - test coverage: `pathlab/pathlab-client/server/tests/test_permission_policy_updates.py:131`.
- `check_dataset_gpu_permission` behaviour: if `user.can_use_gpu()` is true (admin/pathologist), return immediately; otherwise **always** consult `DatasetGrantRepository.has_valid_gpu` for all roles including guest. There is no separate `is_guest()` short-circuit — the DB query is the sole gate: `pathlab/pathlab-client/server/backend/auth/dependencies.py:293`. The net result for guest is unchanged (no GPU grant is ever stored for a guest), but the code path is now uniform.

## 5.3 Revoke model and side effects
- Single revoke endpoint: `DELETE /datasets/{dataset_id}/grants/{target_user_id}`: `pathlab/pathlab-client/server/gateway/routes/wsi_grants.py:546`.
- Batch revoke endpoint: `POST /datasets/{dataset_id}/grants/batch-revoke`: `pathlab/pathlab-client/server/gateway/routes/wsi_grants.py:582`.
- Revoke side effects include:
  - find affected running tasks using dataset WSIs: `pathlab/pathlab-client/server/gateway/routes/wsi_grants.py:112`
  - notify AI service to revoke permission on running tasks: `pathlab/pathlab-client/server/gateway/routes/wsi_grants.py:136`
  - cascade revoke on child datasets: `pathlab/pathlab-client/server/gateway/routes/wsi_grants.py:188`
  - audit log entries: `pathlab/pathlab-client/server/gateway/routes/wsi_grants.py:575`.
- Cross-process revocation (in-process tasks): `_notify_ai_service_permission_revocation` now calls `_local_revoke(task_id)` (via `backend.ai.permission_revocation.revoke_task_permission`) **before** the HTTP call to the AI service. This ensures that external-validation tasks running in the same Gateway process are interrupted even if the HTTP round-trip has not yet completed: `pathlab/pathlab-client/server/gateway/routes/wsi_grants.py:137`, `pathlab/pathlab-client/server/gateway/routes/wsi_grants.py:141`.
- In-flight external-validation checkpoint locations: tasks check `is_permission_revoked(task_id)` at the following points and raise `PermissionRevokedException` if revoked:
  - `_run_external_validation_patch_segmentation`: after PATCHING 10 (`pathlab/pathlab-client/server/gateway/routes/results.py:3703`) and after inference thread returns before DB save (`pathlab/pathlab-client/server/gateway/routes/results.py:3994`). `clear_revocation(task_id)` is called in `finally`.
  - `_run_external_validation_patch_classification`: after PATCHING 10 (`pathlab/pathlab-client/server/gateway/routes/results.py:4264`) and after inference thread returns before DB save (`pathlab/pathlab-client/server/gateway/routes/results.py:4390`). `clear_revocation(task_id)` is called in `finally`.
  - `_run_external_validation` (survival / main body): after PATCHING 0 (`pathlab/pathlab-client/server/gateway/routes/results.py:4557`) and before TRAINING 35 (`pathlab/pathlab-client/server/gateway/routes/results.py:5198`).

## 5.4 Public->private transition side effect
- When visibility switches public->private, non-owner running training tasks on that dataset can be stopped: `pathlab/pathlab-client/server/gateway/routes/wsi_grants.py:270`.

---

## 6) Annotation Permission Model

## 6.1 Shared annotation access
- `can_access_shared` allows only admin / dataset owner / explicit collaborator grant.
- Public dataset status does not grant shared annotation access by itself.

Code: `pathlab/pathlab-client/server/backend/auth/annotation_permissions.py:8`.
Test: `pathlab/pathlab-client/server/tests/test_permission_policy_updates.py:64`.

## 6.2 Personal annotation access
- Route-level owner/admin restriction for dataset-scoped personal operations via `_require_personal_annotation_owner`: `pathlab/pathlab-client/server/gateway/routes/annotation.py:506`, `pathlab/pathlab-client/server/gateway/routes/annotation.py:707`.
- Repository-level access guard for personal drafts via `get_with_permission` owner/admin-only behavior: `pathlab/pathlab-client/server/backend/database/repositories/annotation.py:172`.

## 6.3 Shared finalize
- Only owner/admin can finalize shared annotation into GT: `pathlab/pathlab-client/server/gateway/routes/annotation.py:1417`.
- Finalize writes `label_{dataset_id}` as `status=finalized`, then removes shared draft: `pathlab/pathlab-client/server/gateway/routes/annotation.py:1441`.

## 6.4 Collaborator management
- Add/remove collaborator requires owner/admin (`can_finalize`): `pathlab/pathlab-client/server/gateway/routes/annotation.py:1633`, `pathlab/pathlab-client/server/gateway/routes/annotation.py:1697`.
- Removing collaborator cascades child-dataset collaborator revoke behavior and emits collaboration revocation events (`access_revoked`, `force_disconnect`): `pathlab/pathlab-client/server/gateway/routes/annotation.py:1736`, `pathlab/pathlab-client/server/gateway/routes/annotation.py:1767`, `pathlab/pathlab-client/server/gateway/routes/annotation.py:1770`.

## 6.5 Annotation source semantics
- `annotation_source` is a **derived read-only field** computed at query time; it is never stored as a column.
- Value is `"imported_gt"` when the effective annotation record was imported externally (mask GT import flow), `"user_label"` when it originated from user-drawn or finalized shared annotation.
- Derivation logic lives in `GET /datasets/{dataset_id}/labels` summary endpoint: `pathlab/pathlab-client/server/gateway/routes/annotation.py:865`.
- `SegmentationAnnotation.to_dict()` also exposes `annotation_source` per-record for the WSI-viewer GT overlay: `pathlab/pathlab-client/server/backend/database/models.py`.
- Frontend `AnnotationSource` type mirrors the two values: `pathlab/pathlab-client/src/renderer/src/api/annotation.ts`.

---

## 7) Data Type / Task Type / Aggregation Constraints

## 7.1 Segmentation hard contract
- Constants define segmentation contract as `task_type=segmentation`, `data_type=patch`, `aggregation_level=file`: `pathlab/pathlab-client/server/gateway/utils.py:41`.
- Contract validator exists: `ensure_segmentation_contract`: `pathlab/pathlab-client/server/gateway/utils.py:307`.
- Dataset-level validator wrapper: `ensure_dataset_segmentation_contract`: `pathlab/pathlab-client/server/gateway/utils.py:331`.

## 7.2 Training consistency constraints
- All selected datasets for one training job must share same `(task_type, data_type, aggregation_level)`: `pathlab/pathlab-client/server/gateway/routes/training.py:360`.
- Requested `task_type`/`data_type` must match resolved dataset contracts: `pathlab/pathlab-client/server/gateway/routes/training.py:370`.

## 7.3 Dataset updates constrained by task type
- Segmentation dataset cannot switch aggregation to `case`: `pathlab/pathlab-client/server/gateway/routes/wsi.py:1014`.
- Segmentation WSIs reject image-level label updates: `pathlab/pathlab-client/server/gateway/routes/wsi.py:1330`.

---

## 8) Annotation -> New Dataset Closed Loop

## 8.1 Extraction entry
- Entry endpoint is `POST /annotation/extract`: `pathlab/pathlab-client/server/gateway/routes/annotation.py:1065`.
- Supports dataset-scope extraction from effective annotations (GT + overlay): `pathlab/pathlab-client/server/gateway/routes/annotation.py:1085`.

## 8.2 Access and mode checks during extraction
- Shared extraction requires shared-access check (`can_access_shared`): `pathlab/pathlab-client/server/gateway/routes/annotation.py:1091`.
- Every referenced WSI rechecked via `get_wsi_with_access`: `pathlab/pathlab-client/server/gateway/routes/annotation.py:1137`.

## 8.3 Inheritance into new dataset payload
- When extraction is sourced from an existing dataset, payload carries:
  - `source_dataset_id`
  - `parent_dataset_id = source_dataset_id`
  - inherited `is_public` from parent dataset

Code: `pathlab/pathlab-client/server/gateway/routes/annotation.py:1176`.

## 8.4 Finalization as closed-loop stabilization
- Shared finalize persists GT into finalized record and removes draft, stabilizing produced annotation state before downstream extraction: `pathlab/pathlab-client/server/gateway/routes/annotation.py:1417`, `pathlab/pathlab-client/server/gateway/routes/annotation.py:1441`.

## 8.5 Extraction audit: promoted_to_training_reference
- When extraction succeeds, a `promoted_to_training_reference` audit event is written to `permission_audit_logs` recording the source annotation ID and new dataset ID.
- This closes the data loop traceability: the audit log links the annotation that was promoted to a training dataset.

Code: `pathlab/pathlab-client/server/gateway/routes/annotation.py:1228`.

---

## 9) Boundary Conditions and Safety Handling

## 9.1 Revocation vs historical artifacts
- Annotation cleanup by dataset/user intentionally deletes only `draft` records; finalized records remain.
- This preserves historical outputs after permission revocation.

Code: `pathlab/pathlab-client/server/backend/database/repositories/annotation.py:151`.

## 9.2 Shared edit concurrency
- Shared upsert supports version-based conflict handling (`expected_version`) with force override only for owner/admin flows.

Code: `pathlab/pathlab-client/server/backend/database/repositories/annotation.py:336`.

## 9.3 Empty finalize guard
- Shared finalize rejects empty annotations unless `force=true`: `pathlab/pathlab-client/server/gateway/routes/annotation.py:1433`.

## 9.4 Label deletion guard with active training
- Label delete endpoint (`DELETE /datasets/{dataset_id}/labels`) blocks when active training tasks exist: `pathlab/pathlab-client/server/gateway/routes/annotation.py:1826`.
- Note: the guard is system-wide — any active training task (regardless of dataset) will block deletion.

## 9.5 Task access and analysis visibility boundary
- Task analysis endpoints require task access checks; non-admin analysis listing is further filtered to analyses submitted by current user.

Code: `pathlab/pathlab-client/server/gateway/routes/results.py:5926`, `pathlab/pathlab-client/server/gateway/routes/results.py:5994`.

---

## 10) Tests that Anchor Current Permission Behavior

### Existing anchors
- Guest cannot gain GPU via dataset grant (no valid DB grant → denied): `pathlab/pathlab-client/server/tests/test_permission_policy_updates.py:49`.
- Shared annotation requires explicit collaborator even for public dataset: `pathlab/pathlab-client/server/tests/test_permission_policy_updates.py:71`.
- Non-owner cannot read personal draft via repository permission API: `pathlab/pathlab-client/server/tests/test_permission_policy_updates.py:96`.
- Dataset/WSI access ancestor grant logic: `pathlab/pathlab-client/server/tests/test_permission_logic.py:73`, `pathlab/pathlab-client/server/tests/test_permission_logic.py:116`.
- Upload CSV route gate is authenticated-user (guest-capable) regression check: `pathlab/pathlab-client/server/tests/test_permission_closure_regressions.py:245`.

### New anchors (`test_permission_revocation_fixes.py`)
- `check_dataset_gpu_permission` reaches `has_valid_gpu` DB query for all `can_use_gpu()=False` users (Fix 3): `test_gpu_permission_reaches_has_valid_gpu_when_can_use_gpu_false`.
- Pathologist (role-level GPU) never hits DB in `check_dataset_gpu_permission`: `test_gpu_permission_pathologist_never_hits_db`.
- Non-GPU user without a valid DB grant is denied: `test_gpu_permission_denied_when_no_grant_and_can_use_gpu_false`.
- `_notify_ai_service_permission_revocation` marks task revoked in-process before HTTP call succeeds (Fix 2a): `test_notify_revocation_marks_task_revoked_in_process`.
- Local revoke fires even when HTTP call to AI service fails (Fix 2a): `test_notify_revocation_marks_task_even_when_http_fails`.
- `run_task_analysis` raises HTTP 403 when dataset access has been revoked (Fix 1a): `test_run_task_analysis_raises_403_when_dataset_access_revoked`.
- Admin bypasses dataset access check in `run_task_analysis` (Fix 1a): `test_run_task_analysis_admin_skips_dataset_access_check`.
- `revoke_task_permission` / `clear_revocation` lifecycle: `test_revoke_marks_task_and_clear_removes_it`, `test_revoke_affects_only_named_task`, `test_clear_revocation_is_idempotent`.
- `PermissionRevokedException` is an `Exception` subclass: `test_permission_revoked_exception_is_exception_subclass`.

---

## 11) Practical Summary (Current State)

- **Guest**: can upload and access permitted/public data; cannot perform GPU-required flows (training/external validation/internal analysis requiring GPU), cannot access admin settings. `check_dataset_gpu_permission` no longer has a dedicated `is_guest()` short-circuit — the DB query (`has_valid_gpu`) is the uniform gate, which still returns false for guest because no GPU grant is ever stored for guest accounts.
- **Pathologist**: can use GPU flows and non-admin product functions under dataset/task ownership/grant boundaries. Role-level `can_use_gpu()` bypasses the DB grant check, but `run_task_analysis` now enforces an additional `check_dataset_access_permission` check so that a revoked dataset grant blocks new analysis submissions even for pathologists.
- **Admin**: full access, plus global settings and grant/revoke controls. Admin bypasses the dataset access check in `run_task_analysis`.

**Revocation semantics for in-flight tasks**: on grant revocation the system (a) performs a local in-process revoke synchronously, then (b) notifies the AI service over HTTP. In-flight external-validation tasks across all three paths (patch-segmentation, patch-classification, survival) check `is_permission_revoked` at multiple checkpoints and abort before committing results to the database.

**Analysis submission after revocation**: the dataset and its tasks remain visible to the user. Only new analysis submissions are blocked; the frontend shows a user-friendly toast (`datasetAccessRevoked`) instead of a raw error.

Key architectural point: permissions are a combination of **role capability** + **resource ownership/grants** + **task visibility ownership**.
