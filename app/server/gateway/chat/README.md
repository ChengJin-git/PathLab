# Workspace-aware Chat

> PathLab v1.0.8 · Updated 2026-11-06

PathLab Chat resolves each request against a saved workspace, current permissions and enabled capabilities. "All areas" searches the user's authorized resources with bounded queries.

## Runtime

- `backend/database/models.py`: `Workspace` and conversation `workspace_id`.
- `backend/services/workspaces.py`: scope resolution, SQL visibility, task-input membership,
  scan-root validation and public skill/connector catalog.
- `gateway/routes/workspaces.py`: authenticated workspace CRUD, paginated dataset chooser,
  account/resource capabilities. Workspace archive preserves old conversation bindings.
- `gateway/workspace_access.py`: API execution restrictions and explicit resource checks.
- `gateway/chat/context.py`: intent/expert selection, bounded history, scoped SQL queries,
   permission-aware short-lived Redis cache. Live task status bypasses the context cache.
- `gateway/chat/turn_intent.py`: full-match routing for standalone introductions and
  inventory questions, without inheriting a previous action card or selected expert.
- `gateway/chat/capabilities.py`: read-only, scope-checked recovery for a workflow or
  resource lookup requested by the model when prefetch did not supply enough facts.
- `gateway/prompts/scoped.py` + `workflows.py`: shared identity/interaction rules and
  on-demand capability contracts, with active-language instructions.
- `WorkspaceControls.tsx`: select/create/edit/archive, datasets, scan roots, skill/connector
  availability and read-only policy. Changing workspace starts a fresh conversation.
- `ChatQuickActions.tsx`: desktop keeps Fresh Start / Train Model / Test Model /
  Browse Images / Autonomous research in that order. Mobile shows compact primary
  actions and a bottom sheet; selecting a scenario pre-fills the composer.

## API

`GET/POST /workspaces`, `GET/PUT/DELETE /workspaces/{id}` manage the current user's
workspaces. Admins retain explicit-ID access. `GET /workspaces/datasets` is a paginated
search over authorized dataset metadata. `GET /workspaces/capabilities` exposes public
capability names/configuration status, never credentials. `GET
/workspaces/datasets/{id}/capabilities` reports read/write/GPU/AutoResearch separately.

Chat requests carry `workspace_id`, `expert_id`, `enabled_skills`, `enabled_connectors`,
and `execution_mode` (`standard` or `read_only`). Resource requests use `X-Workspace-ID`,
`X-Workspace-Mode`, and selected `X-Chat-Skills`. Resource lists use the same header scope.
Conflicting scopes are rejected. A saved workspace policy can only be narrowed per turn.
`voice_session_active` loads the microphone-control contract only during voice sessions.

Workspaces reference existing dataset IDs without copying files. Read permissions are
rechecked on every context build/cache lookup. Owned and public dataset access is resolved
server-side. Resource/task/model ownership still applies.
Being a workspace member never grants access to another user's private data or models.

The first public connectors are the existing Exa search and article reader. Their
configuration remains platform-managed. AutoResearch's internal YAML execution skills
remain separate from this Chat capability catalog. Research inputs use the shared current dataset-access policy and workspace scope; execution also requires account GPU capability.

## Performance

Interactive article reading uses native PDF text, whitespace-based column ordering,
ruled-table cells and original-page previews; only scanned pages run layout/OCR.
The file-library extraction profile retains its layout pipeline. Nature landing-page
reads prefer verified publisher HTML body sections (`fulltext_html`); explicit PDF
URLs and download actions still retrieve PDF bytes. Abstracts stay labeled as such.
The reader reports actual received bytes, completed/total pages, OCR, queue state and
elapsed time through SSE. Chat keeps the latest status per URL and displays progress
alongside the activity strip. Unknown download lengths have no fabricated percentage.
Parsing has a 90-second cap and a 10-second queue bound; parser cancellation terminates
the subprocess. Parsing timeouts are distinct from network failures. Successful
reading results share the canonical article cache for follow-up questions.

Article reads and cached follow-ups send `citation_sources` (stable source identity
and bounded page excerpts) before answer tokens. The renderer replaces citations in
Markdown prose nodes as they arrive; code and ordinary links stay literal. Each
unique source/page target gets a display number in first-appearance order, separately
from the conversation source index. Final citation contexts refine tooltips and allow
older saved replies to render identically. CJK-aware emphasis and render-only Markdown
completion handle Chinese punctuation and token boundaries without rewriting replies.

