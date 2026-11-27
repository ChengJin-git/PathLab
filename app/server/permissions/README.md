# PathLab permissions

> PathLab v1.0.8 · Updated 2026-11-06

This document describes the implemented role, resource and workspace boundaries. Backend checks are authoritative; route visibility, disabled buttons and Chat instructions are not substitutes for API authorization.

Paths below are relative to `app/`.

## Roles and authentication

| Role | Base capability |
| --- | --- |
| `admin` | Administrative settings and resource management; workspace selection can still narrow requests |
| `pathologist` | GPU workflows and product features, subject to resource access and task ownership |
| `guest` | Uploads and authorized data access; no role-level GPU execution or admin settings |

- Roles and `can_use_gpu()` are defined in `server/backend/auth/models.py`.
- `require_admin`, `require_pathologist_or_admin` and `require_can_use_gpu` live in `server/backend/auth/dependencies.py`.
- Login uses `POST /auth/secure-login`. JWT validation checks active users and `session_nonces`; `JWT_SECRET` must be stable to preserve sessions across restarts.
- Browser EventSource, image URLs and ASR WebSockets use the supported token query path where headers cannot be supplied. These paths validate JWT/session state rather than bypassing authentication.
- Public captcha configuration exposes `captcha_provider` and `captcha_site_key`; secure login can validate Turnstile or Tencent captcha according to configuration.

### Account creation

| Endpoint | Policy |
| --- | --- |
| `POST /auth/request-access` | Creates an inactive guest access request for administrator review, with educational email validation |
| `POST /auth/users` | Admin-only direct creation, with role and activation control |

Direct self-registration through `/auth/register` is disabled. The standard `/auth/jwt/login` route is blocked; use secure login.

## Resource access

### Datasets and slides

`dataset_access.accessible_dataset_ids()` is the shared read/write policy. Administrators can access all datasets. Other users read the datasets they own and every public dataset; only the owner or an administrator can write to or manage a dataset. There are no per-user grants, collaborators or inherited access: `parent_dataset_id` records lineage only.

`check_wsi_access_permission` applies dataset access when the slide belongs to a dataset. Upload choices use `purpose=upload`: non-admins select their own datasets, admins can select all, and workspace scope narrows both. Selection, target lookup and writes each enforce authorization.

Code: `server/backend/auth/dependencies.py`, `server/backend/services/dataset_access.py`.

### Tasks, models and derived results

- Training task lists/details and model management are owner-filtered for non-admins.
- Internal analysis additionally checks current dataset access and required GPU capability before execution. Making a dataset private can block new computation while preserving visibility of the user's historical task.
- External validation checks model/task access, target dataset access, GPU capability and task/data/label compatibility.
- Research models require a validated native or task-aware prediction contract before activation. Single-slide classification preserves the selected model's class order and checks model ownership/activity.
- Image recommendations independently apply dataset/workspace access and latest visible result ownership; access to original images does not grant access to another user's derived result.
- Viewer result catalogs and analysis sources are owner-filtered: admins see all results, pathologists see their own. Preprocessing result-layer requests require a short-lived Gateway signature.
- Deleting a training task requires pathologist/admin plus task ownership, publishes cancellation before database deletion, and schedules file cleanup afterward. Cancellation publication timeout prevents database deletion.

Code: `server/gateway/routes/training.py`, `models.py`, `results.py`, `analysis_utils.py`, `image_recommendations.py`.

## Workspace scope

`server/backend/services/workspaces.py` and `server/gateway/workspace_access.py` enforce scope independently of the LLM.

