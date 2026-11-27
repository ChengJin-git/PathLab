# Web client tests

This directory holds the web client's unit tests and browser interaction tests. API contracts are
defined by `src/renderer/src/api/` and the Gateway code.

## Tools

| Tool | Configuration |
| --- | --- |
| Vitest | 5.1.0, configured in `vitest.config.ts` |
| Testing Library | `@testing-library/react`, `user-event`, `jest-dom` |
| Environment | jsdom 31, Node.js `^22.22.2 \|\| ^24.15.0 \|\| >=26.0.0` |
| Coverage | V8, text summary and lcov in `coverage/` |

Run from `app/`:

```bash
npm test                 # watch mode
npm run test:run         # single run
npm run test:coverage

# targeted run; lower the worker count on busy machines
npx vitest run test/unit/pages/ListPageMutations.test.tsx test/unit/lib/cache.test.ts --maxWorkers=2
```

`npx tsc --noEmit -p tsconfig.json` is a separate type check; passing tests do not replace it.

## Browser tests

Start the Vite dev server from `app/`:

```bash
cd src/renderer && VITE_API_BASE=/api npx vite --port 5189 --host 127.0.0.1
```

In another terminal run the tests (Python Playwright, Chromium and Pillow required):

```bash
VIEWER_URL=http://127.0.0.1:5189 python test/browser/viewer_workspace.py
VIEWER_URL=http://127.0.0.1:5189 python test/browser/viewer_attention.py
VIEWER_URL=http://127.0.0.1:5189 python test/browser/public_experience.py
VIEWER_URL=http://127.0.0.1:5189 python test/browser/data_navigation.py
VIEWER_URL=http://127.0.0.1:5189 python test/browser/chat_deletion.py
VIEWER_URL=http://127.0.0.1:5189 python test/browser/research_navigation.py
VIEWER_URL=http://127.0.0.1:5189 python test/browser/research_activity.py
VIEWER_URL=http://127.0.0.1:5189 python test/browser/research_preview.py
VIEWER_URL=http://127.0.0.1:5189 python test/browser/chat_activity.py
```

The scripts intercept only the app host's `/api/` requests with isolated fixtures; saving and
access control are verified separately by the backend PostgreSQL tests. Set `VIEWER_SCREENSHOTS` to
a temporary directory to keep screenshots.

- `viewer_workspace.py` — full-screen layouts on desktop and phone, the single toolbar from 320 px
  to desktop widths, create/delete, undo/redo, team publication, zoom after deletion, paging of 120
  annotations, and complex questions handed back to the main page with context.
- `viewer_attention.py` — classification probability hierarchy, single- and multi-class
  segmentation legends, detection colours and filters, 10 highest and lowest thumbnails with raw
  scores, click and keyboard navigation, isolation of old results after a fold change, narrow-screen
  scrolling.
- `data_navigation.py` — `/datasets` and `/upload` navigation, task order, skeletons under slow
  APIs and reduced-motion settings.
- `public_experience.py` — landing-page autoplay, pause and reduced motion, stable layout across
  the three languages, and a one-screen sign-in page with a captcha placeholder on desktop and phone.
- `chat_deletion.py` — immediate removal while DELETE is pending, restoring only the failed
  conversation, isolation from stale list responses, silent clean-up and live language switching.
- `research_navigation.py` — long research records, detail panel toggling and focus return, the
  full page and back, mutually exclusive file panels, mobile entry points; dynamic task plans, hour
  formatting and trilingual labels.
- `research_activity.py` — folding and paging of 60 progress items, stable single-line titles under
  live updates, language switching, mobile overflow; measures the cost of expanding 500 items.
- `research_preview.py` — paging, zoom, spreadsheets, Markdown/HTML/image/code previews and links
  for real PDF/PPTX/DOCX conversions (needs LibreOffice, PyMuPDF, python-pptx, python-docx,
  openpyxl); checks there are no serial requests before the first page.
- `chat_activity.py` — search topics and article titles in the activity strip, no internal fields
  in the DOM, no network requests on expand, desktop/phone and language switching.

## Layout

```text
test/
├── setup.ts                   # fetch/localStorage mocks and jest-dom
├── helpers/apiHelpers.ts      # Response and SSE fixture factories
├── browser/                   # Playwright flows on real pages with isolated APIs
└── unit/
    ├── api/                  # requests, auth headers, parameters, caching, errors
    ├── lib/                  # utilities, hooks, selection state, cache races
    ├── contexts/             # auth and background-task lifecycles
    ├── constants/            # states, task types, copy
    ├── pages/                # page flows, loading and error states
    ├── renderer/             # HTML entry
    └── components/           # chat, settings, viewer, upload, results, common UI
```

- `setup.ts` replaces global `fetch` with a mock and resets calls and the mocked `localStorage`
  before each test.
- `helpers/apiHelpers.ts` provides `ok`, `errResp`, `noContent`, `blobResp` and `createSSEStream`.
- Page tests use `QueryClientProvider`, a router and the necessary contexts, with a new
  `QueryClient` per test and retries disabled.
- Unit tests use synthetic tokens and resource IDs; they never touch a production database or an
  external language model.

## Page actions and caching