Regeneration saves the replacement and archived follow-up boundary in one transaction.
All siblings are deactivated before the new version is selected. Conversation loading
projects one active answer at its original turn position, excluding superseded tails;
cancelled retries are saved as variants too. Switching versions is acknowledged by the
server before the UI updates. Article explanations present scientific conclusions and
specific material limitations, keeping drafting decisions and self-instructions internal.

General and conceptual questions avoid business database queries. Quantity-only questions
load totals; general dataset browsing loads five names/types without IDs or split columns.
Other resource requests use bounded candidates (12 datasets, 5 models, 8 tasks), fetching
actual labels for dataset choices/browsing. Uploaded-image turns use a dedicated visual
contract and compatible patch-model candidates, avoiding dataset/supervision/task scans.
Result-overlay requests check up to three recent, owner-visible result items per candidate
dataset against finalized artifact metadata, reading each task bundle only once. Ordinary
image browsing skips artifact inspection; an explicit annotation capability load can recover
evidence independently of keyword prefetch.
`available_features` reads the shared `FeatureArtifact` inventory. Features without coordinates remain available to compatible analysis, while regional search requires matching coordinates. Text alignment is reported only from a verified explicit contract; see [feature artifacts](../../backend/services/FEATURE-ARTIFACTS.md).
Missing examples do not prove all results are absent. Full counts cover the authorized scope. Short card follow-ups
retain explicit resource IDs for retrieval; option selections retain the preceding workflow.
Context cache keys include user, role, current accessible IDs, workspace version,
query, context schema, active capabilities and mutation revision. TTL is 20 seconds; Redis failures have
a short timeout and do not prevent authoritative database reads.
Mutation revisions are updated in a bounded Redis pipeline. Candidate completeness flags
use scoped totals, while compatibility remains a separate task/data check.

Image cards use `GET /wsi/recommendations` to apply dataset access, workspace, type,
label, survival and latest-visible-prediction filters before a bounded limit (default 3,
maximum 100). Model/task filters also apply before selection. Empty prediction matches
stay empty; they never fall back to unrelated original images. Cards revalidate candidates
on remount/workspace changes instead of retaining a cross-request resource cache.
Training evidence searches existing indexes once across the relevant source set in a
worker thread. PDF parsing/index construction remains in startup prewarming.
If the embedding model is still warming up, optional training retrieval uses the existing
profile guidance without waiting for a cold load or claiming retrieved paper evidence.

SSE opens before context preparation; preparation sends heartbeats and is cancelled on
disconnect. Normal model text streams even when web search is disabled. `context_metrics`
reports preparation milliseconds and prompt/history characters. These are **characters,
not tokenizer token counts**. Conversation authorization avoids loading the full message
history again. History is bounded to recent turns, retaining complete workflow blocks.

## Response behavior

### Chat / built-in / autonomous boundary

`gateway/prompts/execution.py` is the shared execution boundary. Capability contracts
must not reinterpret a limitation of one card as a limitation of the whole platform.

| User's actual work | Execution path |
| --- | --- |
| Explain/discuss methods, brief literature reading, download an original PDF, inspect known results | Chat, using enabled read/search protocols |
| Save supplied findings as Markdown or a small text export | Chat `DELIVER_FILE`, with server-owned saved-file receipt |
| One supported training/evaluation/inference or standard bootstrap CI | Existing functional card and its submission confirmation |
| Custom regression/objective/encoder fine-tuning, coordinated comparisons, iterative original research | Autonomous `experiment`; `scientific` only for original research |
| Custom statistics on saved data/predictions | Autonomous `analysis`, normally `summary`, without implied retraining |
| Produce a binary Word/PDF document from supplied findings | Autonomous `document`, without implied experiments or manuscript |
| Download timeout/403/404/parser failure | Explain the actual failure and recovery; no automatic scope escalation |

An execution NAVIGATE state requires `researchGoal`, `handoffReason`, `datasetIds`,
`references`, `taskKind`, `reportPolicy`, and `researchStandard`. Unknown/omitted state
fields are rejected. The stream allows one schema-repair turn before reporting failure;
invalid envelopes are removed before a corrected envelope is emitted. No old decision
defaults or keyword-based execution classifier remain. The validated decision is saved
with the assistant message; resources are independently reauthorized by `create_session`.

An explicitly delegated custom goal can start in the same turn. Discussion, negation,
quoted proposals, /ask, read-only and the brief-only turn do not authorize execution.
Only the latest unanswered brief carries its confirmation state; saved budget settings
remain reusable without imposing a permanent confirmation gate. Handoff preserves the
task kind, research standard and the intersection of Chat/workspace connector controls.
Research tools and autonomous manuscript citation retrieval recheck that connector scope.

