# PathLab - Technical Documentation

> Version: v1.0.5 | Last Updated: 2026-05-01

PathLab is an integrated desktop/web platform for digital pathology research. It provides whole slide image (WSI) management, AI model training and inference, collaborative annotation, analysis and reporting, and an AI chat assistant with PDF-based RAG -- all packaged as a single Electron desktop application or deployable as a web service.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Repository Structure](#2-repository-structure)
3. [Architecture Overview](#3-architecture-overview)
4. [Frontend](#4-frontend)
5. [Backend](#5-backend)
6. [Electron Desktop](#6-electron-desktop)
7. [Build & Deployment](#7-build--deployment)
8. [Testing](#8-testing)
9. [Core Workflows](#9-core-workflows)
10. [Key Dependencies](#10-key-dependencies)

---

## 1. Project Overview

### What PathLab Does

| Capability | Description |
|------------|-------------|
| **WSI Management** | Upload, browse, tile-based viewing with DZI support for whole slide images |
| **AI Training & Inference** | Train custom models (classification, survival, segmentation), run inference, generate heatmaps |
| **Collaborative Annotation** | Multi-user real-time annotation with WebSocket presence, COCO export |
| **Analysis & Reporting** | Classification, segmentation, survival analysis; PDF/Excel/CSV report generation |
| **AI Chat Assistant** | LLM-powered conversational interface with PDF semantic search (RAG), training recommendations |
| **Storage Management** | Disk usage tracking, file migration, orphaned file/record cleanup |
| **User Management** | Authentication, role-based access control (admin / pathologist / guest), dataset-level permissions |

### Runtime Modes

| Mode | Entry Point | Port Strategy |
|------|-------------|---------------|
| Electron Desktop | `server/main.py` launched by main process | Auto-discover free ports, announce via IPC |
| Browser Debug | `PATHLAB_DEBUG=1` + sidecar + frontend dev server | Fixed 6100 / 6101 / 6102 |
| Web Deployment | `deploy/start.sh` / `deploy/hot-reload.sh` | Fixed 6100 / 6101 / 6102 |

---

## 2. Repository Structure

```
PathLab/
├── README.md                           # Project root README
├── docs/                               # Documentation (this file)
├── pathlab/
│   └── pathlab-client/
│       ├── src/
│       │   ├── main/                   # Electron main process
│       │   │   ├── index.ts            # Window mgmt, IPC, deep linking
│       │   │   ├── sidecar-manager.ts  # Python sidecar lifecycle
│       │   │   └── services-manager.ts # Embedded PostgreSQL + Redis
│       │   ├── preload/                # Electron preload (IPC bridge)
│       │   │   └── index.ts            # Exposes api.auth, api.backend, api.files
│       │   └── renderer/               # React + Vite frontend
│       │       ├── public/             # Static assets, OpenSeadragon
│       │       └── src/                # Frontend source (see Section 4)
│       ├── server/                     # Python backend (see Section 5)
│       │   ├── main.py                 # Unified entry, launches 3 services
│       │   ├── gateway/                # API gateway service
│       │   ├── backend/                # Shared backend modules
│       │   ├── tests/                  # pytest test suite
│       │   ├── requirements.txt        # Python dependencies
│       │   └── main.spec               # PyInstaller config
│       ├── test/                       # Frontend unit tests (Vitest)
│       ├── deploy/                     # Nginx, systemd, start/hot-reload scripts
│       ├── scripts/                    # Build helpers (build-python.sh, prepare-redis.sh)
│       ├── resources/                  # Bundled Redis binary
│       ├── package.json                # npm config, Electron build
│       ├── electron.vite.config.ts     # Vite config for Electron
│       ├── tsconfig.json               # TypeScript config
│       └── vitest.config.ts            # Vitest config
```

---

## 3. Architecture Overview

### Three-Service Architecture

PathLab's backend runs as three independent FastAPI/Uvicorn processes:

```
┌─────────────────────────────────────────────────────────────┐
│  Electron Main Process / Docker Container / systemd         │
└────┬────────────────────────────────────────────────────────┘
     │ spawns main.py
     ▼
┌─────────────────────────────────────────────────────────────┐
│  main.py  (Signal handler, GPU health check, port discovery)│
└──┬──────────────────────┬──────────────────────┬────────────┘
   │                      │                      │
   ▼                      ▼                      ▼
┌──────────────┐   ┌───────────────┐   ┌────────────────┐
│  Gateway     │   │ Preprocessing │   │  AI Service    │
│  port 6100   │   │  port 6101    │   │  port 6102     │
│              │   │               │   │                │
│  Auth/Routes │   │  WSI tiling   │   │  Training      │
│  Task Queue  │   │  Thumbnails   │   │  Inference     │
│  Chat/RAG    │   │  Heatmaps     │   │  Feature ext.  │
│  Storage     │   │  DZI serving  │   │  Model mgmt    │
└──────┬───────┘   └───────┬───────┘   └────────┬───────┘
       │                   │                     │
       │    HTTP (inter-service communication)   │
       ├───────────────────┴─────────────────────┤
       │                                         │
       ▼                                         ▼
┌────────────────────┐              ┌──────────────────┐
│  PostgreSQL        │              │  Redis           │
│  (users, datasets, │              │  (task queue,    │
│   tasks, results)  │              │   progress,      │
└────────────────────┘              │   caching)       │
                                    └──────────────────┘
```

### Frontend-Backend Communication

```
React Frontend
  ├─ API_BASE (Gateway :6100)       → Auth, WSI CRUD, Chat, Storage, Results
  ├─ PREPROCESSING_BASE (:6101)     → Tile serving, thumbnails, heatmaps
  └─ AI_BASE (:6102)                → (rarely direct; mostly via Gateway proxy)
```

Port discovery in Electron mode uses IPC: the sidecar prints `PORT=<n>` to stdout, which the main process parses and forwards to the renderer via `onServicePorts` callback.

---

## 4. Frontend

**Location:** `pathlab/pathlab-client/src/renderer/src/`

### 4.1 Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | React 18 + TypeScript |
| Build | Vite (via electron-vite) |
| Styling | Tailwind CSS + custom theme variables |
| UI Primitives | Radix UI (Select, Tooltip, etc.) + custom components |
| Routing | React Router v6 (HashRouter for Electron, BrowserRouter for web) |
| Server State | TanStack React Query |
| Global State | React Context API (Auth, BackgroundTask, Toast) |
| Rich Text | TipTap editor, React Markdown |
| Charts | ECharts (echarts-for-react) |
| i18n | i18next (en-US, zh-CN, zh-HK) |
| Export | jsPDF, docx, ExcelJS |

### 4.2 Pages

14 pages in `pages/`:

| Page | Lines | Description |
|------|-------|-------------|
| `AIChatPage.tsx` | ~4,650 | Main dashboard -- AI assistant chat with SSE streaming, voice input, embedded action cards, file attachments |
| `ListPage.tsx` | ~3,130 | WSI dataset browser with grouping, bulk operations, split assignment, external validation |
| `WSIViewerPage.tsx` | ~2,580 | Full-screen OpenSeadragon viewer with annotation tools, heatmap overlay, segmentation masks |
| `ResultsViewerPage.tsx` | ~1,800 | Analysis results visualization and exploration |
| `UploadPage.tsx` | ~1,710 | WSI file registration, metadata import (CSV/manual) |
| `TaskDetailPage.tsx` | ~1,070 | Training task progress, logs, configuration |
| `TaskListPage.tsx` | ~1,200 | Training task history and management |
| `NewTaskPage.tsx` | ~990 | 6-step training task wizard (setup, data, preprocessing, model, review, result) |
| `StorageManagementPage.tsx` | ~460 | Storage health, migration monitoring |
| `ReportGeneratorPage.tsx` | ~470 | Report generation (CSV/JSON/Markdown; PDF pending) |
| `LoginPage.tsx` | ~465 | Authentication with optional Cloudflare Turnstile |
| `SettingsPage.tsx` | ~270 | Admin panel with 6 tabs (General, Tasks, Models, Storage, Users, Feedback) |
| `ToolsPage.tsx` | ~117 | Quick access to tools (Custom Analysis, Results Viewer, Report Generator) |
| `IntroductionPage.tsx` | ~47 | Public landing page, redirects if logged in |

### 4.3 Components

Components are organized by feature domain under `components/`:

```
components/
├── ui/           (11)  Reusable primitives: Button, Input, Card, Select, Modal, Tooltip, Badge, etc.
├── chat/         (28)  AssistantMessage renderer, action cards (TaskConfig, Chart, ImageRec, etc.)
├── training/     (13)  Wizard step components, WSIDataTable, split config, metadata modals
├── wsiViewer/    (16)  Annotation toolbar, layer panel, zoom controls, magnification display
├── settings/     (22)  6 tabs: General, Tasks, Models, Storage, Users, Feedback + sub-modals
├── landing/      (14)  Public marketing sections (Hero, Workflow, Pricing, etc.)
├── list/          (8)  WSI data grid, filters, column selector, bulk selection
├── upload/        (8)  File upload, metadata import, CSV handling
├── results/       (5)  Results table, metrics, export
├── taskDetail/    (7)  Task progress, logs, config display
├── charts/        (3)  ROC curve, confusion matrix, metric charts
├── common/        (5)  Language switcher, shared utilities
├── legal/         (3)  Privacy policy, terms, disclaimers
└── Root-level:         Layout, ProtectedRoute, BackgroundTaskPanel, various modals
```

### 4.4 API Layer

21 modules in `api/`:

**Foundation** (`client.ts`):
- `ApiError` class with status, code, details, and helper methods (`isNotFound()`, `isAuthError()`, etc.)
- `apiFetch<T>(url, options, errorContext)` -- main fetch wrapper with JWT auth injection, error parsing
- `apiFetchBlob()` -- binary response handling
- `downloadApiFile()` / `downloadBlobFile()` -- file download helpers
- `SESSION_EXPIRED_EVENT` -- custom event fired on 401 with valid token

**Functional Modules:**

| Module | Purpose |
|--------|---------|
| `auth.ts` | Login, logout, register, avatar management |
| `wsi.ts` | WSI CRUD, metadata, batch delete, external file listing |
| `training.ts` | Create task, list tasks, trained model management |
| `chat.ts` | Conversations, messages, SSE streaming, feedback, model list |
| `annotation.ts` | Save/list/delete annotations, label update, COCO export |
| `analysis.ts` | Run analysis, list/detail/delete results |
| `batchInference.ts` | Batch inference task management |
| `storage.ts` | Disk space, external datasets, scan/register, orphan cleanup, migration |
| `users.ts` | User CRUD, permissions, agreement acceptance |
| `heatmap.ts` | Heatmap generation, listing, deletion |
| `results.ts` | All results listing with WSI metadata |
| `export.ts` | Async export tasks (admin feedback) |
| `feedback.ts` | User feedback submission and listing |
| `stats.ts` | Recent activity statistics |
| `queue.ts` | Task queue status |
| `grants.ts` | Dataset elevation grants |
| `settings.ts` | Public settings, maintenance notice |
| `trainingOptions.ts` | Training config bootstrap data |

**Caching Strategy:**
- `createCache<T>(ttl)` -- single-value cache with request deduplication
- `createKeyedCache<T>(ttl)` -- per-resource cache
- Manual invalidation after mutations via `invalidateXxxCache()` functions

### 4.5 State Management

No Zustand. All state managed via:

| Mechanism | Scope |
|-----------|-------|
| `AuthContext` | Current user, roles, JWT token, session management, maintenance notice |
| `BackgroundTaskContext` | Upload/delete/training/analysis tasks, SSE subscriptions, progress tracking |
| `ToastContext` | Notification queue (success/error/info/warning) |
| React Query | Server state caching and synchronization |
| `useDraftState` | localStorage-backed form draft persistence |
| `useState` | Component-local state |

**AuthContext details:**
- JWT-based login with optional Turnstile CAPTCHA
- Role checks: `isAdmin`, `isPathologist`, `canUseGpu`, `canUseGpuForDataset(id)`
- Listens for `SESSION_EXPIRED_EVENT` to auto-logout
- Dataset-level GPU elevation grants

**BackgroundTaskContext details:**
- Manages local tasks (uploads, deletes) and server-side SSE tasks (training, analysis, storage)
- Task types: upload, delete, training, batch_inference, analysis, external_validation, extraction, migration, metadata_upload, storage_maintenance
- SSE subscriptions with reference counting (enable/disable on demand)
- Dismissed tasks persisted to localStorage

### 4.6 Hooks and Utilities

**Custom Hooks** (in `lib/hooks/` and `lib/`):

| Hook | Purpose |
|------|---------|
| `useTaskWizard` | Multi-step form navigation and task metadata |
| `useDataSelection` | Dataset/WSI selection with pagination and caching |
| `useTrainingConfig` | Model configuration state and validation |
| `useSplitValidation` | K-fold/random split validation checks |
| `useDraftState` | localStorage-backed draft form persistence |
| `usePresence` | WebSocket-based real-time user presence |
| `useVoiceSession` | ASR voice-to-text via Web Audio API |
| `useRealtimeASR` | Advanced real-time ASR with streaming |
| `useAsyncAction` | Async operation with loading/error state |
| `useConfirmDialog` | Confirmation modal state |
| `useDebounce` | Input debouncing |

**Utilities** (in `lib/utils/`):

| Utility | Purpose |
|---------|---------|
| `cache.ts` | Single-value and keyed cache with TTL and request deduplication |
| `chatMessageParser.ts` | Detect PDF context, sanitize internal blocks |
| `chatBlockRegistry.ts` | Maps block types to React card components |
| `csvImporter.ts` | XLSX-to-CSV conversion for attachments |
| `trainingSubmissionTracker.ts` | Track pending training submissions in localStorage |
| `utils.ts` | `formatFileSize`, `formatDate`, `truncateString`, `classnames` |

### 4.7 Internationalization

- **Framework:** i18next with react-i18next
- **Languages:** en-US (default), zh-CN, zh-HK
- **Detection:** Browser language auto-detect with localStorage persistence
- **Structure:** 40+ translation namespaces (common, auth, aiChat, newTask, training, settings, etc.)

### 4.8 Styling

- **Framework:** Tailwind CSS with `@import "tailwindcss"`
- **Typography:** Inter + CJK fallbacks (Noto Sans SC, PingFang SC)
- **Theme Variables:**
  - Primary palette: Indigo/blue gradient (#667eea -> #2a3177)
  - Secondary palette: Purple gradient (#764ba2 -> #471f62)
  - Surface tokens: `--surface-base`, `--surface-work`, `--surface-elevated`
  - Shadow tokens: `--shadow-soft`, `--shadow-elevated`
- **Custom Utilities:** `custom-scrollbar`, `scrollbar-hide`, safe-area insets
- **Prose Overrides:** Table styling, KaTeX math display, highlight.js code blocks

---

## 5. Backend

**Location:** `pathlab/pathlab-client/server/`

### 5.1 Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | FastAPI + Uvicorn |
| ORM | SQLAlchemy 2.0 (async, asyncpg driver) |
| Database | PostgreSQL |
| Cache/Queue | Redis |
| Auth | FastAPI-Users + JWT + bcrypt |
| Image Processing | Pillow, OpenCV, OpenSlide, Aslide, tifffile, zarr |
| ML/AI | PyTorch 2.9+, torchvision, transformers, timm, CONCH, OpenCLIP |
| Analysis | scikit-learn, scipy, lifelines (survival) |
| LLM | OpenAI SDK (via OpenRouter) |
| PDF/RAG | marker-pdf, LanceDB, sentence-transformers |
| Voice | DashScope ASR |
| Logging | loguru, coloredlogs |

### 5.2 Entry Point and Service Startup

`server/main.py` launches three processes:

1. **GPU Health Check** -- probes all GPUs with pynvml, excludes faulty ones from `CUDA_VISIBLE_DEVICES`
2. **Port Discovery** -- debug mode uses fixed ports; production auto-discovers free ports and announces via stdout (`PORT=<n>`)
3. **Process Spawning:**
   - Preprocessing: 4 workers, recycles every 500 requests (releases C library memory)
   - AI: 1 worker (PyTorch DataLoader compatibility)
   - Gateway: 1 worker
4. **Signal Handling** -- SIGTERM/SIGINT triggers parallel termination with 2s grace period, then force kill

### 5.3 Gateway

**Entry:** `gateway/main.py` with async lifespan

**Startup Sequence** (`gateway/startup.py`):
1. Database initialization (engine with pool_size=20, max_overflow=10, auto-migration)
2. Redis connection
3. GPU detection
4. Task queue initialization (`TaskQueueManager` singleton)
5. Cleanup (old progress files, expired grants, interrupted task recovery)
6. Background prewarm (Training RAG embeddings, chat context cache, ASR model)
7. HTTP client creation (for AI and Preprocessing inter-service calls)

**Router Registration** (`gateway/app_setup.py`):

17 routers registered:

| Router | Key Endpoints |
|--------|---------------|
| `auth` | `/auth/secure-login`, `/auth/me`, user CRUD |
| `stats` | System statistics and health |
| `wsi` | WSI CRUD, metadata, classification |
| `wsi_upload` | Batch WSI CSV upload |
| `training` | Training task management |
| `ai_tasks` | Inference task submission |
| `results` | Analysis results, external validation, CSV export |
| `models` | Trained model registry |
| `chat` | Conversations, messages (SSE), PDF search, feedback |
| `storage` | Disk stats, migration, orphan cleanup |
| `queue` | GPU task queue observation |
| `asr` | Automatic Speech Recognition (DashScope) |
| `heatmap` | Heatmap proxy |
| `settings` | System settings (OpenRouter key, HuggingFace token, etc.) |
| `gpu` | GPU info and status |
| `annotation` | Segmentation annotations, ROI extraction, COCO export |
| `training_options` | Training config metadata |

**Common Patterns:**
- Authentication: `user: User = Depends(current_active_user)` dependency injection
- Role checks: `require_admin()`, `require_can_use_gpu()`, `check_wsi_access_permission()`
- Database: `safe_session()` context manager for SSE-safe connections
- Inter-service: `httpx.AsyncClient` with 300s timeout for AI, 120s for Preprocessing

### 5.4 Database Layer

**Connection:** `AsyncAdaptedQueuePool` with pool_size=20, max_overflow=10, pre_ping=True, recycle=3600s

**Core Tables:**

| Table | Model | Purpose |
|-------|-------|---------|
| `data_groups` | `DataGroup` | Task/data/aggregation type taxonomy |
| `datasets` | `Dataset` | Dataset metadata, owner, visibility |
| `wsi_slides` | `WSISlide` | WSI file metadata, path, size, case_id, split |
| `training_tasks` | `TrainingTask` | Training job state, config, progress |
| `ai_tasks` | `AITask` | Inference task state |
| `trained_models` | `TrainedModel` | Model metadata, path, extractor type |
| `ai_results` | `AIResult` | Per-WSI inference results |
| `chat_conversations` | `ChatConversation` | Chat sessions with branching |
| `chat_messages` | `ChatMessage` | Messages with variants |
| `segmentation_annotations` | `SegmentationAnnotation` | Collaborative annotation drafts |
| `dataset_grants` | `DatasetGrant` | Permission grants with expiry |
| `users` | `User` | Accounts with roles and GPU access |

**Repository Pattern:**
All data access via repository classes (`DatasetRepository`, `WSIRepository`, `TrainingTaskRepository`, etc.) with static async methods.

### 5.5 Backend Modules

```
backend/
├── ai/              Training, inference, feature extraction, model management
│   ├── extractors/  Feature extraction models (ResNet, CONCH, OpenCLIP, etc.)
│   ├── classifiers/ ABMIL attention-based classification
│   ├── segmentors/  Foundation model segmentation (SAM, DINOv2)
│   ├── aggregators/ Tile-to-WSI prediction aggregation
│   ├── tasks/       Task type definitions
│   └── result_store Result I/O (zarr format, legacy HDF5)
│
├── preprocessing/   WSI image serving
│   ├── main.py      Tile, thumbnail, DZI endpoints
│   ├── tiling.py    Patch extraction, tissue segmentation
│   └── slide_access  Cached slide handles (Aslide, OpenSlide, tifffile)
│
├── auth/            User model, FastAPI-Users, JWT, role dependencies
├── annotation/      COCO export, summary cache, WebSocket pubsub
├── storage/         Disk stats, orphan detection, migration
├── database/        SQLAlchemy models, repositories, init/migrations
└── common/          Config, Redis client, GPU utils, port utils, progress store
```

**Task Types** (`ai/task_taxonomy.py`):
- `wsi_classification` -- whole slide image classification
- `patch_classification` -- patch-level classification
- `wsi_survival` -- survival analysis (Cox proportional hazards)
- `patch_segmentation` -- pixel-level segmentation

### 5.6 Chat / RAG System

**Components:**
- `gateway/chat/context_builder.py` -- aggregates per-user context (WSI stats, models, tasks, grants)
- `gateway/chat/context_cache.py` -- Redis-backed cache, prewarmed at startup
- `gateway/routes/chat.py` (~161KB) -- core chat API with SSE streaming
- `gateway/routes/chat_pdf.py` (~143KB) -- PDF upload, parsing (marker-pdf), vector indexing (LanceDB + sentence-transformers), hybrid search (BM25 + vector similarity)
- `gateway/routes/chat_training_recommendation.py` (~47KB) -- training RAG with bundled pathology knowledge

### 5.7 Task Queue System

`gateway/task_queue.py` -- centralized GPU concurrency control:

- FIFO queue with configurable `max_concurrent` (default: 1)
- VRAM pre-check before execution (waits up to 30 min for memory)
- GPU assignment tracking per task
- Bad GPU exclusion
- Task types: TRAINING, INFERENCE, EXTERNAL_VALIDATION, ANALYSIS, BATCH_INFERENCE

`gateway/pipeline.py` -- training pipeline:
1. Validation (coordinates, dataset preflight)
2. Patching (extract patches from WSI, can run in parallel)
3. Training (submit to AI service, poll for completion, 3-day timeout)
4. Post-processing (store results, email notification)

---

## 6. Electron Desktop

### 6.1 Main Process

**File:** `src/main/index.ts`

- Window management (900x670, preload script, context isolation)
- Deep linking via `pathlab://` protocol (OAuth callbacks)
- IPC handlers: `open-external-url`, `get-gateway-port`, `get-service-ports`, `select-files`, `select-directory`
- Media permissions auto-granted (microphone, audio capture)
- Service lifecycle: starts embedded PostgreSQL + Redis (if packaged), then Python sidecar

### 6.2 Sidecar Manager

**File:** `src/main/sidecar-manager.ts`

- Spawns Python backend (`python3 server/main.py` in dev, compiled binary in production)
- Parses stdout for port announcements (`PORT=<n>`, `[Services] Gateway: X, Preprocessing: Y, AI: Z`)
- Health check polling (`/health` endpoint, 500ms interval, 60s timeout)
- Process cleanup on app exit

### 6.3 Embedded Services

**File:** `src/main/services-manager.ts`

- **Redis:** Finds free port, starts bundled redis-server (Linux/macOS) or Microsoft Garnet (Windows)
- **PostgreSQL:** Uses `embedded-postgres` npm package; auto-initializes cluster on first run, creates `pathlab` database; persistent storage in `{userData}/postgres-data/`
- Connection strings passed to sidecar via environment variables

### 6.4 Preload Bridge

**File:** `src/preload/index.ts`

Exposes to renderer:
```typescript
window.api = {
  auth:    { openLoginUrl, onAuthCallback }
  backend: { getGatewayPort, getServicePorts, onGatewayPort, onServicePorts }
  files:   { selectFiles, selectDirectory }
}
```

---

## 7. Build & Deployment

### 7.1 Development Mode

```bash
# Frontend dev server
cd pathlab/pathlab-client
npm install
npm run dev              # Starts Vite dev server + Electron

# Backend only (debug mode)
cd pathlab/pathlab-client/server
PATHLAB_DEBUG=1 python main.py
# Services start on fixed ports: 6100, 6101, 6102
```

### 7.2 Electron Packaging

```bash
npm run build:linux      # or build:mac, build:win
# Sequence: build-python.sh → prepare-redis.sh → vite build → electron-builder
```

- **PyInstaller** (`main.spec`): Bundles Python backend as `--onedir` executable
  - Explicit hidden imports for string-based module loading
  - Aslide native libraries preserved as data (not binaries) to maintain directory structure
  - Excludes: pytest, Jupyter, Qt, triton, vLLM
- **Electron Builder:** Packages app with extra resources (server binary, Redis binary)
  - `asarUnpack` for embedded-postgres to avoid re-extraction

### 7.3 Web Deployment

**Scripts:**
- `deploy/start.sh` -- full deployment (kill existing, verify Redis, build frontend, launch backend, Nginx status)
- `deploy/hot-reload.sh` -- zero-downtime rolling restart (targets: frontend, backend, individual service, all)

**Nginx** (`deploy/nginx/`):
- HTTPS version with TLS 1.2+, strong ciphers, gzip
- HTTP-only version for internal networks
- Route mapping:
  - `/api/` -> Gateway (6100)
  - `/preprocessing/` -> Preprocessing (6101)
  - `/ai/` -> AI (6102, with path rewrite)
  - `/avatars/` -> Gateway static files
  - SPA fallback: `try_files $uri $uri/ /index.html`
- Cache headers: `index.html` no-cache; `/assets/*` immutable 1-year

**systemd** (`deploy/systemd/pathlab.service`):
- User service with environment file (`server/.env`)
- Restart=always, 5s restart delay
- 65536 file descriptor limit

### 7.4 Environment Variables

| Variable | Service | Purpose |
|----------|---------|---------|
| `PATHLAB_DEBUG` | Backend | Enable fixed ports (6100/6101/6102) |
| `DATABASE_URL` | Backend | PostgreSQL connection string |
| `REDIS_URL` | Backend | Redis connection string |
| `JWT_SECRET` | Backend | JWT signing secret |
| `OPENROUTER_API_KEY` | Backend | LLM API key |
| `HUGGINGFACE_TOKEN` | Backend | HuggingFace model access |
| `RESEND_API_KEY` | Backend | Email notifications |
| `CUDA_VISIBLE_DEVICES` | Backend | GPU selection |
| `PREPROCESSING_WORKERS` | Backend | Preprocessing worker count (default: 4) |
| `VITE_API_BASE` | Frontend | Override Gateway URL |
| `VITE_DEBUG` | Frontend | Force debug mode |

---

## 8. Testing

### 8.1 Frontend Tests

- **Framework:** Vitest + React Testing Library + jsdom
- **Location:** `pathlab/pathlab-client/test/`
- **Config:** `vitest.config.ts` (environment: jsdom, coverage: v8/lcov)

```bash
cd pathlab/pathlab-client
npm run test             # Watch mode
npm run test:run         # Single run
npm run test:coverage    # With coverage
```

### 8.2 Backend Tests

- **Framework:** pytest + pytest-asyncio + httpx
- **Location:** `pathlab/pathlab-client/server/tests/` (54+ test files)
- **Config:** `pytest.ini`

```bash
cd pathlab/pathlab-client/server
python -m pytest tests/ -v                              # All tests
python -m pytest tests/ -v -k "not pretrained"          # Skip GPU/HF tests
python -m pytest tests/test_ai_extractors_pretrained.py # GPU-only tests
```

**Test Patterns:**
- Route tests: override auth dependencies, test with `TestClient`
- Config tests: reset cache per test via `autouse` fixture
- Async tests: `@pytest.mark.asyncio` decorator
- Model tests: cross-parametrize with `_MODEL_CACHE` for efficiency

---

## 9. Core Workflows

### 9.1 Training Task Creation

```
NewTaskPage (6-step wizard)
  Step 1: Task Setup → Choose type (classification/survival/segmentation) + data level
  Step 2: Data Selection → Choose dataset, filter/select WSI files
  Step 3: Preprocessing → Patch extraction, normalization settings
  Step 4: Model Config → Architecture, hyperparameters, class mapping
  Step 5: Review & Submit → Validation + POST /training/tasks
  Step 6: Result → Success/error display

Backend Flow:
  Gateway receives task → TaskQueueManager.submit()
    → VRAM check → GPU assignment
    → Pipeline: Patching → Training (via AI service) → Post-processing
    → Store results → Email notification
```

### 9.2 AI Chat

```
User composes message (text + optional images/CSV)
  → POST /chat/conversations/{id}/messages
  → Gateway builds user context (WSI stats, models, tasks)
  → LLM call via OpenRouter (SSE streaming)
  → Response parsed into:
      - Markdown + KaTeX text
      - Embedded action cards (TaskConfig, Chart, ImageRec, etc.)
  → Cards can trigger actions:
      - "Run this training" → POST /training/tasks
      - "Analyze these slides" → inference pipeline
  → User feedback → POST /chat/feedback
```

### 9.3 WSI Upload

```
User drops files on UploadPage
  → BackgroundTaskContext.addUploadTask()
  → Chunked upload with AbortController support
  → Progress tracked in BackgroundTaskPanel
  → On success: metadata editor appears
      - Manual edit (label, case_id, age, gender, split)
      - CSV import for bulk metadata
  → POST /wsi/{id}/metadata
  → WSI appears in ListPage
```

---

## 10. Key Dependencies

### Frontend (npm)

| Package | Version | Purpose |
|---------|---------|---------|
| react | 18.2.0 | UI framework |
| electron | 39.2.7 | Desktop shell |
| @tanstack/react-query | ^5 | Server state management |
| react-router-dom | ^6 | Client-side routing |
| tailwindcss | ^4 | Utility-first CSS |
| @radix-ui/* | various | Accessible UI primitives |
| i18next | ^24 | Internationalization |
| echarts / echarts-for-react | ^5 | Charts |
| jspdf | ^4.2.0 | PDF generation |
| docx | ^9.6.0 | DOCX generation |
| exceljs | ^4 | Excel export |
| openseadragon | ^5 | Deep zoom image viewer |
| tiptap | ^2 | Rich text editor |
| embedded-postgres | 18.3.0-beta.16 | Bundled PostgreSQL |

### Backend (pip)

| Package | Version | Purpose |
|---------|---------|---------|
| fastapi | >=0.119.0 | Web framework |
| uvicorn | >=0.38.0 | ASGI server |
| sqlalchemy | >=2.0.34 | ORM |
| asyncpg | >=0.30.0 | PostgreSQL async driver |
| redis | >=6.0.0 | Cache and queue |
| torch | >=2.9.0 | Deep learning |
| transformers | >=4.57.0 | Model hub |
| timm | >=1.0.24 | Image models |
| open_clip_torch | >=2.32.0 | CLIP models |
| pillow | >=12.1.0 | Image processing |
| opencv-python | >=4.12.0 | Computer vision |
| openslide-python | >=1.4.2 | WSI reading |
| scikit-learn | >=1.5.1 | ML utilities |
| lifelines | >=0.30.0 | Survival analysis |
| lancedb | >=0.20.0 | Vector store (RAG) |
| sentence-transformers | >=3.4.0 | Embeddings (RAG) |
| marker-pdf | >=1.10.2 | PDF parsing |
| openai | >=2.5.0 | LLM client (OpenRouter) |
| dashscope | >=1.25.9 | Voice ASR |
| fastapi-users | >=15.0.0 | Auth framework |
| resend | >=2.0.0 | Email notifications |
