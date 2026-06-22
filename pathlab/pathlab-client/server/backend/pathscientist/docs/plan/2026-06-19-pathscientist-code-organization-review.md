# PathScientist Code Organization Review

**Date:** 2026-06-19

**Scope:** `server/backend/pathscientist/` plus the PathScientist Gateway bridge in `server/gateway/routes/pathscientist.py`.

**Branch Reviewed:** `pathscientistv0.1.1dev`

**Purpose:** Identify where the current PathScientist implementation is hardest to maintain, and propose a low-risk cleanup order that preserves behavior while making later agent-workflow changes easier.

## Executive Summary

PathScientist is functionally organized into sensible domains, but the runtime control plane has grown by accretion. The package already has clear directories (`orchestrator`, `dataset`, `literature`, `domain`, `runtime`, `tools`, `synthesis`), yet several files now act as cross-domain coordinators and contain too many unrelated responsibilities.

The main cleanup target is not the model/template code. The highest-leverage work is to split the control-plane files while keeping public functions and tests stable:

1. `orchestrator/runner.py`
2. `orchestrator/grounding.py`
3. `dataset/acquisition.py`
4. `dataset/readiness.py`
5. `gateway/routes/pathscientist.py`

Do this as behavior-preserving extraction first. Avoid changing routing semantics, LLM prompts, data mount rules, or dataset acquisition behavior in the same pass.

## Current Shape

The intended workflow is:

```text
prompt
  -> task grounding
  -> literature search / SOTA lookup
  -> dataset discovery / acquisition
  -> data readiness
  -> execution plan
  -> feature extraction / training / external test
  -> review
  -> synthesis
```

The package structure mostly mirrors this:

```text
backend/pathscientist/
  agent.py, config.py, cli.py, run.py
  orchestrator/
  dataset/
  literature/
  domain/
  runtime/
  tools/
  evidence/
  persistence/
  synthesis/
```

The problem is that the main path through these domains is concentrated in a few large files.

## File Size Hotspots

Approximate line counts from the reviewed tree:

| File | Lines | Primary Issue |
|---|---:|---|
| `backend/pathscientist/orchestrator/runner.py` | 3497 | Coordinates almost every stage, plus many data-path and acquisition helpers. |
| `backend/pathscientist/dataset/acquisition.py` | 3062 | Dataset selection, local identity checks, provider orchestration, normalization, manifests, cache behavior. |
| `backend/pathscientist/orchestrator/grounding.py` | 1760 | Dataset/task extraction, skill routing, literature query planning, paper retrieval, SOTA/RAG state. |
| `backend/pathscientist/dataset/readiness.py` | 1183 | Path probing, split detection, feature cache validation, generated split fallback. |
| `server/gateway/routes/pathscientist.py` | 5000+ | Session API, SSE, persistence, downloads, token security, PathLab dataset sync, config defaults. |

These are the main files to organize before larger workflow redesign.

## Key Findings

### 1. `runner.py` Is the Highest-Risk God File

`orchestrator/runner.py` currently contains all of these concerns:

- Literature service and SOTA lookup construction.
- Feature extractor and MIL model selection.
- External validation request inference application.
- Data readiness assessment and execution plan construction.
- Data mount inference from user question and cache directories.
- Dataset cache/session registry merge.
- Dataset acquisition stage orchestration.
- Feature extraction output path resolution.
- Execution loop and resume loop.
- Stall detection.
- Integrity checks.
- Synthesis stage execution.
- PathLab registration best-effort bridge.

This makes changes risky because a small data-path change can accidentally affect resume, acquisition, external validation, or synthesis.

Recommended extraction targets:

```text
orchestrator/literature_setup.py
orchestrator/model_selection.py
orchestrator/data_mounts.py
orchestrator/acquisition_stage.py
orchestrator/execution_loop.py
orchestrator/synthesis_stage.py
```

Keep `run_research_session()` and `continue_research_session()` in `runner.py` as the public API initially. Move helpers behind them, not callers.

### 2. `grounding.py` Mixes Semantic Decisions With Retrieval Mechanics

