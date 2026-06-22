# Auto Research Platform Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
>
> Update 2026-04-05:
> This document is retained as a legacy backlog source for platform capabilities,
> especially around orchestration, artifacts, and paper generation.
> It is no longer the primary implementation roadmap.
> The active top-level roadmap is
> `server/backend/pathscientist/docs/plan/2026-04-05-pathscientist-master-plan.md`.

**Goal:** Convert the current `auto_research` prototype into a stable Phase 1 platform that can manage a persistent workspace, run reproducible experiments, capture evidence, and generate a grounded report / paper draft.

**Architecture:** Keep the existing LangGraph-based orchestration, but introduce a clearer project-session-run-artifact contract, normalize sandbox semantics across all backends, and add an evidence-driven paper generation path. Execute this as a small series of contract-first changes, with tests protecting behavior before each refactor.

**Tech Stack:** FastAPI, LangGraph, SQLAlchemy, Pydantic, pytest, Apptainer, Docker, local subprocess fallback

---

### Task 1: Normalize session and config contracts

**Files:**
- Create: `server/tests/test_auto_research_contracts.py`
- Modify: `server/backend/auto_research/types.py`
- Modify: `server/backend/auto_research/server.py`
- Modify: `server/backend/database/models.py`
- Modify: `server/backend/database/repositories/auto_research.py`

**Step 1: Write the failing test**

Add tests that prove:
- `StartRequest.locale` propagates into `AutoResearchConfig`,
- a session stores a project-style objective/config payload,
- the graph initial state receives normalized session metadata.

```python
def test_start_request_locale_propagates():
    req = StartRequest(research_question="improve auc", locale="zh-CN")
    config = build_config_from_request(req)
    assert config.locale == "zh-CN"
```

**Step 2: Run test to verify it fails**

Run: `cd server && pytest tests/test_auto_research_contracts.py -v`
Expected: FAIL because `AutoResearchConfig` does not yet define `locale` and there is no normalized config builder.

**Step 3: Write minimal implementation**

Implement:
- `locale` and project/session metadata fields in `AutoResearchConfig`,
- a small helper in `server.py` that builds config from `StartRequest`,
- DB updates so session payload can store normalized config fields without ad hoc `hasattr` checks.

```python
@dataclass
class AutoResearchConfig:
    max_iterations: int = 3
    primary_metric: str = "auc"
    locale: str = "en-US"
    project_mode: str = "research"
```

**Step 4: Run test to verify it passes**

Run: `cd server && pytest tests/test_auto_research_contracts.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add server/tests/test_auto_research_contracts.py \
  server/backend/auto_research/types.py \
  server/backend/auto_research/server.py \
  server/backend/database/models.py \
  server/backend/database/repositories/auto_research.py
git commit -m "feat: normalize auto research session contracts"
```

### Task 2: Unify workspace and sandbox semantics

**Files:**
- Create: `server/tests/test_auto_research_sandbox_contract.py`
- Modify: `server/backend/auto_research/sandbox_base.py`
- Modify: `server/backend/auto_research/sandbox.py`
- Modify: `server/backend/auto_research/apptainer_sandbox.py`
- Modify: `server/backend/auto_research/code_agent.py`
- Modify: `server/backend/auto_research/interactive_agent.py`
- Modify: `server/backend/auto_research/prompts.py`

**Step 1: Write the failing tests**

Add tests that prove:
- local fallback uses the provided workspace and output contract,
- interactive `write_file()` and `run_command()` see the same workspace,
- `OUTPUT_DIR`, `WSI_DIR`, and `FEATURES_DIR` are present in every backend contract.

```python
def test_local_backend_exposes_runtime_env():
    env = build_runtime_env(output_dir="/tmp/out")
    assert env["OUTPUT_DIR"] == "/tmp/out"
```

**Step 2: Run tests to verify they fail**

Run: `cd server && pytest tests/test_auto_research_sandbox_contract.py -v`
Expected: FAIL because local fallback drops env and mount data, and interactive execution does not share a real workspace contract.

**Step 3: Write minimal implementation**

Implement:
- one shared runtime contract object or helper,
- `execute_command()` support that respects `workspace_dir` and `run_cwd`,
- local fallback wiring for `data_mounts`, `env_vars`, `rw_paths`,
- prompt text that matches real mounted paths,
- removal of `proc.returncode` outer-scope access in local fallback.

```python
runtime = build_runtime_contract(
    workspace_dir=workspace_dir,
    output_dir=output_dir,
    data_mounts=data_mounts,
)
```

**Step 4: Run tests to verify they pass**