### Failure and partial-success contract

The article downloader returns verified PDF bytes or `ArticleDownloadError(code)`. HTTP 403/404/429/5xx, timeouts, missing
PDF, unreadable text and storage failure have distinct codes. `gateway/chat/failures.py`
provides localized cause and recovery text, never raw exception bodies, credentials or
internal paths. The server streams the failure before attempting another model reply.
Repeated failed searches are bounded, and missing current/source evidence cannot be
replaced by model memory. Connector/context exceptions complete with an explicit failure
rather than appearing as user cancellation or leaving an empty spinner.

Extracted article text replaces non-whitespace control glyphs (including NUL,
which PostgreSQL rejects) with a visible replacement character before context,
citation and structured-evidence persistence. Replacement preserves text offsets,
page boundaries and printable Unicode; original PDF bytes stay intact. Cache reads
apply the same normalization, so retrying a previously parsed source is safe without
downloading it again. Stream failures save the partial response and publish its
message ID before `[DONE]`, preventing a duplicate frontend fallback save. Diagnostic
logs include the request ID, exception class and SQLSTATE, not document contents.

`read_download` retains a verified original PDF even when parsing fails. Its file delivery
is independent of later model completion; incomplete model-generated files are rejected.
The durable article result includes `error_code`, `message`, `recovery_hint`, and `action`,
so the failure card and next step survive a conversation reload. A completed manuscript
can still be read when new citation retrieval is disabled.

The disconnect watcher has an explicit stop event: a fast cached/failed operation cannot
hang while AnyIO's request check consumes task cancellation. Actual disconnects still
cancel the owned operation. Tests cover both cases.

Natural-language intent is resolved in the existing LLM generation, including negation,
correction, confirmation and topic changes. Keyword matching only prefetches bounded
candidate facts/contracts; it does not execute an action or decide whether a requested
search is allowed. Connector availability, resource access, compatibility and API execution
checks remain deterministic.

There is no separate classification model call. Common requests use prefetched context
and one streaming generation. If needed facts/contracts are missing, the model can emit
`LOAD_CAPABILITY` (at most two actual loads per turn), using the same workspace permissions.
That recovery requires another generation, only on demand; it is not a zero-latency path.
Enabled search/read protocols remain visible so a topic change is not trapped in the
previous card's workflow. Local training evidence is reference, not a forced search order.

Voice intent follows the same pattern: the LLM emits a leading `VOICE_CONTROL` command;
the client executes a complete `stop` while the reply is still streaming. No user-phrase
regex classifier or additional intent round-trip is involved. The local stop button is
immediate. Capture begins when the microphone/worklet are ready; startup PCM buffering
covers the 45-second setup deadline until ASR confirms its configuration. A 15-second
no-progress timeout still applies; stopping discards the buffer and cancels both timers.
Cloud ASR uses `qwen3-asr-flash-realtime`. Upstream stream errors, including concurrency
limits inside an HTTP-200 SSE response, surface as errors rather than empty messages.

The compact shared prompt preserves PathLab Agent's SmartXLab/HKUST identity, active
language, concise conversational prose and one-question-at-a-time guidance. App facts
are private reference: partial lists are described naturally, without retrieval diagnostics.
Business contracts load by capability and preserve canonical task types, supervision and
component constraints, exact frontend card fields, and explicit submission confirmation.
Training scenario/assistant prefills in all three UI locales cover classification, survival, detection and segmentation according to verified dataset metadata; selection alone never submits a task.
Known actionable choices use `OPTIONS` buttons, not prose lists or requests to retype names.
Resource shortlists include a context-specific alternative (another dataset/model/task/paper)
when scoped availability allows it. Complete single-resource scopes, incompatible candidates,
fixed modes/labels and disabled capabilities must not produce fictitious alternative actions.
Context includes scoped totals and `datasets_complete`/`models_complete`/`tasks_complete`
flags so a complete single-resource scope is distinguishable from a bounded shortlist.
Paper discovery alternatives depend on the search connector, and reading URLs depends on
the article connector; a capability reload cannot substitute for a disabled connector.
Every rendered options group, including historical messages, also provides a localized
free-text request entry; opening it does not send a message or execute anything. Submitting
the user's actual text uses the normal conversation flow. Alternative choices preserve the
pending goal, can retrieve a named resource beyond the shortlist, and never imply confirmation.
The client retains option order, model lists and patch model choices in conversation history;
execution/cache fields are stripped from reusable cards while compact operation outcomes
remain available for follow-ups. Training, evaluation and batch-inference confirmations
target the latest valid configuration card; execution waits for validation and never starts
merely because a historical card is mounted. Updated card settings are persisted to history.
Read-only mode permits explanations/display cards; mutation/configuration cards are
suppressed by instruction and execution restrictions remain independently enforced by APIs.