`orchestrator/grounding.py` is already partially phased internally, but still contains several distinct layers:

- Dataset/task extraction orchestration.
- Heuristic task-profile construction.
- Optional LLM task-profile enrichment.
- Skill selection.
- Stop-after intent detection.
- Literature query planning and validation.
- Online/local retrieval handling.
- SOTA and passage/RAG results shaping.

This makes it hard to reason about what is rule-based versus LLM-based. It also makes future workflow changes risky because prompt routing, keyword fallback, and literature search are coupled.

Recommended extraction targets:

```text
orchestrator/task_grounding.py
orchestrator/skill_router.py
orchestrator/stop_after.py
orchestrator/literature_query.py
orchestrator/literature_grounding.py
```

Leave `ground_objective()` as the compatibility wrapper while these modules settle.

### 3. Rule/Keyword Logic Is Spread Across Too Many Files

PathScientist uses many deterministic rules. Some are intentional guardrails, but they are hard to audit because they live in separate modules:

- `orchestrator/objective_extractor.py`
- `dataset/task_profile.py`
- `dataset/llm_task_profile.py`
- `orchestrator/grounding.py`
- `domain/extractor_selector.py`
- `domain/mil_selector.py`
- `dataset/discovery_extractor.py`
- `dataset/scout.py`
- `dataset/readiness.py`
- `orchestrator/execution_plan.py`
- `runtime/metric_parser.py`

This is a product risk because a keyword rule can silently override or bypass an LLM decision.

Recommended direction:

- Create a small `orchestrator/routing_rules.py` or `domain/rules/` package only after extraction.
- Start by moving shared tables, not changing behavior.
- Add provenance fields where absent, e.g. `source: "llm" | "heuristic" | "explicit" | "env" | "default"`.

Do not do a semantic rewrite in the first cleanup pass.

### 4. `dataset/acquisition.py` Needs Internal Boundaries

`dataset/acquisition.py` is doing too much:

- Local dataset path scoring and identity matching.
- Archive/path handling.
- Provider selection and download.
- Normalizer invocation.
- Manifest writing.
- Cache checks.
- TCGA/GDC special casing.
- Prepared/raw/features path resolution.
- LLM local identity fallback.

Recommended extraction targets:

```text
dataset/local_identity.py
dataset/cache_layout.py
dataset/provider_orchestration.py
dataset/manifest_writer.py
dataset/acquisition_service.py
```

Keep `DatasetAcquisitionService` as the public facade at first. Move helpers out gradually and preserve method signatures.

### 5. `readiness.py` Is Mostly Cohesive But Too Dense

`dataset/readiness.py` is more cohesive than `runner.py` or `acquisition.py`: it owns "is data ready?" logic. The issue is density, not domain confusion.

Recommended split:

```text
dataset/readiness_types.py
dataset/readiness_paths.py
dataset/readiness_features.py
dataset/readiness_splits.py
dataset/readiness_assessor.py
```

Keep `assess_data_readiness()` in `readiness.py` as the import-compatible entry point until downstream imports are updated.

### 6. Gateway PathScientist Route Is a Separate Cleanup Project

`server/gateway/routes/pathscientist.py` is now a large product-surface module. It contains:

- Request/response schemas.
- In-memory live session manager.
- Registry and event file persistence.
- SSE streaming.
- Session start/resume/stop/delete endpoints.
- Download/token security.
- Workspace size calculation.
- PathLab dataset sync from PathScientist manifests.
- Gateway-specific PathScientist config defaults.

Recommended extraction targets:

```text
gateway/pathscientist/schemas.py
gateway/pathscientist/session_manager.py
gateway/pathscientist/events.py
gateway/pathscientist/downloads.py
gateway/pathscientist/security.py
gateway/pathscientist/pathlab_sync.py
gateway/pathscientist/config_defaults.py
```

This should be done after backend control-plane extraction, because many route helpers import backend internals.

## Recommended Cleanup Plan

### Phase 0: Safety Baseline

