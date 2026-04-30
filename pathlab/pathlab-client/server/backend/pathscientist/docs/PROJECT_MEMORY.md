# PathScientist Project Memory

> Persistent context for any engineer (or Claude session) working on PathScientist.
> Not a plan or a log — a reference sheet of decisions, conventions, and gotchas.
> Last reviewed: 2026-04-17

---

## What Is PathScientist

An OpenHands-based autonomous research platform for computational pathology. Turns a research objective into code edits, experiment runs, evidence records, literature-grounded baselines, and session summaries with citations.

Master plan: `docs/plan/2026-04-05-pathscientist-master-plan.md`

## Canonical Paths

| What | Path |
|------|------|
| Package root | `server/backend/pathscientist/` |
| Tests | `server/backend/pathscientist/tests/` |
| Plans | `server/backend/pathscientist/docs/plan/` |
| Reviews | `server/backend/pathscientist/docs/review/` |
| Work log | `server/backend/pathscientist/docs/WORKLOG.md` |
| Skills (YAML) | `server/backend/pathscientist/domain/skills/` |
| Templates | `server/backend/pathscientist/domain/templates/` |
| Common library | `server/backend/pathscientist/domain/templates/common/` |
| Literature seed data | `server/backend/pathscientist/literature/seed_data/pathology_papers.json` |
| System prompt | `server/backend/pathscientist/prompts/system_prompt.j2` |
| venv | `server/backend/pathscientist/.venv/` (Python 3.12, openhands-sdk 1.16.1) |
| Legacy reference | `server/backend/auto_research_old/` (do NOT add new code here) |
| Project memory | `server/backend/pathscientist/docs/PROJECT_MEMORY.md` |
| Default runtime sessions | `/project/vcompath/storage/ywangrm/tmp/pathscientist/session_<session_id>/` |
| Default conversation persistence | `/project/vcompath/storage/ywangrm/tmp/pathscientist/conversations/<conversation_id.hex>/` |
| Default literature index | `/project/vcompath/storage/ywangrm/tmp/pathscientist/literature/` |

These last three are defaults derived from `PATHSCIENTIST_BASE_DIR` and can be overridden in config/tests.

## 6-Layer Architecture

```
L6  Product Surface          CLI / API / SSE / Web UI
L5  Paper / Report Gen       evidence → sections → markdown/LaTeX
L4  Retrieval                literature search + evidence queries + (later) RAG
L3  Research Orchestrator    intake → grounding → execution → review → synthesis
L2  Code Agent Execution     edit → validate → run → ratchet, 8 custom tools
L1  Project / Workspace      session, workspace, sandbox, git, persistence
```

## Phase Status

| Phase | What | Status | Plan doc |
|-------|------|--------|----------|
| 0 | Code Agent Foundation | ✅ Complete | `2026-04-03-code-agent-implementation-plan.md` + `gap-closure-plan.md` |
| 1 | Research Orchestrator | ✅ Complete (hardened 04-09: stall detection, approval gate, resume) | `2026-04-06-pathscientist-orchestrator-implementation-plan.md` |
| 2 | Evidence / Artifact System | ✅ Complete (hardened 04-09: DATA_OUTPUT_DIR, external paths, untracked files, claim search) | `2026-04-07-pathscientist-evidence-system-plan.md` |
| 3 | Literature Grounding | ✅ Complete (MVP, local-first; hardened 04-09: integration tests, storage docs) | `2026-04-07-pathscientist-literature-grounding-plan.md` |
| 4 | Report / Paper Generation | ✅ Complete (04-17: section-by-section LLM drafting via `_llm_section_writer` + `_build_section_prompt`, per-section deterministic fallback on failure; manifest now indexes `grounded_sections.json`; `paper_verification_issue_count` persisted and surfaced in `/report`) | `2026-04-08-pathscientist-phase4-report-and-paper-generation-plan.md` + `2026-04-09-pathscientist-grounded-paper-writing-hardening-plan.md` |
| 5 | Product Surfaces | Not started | — |
| 6 | Vendor SDK | 📋 Plan written | `2026-04-05-vendor-openhands-sdk-plan.md` |