## Installation

Fresh databases initialize through `current_schema.py`; existing databases must record `20261105_verified_feature_inventory`. A null conversation workspace means all authorized resources. Deploy frontend, Gateway and both workers together. Historical upgrade scripts are not run at startup; see [database](../../backend/database/README.md).

## Unified research workbench

### Persistent file library and personal retrieval

The sidebar separates Data repository from File library. Files uploaded or delivered
in Chat and cataloged research outputs are stored independently under `chat-files`.
Conversation deletion removes files owned by that conversation or its research sessions; independent library uploads and files merely referenced by the conversation remain. `/file-library` manages folders, names,
replacement, deletion and owner/admin views; there is no separate knowledge-base UI.
Supported documents index automatically with LlamaIndex, multilingual E5-small,
LanceDB keyword/vector fusion and a multilingual cross encoder. Search prefilters
authorized IDs/revisions, then rechecks current metadata before exposing passages.
`@` searches authorized files across conversations. `SEARCH_FILES` lets the model
retrieve from the user's library when the goal calls for it. File citations open
`/files?file=…&revision=…&page=…`; details are in
[FILE-LIBRARY.md](../../backend/services/FILE-LIBRARY.md).

The administrator-only System administration entry appears once in the sidebar.
The top header retains language selection and a personal account menu; logout is
inside the account menu without a divider/border. The Chat page is loaded directly
with the workbench shell and retained across other pages, avoiding a top-left
loading label and preserving the current draft and references.

### Shared sidebar and optional chat folders

The workbench shell owns navigation across Chat, Upload data (`/upload`), Data repository (`/datasets`), File library, Tools and
Assistant abilities. Chat remains mounted across these pages to preserve drafts,
references and scroll. The ability page merges Skill library and Connectors, and
returns a selected skill to the retained chat without submitting a message.
`chat_folders` and the conversation's `folder_id`/`pinned` fields belong to the current
schema. `/chat-navigation` lists owner-only
folders/chats using bounded keyset pages; search crosses folders and returns folder
names. Rename/move/pin never alters workspace scope or conversation context.
Deleting a folder atomically clears its conversations' folder IDs and preserves
messages, files and linked research. Folder controls support desktop drag/drop and
mobile menu actions. Confirming conversation deletion closes the dialog and removes the row immediately. A failed DELETE restores that row with a localized retry message; concurrent deletions and late list responses do not restore successfully deleted rows. Deleting the active thread opens an empty chat.

Data pages use layout skeletons while authentication, page code or data is loading. Sidebar hover/focus preloads their page modules. Chat stays mounted when navigating away, preserving the draft and references.

Chat is the primary research entry point. The normal streaming LLM response decides
whether a clearly requested task warrants autonomous execution; a validated
`NAVIGATE` research decision with `execute:true` creates a durable linked task.
Discussion-only `/ask`, read-only mode and incomplete decisions cannot trigger
execution. Retrying a failed answer may complete its research handoff. Every answer
variant uses the original answer ID as its durable request identity: retries create
at most one research task and reattach its receipt even if the new reply is prose-only.
Historical cards never execute on mount.
`/experiment`, `/literature`, `/analyze`, `/report` and installed scientific skills
provide explicit selection. The 自主探索 quick action prefills an editable brief
(question, inputs, work, deliverables, limits) and selects the research skill.
Research shortcuts submit their first turn to Chat with `research_brief=true`;
the server prohibits launching on that turn, including retries of that reply.
Chat clarifies the request and offers confirmation/revision options. A subsequent
confirmed handoff uses the effort, download permission and advanced options saved
with the brief. Selecting a shortcut/skill alone never starts execution.
The composer uses the shared Select/Checkbox and server-owned effort defaults.

`auto_research_sessions.chat_conversation_id` is the business Chat link;
`conversation_id` remains the native OpenCode identity. A unique `chat_request_id`
makes creation retries idempotent. The ResearchThread uses the existing durable
commands, continuation, recovery and GPU scheduling. Only the active conversation
opens a research event stream; the history sidebar obtains statuses in one bounded
batch request every eight seconds while visible. The details panel loads plans,
results and files on demand. Data Repo supports referencing a dataset back into Chat.