Goal: Make later refactors measurable.

Actions:

1. Capture current focused test commands in a short checklist.
2. Run at least:

```bash
cd /home/yihui/PathLab/pathlab/pathlab-client/server/backend/pathscientist
.venv/bin/python -m pytest \
  tests/test_objective_extractor.py \
  tests/test_dataset_task_profile.py \
  tests/test_grounding_target_integration.py \
  tests/test_orchestrator_acquisition_stage.py \
  tests/test_orchestrator_runner_dataset_discovery.py \
  tests/test_resume_pending_external_test.py \
  tests/test_mil_selector.py \
  tests/test_extractor_selector.py \
  -q

cd /home/yihui/PathLab/pathlab/pathlab-client/server
.venv/bin/python -m pytest tests/test_pathscientist_routes.py -q
```

Adjust `.venv/bin/python` if the server venv differs.

Expected result: test baseline known before any move.

### Phase 1: Extract Runner Support Modules

Goal: Shrink `runner.py` without changing behavior.

Suggested order:

1. Move literature setup helpers:
   - `_build_paper_registry`
   - `_build_literature_service`
   - `_build_paper_cache`
   - `_build_sota_lookup`
   - `_build_literature_store`
   - `_build_hybrid_retriever`

2. Move model selection helpers:
   - `_select_feature_extractor`
   - `_select_mil_model`

3. Move execution-plan/readiness prep:
   - `_prepare_data_readiness_and_execution_plan`
   - `_sync_planned_feature_extraction_env_from_current_step`
   - feature output path helpers

4. Move data mount/cache helpers:
   - `_inject_data_mounts_from_question`
   - `_cache_readiness_mounts`
   - `_internal_readiness_data_mounts`
   - dataset-name mount matching helpers

5. Move acquisition stage helpers:
   - `_maybe_run_acquisition_for_missing_data`
   - `_run_acquisition_stage`
   - dataset discovery/cache merge helpers

Validation after each sub-step:

```bash
cd /home/yihui/PathLab/pathlab/pathlab-client/server/backend/pathscientist
.venv/bin/python -m pytest \
  tests/test_orchestrator_acquisition_stage.py \
  tests/test_orchestrator_runner_dataset_discovery.py \
  tests/test_resume_pending_external_test.py \
  tests/test_execution_brief_dataset_discovery.py \
  -q
```

### Phase 2: Extract Grounding Modules

Goal: Make routing and retrieval independently reviewable.

Suggested order:

1. Move stop-after detection to `orchestrator/stop_after.py`.
2. Move skill selection to `orchestrator/skill_router.py`.
3. Move literature query planning/validation to `orchestrator/literature_query.py`.
4. Move paper retrieval/SOTA result shaping to `orchestrator/literature_grounding.py`.
5. Leave `ground_objective()` as the compatibility orchestrator.

Validation:

```bash
cd /home/yihui/PathLab/pathlab/pathlab-client/server/backend/pathscientist
.venv/bin/python -m pytest \
  tests/test_objective_extractor.py \
  tests/test_dataset_task_profile.py \
  tests/test_grounding_target_integration.py \
  tests/test_paper_grounding.py \
  tests/test_sota_lookup.py \
  tests/test_execution_brief_target_render.py \
  -q
```

### Phase 3: Extract Dataset Acquisition Internals

Goal: Make acquisition easier to reason about without changing provider behavior.

Suggested order:

1. Move local path/token/identity helpers into `dataset/local_identity.py`.
2. Move cache-root/path layout helpers into `dataset/cache_layout.py`.
3. Move manifest writing and prepared contract helpers into `dataset/manifest_writer.py`.
4. Move provider orchestration wrappers into `dataset/provider_orchestration.py`.
5. Keep `DatasetAcquisitionService` as the external facade.

Validation:

```bash
cd /home/yihui/PathLab/pathlab/pathlab-client/server/backend/pathscientist
.venv/bin/python -m pytest \
  tests/test_dataset_acquisition_service.py \
  tests/test_dataset_acquisition_with_discovery.py \
  tests/test_dataset_acquisition_gleason_panda.py \
  tests/test_dataset_providers.py \
  tests/test_dataset_providers_gdc.py \
  tests/test_pathlab_uploads_layout.py \
  -q
```