Next recommended step: start Phase 5 (API/Product Surfaces) **or** Phase 6 vendor SDK execution.

## Package Structure

```
pathscientist/
├── agent.py, cli.py, run.py, config.py, start.sh
├── cli_state.py, cli_commands.py, cli_render.py, cli_sessions.py, cli_input.py
├── context.py, knowledge.py, error_classifier.py, structured_output.py
├── orchestrator/    — types, director, grounding, runner, prompts, summary, state_bridge, metrics_utils
├── evidence/        — types, store, collector, query
├── literature/      — types, store, seed, retriever, citations + seed_data/
├── persistence/     — layout, state_bridge, resume, history
├── runtime/         — workspace, sandbox, session, session_registry, iteration_state, script_safety
├── tools/           — run_experiment, validate_script, ratchet, metrics, checkpoint, skill_browser, workspace_info
├── domain/          — skills/*.yaml + templates/ (classification, survival, feature_extraction) + common/
├── prompts/         — system_prompt.j2
├── tests/           — 27 test files, 124 test cases
└── docs/            — plan/ (14 docs) + review/ (7 docs) + WORKLOG.md + PROJECT_MEMORY.md
```

## Key Design Decisions

### 1. In-repo, not fork
PathScientist lives inside the PathLab repo as `server/backend/pathscientist/`, not in a separate OpenHands fork. Decided 2026-04-03.

### 2. OpenHands SDK via pip (for now)
Using `openhands-sdk==1.16.1` + `openhands-tools` via pip. Vendor plan exists but not yet executed. SDK controls the agent loop; PathScientist controls the prompt + tools.

### 3. Two skill systems
- **Knowledge Skills** (`knowledge.py`): 4 keyword-triggered skills auto-injected by OpenHands `AgentContext` when user message matches keywords. LLM doesn't choose these.
- **Training Skills** (`domain/skills/*.yaml`): 5 YAML-defined skills with templates. LLM chooses via `skill_browser` tool call. Grounding stage uses LLM to select best skill.

### 4. Two identifiers per session
- **`session_id`** (12-char hex): process-local key for `SessionRegistry` tool resolution. Fresh on every process start, including resume.
- **`conversation_id`** (UUID): durable key for OpenHands persistence + resume. Stored in `PathScientistSession`.

### 5. Persistence via OpenHands EventLog
Conversations persist to `conversations/<conversation_id.hex>/`:
- `base_state.json` — mutable snapshot (auto-saves on `agent_state` change)
- `events/event-NNNNN-<id>.json` — append-only event stream
- `literature_citations.json` — per-conversation citation records

PathScientist-specific state (tracker, iteration, loaded skill, orchestrator session state) is stored in `agent_state` inside `base_state.json`. Resume rebuilds everything from there.

### 6. Task-type assessment by LLM
System prompt presents both "one-shot" (extraction) and "iterative" (training) workflows. The LLM decides which to follow via `think` tool. No hardcoded `task_mode` branching.

### 7. Dual output directories
- `OUTPUT_DIR` = per-run UUID dir for `metrics.json` (agent reads this)
- `DATA_OUTPUT_DIR` = stable user-visible path for actual data (features, coords). Set via `data-mount` with container path `/output`, `/results`, or `/data/output`.

### 8. Canonical run_id lineage
`RunExperimentTool` creates the only authoritative `run_id`. This same ID flows through:
- `SessionDeps.last_experiment`
- `IterationState.last_run_id` + `finalized_run_ids`
- `MetricsTracker.history` entries
- `.evidence/runs/<run_id>/record.json`
- Orchestrator `RunRecord.run_id`

No second identifier is created by evidence or orchestrator.

### 9. Evidence before revert
Ratchet revert captures code snapshot and git diff **before** workspace.revert() so failed-run evidence represents the attempted code, not the restored baseline.

