# PathLab Architecture Reference

Source: condensed from repository `CODEBASE_MAP.md`.

## Project Shape

PathLab is a desktop / Web application for digital pathology research.
The main application lives under `pathlab/pathlab-client/` and supports Electron desktop runtime,
browser debugging, and fixed-port Web deployment.

## Stack

- Desktop host: Electron, electron-vite, embedded PostgreSQL, embedded Redis / Garnet.
- Frontend: React 18, TypeScript, Vite 7, Tailwind CSS 4, React Query, Vitest.
- Backend: Python FastAPI, uvicorn, SQLAlchemy async, PostgreSQL, Redis, pytest.
- AI / image: PyTorch, WSI image readers, feature extractors, MIL aggregators,
  classification / survival / segmentation training and inference.

## Main Entrypoints

| Runtime | Entrypoint | Role |
|---|---|---|
| Electron main | `pathlab/pathlab-client/src/main/index.ts` | Window lifecycle, deep-link auth, IPC, embedded services, Python sidecar startup. |
| Electron preload | `pathlab/pathlab-client/src/preload/index.ts` | Port discovery, auth callbacks, file/directory picker APIs. |
| Renderer | `pathlab/pathlab-client/src/renderer/src/main.tsx`, `App.tsx` | Router, providers, PWA, page routes. |
| Python sidecar | `pathlab/pathlab-client/server/main.py` | Starts Gateway, Preprocessing, AI, and TaskWorker. |
| Gateway | `pathlab/pathlab-client/server/gateway/main.py` | Public API, auth, aggregation, static mounting, task descriptor enqueueing. |
| Preprocessing | `pathlab/pathlab-client/server/backend/preprocessing/main.py` | WSI info, thumbnail, DZI, tile, ROI / COCO helpers. |
| AI service | `pathlab/pathlab-client/server/backend/ai/main.py` | Training, inference, model, and feature extractor internal APIs. |
| TaskWorker | `pathlab/pathlab-client/server/task_worker/main.py` | Redis descriptor queue consumer for long jobs and GPU execution. |
| Fixed-port deploy | `pathlab/pathlab-client/deploy/start.sh` | Builds frontend and starts fixed `6100 / 6101 / 6102` backend ports. |

## Service Boundary Rules

- Electron main starts embedded PostgreSQL / Redis and the Python sidecar.
- The Python sidecar starts three HTTP services plus one no-port worker.
- Gateway exposes public APIs and enqueues long tasks as Redis descriptors.
- TaskWorker claims descriptors, runs long work, reports heartbeat/status, handles cancellation, retries, and DLQ.
- Preprocessing provides low-level image services.
- AI provides training / inference internals.
- React renderer consumes Gateway / Preprocessing / AI through modular API clients.

## Important Current Facts

- Old docs that mention a monolithic backend are stale; use the Gateway / Preprocessing / AI / TaskWorker split.
- Old annotation table name `annotation_drafts` is stale. Current ORM model is `SegmentationAnnotation`,
  table `segmentation_annotations`.
- Fixed-port deployment and `PATHLAB_DEBUG=1` share ports `6100 / 6101 / 6102`.
- Current module map was generated from README, source, and directory scanning; MCP graph coverage may be shallow,
  so verify symbols with MCP first, then `rg` if graph data is incomplete.

## Hotspots

- `server/gateway/routes/results.py`: results, analysis, external validation, batch / independent inference.
- `server/gateway/routes/training.py`: training task creation, logs, models, GPU stages.
- `server/backend/common/config.py`: ports, database, Redis, uploads, global settings.
- `src/renderer/src/config.ts`: frontend service address and port discovery.
- `server/gateway/routes/chat.py`: AI chat, training recommendations, PDF / patch inference.
