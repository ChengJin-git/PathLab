# PathLab Research with OpenCode V2

> PathLab v1.0.8 · Updated 2026-11-26

PathLab Research runs an autonomous OpenCode session inside Apptainer or Docker. The agent
uses the model configured in Settings, reads authorized Data Repo inputs,
uses PathLab's existing literature/data providers, writes experiment code, and
submits background experiments. The Research workbench shows messages, plans,
downloads, experiments, metrics, logs and deliverables.

## Runtime

```text
Web → Gateway → PostgreSQL commands/events → Research Worker
                                             └─ Apptainer / OpenCode V2
                                                  └─ PathLab MCP tools
                                                       └─ Redis → TaskWorker
                                                                    └─ Apptainer experiment
```

- `engine/worker.py`: independent supervisor, native conversation recovery,
  message reconciliation, native event subscription, commands and job wakeups.
- `engine/runtime.py`: Apptainer process groups, persistent OpenCode directories,
  session-specific environment, read-only input mounts.
- `engine/client.py`: OpenCode V2 HTTP API, authenticated with a per-session password.
  Startup verifies the PathLab MCP connection; the supervisor checks it every 30 seconds
  and reconnects failed discovery with bounded retries. Agent progression does not
  silently continue without its scheduling and decision tools. MCP discovery retries
  transient Gateway startup failures, reports JSON-RPC errors correctly, and never
  replays tool calls. An empty MCP resource catalog does not imply missing tools.
- `engine/tools.py`, `engine/mcp_stdio.py`: research capabilities exposed through MCP.
- `engine/pathtrove.py`: pinned PathTrove dataset-catalogue MCP server, data install and sandbox mount.
- `engine/datasets.py`: scoped Data Repo manifests and existing provider adapters.
- `engine/jobs.py`: source snapshots, durable jobs, progress, timeout, cancellation.
- `engine/registration.py`: persistent model and feature registration.
- `engine/store.py`: database state and monotonic per-session event sequences.
- `engine/scheduler.py`: independent research admission limit, FIFO queue, recovery
  cleanup and immediate queued-session controls.
- `../services/chat_deletion.py`: durable conversation deletion, process shutdown and file cleanup, executed by ResearchWorker.

`dataset/` (providers, downloads, registration) and `literature/` (paper search and SOTA lookup)
serve the engine's MCP tools; `domain/templates/` and `domain/skills/` are mounted read-only into
the sandbox as reference implementations and guidance. Public requests use the contract below.

Each session row keeps its last event number in `event_sequence`, so appending an event never
rewrites `recovery_metadata`. Research decisions store evidence hashes, not file contents. Long
experiments may not carry `CUDA_LAUNCH_BLOCKING`: it serializes every kernel and is accepted only
for debug runs with `timeout <= 1800` s.

Continuations reuse completed dataset manifests and selected-file input views, while access
is rechecked before the agent or a job runs. `prepare_dataset` explicitly refreshes an input;
missing prepared artifacts are rebuilt individually. Source parent resolution is cached within
one preparation, including per-file symlink targets. Preparation timeouts report the dataset,
phase and progress under `data_preparation`, rather than implying a model outage.

## Prerequisites and deployment

Installation is described in [docs/installation.md](../../../../docs/installation.md). To move a
verified environment to another server, see
[`deploy/guides/MIGRATION.md`](../../../deploy/guides/MIGRATION.md).

- OpenCode **V2**: `PATHLAB_OPENCODE_BIN`, else `opencode` on the backend PATH, else
  `~/.opencode/bin/opencode` (so a boot-time service with a minimal PATH still finds it).
  The release baseline is OpenCode **2.4.2**; `deploy/install-opencode.py` installs
  the pinned native binary with npm SHA-512 verification. Docker can be used instead of
  Apptainer with `PATHLAB_SANDBOX_BACKEND=docker` and an image built from `deploy/sandbox/Dockerfile`.
- Apptainer and the CUDA/PyTorch/scientific-tools image. From `app/` run
  `"$PATHLAB_PYTHON" deploy/build-skills-runtime.py --rebuild-base`.
  The builder uses `deploy/build-autoresearch-sandbox.sh` for the ML layer and publishes
  to `~/.local/share/PathLab/sandbox/pathlab-sandbox.sif` (or `XDG_DATA_HOME`) after verification.
- Configure the model endpoint, API key and model in PathLab Settings.
- PostgreSQL and Redis, as used by the rest of PathLab.

The host OpenCode executable is mounted into the image read-only. It is not
installed on each run. The MCP transport uses Python's standard library and
works with the existing image.

The base sandbox includes `tabulate==0.9.0` and verifies `DataFrame.to_markdown()`.
To update an existing verified image without re-resolving the ML stack, build
`runtime/containers/report-dependencies.def` with `--build-arg base_image=/path/to/current.sif`
into a separate SIF, run its tests, then atomically replace the configured image.
Previously exported migration bundles retain their original image; apply this recipe
after restoring them or export a new verified bundle.