### 10. Literature grounding is local-first
~14 curated pathology papers in `seed_data/pathology_papers.json`. Keyword + metadata search, no embeddings. API augmentation (Semantic Scholar, PubMed, arXiv, PathLab API) deferred. Baselines injected into execution brief.

### 11. Two-level literature storage
- **Global corpus** (`{BASE_DIR}/literature/`): `LiteratureStore` — shared singleton, read-only after seeding.
- **Conversation-scoped citations** (`{persistence_root}/{conv_id_hex}/literature_citations.json`): `CitationTracker` — per-conversation, independent from global corpus.

### 12. Stall detection prevents infinite orchestrator loops
`MAX_CONSECUTIVE_STALLS = 2` in `orchestrator/types.py`. If the agent completes N consecutive turns without calling ratchet_commit or ratchet_revert, the runner forces the session to synthesis with `stop_reason="stall_limit"`.

### 13. Approval gating uses a real state machine
`ResearchSessionState.approval_status` (none/pending/approved/rejected) replaces the old `pending_approval: bool`. The director stays in GROUNDING until `approval_status == "approved"`. CLI provides `/approve` and `/reject` commands. Batch mode (`auto_approve=True`) bypasses the gate entirely.

### 14. Evidence tracks DATA_OUTPUT_DIR and untracked files
- `EvidenceRecord.data_output_dir` records where user-visible outputs were written.
- `EvidenceRecord.untracked_files` preserves content of files created during failed iterations but never committed (captured before workspace.revert() via `git ls-files --others`).
- `query_evidence_for_claim()` searches across git_diff, error_type, error_hint, artifact names, and stdout/stderr — not just agent_notes.

### 15. Tool-gate policy (2026-04-21)

- `ratchet_commit` and `ratchet_revert` refuse to fire when
  `deps.last_experiment is None`. Reason: the evidence store can only
  capture data attached by `RunExperimentTool` — bare `terminal + python
  script.py + ratchet_commit` produces empty `.evidence/runs/` and
  silent paper-ready claims.
- Escape hatch: `RatchetCommitAction.external=True` (and the revert
  analog) bypasses the gate. When set, the evidence skip reason is
  `external_experiment_opt_in` and IntegrityGuard downgrades the
  missing-evidence issue from fatal to warning.
- Commits: 57231463 (commit gate), f5208311 (revert gate), 40aaf4b3
  (external-opt-in distinction), 01f59430 (system-prompt + skill
  constraint), d59327f8 (integration coverage + this note).

## Test Conventions

- Tests live in `server/backend/pathscientist/tests/`; each file does `sys.path.insert(0, str(Path(__file__).parent.parent.parent))`
- Product code imports: `from pathscientist.X import Y`
- Shared test helpers: `from persistence_helpers import build_test_conversation`
- Run: `cd server/backend/pathscientist && .venv/bin/python -m pytest tests/ -v`
- Skip smoke tests: `--ignore=tests/test_smoke_agent.py --ignore=tests/test_smoke_skill.py`
- Persistence tests use `persistence_helpers.py` (shared fixtures, no real LLM)
- Smoke tests (`test_smoke_agent.py`, `test_smoke_skill.py`) require real LLM access

## Running PathScientist

```bash
# Interactive research mode (default, with orchestrator + literature grounding)
cd server/backend/pathscientist && bash start.sh

# Batch research mode
bash start.sh -q "Improve AUC on BRACS" --skill mil_classification

# Code mode (skip orchestrator)
bash start.sh --mode code

# With data mounts
bash start.sh -q "Extract UNI features" \
  --data-mount "/path/to/WSIs:/data/wsi" \
  --data-mount "/path/to/output:/output" \
  --metric patches_extracted --max-iter 1

# Override model
bash start.sh --model claude-sonnet-4-20250514 --api-key "$ANTHROPIC_API_KEY" --base-url ""
```

Interactive commands: `/status`, `/metrics`, `/workspace`, `/summary`, `/mode`, `/new`, `/sessions`, `/resume <uuid>`, `/approve`, `/reject`, `/report`, `/details`, `/help`, `/quit`. Also `@file` expansion and `!shell` execution.