### Phase 4: Split Readiness by Concern

Goal: Make data readiness failures easier to debug and test.

Suggested order:

1. Move dataclasses to `dataset/readiness_types.py`.
2. Move path resolution/probing to `dataset/readiness_paths.py`.
3. Move feature cache checks to `dataset/readiness_features.py`.
4. Move split file helpers to `dataset/readiness_splits.py`.
5. Keep `assess_data_readiness()` import-compatible.

Validation:

```bash
cd /home/yihui/PathLab/pathlab/pathlab-client/server/backend/pathscientist
.venv/bin/python -m pytest \
  tests/test_dataset_manifest.py \
  tests/test_dataset_normalizers.py \
  tests/test_orchestrator_acquisition_stage.py \
  tests/test_sandbox_data_mounts.py \
  -q
```

### Phase 4.5: Generalize Task-Specific Label Resolution

Goal: Move beyond the current Chronic-gastritis `Task1`/`Task2`/`Task3`/`Task4` hotfix and make PathScientist able to resolve task labels from arbitrary registered label tables.

Current boundary:

- The June 20 hotfix handles the common Chronic-gastritis table convention:
  `Task1=inflammation`, `Task2=activity`, `Task3=atrophy`, `Task4=intestinal_metaplasia`.
- It also avoids treating a complete `label_semantics` catalog as the requested target, so an inflammation prompt does not accidentally choose `Task4` just because the catalog mentions intestinal metaplasia.
- This is not a generic schema resolver. Datasets with different column names, multi-file metadata, free-text labels, or cohort-specific task definitions still need a general mechanism.

Suggested design:

1. Create `dataset/label_schema.py`.
   - Add a `LabelSchemaCandidate` dataclass with:
     `source_file`, `slide_id_column`, `label_column`, `label_semantics`, `confidence`, `evidence`, and `source` (`explicit`, `manifest`, `llm`, `heuristic`).
   - Add a `ResolvedLabelContract` dataclass with:
     `labels_file`, `splits_file`, `label_column`, `label_counts`, `num_labeled`, `requires_label_inference`, and `provenance`.

2. Add deterministic table scanning.
   - Read all nearby `*.csv` / `*.tsv` metadata files, not just `*label*`.
   - Detect slide-id columns by matching against actual WSI stems.
   - Detect candidate label columns by task intent, column cardinality, missing rate, and whether values can produce valid classification splits.
   - Keep deterministic evidence for every candidate, even rejected ones.

3. Add optional LLM ranking only after deterministic scanning.
   - Feed the LLM a compact schema summary: file names, columns, value examples, match counts, missing rates, and the user task.
   - The LLM may rank candidates or map a task to a column, but it must return structured JSON with evidence.
   - The resolver must reject LLM choices that do not match enough WSI files or cannot produce splits.

4. Replace hardcoded task-column helpers gradually.
   - Route `_write_task_labels_from_source_tables()` through `label_schema.resolve_label_schema()`.
   - Route `MILClassificationNormalizer.prepare(..., task_profile=...)` through the same resolver.
   - Keep the Chronic-gastritis `Task1`-`Task4` mapping as one explicit rule inside the resolver, not as scattered gateway/normalizer logic.

5. Register provenance in manifests.
   - Store `label_resolution` in `dataset_manifest.json`:
     selected file, selected column, rejected candidates, task intent, and confidence.
   - Keep `requires_label_inference=true` when no safe candidate exists.

Validation:

```bash
cd /home/yihui/PathLab/pathlab/pathlab-client/server
../server/backend/pathscientist/.venv/bin/python -m pytest \
  backend/pathscientist/tests/test_dataset_normalizers.py \
  backend/pathscientist/tests/test_label_schema.py \
  tests/test_pathscientist_routes.py::test_prepare_pathlab_dataset_view_uses_task_specific_source_labels_for_im \
  tests/test_pathscientist_routes.py::test_prepare_pathlab_dataset_view_uses_chinese_intestinal_metaplasia_intent \
  -q
```

