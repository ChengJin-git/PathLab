# PathLab Testing Map

Use this when selecting focused tests for a feature location plan.

## Frontend Tests

Location: `pathlab/pathlab-client/test/`

- `test/setup.ts`: global frontend mocks, including `fetch` and `localStorage`.
- `test/helpers/apiHelpers.ts`: `ok()`, `errResp()`, `createSSEStream()` response/SSE utilities.
- `test/unit/api/`: API client tests.
- `test/unit/components/`: React component tests.

Common command:

```bash
npm run test:run
```

Run focused Vitest files when possible instead of the whole suite.

## Backend Tests

Location: `pathlab/pathlab-client/server/tests/`

- `conftest.py`: fixtures, auth mocks, app factory, dotenv setup.
- `test_*.py`: route, permission, task, storage, analysis, AI, GPU regression tests.
- `pytest.ini`: `asyncio_mode = auto`.

Common command:

```bash
python -m pytest server/tests/ -v
```

Run focused pytest modules when possible.

## Feature-To-Test Guide

| Feature area | Frontend tests | Backend tests |
|---|---|---|
| API client shape/error behavior | `test/unit/api/*.test.ts` | Matching route test if backend changes |
| Results / analysis UI | `ResultsViewerPage.sse.test.tsx`, `results.test.ts`, `analysis.test.ts` | `test_task_worker_analysis.py`, `test_external_validation_analysis.py`, results route tests |
| Training submit/logs | `training.test.ts`, task page tests | `test_training_task_dispatch.py`, `test_training_preflight.py` |
| Export/report | `export.test.ts` | `test_segmentation_analysis_export.py` |
| Batch/independent inference | `batchInference` API tests if present or add one | `test_results_task_dispatch.py` |
| Queue/cancel/status | queue API/page tests | TaskWorker and queue route tests |
| WSI/dataset/upload | `wsi` API tests, upload page/component tests | WSI/upload route tests |
| Viewer tile/DZI/thumbnail | viewer/component tests if behavior reaches UI | preprocessing route tests |
| Annotation/collaboration | annotation API/component tests | annotation route, pubsub/cache tests |
| Storage stats/cleanup/migration | `storage.test.ts` | storage route/manager tests |
| Auth/permissions/grants | auth/users/grants API tests | auth, access control, grant route tests |
| Electron IPC/sidecar | preload/main focused tests if available | startup smoke/build checks |

## Test Selection Rules

- If only a TypeScript interface/API client changes, add or update `test/unit/api/`.
- If route response shape changes, test both backend route and frontend API client.
- If a long task descriptor changes, test enqueue shape, TaskWorker dispatch, and status/cancel behavior if affected.
- If an ORM field changes, test route serialization plus repository persistence behavior.
- If Preprocessing image behavior changes, include route-level tests and manually verify viewer integration when UI framing changes.