## LLM Configuration

Default (in `start.sh`):
```
Model:    openai/Qwen/Qwen3.5-397B-A17B-FP8
Base URL: http://dgx-52.cm.cluster:8000/v1
API Key:  sk-pathlab
```

Known issue: litellm emits "Cost calculation failed" warnings for Qwen. Suppressed via `warnings.filterwarnings` in `cli.py`/`run.py`.

LLM completion logs saved to `<workspace>/logs/completions/` (enabled by default).

## Common Gotchas

1. **Agent uses terminal instead of run_experiment** — bypasses policy checks and metrics tracking. Prompt says "use run_experiment", but Qwen sometimes ignores this.
2. **UNI model needs HF token** — `checkpoint_manager.py` tries `hf_hub_download("MahmoodLab/UNI")` which is a gated repo. Without token, falls back to random init ViT-L.
3. **Git root is `/project/vcompath/storage/ywangrm/PathLab`**, not `pathlab/pathlab-client`. All git commands must use paths relative to that root.
4. **`.venv/` and `test_data/` are gitignored** — never commit them.
5. **`structured_output.py` has stale legacy imports** — `llm_generate_structured()` currently imports missing `langchain_core` and `.nodes`; only `extract_json()` is safely exercised in the current test suite.
6. **Sandbox in tests** — always use `sandbox_mode="local"` and `gpu_ids=[]` in test configs.
7. **Conversation persistence dir in tests** — must set `conversation_persistence_dir=str(tmp_path)` in test config, otherwise conversations persist to the global `/project/.../tmp/pathscientist/conversations/` directory.
8. **Plan navigation** — use `docs/plan/2026-04-05-pathscientist-master-plan.md` as the top-level roadmap; the `2026-04-02` docs are retained reference material, not the active execution plan.
9. **Citation tracker normalizes UUIDs** — `CitationTracker` converts UUID strings to `.hex` format to match OpenHands conversation directory names.
10. **Evidence is workspace-scoped** — `.evidence/` lives inside the workspace, not the conversation persistence directory.
11. **`pending_approval` is now a read-only property** — old code that assigns `state.pending_approval = True` will fail. Use `state.approval_status = "pending"` instead. Old persisted sessions with `pending_approval: bool` are auto-migrated on load.
12. **Evidence `run_dir` can be absolute** — if `--output` points outside the workspace, `run_dir` in `deps.last_experiment` is stored as an absolute path. Evidence collector handles both relative and absolute paths.

## Repository Snapshot (as of 2026-04-09)

```
Python modules:    139 .py files
  Top-level:        15 .py files (agent, cli, config, run, context, knowledge, etc.)
  CLI modules:       5 .py files (cli_state, cli_commands, cli_render, cli_sessions, cli_input)
  Orchestrator:      8 .py files
  Evidence:          4 .py files
  Literature:        5 .py files + seed_data/
  Persistence:       4 .py files
  Runtime:           6 .py files
  Tools:             8 .py files
  Domain:           ~50 .py files (templates + common library)
Tests:              28 files, 171 test cases
Plan docs:          14 .md files
Review docs:        11 .md files
Prompts:             1 .j2 file
```

## Dataset Acquisition (2026-04-25)

PathScientist now has an orchestrator-owned dataset acquisition stage that
runs between grounding and execution when `auto_acquire_data=True` and the
user has not supplied `data_mounts`.

**Flow:**
1. Grounding emits a `task_profile` (heuristic; see `dataset/task_profile.py`).
2. Acquisition stage scouts `dataset/seed_data/pathology_datasets.json` via
   `DatasetScout` (scoring: +5 task / +3 organ / +2 asset / +1 keyword;
   policy reject −100).
3. `AcquisitionPolicy` defaults to `public_only` and 20 GB max — gated /
   manual / oversize records skip with evidence rather than a silent attempt.
4. The first allowed candidate is handed to its provider:
   - `HuggingFaceProvider` (snapshot_download)
   - `ZenodoProvider` (file URL list; DOI metadata is later)
   - `DirectHTTPProvider` (rejects landing-page URLs as `skipped_policy`)