- Workspaces are owned resources with dataset IDs, permitted scan roots, enabled skills/connectors, an execution mode, archive state and a version.
- Scope intersects current resource access. A workspace entry never grants access by itself; an empty dataset selection stays empty.
- Task scope requires all referenced inputs to belong to the effective dataset scope.
- `X-Workspace-ID`, `X-Workspace-Mode` and `X-Chat-Skills` carry request scope. Saved policies can be narrowed, not expanded by per-request settings.
- Read-only mode rejects mutations. Disabled skills reject their associated mutation endpoints.
- Chat conversations bind to one workspace; conflicting conversation/header/body scope is rejected. Selecting another workspace starts a new conversation.
- Context cache identities include refreshed access IDs, user/role, scope version and mutation revision. Cached candidates cannot stand in for an execution-time permission check.

API: `server/gateway/routes/workspaces.py`. Frontend: `src/renderer/src/components/chat/WorkspaceControls.tsx`, `src/renderer/src/lib/workspaceSelection.ts`, `src/renderer/src/api/client.ts`.

## Dataset properties and visibility

### Property updates

`PATCH /wsi/datasets/{dataset_id}/properties` updates name, task types, aggregation level, source, metadata and visibility with a revision check. It requires management access, validates the final task/data combination, and commits property/slide changes together. `DatasetTask` supports multiple tasks; labeled tasks cannot be removed by an ordinary property edit.

Data Repo and upload-source changes both use this endpoint. Source/type changes cannot change a dataset into an incompatible modality. Segmentation requires `patch_segmentation`, `data_type=patch`, `aggregation_level=file`.

Code: `server/gateway/models.py:DatasetPropertiesRequest`, `server/gateway/routes/wsi.py:update_dataset_properties`.

### Public-to-private changes

- Making a public dataset private finds non-owner active training tasks that use it through SQL membership, persists their cancelled state and publishes the shared Worker cancellation signal before notifying the AI service.
- Viewer SSE rechecks account, token, slide, team and workspace access every two seconds.
- Completed/failed/cancelled task rows are not rewritten as active cancellations. Historical finalized annotations are preserved.
- Runtime external-validation paths check permission revocation at their execution checkpoints. A failed advisory AI HTTP call does not erase the durable cancellation state.

Code: `server/gateway/routes/dataset_visibility.py`, `server/backend/ai/permission_revocation.py`, `server/backend/common/task_dispatch.py`.

## Annotation

| Operation | Policy |
| --- | --- |
| Team objects | Dataset owner or administrator |
| Personal objects | Any user with current slide read access; objects remain user-scoped |
| Object updates and undo | Expected object revision and idempotent operation ID; stale writes return 409 |
| Publish reference labels | Dataset manager/admin, matching selected-object revisions and patch images |
| ROI extraction | Current dataset access and selected-layer access; source slides are rechecked |

Extraction records source lineage; the extracted dataset is owned by the user who created it. Reference publication preserves existing labels, updates selected objects by `viewer_region_id`, and writes a `promoted_to_training_reference` audit record. Extracted datasets contain patches; segmentation uses paired images/masks.

`annotation_source` is derived from published records: `imported_gt` for imported/uploaded labels and `user_label` for viewer-published labels. Interactive objects live in `viewer_regions`; published COCO labels live in `segmentation_annotations`, separated by task type.

Code: `server/gateway/routes/viewer.py`, `annotation.py`, `server/backend/services/viewer_annotations.py`, `viewer_reference.py`. See [viewer contracts](../backend/services/VIEWER.md).

## Training and validation contracts

- Canonical task IDs are `wsi_classification`, `patch_classification`, `wsi_survival`, `patch_detection`, `patch_segmentation`; validation is centralized in `server/backend/ai/task_taxonomy.py`.
- One training job uses homogeneous task/data/aggregation metadata and rechecks input access.
- External validation excludes the training source dataset and validates model/target compatibility. Missing cached WSI features alone is not a permission or compatibility failure.
- Admin reruns may preserve the original task owner; non-admin submissions remain owned by the requester and go through normal checks.

## Chat and AutoResearch

### Chat