For task-specific missing packages, the MCP `install_dependencies` tool creates a
session `.venv --system-site-packages` inside Apptainer, installs ordinary package
requirements, and verifies the required import list. `python`/`python3` jobs use it
automatically; the environment is not copied into every frozen source snapshot.
The tool has a 150-second installation bound within the MCP transport timeout.
Jobs read previous run outputs through `PATHLAB_WORKSPACE` and write only into
`OUTPUT_DIR`; the agent updates `findings.md` after the computation returns.

`server/main.py` starts Gateway, AI, Preprocessing, TaskWorker and ResearchWorker.
For a fixed-port deployment use `deploy/start.sh`. Deploy the frontend and backend
together. Hot-reload supports `task-worker` and `research-worker` in addition to
the HTTP services; an already running unified `main.py` deployment should be
restarted through its owning launcher when upgrading the process topology.

Environment settings:

| Setting | Purpose |
| --- | --- |
| `PATHLAB_OPENCODE_BIN` | OpenCode V2 executable |
| `APPTAINER_BIN` | Apptainer executable |
| `AUTORESEARCH_SANDBOX_IMAGE` | Existing sandbox image path |
| `GATEWAY_SERVICE_URL` | Gateway reachable from the sandbox, default `http://127.0.0.1:6100` |
| `PATHLAB_UPLOADS_DIR` | Existing storage root; otherwise resolved from Settings |
| `HF_HOME`, `PATHLAB_CKPT_DIR` | Existing model caches |
| `AUTORESEARCH_RAG_EMBEDDING_*` | Optional retained dense literature retrieval |
| `PATHLAB_RESEARCH_POLISH_MODEL` | Lightweight brief editor model (default `gpt-6-luna`), using the saved API endpoint/key |

The model resolver reads saved Settings in each worker. API keys are injected
through per-process environment variables and are not persisted in public session
metadata. OpenRouter and OpenAI-compatible endpoints, including local vLLM, are
supported. Local vLLM selection uses availability probing and remote fallback.

## API

### Scientific paper loop

Scientific tasks (`research_standard=scientific`) aim at a result that clears the publication bar
the user named. The skill (`engine/research-skill/SKILL.md`, references loaded on demand) asks for
at least three paper-level pitches before the protocol; the service enforces the loop:

- `record_study_protocol` requires the pitches as `directions`, verified full dataset sizes in
  `data`, `evaluation.minimum_gain` no smaller than `evaluation.resolution` (what one evaluation
  unit moves the metric), `evaluation.best_possible` (the metric's best value, or null), a
  `premise` on every pitch (the mechanism step and metric measuring the effect it exploits, or
  null), a closest baseline with a published `reference` result, a required
  closest-baseline validation step, and at least 3 repeats on validation method and closest-baseline steps.
  Validation steps must use the full declared data; confirmation evaluates the full set. After 3
  pitches are ruled out under unchanged evaluation, data and baselines, new pitches need a new frame.
- `submit_experiment` accepts at most three non-debug exploration runs per pitch since its last
  full-scale run, and full-scale method runs only after a completed run of a closest baseline (on
  the study data or the reference's own benchmark) reproduces its published reference within 5%.
  Method, ablation and replication runs then also need a frame that can show `minimum_gain`: the
  closest baseline's repeated mean at least 3 × `minimum_gain` from `best_possible`, its seed spread
  resolvable with at most 10 repeats per arm (and the step planning that many), and, for a pitch
  with a premise, a measured premise effect of at least `minimum_gain`.
- `record_research_decision` rules a direction out only after 3 tried candidates in it.
- `record_study_review` reports `publication_gain` over independent repeats (mean gain, standard
  error, missing reasons); `write` requires `bar_met`: 3 repeats per arm, gain at least
  `minimum_gain` and above twice its standard error.
- `set_task_scope` keeps `research_standard=scientific` once set: sub-steps change `task_kind` and
  `current_goal`; lowering the standard needs a `user_request` quote from the user's instructions.
- `finish_research` with `partial`/`no_result` on a scientific task requires a `user_stop` quote
  found verbatim in the user's own instructions. When a frame is exhausted the agent changes data,
  endpoint or evaluation itself within the user's question; `request_help(reason="direction")` is
  accepted only after two frames are exhausted.
- Scientific effort presets span days (`engine/effort.py`); budget walls pause through
  `request_help(reason="budget")` rather than ending the study.

### Built-in scientific skills

The sandbox exposes 36 skill entries: `pathlab-research`, six `pathlab-*` pathology
task skills, all 23 functional Nature Skills plus `nature-shared`, English
`humanizer` / Chinese `humanizer-zh`, and the three PathTrove skills. The complete, pinned upstream packages include
their scripts, references, manifests, assets and licenses. See
[`skill_library/README.md`](skill_library/README.md) and `sources.lock.json` for provenance.
No runtime download or upstream auto-update hook is needed. Skill files are mounted
read-only at `/opt/pathlab/skill-library` and discovered via the OpenCode V2 `skills`
sources; optional external services still require their own runtime configuration.

OpenCode gets two MCP servers: `pathlab` (PathLab tools) and `pathtrove`, the pinned PathTrove
catalogue of public pathology datasets, challenges and benchmarks. The agent is told to choose
datasets and benchmarks with it before `acquire_dataset`. Its data package is pinned by SHA-256,
installed by `deploy/start.sh` and mounted read-only; see
[`skill_library/README.md`](skill_library/README.md).
The skills-runtime image recipe includes scientific Python/R, PDF/Word/PPT conversion, Node,
Chromium, XeLaTeX and OCR. See
[`runtime/containers/SKILLS-RUNTIME.md`](runtime/containers/SKILLS-RUNTIME.md) for
installed tools, reproducible builds and the optional credential configuration.

`GET /research/configuration` returns the built-in catalog to authorized users.
The core workflow loads the skills needed for each phase. User-imported Markdown skills retain their
separate `user-skill-N` IDs. Data acquisition uses existing PathLab authorized data
tools, and citations remain verified independently of writing style guidance.

Background article generation loads `nature-writing` manifest fragments for each
section, then `nature-polishing` and the language-appropriate Humanizer at final
review. The report-page polishing endpoint uses the same skill context and rejects
changes to numeric values, citation IDs and protected document syntax. Selected
fragment paths and SHA-256 are retained in generation progress. Chinese prose stays
Chinese unless translation was explicitly requested; public template labels remain
conference / journal (会议模板 / 期刊模板).

### Editable reports

Model experiments whose effective report policy requires a manuscript finish with an editable conference/journal manuscript, shared with
the manual result-to-report editor at `/reports`. Agents checkpoint sections with
`save_report_draft` and request the shared LLM writer through `generate_article`.
Verified citations and measured Nature-style figures are included. Time/attempt overruns
enter a bounded checkpoint window and then the existing recoverable budget pause;
unfinished manuscripts remain drafts. See [report workflow](../services/REPORTS.md)
for APIs, deployment and continuation semantics. Data-only tasks do not need reports.

`task_kind`, `report_policy`, `research_standard` and `current_goal` record the agent's working interpretation. Live context
keeps `original_request`, `working_goal` and persisted `recent_instructions` distinct; agent summaries do not create user requirements. The agent records its
interpretation with `set_task_scope`: pure analysis uses existing data/predictions and
`submit_computation`, without consuming experiment attempts or starting an unsolicited
paper. Explicit summary-only experiments can finish with measured findings. Complex
analysis publishes saved `pathlab-analysis-v1` results through `publish_analysis`:
custom metric names, units and intervals, tables, generated figures and reusable ROC,
confusion matrix, KM and loss curves appear in Chat's result panel. The result schema,
size bounds, reference snapshots and API are documented in
[Chat workbench](../../gateway/chat/README.md#analysis-and-experiments).

`@` can reference an authorized conversation. Autocomplete queries only titles; selected
conversations supply bounded, attributed excerpts of the first user goal, latest user
corrections, recent turns and lexical matches to the current question, plus linked research
findings. Inactive/regenerated-away replies and deleting conversations are excluded. Each
conversation is capped at 10,000 characters, multiple conversations share 14,000, and the
combined Chat reference context is capped at 16,000. These are excerpts, not a complete
transcript or generated factual summary; source message IDs and truncation are explicit.
Research receives a bounded read-only JSON snapshot and rechecks source access on resume.
Conversation references also attach directly linked, authorized research file views. The
views retain report/code/result paths, exclude runtime configuration, hidden directories
and symlinks, and are mounted read-only under `/research-data/references/research-<id>`.
They do not inherit the source research's data mounts or recursively expand its references.
Users see their own conversations/research; administrators can access all, still subject to
the chosen workspace scope. Reauthorization applies before every resumed agent/job.

The research toolbar, composer and individual history updates offer **Ask without
interrupting** (随时问问). Questions open a separate, non-modal read-only panel backed by
`POST /workbench/research/{id}/questions`. The endpoint only reads authorized saved events
and job metrics and calls the model without tools. It never changes research state, budget,
commands, jobs or Chat history. Closing the panel cancels only the question request; its
temporary discussion stays separate from the active research conversation.

Research execution requires an administrator or pathologist. Guests can use Chat
and their personal skill library; GPU/autonomous requests receive a friendly permission
response and no job is submitted. Settings and queue configuration are administrator-only.
Workspace policies and account GPU capability apply to execution. Internal MCP
requests use a session-scoped token. Public SSE/archive tokens recheck the current role.

### Research admission and workbench

Long histories load in bounded time. `store.activity` pages logical activity from a per-session
in-process index extended only with events after its last sequence (events are append-only and
sequenced under the session row lock; a replaced history is detected and rebuilt), and the Gateway
warms recently active sessions at startup. Session detail carries metric previews
(`engine/metric_preview.py`, with `metrics_total`); the full metrics of a run are read from
`GET /research/sessions/{id}/runs/{run_id}/metrics` when its details are opened. The workbench polls
the detail only while a session is live; the event stream carries live activity.

Settings → Tasks includes a **Maximum concurrent AutoResearch sessions** slider
(1 to 10, default 2). `/api/queue/config` persists `max_autoresearch_concurrent`
independently of the GPU queue's `max_concurrent`. Waiting-for-experiment agents
retain their slot. Excess sessions show a busy notice and queue position, and start
automatically when capacity is available. Pause/stop also work when every slot is full.
All users share one strict submission-order FIFO. There is no per-user admission
bypass; ties use the database sequence. Explicit continuation joins the tail, while
system restart/capacity suspension retains the existing submission position. Queue
positions and Worker admission use the same ordering expression.
Lowering the limit saves excess OpenCode sessions and requeues them; submitted GPU
experiments continue independently. Queue time does not consume their research budget.

The workbench follows the task's actual plan rather than assuming an experimental
workflow. A compact current-work line sits with the task title/status, and the
collapsible task plan shows recorded steps, completion, parallel active steps and
their actual state. Literature reviews, data analysis, document delivery and model
experiments therefore share the same surface without a fixed four-phase stepper.
Only relevant tabs appear: data when inputs/downloads exist, experiments when the
task actually uses them, and logs when jobs exist. Completed document/analysis
tasks offer a generic follow-up, without implied baseline or additional training
options. Stable step IDs preserve selection across plan updates; steps without
associated activity retain the full record rather than showing an empty timeline.
`update_plan` may still record phase, summaries and subtasks for the task itself.
Long elapsed time is displayed in hours/days with localized units.

Chat's normal model response decides whether a clear execution request needs
AutoResearch, without another classifier call. An explicit execution decision starts
a linked background task in the current conversation; an exploratory suggestion
selects the research skill in its composer. `/experiment` is the explicit shortcut.
The Chat sidebar shows running/queued research alongside conversation history.
At 24 visible messages or 24,000 characters, a local hint
offers a fresh conversation. Dismissal is remembered for that conversation in the tab.

### Recoverable work and Chat continuity

Research follows the actual requested scope: a download/registration, metrics-only
calculation, code repair or data inspection can complete without training. Final
outcomes distinguish `completed`, `partial`, and `no_result`; evidence and limitations
are retained rather than forcing a successful research conclusion.

Agents diagnose, repair and verify ordinary code, dependency, path, tool-argument,
resource-setting and transient service failures themselves. `request_help` is a last
resort: it requires actual `attempts` (action/result), `why_user`, and a `blocker` of
`external_dependency` or `repair_exhausted`, alongside reason/summary/next_steps.
Exhausted repairs require distinct approaches; a pending retry must settle first.
Referenced failed `job_ids` must belong to this session and postdate its latest
continuation. Old failure logs do not establish a current outage. Genuine access,
data, budget or user-only decisions can be escalated after checking the dependency.
Native turn failures get bounded corrective continuations; non-budget manuscript
failures return to the agent for diagnosis/resumption rather than immediately blocking.
The
worker saves a `blocked` session and releases its agent slot. Existing independent
jobs can finish. A recovery panel explains the issue and offers data registration,
attaching/replacing authorized datasets, revision-checked source editing, additional
experiment attempts and a free-text instruction. Continue atomically queues the
instruction and resumes the same native conversation. Only paused/recoverable workspace
source files can be edited; datasets, run snapshots and runtime configuration cannot.

Blocked tasks use the general heading **助手需要进一步协助** (The assistant needs
further assistance), with the specific data/access/code/service/budget/decision
reason below it. Chat shows a neutral saved-progress card linking to the assistance
panel; the panel retains the cause, suggested steps, optional guidance and Continue
action. Extra data/code/budget controls are disclosed as needed. A service timeout
does not imply the user must upload new data or purchase more experiment attempts.

### Input preparation performance

`engine/dataset_files.py` maintains request-local directory inventories. Source label
directories and extractor/parameter directories are scanned once per preparation,
not once per slide. The request-local lifetime picks up newly created/deleted files
on the next preparation, preserves registered-feature precedence, original filename
aliases, labels, case IDs and existing splits. A per-session/dataset lock prevents
overlapping builds; cooperative cancellation/deadline checks stop the scan and leave
the last completed manifest intact. Manifest/CSV writes use temporary files and
atomic replacement. The 120-second preparation deadline precedes the 180-second MCP
transport deadline and reports a storage/preparation error rather than a bare timeout.

Preparation reads the shared `FeatureArtifact` inventory as well as registered source metadata. Existing features can be reused without regional coordinates when the analysis accepts them. The viewer requires matching coordinates for regional retrieval and an explicit aligned text encoder for text localization. Historical assets with no recorded weights revision retain a null contract. See [feature artifacts](../services/FEATURE-ARTIFACTS.md).

Cross-filesystem inputs use private, selected-file-only hardlink views on the source
filesystem, mounted read-only with stable `/research-data` aliases. This avoids
thousands of per-file binds overflowing Apptainer's startup configuration. Sources
that prohibit hardlinks retain exact read-only binds. View locations are registered
in the session's private runtime directory and removed with conversation cleanup.
Startup failures include the current launch's bounded, credential-redacted log tail.

Chat's **Autonomous research** shortcut selects the skill in the current input box.
Research receives an authorized snapshot of recent active-variant conversation
(bounded to 24k characters) and typed resource references. There is no extra summarizer
model call. The new goal and later corrections take precedence over historical proposals.
During execution, the same composer can send durable instructions or switch to discussion;
plans, results and files appear in an optional details panel. The dedicated research
workbench remains available for professional recovery and source editing.
See [unified Chat](../../gateway/chat/README.md#unified-research-workbench) for
reference indexing, concurrency limits and cascading deletion.

Session status/phase/plan use the latest database snapshot plus only newer events.
Completed sessions show Saved, not Live, and their elapsed display stops advancing.
Supervisor prompts use OpenCode synthetic messages and are excluded from public event
content, including old native user messages; user instructions remain visible through
command events. Job summaries are readable cards with collapsed technical details.

Additional instructions use OpenCode steer delivery and include the current goal and remaining budget. The supervisor checks the main session, active descendants, pending inbox messages and location shell jobs before deciding the agent is idle. Recovery reports interrupted child work and preserves the native conversation. Repeated reads and ordinary prose alone do not reset the no-progress counter.

Tool liveness is separate from scientific progress. Scientific experiment context and job
completion notices include a short `strategy_checkpoint`: settled experiments, recent
repair/discard decisions, direction coverage and measured job durations. These are planning
signals, not a quality score or submission gate. Repeated local repairs prompt a comparison
of rival explanations and a bounded continue/pivot decision. Development reviews stay
concise; the full manuscript reviewer workflow is for pre-writing or explicit review requests.
Reuse unchanged validation receipts and profile preparation versus optimization before
scaling a slow pilot. Nested metrics, source snapshots and full artifact listings remain
accessible through job records/files rather than being repeated in every continuation.
`evidence_progress` tracks actual sample-count scales across candidate/direction changes;
repeated-scale windows prompt a scientific resource decision rather than another audit.
Counts are not summed into independent samples, and a confirmation stage name is not proof
of adequate precision. Updating the working goal retains the protocol for reconciliation
and invalidates its review; `protocol_needs_update` exposes the mismatch until re-registration.
`comparator_progress` exposes method trials preceding the current closest-method evidence.
It prompts early strong controls and contribution assessment, without declaring scientific
success or failure from an experiment count. Replication estimates variability; it cannot
substitute for novelty, an informative mechanism contrast or independent transfer evidence.
Stage allocations count submitted attempts, including failed/queued jobs, across revisions.
The scheduler protects later validation/confirmation attempts under the session lock.

Chat and task details share `ResearchTimeline`. Consecutive public actions are grouped
into a collapsed section with one fixed-height current-action label; user instructions,
findings and decisions remain separate. `engine/activity.py` projects SSE, snapshots
and paged history to the same public receipt schema. Internal tools, raw arguments,
outputs/errors, child IDs and shell state never enter the timeline payload. A native
work update carries at most one bounded public topic, not a growing list of child tasks.
Events merge by stable IDs; loading earlier pages and resuming preserve visible history.
Expanded activity renders twenty rows initially, with bounded incremental history.

Public research tools accept an optional `activity` description in the session output
language, alongside the existing invocation; it is removed before business adapters
run. The model writes concrete scientific actions rather than internal process names.
Raw English retrieval queries are not progress copy. Labels/statuses have English,
Simplified and Traditional Chinese translations; a UI language switch uses local
translated labels when a saved description is in another language. Runtime and
continuation instructions explicitly carry the output language into delegated tasks.
There is no extra model/translation request or progress polling.

### Scientific protocols and measured decisions

`set_task_scope` records `analysis | experiment | document`, report policy, research standard and the current goal. Standard analysis or document work can finish with its requested calculations or files. Original method/discovery work uses `research_standard=scientific`.

`get_study_schema` exposes exact protocol, decision, experiment-design and measurement schemas.
Protocols contain a valuable question, rival mechanisms, closest baselines, structured primary
evaluation and ordered exploration/validation/confirmation stages. Stages allocate attempts
and per-job time; each comparison declares sample units, input coverage, optimization and repeats. At least one
required method/mechanism comparison reaches validation or confirmation. Stage allocations
reserve future attempts; plans never increase authorization.

Steps bind explicitly to stages and directions; shared baselines can be direction-neutral.
Comparison fingerprints include the evaluation, inputs, step, target scale and its own
direction. Changing the selected direction, wording of the working goal or budget alone
does not invalidate unrelated measurements. Keep only active claim-critical steps required.

Scientific runs identify a candidate and an operation: draft, improve, debug, scale or replicate.
Parents are settled runs in the same session; failed or cancelled runs can be debug parents.
Improvements fork, repairs/scaling/repeats retain
the candidate. Lineage and stage reservations are checked atomically before job publication.
`study-result.json` contains actual unit/counts, independent replicate IDs, input coverage and
optimization details. The worker records it with the frozen run. Separate candidate IDs are
not pooled automatically. For equivalent repeats
of one current comparison, `record_replication_group` appends an immutable association
bound to full run hashes and method-equivalence evidence files. Each linked run must meet
the full sample target; repetitions are deduplicated, sample counts are never summed, and
different comparison fingerprints cannot mix. Context and final review use the same
association. Source changes invalidate linked evidence at review/writing. Historical
candidate IDs and operations remain intact; no data migration is needed.

Validation method comparisons
require the primary metric; baseline/sanity runs require their own finite measured metrics,
not a downstream method gain that cannot yet be computed.
Target-scale checks do not pool unlinked candidates, duplicate repeats or undersized cohorts.

After a run settles, `record_research_decision` separates action (keep/discard/repair/pivot),
assessment (supported/contradicted/inconclusive/invalid), scope (candidate/direction) and next
operation. Inconclusive evidence cannot discard an entire direction; direction conclusions need
measured target-scale evidence. Missing-input blockers assess the other declared directions.
`record_study_review` releases writing only with current, recorded evidence meeting required
sample/repeat targets. Coverage, optimization adequacy and scientific merit still require evidence
interpretation; declared counts are not independent scientific certification.

These checks establish provenance and comparison conditions. They do not certify novelty, clinical validity or publication readiness. Useful development experiments can proceed with explicitly limited claims; insufficient evidence or budget remains a recorded limitation or recoverable blocker.

### Improve an existing result

Completed sessions offer **Improve existing results** on every workbench tab. Select
the current findings or a completed experiment, describe the desired improvement,
and optionally add experiment attempts (up to 20 per continuation, 100 total).
`POST /sessions/{id}/continue` accepts `text`, `baseline_run_id` and
`additional_experiments`, as well as the recovery panel's dataset options.

Continuation atomically archives the previous report, resets completion flags,
queues the instruction and reuses the native conversation/workspace. The selected
run's configuration, metrics and read-only run path accompany the instruction.
New runs retain their own source snapshots; previous reports remain accessible
under Findings. Additional analysis/report work does not require experiment budget.
The existing time budget applies anew to the resumed round.

The product name is **自主探索 / 自主探索 / AutoResearch**. Chat card titles and
buttons are localized by the UI; model prompts localize prose and descriptions.
Pathologists see only their own sessions, admins see all, and guests have no access.

The new-session request editor offers **Polish** and **Undo polish**. Editing is
explicit and does not create a session or execute work. `POST /polish-goal` accepts
`question`, `language` (`en-US`, `zh-CN`, `zh-HK`) and an optional
`source_conversation_id`; the server checks conversation ownership before loading
context. Omitting the source ID excludes chat history. The editor preserves scope,
constraints and unknowns rather than inventing a protocol. The response contains
only `question`; provider details are not exposed. Concurrent user edits take
precedence over a late editing result, and failures retain the original text.

Creation uses a **Low / Medium / High research effort** segmented control (default
Medium), with the shared system checkbox for public data access. Server-owned
ceilings are Low: 3 attempts / 1 hour; Medium: 8 / 4 hours; High: 20 / 12 hours.
These are limits, not required work; the agent should finish when the goal is met.
The creation API accepts `effort` instead of raw attempt/time budget fields.

**Advanced settings** is collapsed below the effort selector. Its `advanced`
request object can override `max_experiments` (1 to 100) and `time_budget_seconds`
(360 to 259200), and attach up to 32 `skills` (`name`, `content`, optional
`source_url`, `package_id`, `entrypoint`). Switching effort resets only budget overrides. The preset values
are returned by `/configuration`, keeping their source of truth on the server.

`POST /skills/import` accepts public GitHub repository, directory, blob and raw
links, direct Markdown URLs and ZIP/.skill archives. GitHub imports preserve the
repository tree so references to sibling skill resources remain valid. Branches
are resolved to commits. `POST /skills/upload` accepts a directory (multipart
relative filenames), ZIP/.skill or standalone UTF-8 Markdown. The preview returns
entrypoints, a resource inventory and localized compatibility issue codes. A
marketing/login webpage is not silently interpreted as skill instructions.

Limits are 64 MiB download/upload, 128 MiB expanded, 16 MiB per file, 4,096 files,
128 discoverable entries and 32 selected skills. Archive paths, symlinks,
duplicates, expansion and every HTTP redirect are checked. User-owned previews
expire after 24 hours and are bounded to 20 pending packages; expired previews
are pruned on the next import. Session creation copies selected packages to
`.opencode/packages/<content-hash>` (at most 256 MiB total), with executable bits
and binary resources preserved. No network is needed to resume that session.
Generated `user-skill-N` wrappers point to the original resource base directory;
packages are mounted read-only in agents/jobs. Source snapshots refer to these
session-owned resources through `PATHLAB_WORKSPACE`; session/run downloads include
the imported trees for reproducibility. Imports never execute hooks,
install dependencies or replace the built-in workflow. Supporting tools/accounts
are checked against the actual sandbox; unresolved requirements remain explicit.

The creation request includes `language` (`en-US`, `zh-CN`, `zh-HK`) from the UI.
Agent messages, plans, findings and article generation follow that language unless
the user asks otherwise; imported source Markdown/code keep their original text.
Article section labels, captions and document labels are localized on publication.
References: [OpenCode V2 skills](https://opencode.ai/v2/docs/skills),
[Agent Skills specification](https://agentskills.io/specification).

Example request body for `POST /api/research/sessions`:

```json
{
  "question": "Compare two WSI baselines using the selected cohort",
  "dataset_ids": ["existing-data-repo-id"],
  "workspace_id": null,
  "effort": "medium",
  "allow_downloads": true
}
```

Creation returns immediately with a durable queued session. Data preparation and
agent startup happen in Research Worker.

The worker summarizes the full request into a localized task title before preparing
inputs: at most 24 characters for Chinese, or 64 characters / 8 words for English.
The title is persisted separately from the full goal and also names the native
OpenCode session. New linked conversations receive that title unless the user has
renamed them. Until generation completes, or if the provider fails, the UI shows a
short localized placeholder rather than copying the request into the title.

All endpoints in the following table are relative to `/api/research` through the
web proxy (`/research` on the Gateway, following the application's API-base convention).
Browser routes use `/autoresearch/new` and `/autoresearch/sessions/{id}`.

| Endpoint | Purpose |
| --- | --- |
| `GET /configuration` | Effective Settings model and execution capability |
| `GET /datasets?query=...` | Authorized Data Repo candidates |
| `GET /sessions`, `GET /sessions/{id}` | Session list and workbench data |
| `POST /sessions/{id}/messages` with `{ "text": "..." }` | Queue additional instructions |
| `POST /sessions/{id}/pause` | Stop agent progression; submitted jobs can finish |
| `POST /sessions/{id}/resume` | Resume the same native OpenCode conversation |
| `POST /sessions/{id}/continue` | Recover or improve saved results with instructions, baseline and budget |
| `POST /sessions/{id}/stop` | Interrupt the agent and cancel its queued/running jobs |
| `DELETE /sessions/{id}` | Commit deletion of the associated conversation; stop and clean linked work asynchronously |
| `GET /sessions/{id}/events?after=N` | SSE with database cursor replay |
| `GET /sessions/{id}/files?path=...` | Preview/download workspace artifacts |
| `GET /sessions/{id}/download` | Research archive |
| `GET /sessions/{id}/runs/{run_id}/download` | One experiment archive |

SSE/archive URLs use the existing scoped access-token endpoint. Session status includes
`preparing`, `queued`, `running`, `waiting`, `pausing`, `paused`, `stopping`, `interrupted`,
`blocked`, `failed` and `completed`. An agent turn ending is not research completion;
`finish_research` explicitly publishes the final result after background jobs end.

## Experiment contract

`submit_experiment` is for model training and method-comparison experiments.
`submit_computation` runs metrics-only calculations, data preparation and reporting
with the same sandbox/source snapshot contract, without an experiment row or an
experiment-attempt charge. Downloads and computations remain visible in session
activity/artifacts, not the experiment comparison/catalog. `register_model` requires
a completed experiment job plus explicit architecture and prediction metadata;
feature-input models also declare their extractor, while image adapters own preprocessing.
Registered tasks save `preprocessing_config.feature_extractor` and real job timing;
task list pagination and status totals exclude linked non-experiment research jobs.

The agent submits an argument array, name, device (`gpu` or `cpu`), timeout and
optional dataset/config metadata. Each run executes a source snapshot in a sibling
Apptainer process. The source/workspace and registered inputs are read-only during
execution; `OUTPUT_DIR` is writable.

GPU jobs require `resources`: operation, model, batch size and input dimensions;
custom code additionally supplies `peak_vram_mb`. Both research and Chat training
use `backend/common/gpu_resources.py` and the same TaskWorker GPU lease scheduler.
CPU-only jobs do not acquire GPU slots. Busy GPUs queue automatically; impossible
single-GPU requests receive an explicit size error. The user sees queue position
and memory estimates, and the agent is told to wait without duplicate submissions.
Idle GPU queue wait does not consume the research wall-clock budget. See
[GPU scheduling](../../task_worker/GPU-SCHEDULING.md) for estimation, fairness, telemetry and cancellation.

```python
import json, os
from pathlib import Path
output = Path(os.environ["OUTPUT_DIR"])
device = os.environ["PATHLAB_DEVICE"]  # cuda:0 or cpu
(output / "metrics.json").write_text(json.dumps({"test": {"auc": 0.82}}))
(output / "progress.json").write_text(json.dumps({"epoch": 2, "total_epochs": 10}))
```

Nested finite numeric metrics retain their names (`test.auc`). Logs, source,
execution metadata, metrics and models remain associated with the run ID.
Registering a model copies it to durable model storage. Automatic activation requires
either a validated native checkpoint or a task-aware `prediction` contract, with
custom Python code/resources saved alongside the model. Runtime input/output validation
and weight/adapter hashes are checked before reuse; unsupported formats fail registration.
Settings shows recorded metric groups (OOF/validation/holdout and patient/slide
granularity), shows concise active/inactive states, and offers model export. It does not relabel
holdout metrics as validation or imply that every custom checkpoint is inference-ready.

Input manifests expose original labels, patient/case IDs, source split assignments,
feature availability and container paths. Data files are represented by read-only
session input views; the agent cannot edit the original Data Repo files.

## Persistence and recovery

### Download registration metadata

`acquire_dataset.record` is validated before dispatch. Required source metadata
includes stable ID, display name, provider, source URL, access, organs, license,
one task type and asset types. `visibility` overrides the source-access default;
public sources initially default to public Data Repo visibility, gated/manual sources to
private. Re-import preserves current visibility unless explicitly overridden, checks
stable source identity and retains manually corrected fields. Unstated organs/license
must be `Unknown`, not guessed. Metadata survives
the download cache, preparation manifest, Dataset.acquisition_metadata, slice
associated_files and session input manifest. Dataset/source identity is independent
of its display name. Dataverse (including Harvard) resolves persistent identifiers
via the source API and preserves official title, description, license and checksums.

`annotations_file`, `annotation_columns`, `aggregation_level` and `splits_file`
declare actual labels/patient IDs/censoring/COCO annotations and official splits.
Survival and segmentation are not passed through a classification normalizer.
Case-level datasets do not inherit file-wise generated splits. Registration updates
statistics and returns visibility, organ, missing_metadata, metadata_complete,
training_ready and split_ready. Missing annotations or metadata remain explicit;
metadata-incomplete downloads cannot finish as a fully completed research task.

### Reusable model predictions

See [prediction contracts](../services/RESEARCH-PREDICTORS.md). Model registration requires a
task-aware prediction contract for custom models, supporting classification,
survival, detection and segmentation through one sandbox adapter boundary. Standard inference,
batch validation and model management use the connected model without a separate
"research artifact" workflow.

- `auto_research_sessions`, `auto_research_events`, `auto_research_experiments`:
  business metadata, commands, experiment records and event replay.
- `auto_research_jobs`: durable queued/running experiment and acquisition jobs.
  Fresh database initialization creates the current schema. Existing databases are version-checked without startup DDL or historical backfills.
- `<uploads>/autoresearch/autoresearch_sessions/session_<id>/`: source and artifacts.
- `<uploads>/autoresearch/runtime/<id>/`: private credentials, OpenCode state and
  session input views. This directory is outside downloadable workspace artifacts.
- Public downloads use durable provider caches and register through the existing
  Data Repo repository interfaces.

Research Worker restarts restore native conversations.
Database/Redis outages retry with backoff; a crashed runner retains its last active
budget checkpoint. The launcher restarts exited queue workers, and Redis dequeue
errors back off instead of flooding logs in a tight loop.

TaskWorker restarts terminate
identified orphan processes and requeue unfinished jobs with their original IDs,
source snapshots and output/checkpoints; completed jobs remain complete and user
cancellations remain cancelled. A recovered run uses its existing experiment attempt.
Generated scripts are instructed to resume saved checkpoints or recognize complete
output. Queued jobs are redispatched idempotently. Agent recovery preserves the plan,
native conversation, delivered job identities and results; downtime and queue wait
are excluded from the remaining time budget using a persisted activity checkpoint.
User-paused/stopped and blocked sessions require their explicit continuation.
Frontend reconnects replay database events and merge messages by their native IDs.

`backend/common/queue_lifecycle.py` is shared by ordinary training, research agents
and research jobs: persisted FIFO ordering, serial recovery and tagged system
interruption. Executors retain their own checkpoint/data preparation and resource
admission. GPU stages still share TaskWorker's memory-aware GPU scheduler; research
agent slots are the separate Settings concurrency limit.

### Conversation deletion

The deletion transaction hides the conversation, cancels queued work, marks running work for cancellation and revokes associated file access. It returns before process or disk cleanup completes. A retained asynchronous cancellation task accelerates shutdown; ResearchWorker can recover the committed cleanup record after a restart.

The cleanup worker stops owned agents, experiment/download processes and article writers before deleting files and records. PID/start-time ownership checks protect unrelated processes, and process publication shares the session lock with deletion. A stored cleanup manifest supports retries after partial file removal.

Conversation-owned attachments, research outputs, registered models and reports are removed. Source datasets and independently referenced library files remain. Cleanup has two slots and retries failures; its internal `chat_delete` records are excluded from the progress panel. Other deletion operations retain their normal progress and cancellation behavior.

## Verification

From `server/`:

```bash
python -m pytest \
  tests/test_research_engine.py tests/test_autoresearch_routes.py \
  tests/test_auto_research_repository.py tests/test_task_worker_handlers.py \
  tests/test_research_harness.py tests/test_scientific_study.py \
  tests/test_chat_deletion.py tests/test_research_processes.py -q
python -m pytest backend/autoresearch/tests -q
```

Use a Python environment with runtime/test dependencies. Set `PATHLAB_TEST_POSTGRES_URL` for isolated-schema row-lock tests; real sandbox tests use the explicit switches in their test files. Use a separate Redis database and dedicated sessions for live acceptance.
The maintained API, scheduler and recovery regression tests live in `server/tests/`.