5. Archives are extracted via `extract_archive` (zip + tar + tar.gz with
   path-traversal protection).
6. A normalizer (`PatchClassificationNormalizer` or
   `MILClassificationNormalizer`) writes a prepared layout under
   `<persistence_root>/datasets/prepared/<normalizer>/<safe_id>/` and emits
   a contract dict (`images_dir`, `splits_file`, `data_mounts`, ...).
7. `<workspace>/.dataset/manifest.json` and
   `<workspace>/.evidence/datasets/<safe_id>.json` are written.
8. `state.acquisition_status / dataset_manifest_path / selected_dataset` are
   populated; `config.data_mounts` is mutated so runtime tools see the
   prepared paths; the execution brief renders
   `Selected dataset:` and `Dataset manifest:` lines.

**Config knobs (CLI flags pending — see deferred T2b / SOTA T11):**
- `auto_acquire_data: bool = False`
- `download_policy: "public_only" | "manual_only" | "disabled"`
- `dataset_cache_dir: str` (defaults to `<persistence_root>/datasets/`)
- `max_download_size_gb: float = 20.0`
- `allow_large_downloads: bool = False`

**Failure semantics — every path produces a manifest, no exceptions
propagate:**
- `no_candidate`: registry returned 0 records or all policy-rejected.
- `skipped_policy`: top candidate denied by access / size policy.
- `failed`: provider returned `failed`, no normalizer supports the task,
  or the normalizer raised.
- `skipped`: user supplied `config.data_mounts` (acquisition is a no-op
  in this case — the user paths are authoritative).

The acquisition stage is orchestrator-owned. The OpenHands code agent
receives prepared paths via `config.data_mounts` and the execution brief;
it must NOT invent download commands.

## LLM Task-Profile Enrichment (2026-04-30)

Grounding now keeps the deterministic `dataset/task_profile.py` heuristic as
the offline baseline, then optionally runs structured LLM enrichment before
skill selection, literature retrieval, RAG/SOTA, and acquisition.

**Why:** keyword organ inference misses implicit medical knowledge such as
`Gleason grading -> prostate / Gleason-ISUP labels`. The LLM enrichment fills
missing fields without becoming an unchecked source of truth.

**Behavior:**
1. `infer_task_profile()` builds the initial heuristic `TaskProfile`.
2. `dataset/llm_task_profile.py` asks an LLM/text caller for strict JSON:
   organ, confidence, task shape, modality, prediction target, label keywords,
   and dataset hint candidates.
3. The JSON is validated against allowlists. Invalid JSON, unknown organs, or
   missing LLM config fail open and keep the heuristic profile.
4. High-confidence LLM fields can fill missing organ/target metadata; explicit
   user `preferred_skill` is not overridden.
5. Grounding records provenance in `grounding["llm_task_profile"]`,
   `grounding["task_profile_sources"]`, and `grounding["dataset_hint_candidates"]`.

For example, with an LLM caller available, "训练一个 Gleason 分级任务" can now
produce `organ=prostate`, `prediction_target=gleason_grade`, and PANDA as a
candidate dataset hint before literature search/acquisition run.

## Literature-Grounded Dataset Discovery (2026-04-30)

The acquisition stage now runs an offline-by-default discovery pass before
hitting the curated registry, turning literature evidence (`baselines`,
`sota_target`, `papers[].datasets`, `dataset_hint_candidates`, `passages`)
into auditable dataset candidates without spending any new network budget.

**Flow (`orchestrator/runner.py::_run_acquisition_stage`):**
1. `dataset/discovery_extractor.extract_dataset_candidates(grounding, profile)`
   reads the **persisted** `state.grounding` dict — it does NOT re-call
   `LiteratureService.find_papers()`. Source priority: baseline (medium) →
   sota_target (medium) → papers.datasets (low) → dataset_hint_candidates
   (LLM-supplied confidence) → passages (medium when a known provider URL
   appears, denylisted otherwise).