| File | Behaviour |
| --- | --- |
| `unit/pages/ListPageMutations.test.tsx` | One property request; the card updates from the response and the dialog closes without waiting for the list; failures keep the draft |
| `unit/pages/TaskListPage.test.tsx` | Delete confirmation, storage summary, removal after success; no duplicate cancellation from the client |
| `unit/lib/cache.test.ts` | TTL, de-duplication, invalidation and error recovery for value, keyed and persistent caches; late requests cannot overwrite newer values |
| `unit/lib/datasetQueryInvalidation.test.ts` | API cache cleared before React Query pages and source options are invalidated |
| `unit/lib/datasetPagination.test.ts` | Page number kept during loading and errors, corrected once data is stable |
| `unit/lib/listPageFileView.test.ts` | Initial load, empty dataset, no search matches, normal view |
| `unit/pages/UploadPage.test.tsx` | Registration, constraints on appending, segmentation image/JSON pairing |

The cache lives in `src/renderer/src/lib/utils/cache.ts`. `forceRefresh` bypasses a completed cache
entry but may reuse a valid in-flight request; `invalidate()` removes the right of earlier requests
to write back.

## Chat, multi-turn interaction and speech

| File | Behaviour |
| --- | --- |
| `unit/lib/chatMessageParser.test.ts` | Keeps option order, model lists, patch-inference selections and configurations; strips execution and cache fields |
| `unit/components/chat/OptionButtons.test.tsx` | Option text returned as is, trilingual free-text entry, disabled while generating, IME confirmation does not send |
| `unit/lib/useConfirmedSubmission.test.tsx` | Only a new confirmation submits; mounting a historical card does not execute it |
| `unit/components/chat/AnalysisConfigCard.test.tsx` | Edited evaluation parameters, confirmation and errors |
| `unit/components/chat/BatchInferenceConfigCard.test.tsx` | Batch inference configuration, confirmation and submitted state |
| `unit/components/chat/ImageRecommendationLoading.test.tsx` | Bounded server-side filtering, re-validation on workspace change |
| `unit/components/chat/WorkbenchSidebar.test.tsx` | Immediate conversation removal, failure recovery, late list responses; upload navigation and folders |
| `unit/components/chat/VoiceControlBlock.test.ts` | Parsing streamed voice control blocks |
| `unit/lib/useRealtimeASR.test.tsx`, `pcmProcessor.test.ts` | Device and connection lifecycle, start-up buffering, timeouts, PCM processing |
| `unit/api/workspaceScope.test.ts` | Request scope for workspaces and execution policy |

## API tests

| Module | Coverage |
| --- | --- |
| `client.test.ts` | `ApiError`, error bodies, auth headers, query parameters, JSON/Blob responses, session expiry |
| `crypto.test.ts`, `auth.test.ts` | Sign-in hashing, credentials, profile, avatar, sign-out |
| `wsi.test.ts` | Paging, lookups, duplicate checks, `updateDatasetProperties()`, metadata, upload, templates |
| `training.test.ts` | Models, training tasks, configuration, rename/delete, list cache |
| `results.test.ts`, `analysis.test.ts` | Slide results, result lists, internal analysis, external validation |
| `batchInference.test.ts` | Unlabelled-dataset inference, progress, results, CSV export |
| `chat.test.ts` | Conversation and message CRUD, chat SSE, patch inference |
| `heatmap.test.ts` | Available heatmaps, image URLs, masks, cache invalidation |
| `users.test.ts` | Administrator user operations, terms, maintenance mode |
| `settings.test.ts` | System settings; public settings use `PublicSettings` |
| `storage.test.ts` | Storage configuration, inventory paging, scan-bound clean-up, migration, background tasks |
| `queue.test.ts`, `trainingOptions.test.ts` | Queue status and cancellation, supported training components |
| `stats.test.ts`, `export.test.ts`, `feedback.test.ts` | Statistics, export tasks, message feedback |
| `autoresearch.test.ts` | Research sessions, events and artifacts |
| `config.test.ts` | Service URLs from environment variables and defaults |

Contract notes:

- Dataset properties, including visibility, are updated through
  `PATCH /wsi/datasets/{dataset_id}/properties` (`api/wsi.ts`).
- `fetchRecommendedImages()` is the bounded entry for image cards.
- Training and data tasks use the canonical IDs `wsi_classification`, `patch_classification`,
  `wsi_survival`, `patch_detection` and `patch_segmentation`.
- Public captcha settings use `captcha_provider` and `captcha_site_key`.

## Contexts and components

- `unit/contexts/AuthContext.test.tsx` — authentication state, terms, maintenance-mode sign-in
  messages, session expiry.
- `unit/contexts/backgroundTask/` — SSE lifecycle, account isolation, late events, task actions and
  the background panel.
- `unit/components/chat/`, `list/`, `upload/`, `wsiViewer/`, `results/`, `settings/` — the
  corresponding components; `unit/components/wsiViewer/useViewerAnnotations.test.tsx` covers object
  editing, revision conflicts, idempotent retries and undo/redo.
- `unit/lib/externalValidationUtils.test.ts` — task, data type, label set, training source and
  segmentation model compatibility for external validation.
- Research tests: `unit/api/autoresearch.test.ts`, `unit/pages/AutoResearch*.test.tsx`,
  `unit/components/autoresearch/`, `unit/lib/autoresearch*.test.ts`.
- `ReportGeneratorPage` tests cover article generation, saving and polishing, paging, recovery and
  deletion.

## Conventions

1. Use controllable promises to test "write finished, refresh still running" orderings instead of
   fixed sleeps.
2. Clear caches, restore real timers and restore global stubs after each test.
3. Network errors, permission denials, empty lists and partial failures must never look like
   success; assert visible state and request parameters.
4. Report the suites actually run and their results. A command that starts, a passing type check or
   a successful build is not a verified interaction.
5. Tests use temporary directories, fixtures and controlled services. One-off deployment probes,
   screenshots and temporary credentials are not part of the suite.

Backend tests are in `../server/tests/`; see [server/README.md](../server/README.md#tests).
