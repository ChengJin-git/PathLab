# PathLab application

`app/` contains the PathLab web application: the React client (`src/renderer/`), the Python
services (`server/`), tests and deployment scripts. The backend runs five processes — Gateway,
Preprocessing, AI, TaskWorker and ResearchWorker — on a Linux GPU server; users work in the browser.

Installation: [docs/installation.md](../docs/installation.md). Architecture and the mapping to the
manuscript: [docs/architecture.md](../docs/architecture.md).

## Development commands

Run from `app/`:

```bash
npm ci                 # the only package-lock.json is in this directory
npm run typecheck
npm run test:run
npm run build          # web client into src/renderer/dist
npm run dev            # Vite dev server

pip install -r server/requirements.txt -r server/requirements-test.txt
cd server && python -m pytest tests/ -q --ignore=tests/test_ai_extractors_pretrained.py
```

Host Python dependencies are pinned in `server/requirements.txt`. The research sandbox has its own,
independent Python and ML stack defined in `server/backend/autoresearch/runtime/containers/`
(`pathlab-sandbox.def`, `skills-runtime-requirements.txt`). `server/requirements-sandbox-survival.txt`
provides scikit-survival for research sessions that need it, without changing the scikit-learn
version the sandbox uses to load saved models. PDF reading uses PyMuPDF layout analysis on the CPU,
and scanned pages are OCR'd once with PP-OCRv6-small (ONNX); prepare the models with
`python deploy/prepare-ocr.py`.

## Entry points

- `src/renderer/vite.config.ts` — web build.
- `src/renderer/src/main.tsx` — client entry.
- `server/main.py` — starts all backend processes.
- `deploy/start.sh`, `deploy/hot-reload.sh` — start and partial restart with fixed ports.
- `package.json` — npm scripts `dev`, `build`, `preview`, `typecheck`, `test`, `test:run`,
  `test:coverage`, and the pinned OpenCode version (`opencodeVersion`).

## Layout

```text
app/
├── deploy/                 # start scripts, nginx and systemd templates, sandbox build
├── server/                 # Python backend
│   ├── backend/            # shared modules and internal services
│   │   └── autoresearch/   # research runtime, orchestration, persistence
│   ├── gateway/            # public API, chat workspace, prompts
│   ├── task_worker/        # Redis descriptor queue and GPU job execution
│   ├── tests/              # backend tests (pytest)
│   ├── pytest.ini
│   └── requirements*.txt
├── src/renderer/           # React + Vite client
├── test/                   # client tests (Vitest) and browser tests (Playwright)
├── scripts/                # landing-asset builder, sandbox image check
├── vitest.config.ts
└── package.json
```

## How it runs

- `deploy/start.sh` (or the systemd unit) starts the services on fixed ports 6100, 6101 and 6102 and
  builds the client; nginx serves the client and proxies `/api`, `/preprocessing` and `/ai`
  ([deploy/README.md](deploy/README.md)).
- PostgreSQL, Redis and the storage directory hold the runtime state. The storage root is
  `PATHLAB_UPLOADS_DIR`, else the location saved in Settings, else `uploads/` in the
  application-data directory.

### Client

- React 18.3, TypeScript 5.9, Vite 8, Tailwind CSS 4; Node.js `^22.22.2 || ^24.15.0 || >=26.0.0`.
- API clients per domain in `src/renderer/src/api/`.
- `/datasets` and `/upload` share the dataset property, task and label contracts.
- `components/wsiViewer/` manages object annotation, the result inspector and the slide assistant.
- Chat uses persistent workspaces, on-demand capability protocols and streaming; selection,
  confirmation and execution are separate steps.
- Research sessions: `/autoresearch/new` and `/autoresearch/sessions/:id`, client in
  `src/renderer/src/api/autoresearch.ts`.
- `/reports` lists, generates, edits, polishes and exports articles; new research sessions can
  import skill folders, ZIP/`.skill` files or GitHub repositories.

### Backend

- Gateway: authentication, public API, task descriptors and status, static files.
- Preprocessing: slide metadata, images, thumbnails, DeepZoom tiles, heatmap helpers.
- AI: training, inference and model internals.
- TaskWorker: consumes Redis descriptors, schedules GPU memory leases and runs long jobs.
- ResearchWorker: supervises OpenCode research sessions in the Apptainer sandbox and article writing;
  research jobs run on the TaskWorker and reuse the platform's dataset, literature and article
  services.

Routers are registered in `server/gateway/app_setup.py`. The database schema is created and checked
by `server/backend/database/current_schema.py` ([database README](server/backend/database/README.md)).

## Tests

- Client: Vitest and Testing Library cover API clients, utilities, contexts, pages and components;
  `test/browser/` runs Playwright interaction tests ([test/README.md](test/README.md)).
- Backend: pytest, pytest-asyncio and httpx cover configuration, routes, access control, data and
  labels, object concurrency, features, results, deletion ordering, storage, the GPU queue and
  research control; research data adapters are tested in `server/backend/autoresearch/tests/`.
  `test_ai_extractors_pretrained.py` needs a GPU and a Hugging Face token and runs separately
  ([server/README.md](server/README.md)).

## Further reading

Datasets ([DATASETS.md](server/backend/services/DATASETS.md)) · viewer
([VIEWER.md](server/backend/services/VIEWER.md)) · features
([FEATURE-ARTIFACTS.md](server/backend/services/FEATURE-ARTIFACTS.md)) · backend
([server/README.md](server/README.md)) · research runtime
([autoresearch/README.md](server/backend/autoresearch/README.md)) · permissions
([permissions/README.md](server/permissions/README.md)) · Gateway
([gateway/README.md](server/gateway/README.md)) · client ([src/renderer/README.md](src/renderer/README.md)) ·
deployment ([deploy/README.md](deploy/README.md))