2. `paper_id` on every evidence entry is canonicalized via
   `literature.id_resolver.to_canonical_id` so cross-session linking through
   `PaperRegistry` works.
3. `dataset/discovery_store.save_discovery_records()` writes
   `<workspace>/.dataset/discovery.json` (always — even when empty).
4. `dataset/discovery_registry.merge_curated_and_discovered()` merges the
   curated registry with discovered records into a session-local
   `<workspace>/.dataset/session_registry.json`. Curated wins on name + tags
   conflict; discovered records require `confidence ∈ {medium, high}` AND ≥1
   evidence entry. Discovered records always start `access="manual"` —
   discovery is NEVER proof of downloadability.
5. `DatasetAcquisitionService.acquire()` consumes the session-local registry,
   calls `provider.probe()` on each candidate (probe only adds tags such as
   `probe:hf_remote_unverified` — it never upgrades access), runs the same
   relevance / policy / download / normalize gates as before.
6. `dataset/acquisition_plan.acquisition_plan_path_for_workspace` writes
   `<workspace>/.dataset/acquisition_plan.json` at every exit path —
   considered candidates + selected_dataset_id + status — so reviewers can
   inspect "what would have been picked" even under
   `--stop-before-execution` or `download_policy=disabled`.
7. `state.grounding["dataset_discovery_path"]` and
   `state.grounding["dataset_acquisition_plan_path"]` are persisted, so the
   execution brief always renders both paths regardless of acquisition
   outcome.

**Optional LLM enrichment** (`dataset/discovery_llm_extractor.py`): when
`build_llm_text_caller(config)` returns a callable, the LLM extractor
parses passage / baseline texts into additional `DatasetDiscoveryRecord`s.
Merge rule: heuristic records win on name conflict unless the LLM record
has higher confidence AND at least one provider hint. Malformed JSON or
LLM exceptions return `[]` cleanly so the heuristic path stays the source
of truth.

**Network policy leg** (`runtime/network_policy.py`): `LegName` includes
`"dataset_discovery"`; `NetworkPolicy.allow_dataset_discovery` defaults
True (heuristic extraction is offline-safe). Disabled by `stage="local"`,
by `allow_dataset_discovery=False`, or by env
`PATHSCIENTIST_DATASET_DISCOVERY=0`. CLI flags
(`--dataset-discovery` / `--no-dataset-discovery`) deferred to Phase 1.5
alongside `--network=...`, `--no-online-papers`, `--allow-auto-ingest`.

**Files:**
- `dataset/discovery_types.py` — `DatasetDiscoveryEvidence` /
  `ProviderHint` / `DatasetDiscoveryRecord` (paper_id docstring documents
  canonical-shape expectation).
- `dataset/discovery_store.py` — JSON read/write helpers.
- `dataset/discovery_extractor.py` — heuristic + optional LLM enrichment.
- `dataset/discovery_registry.py` — `discovery_record_to_dataset_record`
  (always `access="manual"`) + `merge_curated_and_discovered` (curated
  wins).
- `dataset/discovery_llm_extractor.py` — `DatasetDiscoveryLLMExtractor`
  (caller injects `llm_parser` from `build_llm_text_caller`).
- `dataset/acquisition_plan.py` — plan artifact helpers.
- `dataset/providers/{direct_http,zenodo,huggingface}.py` — `probe()`
  methods that ONLY tag, never upgrade access.

**Tests (78 new):**
`test_dataset_discovery_types.py` (7),
`test_dataset_discovery_store.py` (6),
`test_dataset_discovery_extractor.py` (15),
`test_dataset_discovery_registry.py` (12),
`test_dataset_provider_probe.py` (11),
`test_dataset_acquisition_with_discovery.py` (4),
`test_dataset_acquisition_plan_artifact.py` (6),
`test_orchestrator_runner_dataset_discovery.py` (6),
`test_execution_brief_dataset_discovery.py` (4),
`test_dataset_discovery_llm_extractor.py` (9),
`test_dataset_discovery_network_policy.py` (8),
`test_dataset_discovery_e2e.py` (3).

