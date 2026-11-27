# PathLab web client

`src/renderer/` is the React client of the PathLab web application: data management, training and
analysis, the chat workspace, research sessions and the whole-slide viewer.

## Overview

- React 18.3 + TypeScript 5.9 + Vite 8 + Tailwind CSS 4.
- Node.js `^22.22.2 || ^24.15.0 || >=26.0.0` (26.13.0 LTS recommended).
- `BrowserRouter`; languages `en-US`, `zh-CN`, `zh-HK`.
- Progressive web app: a service worker is registered in production builds.
- Whole-slide viewing with OpenSeadragon (assets bundled in `public/`).
- Research sessions: `/autoresearch` redirects to `/autoresearch/new` (new session);
  `/autoresearch/sessions/:id` shows a running session and its event stream.

## Install and build

Run from `app/`, which holds the only `package.json` and `package-lock.json`:

```bash
npm ci
npm run typecheck
npm run test:run
npm run build        # writes src/renderer/dist
npm run dev          # Vite dev server
```

Direct dependencies are pinned to exact versions and `.npmrc` saves exact versions.

## Key files

- `vite.config.ts` — web build configuration (PWA manifest, chunking).
- `src/main.tsx` — runtime entry: providers, router, service worker.
- `src/App.tsx` — routes.
- `src/config.ts` — Gateway, Preprocessing and AI URLs from `VITE_*` variables or the page host with
  ports 6100/6101/6102.

```text
src/renderer/
├── public/                 # static assets (images, OpenSeadragon)
├── src/
│   ├── api/                # API clients per domain
│   ├── components/         # UI, chat, viewer, results, settings, research components
│   ├── constants/          # constants
│   ├── contexts/           # Auth, BackgroundTask, Toast
│   ├── hooks/              # React hooks
│   ├── lib/                # utilities
│   ├── locales/            # translations
│   ├── pages/              # pages
│   ├── types/              # type declarations
│   ├── App.tsx
│   ├── config.ts
│   ├── i18n.ts
│   └── main.tsx
└── vite.config.ts
```

## Runtime

`src/main.tsx` waits for the current language to load, composes `QueryClientProvider`,
`TooltipProvider`, `ToastProvider`, `AuthProvider` and `BackgroundTaskProvider` inside a
`BrowserRouter`, and registers the service worker.

## Routes

- Public: `/`, `/login`.
- Signed in: `/dashboard`, `/dashboard/:conversationId`, `/tools`, `/files`, `/abilities`;
  `/settings` requires an administrator.
- Tasks: `/task-setup` (GPU role), `/task-list`, `/task/:task_id`.
- Data: `/datasets`, `/upload`, `/wsi/:wsi_id`.
- Results: `/results`, `/evaluate` (GPU role), `/reports` (research role).
- Research: `/autoresearch`, `/autoresearch/new`, `/autoresearch/sessions/:id` (research role).
- A `*` fallback.

The research role is granted to administrators and pathologists. In the optional standalone research
mode (`VITE_AUTORESEARCH_STANDALONE=true`), `/` and unknown paths redirect to `/autoresearch/new`.

## API clients

`src/api/` has one module per domain (see `src/renderer/src/api/*.ts`): `analysis`, `annotation`,
`auth`, `batchInference`, `chat`, `export`, `feedback`, `heatmap`, `viewer`, `datasetCatalog`,
`chatNavigation`, `fileLibrary`, `resultWorkbench`, `queue`, `autoresearch` (base
`${API_BASE}/research`), `reports`, `results`, `settings`, `stats`, `storage`, `training`,
`trainingOptions`, `workspaces`, `users`, `wsi`, plus the shared `client`, `crypto` and `index`.

API modules read the base URL at request time from `src/config.ts`.

## Interaction and state

- Dataset edits are one `updateDatasetProperties()` call; the card updates from the response and
  the dialog closes, while pages and filters refresh in the background. Failures keep the draft.
- The server orders task cancellation and deletion; renaming, deleting and submitting inference do
  not wait for list refreshes.
- Deleting a conversation removes it from the list immediately and restores it only if the request
  fails.
- `/datasets` and `/upload` show layout skeletons while loading; `lib/dataPages.ts` preloads their
  code on sidebar hover or focus.
- Upload tables render page by page; images can be added and CSV/COCO labels appended to existing
  images; tasks are multi-select, with detection and segmentation stored separately.
- After a cache is invalidated, older requests cannot write stale values back.
- Chat option groups always offer a localized free-text choice; confirmed cards are submitted
  through `useConfirmedSubmission`, and opening a historical card never executes it.
- Image recommendation cards show a small server-filtered set and re-validate when the workspace
  changes.
- Research sessions support effort levels, brief polishing, skill-package import, follow-up
  instructions, budget recovery and continued optimisation.
- The model catalog groups metrics as out-of-fold, validation and test, with task-specific views.
- The viewer uses object revisions, idempotent operations and tombstones with undo/redo, conflict
  handling and recovery of unfinished operations ([VIEWER.md](../../server/backend/services/VIEWER.md)).

## Related documents

[Source details](src/README.md) · [App overview](../../README.md) · [Backend](../../server/README.md) ·
[Datasets](../../server/backend/services/DATASETS.md) · [Features](../../server/backend/services/FEATURE-ARTIFACTS.md)