`research_handoff` SSE events persist in message artifacts and drive a compact status
card: preparing → submitting → accepted, or a retained failure with its cause. The
accepted card links to the task and uses the existing conversation research state for
live status. An interrupted stream stops its spinner and offers retry guidance. Raw
NAVIGATE payloads stay buffered until validated.
The task detail route uses the shared Chat navigation, with a direct return link to
its associated conversation. The separate research-session sidebar/list is removed;
the adaptive task plan, current recorded work, results and artifacts remain in the task view.
Opening/switching Chat starts at its latest message. A visible return-to-latest
button floats over the message pane when the reader scrolls up; ResizeObserver
follows growing messages/research cards only while the reader is following the end.
The active research status, task selector, details toggle and **Expand details**
link live in Chat's fixed toolbar, outside the scrolling transcript. The inspector
uses shared surface tokens, Buttons and the segmented control; its close/Escape
action restores toolbar focus without scrolling. File previews and the research
inspector are mutually exclusive. Mobile keeps the same actions in a compact
two-row toolbar, with an overlaid details panel.

### Customizable skill preload and personal connectors

The Chat sidebar exposes Skills and Connectors. `CapabilityLibrary` offers Added,
Discover, Created by me, and an administrator-only All users view. Built-in skills
(32 visible PathLab/Nature/Humanizer entries) and the two built-in connectors are
seeded during fresh database initialization. Metadata and introductions
retain English/Simplified/Traditional Chinese translations.

`/capabilities` manages user definitions and personal installations. Ordinary users
edit only their own definitions; public definitions are discoverable/installable,
while private definitions are visible only to their owner and administrators.
Unpublishing or deleting immediately revokes other users' future loads/calls.
Editing uses a revision conflict check. Lists are 20-item keyset pages; search is
debounced/cancellable and bodies/resources load only on demand. Users may create
200 definitions. Skill import accepts Markdown or a single-entry ZIP/.skill package
(16 MiB compressed, existing bounded archive validation). Packages are copied into
durable library storage and later into research snapshots when needed.

Every turn preloads up to 64 enabled skill names/descriptions. The same LLM semantically chooses
`LOAD_SKILL` to read relevant instructions; it can search further enabled skills and
load bounded package resources. Explicit “Use in Chat” or `/` selection immediately
loads the selected instructions. No keyword router decides which custom skill runs.
Each load rechecks access and activation. Up to eight skills used in a Chat turn can
be carried into an autonomous handoff as validated skill snapshots. Disabled skills
leave both the preload catalog and slash search. Skill instructions never expand
account/workspace permissions.

User-created skills are editable packages. The detail
screen includes a paginated/searchable file browser and owner/admin file management:
create/edit UTF-8 text (Python, JS, JSON, YAML, HTML, templates, references), preserve
script executable flags, upload/replace/download arbitrary binary assets, delete
resources, or replace the complete ZIP/`.skill` package. A Markdown entrypoint still
describes when and how the package is used. Text editing is bounded to 256 KiB;
each uploaded file/archive to 16 MiB, with the shared 4096-file/128 MiB expanded cap.
All file operations recheck visibility/ownership, validate paths and reject stale
revisions. Publication writes an immutable archive before switching its database
pointer; failed writes leave the prior package intact. Entry instructions and the
package entrypoint are updated together. Readers take short shared locks, and task
creation snapshots the entire package, including scripts, executable flags and
binary resources. Later library edits do not change an already-created task.

Custom connectors use MCP Streamable HTTP over public HTTPS, with optional personal
Bearer credentials. Public sharing exposes the definition, never another user's
token. Credentials are encrypted using a key derived from the deployment's stable
JWT secret; API responses expose only whether the current user has configured one.
Test connection performs initialize → initialized → tools/list, accepting at most
100 tools/48k catalog characters. Chat uses LOAD_CONNECTOR then CONNECTOR_TOOL;
research exposes equivalent connector adapters. JSON/SSE responses are bounded to
1 MiB, tool arguments to 32 KiB, model evidence to 24k characters, and requests to
25 seconds with eight slots. Calls recheck activation, current definition revision,
tool schema and read-only rules. No credentials are embedded in prompts or shared
definitions. OAuth and local stdio command installation are not part of this API.

Authenticated guests can enter Chat and use personal skills. The model receives an
explicit account capability policy and explains GPU/autonomous permission failures
in the active language. Server streaming hides execution cards and replaces an
unauthorized proposed action with a friendly permission response; research dispatch
is blocked before creation and the execution APIs retain their own permission checks.
Guest/read-only connector calls accept only tools annotated readOnlyHint=true.