## Dataset Provider Repair (2026-04-30)

Follow-up plan
(`docs/plans/2026-04-30-pathscientist-dataset-provider-repair-plan.md`)
hardened the acquisition surface so PANDA / TCGA-style records reach a
real provider rather than silently falling back to ``no_provider:<name>``.

**Provider factory (Task 1 / `dataset/providers/factory.py`):**
``build_default_providers()`` is the only place to register a provider.
It returns fresh instances each call to keep injected sessions / runners
from leaking between tests. Current map (Task 4 / 5 added Kaggle + GDC):

| key | class | notes |
|---|---|---|
| `direct_http` | `DirectHTTPProvider` | rejects landing-page URLs |
| `zenodo` | `ZenodoProvider` | resolves `/api/records/<id>` when no urls |
| `huggingface` | `HuggingFaceProvider` | `snapshot_download` |
| `kaggle` | `KaggleProvider` | runner-injectable CLI; `kaggle_competition` / `kaggle_dataset` kinds |
| `gdc` | `GDCProvider` | manifest / explicit `api.gdc.cancer.gov/data/<uuid>` only |
| `tcia` | (alias to same `GDCProvider` instance) | so legacy seed records reach an adapter |

**Plan entries (Task 6) — `acquisition_plan.json["considered"][i]` carry:**

`dataset_id`, `name`, `provider`, `provider_available`, `access`,
`estimated_size_gb`, `license`, `source_paper_ids`, full `download` dict,
`score`, `relevant`, `allowed`, `policy_reason`, `reasons`, `tags`. Plan
is written **before** `provider.download()` (status=`planned`) and again
at every final exit, so ``--stop-before-execution`` reviewers always have
a complete artifact even if download takes minutes or crashes.

**PANDA / Gleason behavior contracts (Task 7 — characterization):**

- `download_policy="public_only"` → PANDA selected as top relevant
  candidate, `skipped_policy/access=manual`.
- `download_policy="manual_only"` + default `max_download_size_gb=20` →
  PANDA selected, `skipped_policy/too_large` (PANDA is 400 GB).
- `download_policy="manual_only"` + `max_size=500` +
  `allow_large_downloads=True` + Kaggle creds → policy + provider both
  pass; `KaggleProvider` runner is invoked with `kaggle competitions
  download -c prostate-cancer-grade-assessment …`.

**Brief surfacing (Task 8):**

For `acquisition_status in {skipped_policy, failed}` AND
`state.selected_dataset` set, the execution brief renders:

```
Selected dataset candidate: <name> (provider: <p>, access: <a>)
Dataset acquisition: skipped_policy (<reason>)
```

so the agent / reviewer sees *which* dataset got blocked, not just a
status string.

**Operational reference:** `docs/dataset_acquisition.md` for the full
provider matrix, recipes (safe Gleason dry run, real Kaggle attempt,
TCGA-BRCA), and reason-string catalogue.

**Files added in this round:**
- `dataset/providers/factory.py`
- `dataset/providers/kaggle.py`
- `dataset/providers/gdc.py`
- `dataset/acquisition_plan.py` (Task 8 of dataset-discovery; enriched in Task 6)
- `docs/dataset_acquisition.md`

**Tests added (40 new in this plan):**
`test_dataset_provider_factory.py` (4),
`test_dataset_providers_kaggle.py` (9),
`test_dataset_providers_gdc.py` (9),
`test_dataset_acquisition_gleason_panda.py` (4),
`test_dataset_provider_e2e_stop_before_execution.py` (2),
plus 4 new tests added to `test_dataset_providers.py` (Zenodo metadata),
plus 6 review-blocker tests added to `test_dataset_acquisition_plan_artifact.py`,
`test_orchestrator_runner_dataset_discovery.py`, `test_execution_brief_dataset_discovery.py`,
`test_dataset_provider_probe.py`,
plus 2 enrichment tests added to `test_dataset_acquisition_plan_artifact.py` (Task 6),
plus 2 brief tests added to `test_execution_brief_dataset_discovery.py` (Task 8).
