# Web client source

`src/renderer/src` contains the React source of the PathLab web application: pages, API clients,
chat, viewer and training components, and the research-session front end.

```text
src/
├── App.tsx                 # routes
├── main.tsx                # providers, router, service worker
├── config.ts               # Gateway / Preprocessing / AI URLs
├── i18n.ts                 # i18next; one chunk per language, only the active one is downloaded
├── api/                    # API clients per domain
├── components/             # reusable UI, chat, viewer, results, settings and research components
├── contexts/               # Auth, BackgroundTask, Toast
├── constants/              # file types, metrics, training constants
├── hooks/                  # React hooks
├── lib/                    # utilities
├── locales/                # en-US, zh-CN, zh-HK
├── pages/                  # pages
└── types/                  # type declarations
```

Routes are listed in [../README.md](../README.md#routes). Chat is available to signed-in guests;
research sessions and articles require the administrator or pathologist role.

## Main pages and state

- `IntroductionPage.tsx`, `LoginPage.tsx`, `PublicSite.tsx` — public pages and sign-in.
- `AIChatPage.tsx`, `ToolsPage.tsx` — chat, tools and PDF reading.
- `ListPage.tsx` — paginated dataset and slide browser; property edits use one PATCH endpoint.
- `UploadPage.tsx` — create datasets or add images, tasks and labels.
- `WSIViewerPage.tsx` — full-screen slide canvas with result, annotation and assistant panels.
- `NewTaskPage.tsx`, `TaskDetailPage.tsx`, `TaskListPage.tsx` — task configuration and tracking.
- `ResultsViewerPage.tsx`, `ReportGeneratorPage.tsx` — results; article list, background writing
  from real experiments, versioned editing, polishing and export.
- `SettingsPage.tsx` — system settings, users, storage (`StorageManagementPage.tsx` is an internal
  view, not a route).
- `AutoResearchNewSessionPage.tsx`, `AutoResearchSessionPage.tsx` — start and follow research
  sessions; a session links back to its conversation.
- `contexts/backgroundTask/` — SSE and actions for training, analysis and storage tasks.
- `components/common/PageLoading.tsx`, `lib/dataPages.ts` — skeletons, lazy data pages and intent
  preloading.
- `types/autoresearch.ts`, `lib/autoresearch*.ts` — research API types, event and session helpers,
  artifact downloads.

## Chat

- `useChatWorkbench` manages skills, references and research links; `WorkbenchPicker` offers bounded
  `/` (skills) and `@` (resources) completion; `ResearchThread` shows the persisted research process
  with a detail panel on demand.
- `Layout` holds the shared `WorkbenchSidebar`: new and searchable chats, upload, data repository,
  file library, tools, assistant capabilities, chat list, background progress and an
  administrator-only system entry. Switching between data, tools and capabilities keeps the chat
  instance, draft and references. Folders organise chats only; they do not share context or change
  access. `/chat-navigation` returns bounded cursor pages without message bodies.
- Deleting a conversation removes it at once and restores it on failure. Its attachments, research
  files and outputs are cleaned in the background; independent library files and referenced files are
  kept.
- `FileLibraryPage` is the single place for file management and personal retrieval: automatic
  processing after upload, folders, rename, move, replace, download, delete, file-name and content
  search. `@` references files across chats by ID and revision; citation links open the exact file or
  PDF page. Administrators can switch to all users' files.
- The chat page (Markdown, KaTeX, code highlighting) is not in the first chunk; it is prefetched when
  idle or on sidebar hover. Charts (`LazyECharts`) and ExcelJS load on demand.
- `ConversationFiles` and `HistoryFiles` browse and preview conversation files (20 per page) with
  cancellable content requests.
- `/` command names and descriptions come from the server's trilingual catalog.
- *Assistant capabilities* (`/abilities`, `CapabilityLibrary`) lists skills and connectors: added,
  discover and created by me, plus an all-users view for administrators. Private entries are visible
  to their owner and administrators; public entries can be added by others; credentials are stored
  encrypted per user. Enabled skill metadata is preloaded each turn and the model loads instructions
  with `LOAD_SKILL` when needed. Guests can chat, but GPU and autonomous requests are explained by the
  model and blocked by the server.
- `SkillPackageEditor` lists, searches, edits, uploads, replaces, deletes and downloads files of a
  skill package; saves are versioned so concurrent edits cannot overwrite each other, and running
  tasks keep their own snapshot.
- Text files are delivered through server-persisted `FILE_DELIVERY` cards; `ActivityStrip` shows only
  real search, read, execution and save actions.
- `AnalysisResultView` shows saved metrics, intervals, tables and generated figures, reusing ROC,
  confusion-matrix, Kaplan–Meier and loss-curve charts.
- `WorkspaceControls.tsx` and `lib/workspaceSelection.ts` keep the workspace, capabilities,
  connectors and execution mode; `api/client.ts` adds the matching request headers.
- `OptionButtons.tsx` keeps option text and order and adds an "other" input that does not send
  until submitted.
- `lib/utils/chatMessageParser.ts` keeps resource choices and reusable configuration and strips
  execution and cache fields.
- `ImageRecommendationCard.tsx` calls `fetchRecommendedImages()`; filtering, the latest visible
  prediction and limits are decided by the server.
- `lib/utils/cache.ts` provides value, keyed and persistent caches that reject late writes after
  invalidation.
- The three language files must have identical key sets (`test/unit/i18n.test.ts`); there is no
  runtime fallback language, and `changeLanguage` downloads the target language before switching.

## Storage page

The storage overview shows the existing snapshot immediately and keeps it while refreshing.
Inspections (`/storage/inspections/{kind}`) report real progress; leaving the page cancels the
browser query but not the shared inspection. Health-check results render 100 rows per page.

## Research, models and viewer state

- `ResearchRefinementPanel` and `ResearchRecoveryPanel` continue or unblock the current session;
  `useSessionStream` merges new events by sequence, isolated per account and role.
- The new-session page accepts skill folders, ZIP/`.skill` files, GitHub repositories and Markdown
  skills, previews resources and compatibility, and submits a package snapshot.
- `ResearchJobNotice` shows dataset download receipts (missing metadata, missing annotations or
  ready for training).
- `ModelsTab` uses `inference_ready` and the active flag and keeps actual metric names and
  experiment sources.
- `components/wsiViewer/useViewerAnnotations.ts` manages object editing, idempotent operations,
  undo/redo, conflicts and recovery. Personal and team objects, assistance previews and published
  labels are shown separately.

Viewer results are loaded per slide and opened layer by layer: attention thumbnails show the 10
highest and lowest patches, classification probabilities are grouped, detection boxes and
segmentation masks use the real classes and colours. Annotation lists show 50 items per page; the
canvas loads 500 objects per batch and keeps at most 2,000. See
[VIEWER.md](../../../server/backend/services/VIEWER.md).

## Component groups

`components/` contains `charts/`, `chat/`, `common/`, `landing/`, `legal/`, `list/`, `autoresearch/`,
`results/`, `settings/`, `taskDetail/`, `training/`, `ui/`, `upload/` and `wsiViewer/`.

## Related documents

[Web client](../README.md) · [Repository README](../../../../README.md) · [Backend](../../../server/README.md)