Chat is available to authenticated users, including guests. Guests can discuss, read and use their own enabled skills, but Chat cannot submit GPU or autonomous tasks for them. The LLM receives the current capability policy and returns a friendly permission explanation; server-side stream filtering and dispatch checks independently prevent execution. AutoResearch APIs still require administrator/pathologist access. Public capability definitions are discoverable, private definitions remain owner/admin-only, and connector credentials belong to each individual user. Configuration selection is not submission, and opening a historical card does not execute it.

Resource menus use authorized facts and completeness information. A single-resource workspace must not offer fictitious alternative resources. Free-text requests and scope-changing suggestions cannot automatically widen scope, enable connectors or bypass read-only mode.

Conversation deletion checks owner/admin access before committing its internal cleanup record. The conversation disappears immediately; associated files become unreadable before asynchronous cleanup. Source datasets and independently owned reference files remain accessible under their own policies. Cleanup records are excluded from the progress panel, while other deletion tasks keep their usual progress and cancellation controls.

### AutoResearch

- Every public session endpoint requires administrator/pathologist access. Pathologists can list/read/manage only their own conversations; administrators can access all sessions. Dataset sharing does not share research conversations.
- Creating or resuming execution explicitly requires `user.can_use_gpu()`; guests cannot start/resume execution merely because they can open the frontend route.
- Dataset mounts use the shared current-access policy and workspace intersection. Preparation, resume and queued jobs recheck access; a previously mounted input does not stay readable after its dataset is made private.
- Workspace-bound creation checks datasets, permitted paths, read-only policy and the training skill. Empty scope cannot silently expand to the full inventory.
- Event/download routes use AutoResearch-purpose access tokens or the route's supported authenticated header mechanism, with session ownership checks.
- Open SSE connections revalidate token expiry, current account role and session ownership before each batch. Frontend research state is remounted per account/role; sidebar reloads replace authorized results, and notification tasks reject stale account events.
- Continuation baselines must be completed experiments in the same authorized session; arbitrary run IDs cannot import another user's results.
- First acquisition defaults public sources to public Data Repo visibility; an explicit private request takes precedence. Re-import keeps current visibility unless explicitly overridden and never adopts an unrelated same-name dataset.
- Skill previews/packages are user-owned; imports validate paths, resources and bounded sizes. Session snapshots remain read-only to background jobs. Credentials stay outside downloadable artifacts.
- Reports require admin/pathologist and source/workspace access. Pathologists manage their own articles; queued/running generation prevents deletion. Report deletion preserves source experiments.

Code: `server/gateway/routes/autoresearch.py`, `server/backend/auth/dependencies.py`. Operational guide: [AutoResearch](../backend/autoresearch/README.md).

## Regression anchors

- `server/tests/test_permission_logic.py`, `test_permission_closure_regressions.py`: ownership, public visibility and execution access.
- `server/tests/test_workspace_api.py`, `test_workspace_context.py`, `test_chat_semantic_routing.py`: scope narrowing, empty/single-resource scopes, cache identity and semantic recovery.
- `server/tests/test_mutation_responsiveness.py`: property validation/ownership, public-to-private effects, cancellation ordering and failure handling.
- `server/tests/test_image_recommendations.py`: bounded, authorized prediction candidates.
- `server/tests/test_viewer_workspace.py`, `test_viewer_postgres.py`, `test_dataset_catalog_and_result_privacy.py`: object ownership, team layers, reference publication and result privacy.
- `server/tests/test_chat_deletion.py`, `test_research_processes.py`: durable logical deletion, process shutdown, retries and independent-file preservation.
- `server/tests/test_training_task_dispatch.py`, `test_task_response_regressions.py`: deletion, task state and runtime boundaries.
- `test/unit/api/workspaceScope.test.ts`, `test/unit/contexts/backgroundTask/sessionIsolation.test.ts`: request scope and late events after account changes.

Gateway router registration is maintained in `server/gateway/app_setup.py`; auxiliary route files are not independent authorization boundaries. See [Gateway](../gateway/README.md) and [Workspace-aware Chat](../gateway/chat/README.md) for API/runtime details.