Interaction references: [WorkBuddy Skills](https://www.workbuddy.ai/docs/zh/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market)
and [Connectors](https://www.workbuddy.ai/docs/zh/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Connector).

### Resource lookup limits

- `GET /workbench/commands`: up to 20 metadata entries, cursor paging; no skill
  contents or package traversal while typing.
  Names and introductions for every built-in skill (including Nature Skills) use
  `language=en-US|zh-CN|zh-HK`; search matches all three languages and stable IDs.
- `GET /workbench/resources`: up to 20 scoped resources, keyset pagination, no
  exact total. Files within a dataset require its ID. Name-prefix ranges and sort
  order share a PostgreSQL `lower(name) COLLATE "C"` index, including generic
  prepared query plans. SQL timeout is 800ms; request admission is bounded.
- `POST /workbench/resolve`: authorize at most 16 typed references per turn.
  A dataset remains one reference regardless of file count. Selected file previews
  have a shared 16k-character context budget; filenames never expand into prompts.
- `POST /workbench/uploads`: persistent reference uploads, 32 MiB maximum.
- Research file catalogs use 200-row batches, shallow directory indexing, a 10k
  entry/20-second indexing budget, and partial-index status. Exact relative-path
  references remain available for files outside a partial index.
- Frontend completion waits 180ms, pauses during IME composition, aborts superseded
  requests, ignores late results and retains one result page. Research stream memory
  is bounded to 250 events; native message updates coalesce and old activity is paged.

### Conversation files and previews

Lightweight text deliverables use `[DELIVER_FILE]{"filename":"report.md","content":"..."}[/DELIVER_FILE]`.
The server validates filename/format/size, saves the bytes and file catalog entry,
then emits an authoritative `FILE_DELIVERY` receipt. Model-authored file/research
receipts are discarded. Up to four UTF-8 files per turn, 250,000 characters each,
1 MiB combined. Payloads stay hidden during streaming; incomplete/cancelled or
read-only deliveries never become download cards. Ordinary replies stay inline.
Binary deliverables and computations use the autonomous runtime. Compact activity
indicators reflect context loading, actual searches/reads, writing and saving;
reasoning text is not displayed. Missing search/read tool closing tags are repaired
only for complete JSON; malformed envelopes get one correction attempt. Empty
upstream completions get one retry with an explicit continuation/handoff instruction,
without replaying completed tool operations. Tool envelopes are filtered incrementally
at every chunk boundary, even after prose; all tool-step prose remains visible and is
persisted. Reference cleanup preserves the existing answer. Necessary canonical
updates (normalized configuration or server-owned file/research receipt) use one
`content_replace` snapshot, applied atomically by the client.

Chat's activity disclosure describes concrete public work from the latest twelve
events: the search topic, article being read, or file being delivered. The server
emits a bounded `subject` only from these operations' public fields, dropping URLs,
internal paths and technical payloads. Preparation and tool dispatch are not shown
as workflow steps; raw details and reasoning never enter the activity display.
The collapsed row names the current action; expanded rows use natural-language
sentences with actual completion/failure/interruption states. Identical actions
are grouped while distinct searches and articles remain separate. This uses the
existing SSE/persistence path and a memoized client projection, with no extra
model/API call, timer or exit-animation wait. Response tokens do not recompute
unchanged activity.

Autonomous research uses its own public event projection (`engine/activity.py`)
and the shared `ResearchTimeline` in Chat and full task details. Raw tool names,
inputs, outputs and internal setup steps are not activity rows. Public descriptions
travel in the existing tool call's `activity` field in the session language, with
localized action/status labels. The current-action header stays one line and native
work shows at most one public topic; child task titles are never concatenated.

A completed research decision ends Chat's tool loop before any further skill load.
Selected-direction follow-ups that delegate investigation and a report hand off with
verified resource references; feasibility checks belong in the research task. Loaded
skills do not make sandbox-only tools available in Chat. Failed/truncated generations
retain their prose and failed activity status and cannot dispatch research or files.

`ConversationFiles` provides a resizable right-side file browser with up to eight
open tabs, downloads, references and full-screen viewing. Moving between docked
and full-screen views retains the same preview DOM, media URL and scroll position.
Message attachments, generated artifact buttons and local research links open it
directly. Ordinary image/table attachments are also persisted when sent.

`GET /workbench/conversations/{id}/files` lists uploads or all indexed files from
that conversation's research tasks. History rows expose a lazy, collapsible list;
only one history file section is open at a time, with 20-item cursor pagination,
previous/next buttons and scoped downloads. History availability is batched with
research statuses using indexed existence queries, not per-row requests or counts.
Opening another conversation's file switches to that conversation and its workspace.

`GET /workbench/files/{id}` returns typed, bounded previews; `/content` streams
authorized image/audio/video media or original downloads. Text/Markdown/code/HTML
previews are limited to 1 MiB, tables to 200 rows × 40 columns, media to 32 MiB.
XLSX/XLSM worksheets can be selected. PDF, PPT/PPTX/ODP and DOC/DOCX/ODT/RTF use
the shared page viewer with page navigation, zoom and fit-to-page. Office files
convert through LibreOffice (host or the installed research sandbox), with an
isolated profile and 45-second deadline. PDF/Office previews are capped at 300 pages;
page images are rendered on demand at a bounded resolution. HTML stays sandboxed.

Uploaded/published documents schedule background conversion and first-page rendering
in a single-worker queue (eight pending maximum). Preview caches live beside the
immutable source version and are removed with it. Identical byte publication keeps
the existing mtime/cache. Cached metadata and pages bypass PDF parsing; cold Office
conversions have separate admission slots from lightweight previews. Concurrent
requests share the converted PDF rather than launching duplicate Office processes.

Research file links request the authorized resource and its preview in one response.
The descriptor includes the first page when its PNG fits within 1 MiB; subsequent
pages use `/workbench/files/{id}/pages/{page}?revision=...`, rechecking access and
current source version. After first paint the client prefetches only the next page
and keeps at most three page images. Closing/changing the preview aborts stale
requests and releases object URLs; fullscreen keeps the same viewer state. Full
research task details use this same typed viewer, including links in report prose.
Cancelling HTTP requests never releases a parser slot before its thread completes.

The conversation/name/ID range index supports file lists without recursive disk scans.

### Analysis and experiments

The same model response resolves goals into `taskKind` (`analysis`, `experiment` or `document`), `reportPolicy` and `researchStandard`. Users need not select a mode. `set_task_scope` records these with `current_goal`, including later goal changes.
Analysis uses existing inputs and `submit_computation`; it does not consume training
attempts. Summary-only tasks cannot launch the article writer. Experiment work can
train/compare models and follows its report policy. No user-text keyword classifier
decides execution.

Standard metrics/charts retain their existing analysis cards. For custom work,
`publish_analysis` validates a saved `pathlab-analysis-v1` JSON result with executed
source, arbitrary named metrics/units/intervals, tables and generated figures.
`GET /research/sessions/{id}/analysis/{analysis_id}` rechecks ownership and validates
the file before display. ROC, confusion matrix, KM and loss curves reuse the existing
chart components; novel plots use real generated images. The result selector loads
one view at a time, preserving raw custom metric units rather than guessing percentages.
Limits: 20 views/session, 2 MiB/view, 100 metrics, 8 tables (200×30), 12 figures and
5,000 points per series. Invalid/nonfinite/mismatched arrays cannot reach renderers.

Explicit `@` references and model-selected **verified** `references` in a research
decision are reauthorized together. Worker-side task export uses 500-row keyset
batches and a 256 MiB maximum to produce a read-only prediction JSONL; it retains
split, case ID, available demographics and task-specific outputs. Reference lookup
and autocomplete do not perform that export. Existing research files are mounted
read-only; source datasets remain scoped. Missing inputs are clarified in everyday
language rather than silently substituting metrics or retraining a model.

### Article reading, downloads and stable citations

`READ_ARTICLE` has `action=read|download|read_download` and an optional focused
`query`. Download-only copies verified original PDF bytes into conversation files;
it does not parse or summarize. Reading extracts evidence and lets the current Chat
generation answer once in the requested language/format. Autonomous `read_paper`
uses the same reader. Network requests validate redirects, bound response bytes,
share a total download deadline, follow publisher PDF metadata, and race the two
open-access providers with cancellation of the losing request. Arbitrary cited or
supplemental PDF links are not treated as the requested paper.

PDF requests honor a publisher's `Retry-After` on HTTP 429/503 once when the
requested delay is at most ten seconds, within the existing total deadline.
Persistent rate limiting does not trigger another landing-page read. bioRxiv and
medRxiv PDF URLs retain the requested version; DOI provider lookups strip the
version and representation suffix rather than querying an invalid registry DOI.

PDFs have one CPU pipeline (`backend/services/pdf_cpu.py`): native pages retain
their text; scanned/garbled pages get one PP-OCRv6-small ONNX CPU pass, then the same
PyMuPDF layout extraction. Ruled scan-table cells are reconstructed from detected
grid lines and the same OCR bounding boxes, with no generated values. There is no Marker parser,
fast/slow compatibility layer, background reparse, or additional summary LLM call.
Parser subprocesses receive `CUDA_VISIBLE_DEVICES=''` and two CPU threads. There
are two parse slots, at most four waiting requests, a 10-second queue bound, a 90-second parser timeout and a
150-second overall article-read deadline; cancellation kills the parser process group.
The interactive limits are 50 MiB and 300 pages; OCR cost can reach the deadline
earlier. The pinned OCR model supports Simplified/Traditional Chinese, English and
its documented multilingual vocabulary; unsupported/unreadable
content returns an explicit error. HTML and abstracts are labelled as such.

Each conversation persists a bounded registry of up to 64 article sources in hidden
message metadata. Atomic registration locks the conversation: repeated URLs and
arXiv abs/pdf/html variants reuse the same source ID and ordinal, while explicit
arXiv versions remain distinct. Recent cited pages are retained for follow-up
retrieval, including Chinese questions about English articles. The server owns the
`source_index`, `source_id` and page snippets in reference receipts. The UI resolves
IDs before indices and never falls back to the first article when a source/page is
unknown. Reloading and unrelated turns do not renumber existing sources.

The OCR detector uses OpenCV float32 normalization and a 960-pixel bound; recognition retains higher-resolution crops. Weights are hash-pinned and provisioned by `deploy/prepare-ocr.py`. Requests do not download weights or try another OCR backend. Check original figures when handwriting, formulas or complex tables are uncertain.

Design references: [PP-OCRv6](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/algorithm/PP-OCRv6/PP-OCRv6.en.md),
[RapidOCR](https://github.com/RapidAI/RapidOCR),
[PyMuPDF4LLM](https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/),
[selective OCR](https://pymupdf.readthedocs.io/en/latest/ocr/index.html), and
[Docling native/CPU options](https://docling-project.github.io/docling/usage/advanced_options/).
The tested runtime pins PyMuPDF, PyMuPDF4LLM and Layout to 1.27.2.3; newer documented
APIs are not assumed to exist in this installation.

### Concurrency and deletion

Global research concurrency is controlled by Settings. Environment limits:
`PATHLAB_RESEARCH_MAX_PENDING_PER_USER=8`,
`PATHLAB_RESEARCH_MAX_PENDING=100`. Creation/continuation capacity checks use a
PostgreSQL advisory transaction lock. A session accepts at most 32 pending instructions.

Deleting a conversation commits a `storage_tasks` entry (`chat_delete`), marks research jobs for cancellation and revokes associated file access. The HTTP response returns `status=deleted` after commit. A retained asynchronous task promptly broadcasts cancellation and stops owned local processes; the persisted record remains authoritative if Gateway exits.

ResearchWorker stops agents, compute jobs and article writers before deleting experiment files, registered models, reports, conversation-owned uploads, research feature copies and associated records. It saves a cleanup manifest before removing bytes. Source datasets and independently referenced library files remain independent resources. Cleanup runs with concurrency two, retries failures after 30 seconds and survives restarts.

Internal cleanup records are excluded from the storage-task query before pagination and from the frontend progress list. They are retained for retry rather than expired with ordinary failed tasks. Dataset, slide and external-file deletions keep their progress and cancellation controls. A deleting conversation cannot execute new work or reappear in history.

### Migration

`backend/database/current_schema.py` initializes empty databases and validates the current version on existing ones. Completed migrations remain in `pathlab_schema_migrations`; their one-time scripts have been removed. Use a matching database snapshot and deploy frontend, Gateway, ResearchWorker and TaskWorker together.

Chat training and research GPU jobs share the resource estimator and TaskWorker
lease scheduler. Busy GPUs expose queue position and memory estimates rather than
starting duplicate work. Model choices use the actual supported task and validated
prediction contract; registered research classifiers, survival, detection and segmentation
adapters reuse standard inference/result paths. See [research](../../backend/autoresearch/README.md)
and [GPU scheduling](../../task_worker/GPU-SCHEDULING.md).

### Maintained verification

Backend suites include `test_chat_workbench.py`, `test_chat_scope_and_failures.py`, `test_chat_deletion.py`, `test_research_processes.py`, `test_file_library.py` and `test_pdf_cpu_acceptance.py`. Frontend suites cover the sidebar, handoff, references, file previews and background-task lifecycle. `test/browser/chat_deletion.py` checks immediate removal, concurrent rollback, stale lists, quiet cleanup and language changes against real components with isolated APIs. Run instructions are in [tests](../../../test/README.md).