Run: `cd server && pytest tests/test_auto_research_sandbox_contract.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add server/tests/test_auto_research_sandbox_contract.py \
  server/backend/auto_research/sandbox_base.py \
  server/backend/auto_research/sandbox.py \
  server/backend/auto_research/apptainer_sandbox.py \
  server/backend/auto_research/code_agent.py \
  server/backend/auto_research/interactive_agent.py \
  server/backend/auto_research/prompts.py
git commit -m "fix: unify auto research sandbox workspace contract"
```

### Task 3: Make experiment runs and artifacts first-class

**Files:**
- Create: `server/tests/test_auto_research_artifacts.py`
- Create: `server/backend/auto_research/evidence.py`
- Modify: `server/backend/database/models.py`
- Modify: `server/backend/database/repositories/auto_research.py`
- Modify: `server/backend/auto_research/server.py`
- Modify: `server/backend/auto_research/code_agent.py`
- Modify: `server/backend/auto_research/nodes.py`

**Step 1: Write the failing test**

Add tests that prove:
- a completed run persists structured artifacts,
- the repository can list artifacts by session/run,
- a result summary can point back to logs, metrics, and output files.

```python
def test_artifact_manifest_is_persisted():
    manifest = persist_run_artifacts(run_id="r1", artifacts=[{"kind": "metrics"}])
    assert manifest[0]["kind"] == "metrics"
```

**Step 2: Run test to verify it fails**

Run: `cd server && pytest tests/test_auto_research_artifacts.py -v`
Expected: FAIL because there is no artifact model/helper yet.

**Step 3: Write minimal implementation**

Implement:
- structured artifact records in DB or event payloads,
- a small `evidence.py` helper for artifact manifests and claim links,
- run completion hooks in `code_agent.py` / `nodes.py` that emit artifacts consistently.

```python
artifact = {
    "kind": "metrics",
    "path": metrics_path,
    "run_id": run_id,
}
```

**Step 4: Run test to verify it passes**

Run: `cd server && pytest tests/test_auto_research_artifacts.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add server/tests/test_auto_research_artifacts.py \
  server/backend/auto_research/evidence.py \
  server/backend/database/models.py \
  server/backend/database/repositories/auto_research.py \
  server/backend/auto_research/server.py \
  server/backend/auto_research/code_agent.py \
  server/backend/auto_research/nodes.py
git commit -m "feat: persist auto research artifacts and evidence"
```

### Task 4: Split orchestration into explicit research stages

**Files:**
- Create: `server/tests/test_auto_research_flow.py`
- Modify: `server/backend/auto_research/builder.py`
- Modify: `server/backend/auto_research/nodes.py`
- Modify: `server/backend/auto_research/types.py`
- Modify: `server/backend/auto_research/literature.py`
- Modify: `server/backend/auto_research/verifier.py`

**Step 1: Write the failing test**

Add tests that prove the graph can move through:
- intake,
- grounding,
- experiment loop,
- evidence consolidation,
- paper generation.

```python
def test_graph_routes_from_grounding_to_experimentation():
    state = build_state(phase="grounding")
    assert route_next_phase(state) == "experiment"
```

**Step 2: Run test to verify it fails**

Run: `cd server && pytest tests/test_auto_research_flow.py -v`
Expected: FAIL because these stages are not yet first-class routing concepts.

**Step 3: Write minimal implementation**

Implement:
- explicit phase names in `types.py`,
- clearer graph transitions in `builder.py`,
- stage-specific state updates in `nodes.py`,
- a distinct evidence consolidation phase before final report writing.

```python
PHASE_EVIDENCE = "evidence"
PHASE_PAPER = "paper"
```

**Step 4: Run test to verify it passes**

Run: `cd server && pytest tests/test_auto_research_flow.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add server/tests/test_auto_research_flow.py \
  server/backend/auto_research/builder.py \
  server/backend/auto_research/nodes.py \
  server/backend/auto_research/types.py \
  server/backend/auto_research/literature.py \
  server/backend/auto_research/verifier.py
git commit -m "refactor: split auto research into explicit stages"
```

### Task 5: Add evidence-driven paper generation

**Files:**
- Create: `server/tests/test_auto_research_paper_writer.py`
- Create: `server/backend/auto_research/paper_writer.py`
- Modify: `server/backend/auto_research/prompts.py`
- Modify: `server/backend/auto_research/nodes.py`
- Modify: `server/backend/auto_research/server.py`
- Modify: `server/backend/auto_research/cli.py`

**Step 1: Write the failing test**

Add tests that prove:
- paper sections are generated from evidence inputs,
- unsupported claims are marked as TODO or limitation,
- report export and paper export are distinct outputs.

```python
def test_paper_writer_marks_unbacked_claims():
    draft = build_paper_draft(claims=[{"text": "best model", "evidence": []}])
    assert "TODO" in draft["limitations"]
```

**Step 2: Run test to verify it fails**

Run: `cd server && pytest tests/test_auto_research_paper_writer.py -v`
Expected: FAIL because there is no dedicated paper writer module.

