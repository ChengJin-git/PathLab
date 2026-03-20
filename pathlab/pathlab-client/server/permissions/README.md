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

## 4.4 Internal validation (implemented as task analysis flow)
- Internal validation trigger is `POST /results/tasks/{task_id}/analysis`: `pathlab/pathlab-client/server/gateway/routes/results.py:6006`.
- Enforced checks:
  - `_get_task_with_access` (owner/admin visibility): `pathlab/pathlab-client/server/gateway/routes/results.py:6029`, `pathlab/pathlab-client/server/gateway/routes/analysis_helpers.py:80`
  - `_require_task_gpu_permission` for analysis execution path: `pathlab/pathlab-client/server/gateway/routes/results.py:6036`, `pathlab/pathlab-client/server/gateway/routes/analysis_helpers.py:102`
- Analysis visibility:
  - `GET /results/tasks/{task_id}/analysis` filters non-admin to analyses submitted by that user: `pathlab/pathlab-client/server/gateway/routes/results.py:5926`, `pathlab/pathlab-client/server/gateway/routes/results.py:5994`.

## 4.5 External validation
- Entry: `POST /results/external-validation`: `pathlab/pathlab-client/server/gateway/routes/results.py:3034`.
- Enforced checks:
  - model ownership/task access (`_require_task_access`): `pathlab/pathlab-client/server/gateway/routes/results.py:3079`
  - target dataset access (`_has_external_validation_dataset_access`): `pathlab/pathlab-client/server/gateway/routes/results.py:3099`, `pathlab/pathlab-client/server/gateway/routes/results.py:142`
  - dataset GPU permission: `pathlab/pathlab-client/server/gateway/routes/results.py:3108`
  - model/dataset compatibility (`data_type/task_type/aggregation_level/labels/features`): `pathlab/pathlab-client/server/gateway/routes/results.py:3115`
- Auto-triggers post-inference analysis, but task visibility still follows owner/admin model: `pathlab/pathlab-client/server/gateway/routes/results.py:5721`, `pathlab/pathlab-client/server/gateway/routes/results.py:5781`.

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

## 5.3 Revoke model and side effects
- Single revoke endpoint: `DELETE /datasets/{dataset_id}/grants/{target_user_id}`: `pathlab/pathlab-client/server/gateway/routes/wsi_grants.py:546`.
- Batch revoke endpoint: `POST /datasets/{dataset_id}/grants/batch-revoke`: `pathlab/pathlab-client/server/gateway/routes/wsi_grants.py:582`.
- Revoke side effects include:
  - find affected running tasks using dataset WSIs: `pathlab/pathlab-client/server/gateway/routes/wsi_grants.py:112`
  - notify AI service to revoke permission on running tasks: `pathlab/pathlab-client/server/gateway/routes/wsi_grants.py:136`
  - cascade revoke on child datasets: `pathlab/pathlab-client/server/gateway/routes/wsi_grants.py:188`
  - audit log entries: `pathlab/pathlab-client/server/gateway/routes/wsi_grants.py:575`.

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
- Finalize writes `annot_{dataset_id}` as `status=finalized`, then removes shared draft: `pathlab/pathlab-client/server/gateway/routes/annotation.py:1441`.

## 6.4 Collaborator management
- Add/remove collaborator requires owner/admin (`can_finalize`): `pathlab/pathlab-client/server/gateway/routes/annotation.py:1633`, `pathlab/pathlab-client/server/gateway/routes/annotation.py:1697`.
- Removing collaborator cascades child-dataset collaborator revoke behavior and emits collaboration revocation events (`access_revoked`, `force_disconnect`): `pathlab/pathlab-client/server/gateway/routes/annotation.py:1736`, `pathlab/pathlab-client/server/gateway/routes/annotation.py:1767`, `pathlab/pathlab-client/server/gateway/routes/annotation.py:1770`.

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

## 9.4 GT deletion guard with active training
- Ground-truth delete endpoint blocks when active training tasks exist: `pathlab/pathlab-client/server/gateway/routes/annotation.py:1796`.
- Note: the guard is system-wide — any active training task (regardless of dataset) will block deletion.

## 9.5 Task access and analysis visibility boundary
- Task analysis endpoints require task access checks; non-admin analysis listing is further filtered to analyses submitted by current user.

Code: `pathlab/pathlab-client/server/gateway/routes/results.py:5926`, `pathlab/pathlab-client/server/gateway/routes/results.py:5994`.

---

## 10) Tests that Anchor Current Permission Behavior

- Guest cannot gain GPU via dataset grant: `pathlab/pathlab-client/server/tests/test_permission_policy_updates.py:49`.
- Shared annotation requires explicit collaborator even for public dataset: `pathlab/pathlab-client/server/tests/test_permission_policy_updates.py:71`.
- Non-owner cannot read personal draft via repository permission API: `pathlab/pathlab-client/server/tests/test_permission_policy_updates.py:96`.
- Dataset/WSI access ancestor grant logic: `pathlab/pathlab-client/server/tests/test_permission_logic.py:73`, `pathlab/pathlab-client/server/tests/test_permission_logic.py:116`.
- Upload CSV route gate is authenticated-user (guest-capable) regression check: `pathlab/pathlab-client/server/tests/test_permission_closure_regressions.py:245`.

---

## 11) Practical Summary (Current State)

- **Guest**: can upload and access permitted/public data; cannot perform GPU-required flows (training/external validation/internal analysis requiring GPU), cannot access admin settings.
- **Pathologist**: can use GPU flows and non-admin product functions under dataset/task ownership/grant boundaries.
- **Admin**: full access, plus global settings and grant/revoke controls.

Key architectural point: permissions are a combination of **role capability** + **resource ownership/grants** + **task visibility ownership**.