Add new tests for:

- Multiple metadata files where only one matches WSI stems.
- Chinese and English task descriptions.
- A complete `label_semantics` catalog that must not override the requested target.
- A dataset with registered single-class DB labels but a multi-class source label table.
- A dataset with no safe label table, which must continue to require label inference instead of fabricating labels.

### Phase 5: Split Gateway Route

Goal: Reduce frontend/API blast radius and make security/download/session changes safer.

Suggested order:

1. Extract Pydantic/dataclass schemas.
2. Extract session manager.
3. Extract event normalization/SSE helpers.
4. Extract download/archive helpers.
5. Extract PathScientist access-token validation helpers.
6. Extract PathLab dataset sync helpers.
7. Extract Gateway default config builders.

Validation:

```bash
cd /home/yihui/PathLab/pathlab/pathlab-client/server
.venv/bin/python -m pytest tests/test_pathscientist_routes.py -q
```

Frontend smoke tests if UI-facing event shapes change:

```bash
cd /home/yihui/PathLab/pathlab/pathlab-client
npm test -- \
  test/unit/api/pathscientist.test.ts \
  test/unit/lib/pathscientistEventSelectors.test.ts \
  test/unit/components/pathscientist/PathScientistExecutionConsole.test.tsx
```

## What Not To Change First

Avoid these in the first cleanup pass:

- Do not change LLM prompts while moving files.
- Do not change skill-routing semantics.
- Do not remove rule/keyword fallbacks yet.
- Do not remove `Plan-...` comments until their behavior has an equivalent test name or doc reference.
- Do not replace lazy imports with top-level imports unless circular dependencies are checked.
- Do not reformat entire files unrelated to the extraction.
- Do not move `domain/templates/common/extractors/` during control-plane cleanup.
- Do not merge Gateway cleanup with backend runner cleanup in one patch.

## Notes On Dirty Worktree

The reviewed worktree contains many modified and untracked files across:

- `backend/pathscientist/`
- `server/gateway/`
- `src/renderer/`
- `server/tests/`
- `test/unit/`

Before starting refactor work, either:

1. Commit/stash unrelated work, or
2. Create a new branch/worktree from the current dirty state intentionally and only touch the target files.

Do not run broad cleanup commands like `black .`, `ruff --fix .`, or `prettier --write .` during this reorganization.

## Suggested First PR

The first PR should be deliberately small:

**Title:** `Chore: Extract PathScientist runner literature and model setup helpers`

Target files:

```text
backend/pathscientist/orchestrator/runner.py
backend/pathscientist/orchestrator/literature_setup.py
backend/pathscientist/orchestrator/model_selection.py
backend/pathscientist/tests/test_build_sota_lookup.py
backend/pathscientist/tests/test_extractor_selector.py
backend/pathscientist/tests/test_mil_selector.py
```

Expected behavior change: none.

Recommended tests:

```bash
cd /home/yihui/PathLab/pathlab/pathlab-client/server/backend/pathscientist
.venv/bin/python -m pytest \
  tests/test_build_sota_lookup.py \
  tests/test_extractor_selector.py \
  tests/test_mil_selector.py \
  tests/test_orchestrator_runner_dataset_discovery.py \
  -q
```

This first cut is low risk because literature/model setup already has relatively clear helper boundaries and focused tests.

## Longer-Term Architecture Target

After cleanup, the public orchestration surface should look closer to:

```text
ResearchDirector
  -> ground_objective()
  -> prepare_execution_context()
  -> maybe_acquire_data()
  -> build_execution_plan()
  -> run_execution_loop()
  -> synthesize_results()
```

Where each step has a small module with:

- A dataclass input/output contract.
- Explicit provenance for LLM vs rule decisions.
- Focused tests.
- No hidden Gateway dependency.

The important principle is to make the workflow inspectable before making it more agentic.