**Step 3: Write minimal implementation**

Implement:
- `paper_writer.py` with section builders,
- prompt templates that accept evidence manifests and citations,
- final session outputs for `report.md` and `paper.md`,
- CLI/API wiring to surface those outputs.

```python
def build_results_section(best_runs, claims, citations):
    ...
```

**Step 4: Run test to verify it passes**

Run: `cd server && pytest tests/test_auto_research_paper_writer.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add server/tests/test_auto_research_paper_writer.py \
  server/backend/auto_research/paper_writer.py \
  server/backend/auto_research/prompts.py \
  server/backend/auto_research/nodes.py \
  server/backend/auto_research/server.py \
  server/backend/auto_research/cli.py
git commit -m "feat: add evidence-driven paper writer"
```

### Task 6: Expose project, run, artifact, and draft surfaces

**Files:**
- Create: `server/tests/test_auto_research_api.py`
- Modify: `server/backend/auto_research/server.py`
- Modify: `server/backend/auto_research/cli.py`
- Modify: `server/backend/database/repositories/auto_research.py`
- Modify: `docs/auto-research-plan.md`
- Modify: `docs/plans/2026-04-02-auto-research-platform-design.md`

**Step 1: Write the failing test**

Add tests that prove the API can:
- create a session with normalized config,
- fetch runs and artifacts,
- fetch report/paper outputs,
- expose enough metadata for a future UI.

```python
def test_get_session_artifacts_returns_manifest(client):
    response = client.get("/api/auto-research/sessions/ar_1/artifacts")
    assert response.status_code == 200
```

**Step 2: Run test to verify it fails**

Run: `cd server && pytest tests/test_auto_research_api.py -v`
Expected: FAIL because these endpoints and CLI surfaces do not yet exist.

**Step 3: Write minimal implementation**

Implement:
- session/run/artifact/report endpoints,
- matching CLI commands or subcommands,
- documentation refresh for the stabilized Phase 1 architecture.

```python
@router.get("/sessions/{session_id}/artifacts")
async def get_session_artifacts(...):
    ...
```

**Step 4: Run test to verify it passes**

Run: `cd server && pytest tests/test_auto_research_api.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add server/tests/test_auto_research_api.py \
  server/backend/auto_research/server.py \
  server/backend/auto_research/cli.py \
  server/backend/database/repositories/auto_research.py \
  docs/auto-research-plan.md \
  docs/plans/2026-04-02-auto-research-platform-design.md
git commit -m "feat: expose auto research runs artifacts and drafts"
```

### Task 7: Add end-to-end smoke coverage for the Phase 1 loop

**Files:**
- Create: `server/tests/test_auto_research_smoke.py`
- Modify: `server/backend/auto_research/test_data/`
- Modify: `server/backend/auto_research/start.sh`
- Modify: `docs/auto-research-code-review-2026-04-01.md`

**Step 1: Write the failing smoke tests**

Add smoke coverage for:
- local backend end-to-end run,
- interactive workspace write-and-run path,
- paper output generation after a minimal successful run.

```python
def test_local_backend_smoke_generates_report(tmp_path):
    result = run_minimal_auto_research_session(tmp_path)
    assert result.report_path.exists()
```

**Step 2: Run smoke tests to verify they fail**

Run: `cd server && pytest tests/test_auto_research_smoke.py -v`
Expected: FAIL until the Phase 1 contracts are in place.

**Step 3: Write minimal implementation**

Implement:
- test helpers using local test data,
- a deterministic minimal session path,
- start script notes or flags that support reproducible local verification.

```python
def run_minimal_auto_research_session(tmp_path):
    ...
```

**Step 4: Run smoke tests to verify they pass**

Run: `cd server && pytest tests/test_auto_research_smoke.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add server/tests/test_auto_research_smoke.py \
  server/backend/auto_research/test_data \
  server/backend/auto_research/start.sh \
  docs/auto-research-code-review-2026-04-01.md
git commit -m "test: add auto research phase 1 smoke coverage"
```

## Recommended Order

Execute tasks in this order without skipping:
1. Task 1: config and session contracts
2. Task 2: sandbox and workspace contract
3. Task 3: artifacts and evidence
4. Task 4: explicit stage orchestration
5. Task 5: paper writer
6. Task 6: API and CLI surfaces
7. Task 7: smoke coverage

## Definition Of Done

Phase 1 is done when all of the following are true:
- a session has a normalized config and locale contract,
- all backends share one execution contract,
- local fallback and interactive mode behave coherently,
- every completed run records artifacts and evidence,
- the graph includes evidence consolidation and paper generation,
- the API and CLI expose runs, artifacts, and paper outputs,
- smoke tests prove the end-to-end loop works on local test data.
