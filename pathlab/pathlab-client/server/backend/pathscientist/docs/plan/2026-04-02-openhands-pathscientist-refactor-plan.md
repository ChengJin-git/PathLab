# OpenHands-Based PathScientist Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
>
> Update 2026-04-05:
> This document is retained as architectural rationale for the OpenHands-first
> direction and migration thinking.
> It is no longer the primary project roadmap.
> The active top-level roadmap is
> `server/backend/pathscientist/docs/plan/2026-04-05-pathscientist-master-plan.md`.

**Goal:** Rebuild the current PathLab `auto_research` prototype on top of an OpenHands fork so the system becomes a repo-scale coding agent platform with experiment execution, evidence capture, and paper generation.

**Architecture:** Use a new OpenHands fork as the primary runtime and product shell, then port PathLab-specific capabilities into a dedicated vertical package named `openhands/pathscientist`. Keep the current PathLab repository as the source of domain logic during migration, and move in layers: contracts first, execution second, domain assets third, orchestration fourth, product surfaces last.

**Tech Stack:** OpenHands, Python, FastAPI, SQLAlchemy, LangGraph/LangChain, Apptainer, Docker, pytest, PathLab training code, Markdown/LaTeX export

---

## Working Assumptions

- Current repo root: `.`
- New OpenHands fork root: `../pathlab-openhands`
- New PathScientist package root inside the fork: `../pathlab-openhands/openhands/pathscientist`
- New test root inside the fork: `../pathlab-openhands/tests/pathscientist`
- Current PathLab prototype source of truth during migration:
  - `server/backend/auto_research/`
  - `server/backend/database/repositories/auto_research.py`
  - `server/backend/database/models.py`

If you later choose a different fork directory, only the path prefix changes; the package layout should remain the same.

## Strategic Decision

This refactor should **not** try to merge two large codebases in place.

Use this model instead:
- OpenHands fork = runtime, repo workspace, agent shell, product entrypoints
- PathScientist vertical = literature, experiment planning, training execution, result analysis, paper writing
- Current PathLab repo = domain source during migration, then optional downstream integration target

This avoids turning the current PathLab backend into a second-rate coding platform and avoids turning OpenHands into a one-off experiment script runner.

## Target Repository Layout

```text
../pathlab-openhands/
  .openhands/
    setup.sh
    pre-commit.sh
  openhands/
    pathscientist/
      __init__.py
      config.py
      contracts.py
      orchestrator.py
      sessions.py
      evidence.py
      api/
        __init__.py
        schemas.py
        router.py
      agents/
        __init__.py
        code_agent.py
        interactive_agent.py
        planner.py
        result_analyst.py
        paper_writer.py
      runtime/
        __init__.py
        workspace.py
        sandbox_base.py
        apptainer.py
        docker.py
        local.py
      domain/
        __init__.py
        literature.py
        knowhow.py
        skills/
        templates/
      storage/
        __init__.py
        models.py
        repository.py
      prompts.py
  tests/
    pathscientist/
      test_contracts.py
      test_runtime_contract.py
      test_agents.py
      test_artifacts.py
      test_paper_writer.py
      test_api.py
      test_smoke.py
```

## Current-To-Target Mapping

- `server/backend/auto_research/code_agent.py` -> `../pathlab-openhands/openhands/pathscientist/agents/code_agent.py`
- `server/backend/auto_research/interactive_agent.py` -> `../pathlab-openhands/openhands/pathscientist/agents/interactive_agent.py`
- `server/backend/auto_research/sandbox_base.py` -> `../pathlab-openhands/openhands/pathscientist/runtime/sandbox_base.py`
- `server/backend/auto_research/apptainer_sandbox.py` -> `../pathlab-openhands/openhands/pathscientist/runtime/apptainer.py`
- `server/backend/auto_research/sandbox.py` -> `../pathlab-openhands/openhands/pathscientist/runtime/docker.py`
- local fallback in `server/backend/auto_research/code_agent.py` -> `../pathlab-openhands/openhands/pathscientist/runtime/local.py`
- `server/backend/auto_research/literature.py` -> `../pathlab-openhands/openhands/pathscientist/domain/literature.py`
- `server/backend/auto_research/knowhow.py` -> `../pathlab-openhands/openhands/pathscientist/domain/knowhow.py`
- `server/backend/auto_research/prompts.py` -> `../pathlab-openhands/openhands/pathscientist/prompts.py`
- `server/backend/auto_research/skills/*.yaml` -> `../pathlab-openhands/openhands/pathscientist/domain/skills/*.yaml`
- `server/backend/auto_research/templates/*` -> `../pathlab-openhands/openhands/pathscientist/domain/templates/*`
- `server/backend/database/repositories/auto_research.py` -> `../pathlab-openhands/openhands/pathscientist/storage/repository.py`
- `server/backend/database/models.py` auto-research tables -> `../pathlab-openhands/openhands/pathscientist/storage/models.py`

## Refactor Principles

- Do not port current bugs into the new fork; fix contracts during migration.
- Do not start with free-form autonomous science; start with constrained, reproducible workflows.
- Do not embed PathLab research logic directly into generic OpenHands runtime folders when a vertical package can isolate it.
- Preserve execution evidence: code diff, env, mounts, logs, metrics, artifacts, and claims.
- Keep the current prototype runnable until the new fork passes end-to-end smoke coverage.

## Milestones

- Milestone A: OpenHands fork boots with a PathScientist package skeleton.
- Milestone B: One unified runtime contract works across Apptainer, Docker, and local fallback.
- Milestone C: One repo-scale code agent can edit files, run experiments, and persist artifacts.
- Milestone D: One complete session can produce report and paper draft outputs.
- Milestone E: Cutover path from current prototype is documented and reversible.

### Task 1: Freeze the current prototype and write migration contracts

**Files:**
- Create: `docs/plans/2026-04-02-openhands-pathlab-refactor-plan.md`
- Create: `docs/plans/2026-04-02-openhands-pathlab-migration-checklist.md`
- Modify: `docs/auto-research-code-review-2026-04-01.md`
- Modify: `docs/plans/2026-04-02-auto-research-platform-design.md`

**Step 1: Write the migration checklist**

Document the source modules, known defects, and contract mismatches that must not be carried over.

```md
- local fallback must not reference out-of-scope proc handles
- interactive write_file and run_command must share one workspace contract
- locale must propagate from API to session config
```

**Step 2: Review the checklist against the current code**

Run: `rg -n "locale|execute_command|run_training|interactive|fix_loop|ratchet" server/backend/auto_research server/backend/database`
Expected: Confirm all current hot spots are captured in the checklist.

**Step 3: Mark migration boundaries explicitly**

Update the current docs so engineers know which modules will be ported and which are deprecated after cutover.

```md
Current repo remains the source implementation until Milestone D.
New feature work after Milestone B should target the OpenHands fork first.
```

**Step 4: Re-read the docs for consistency**

Run: `sed -n '1,240p' docs/plans/2026-04-02-openhands-pathlab-refactor-plan.md`
Expected: Contract, scope, and cutover wording are aligned.

**Step 5: Commit**

```bash
git add docs/plans/2026-04-02-openhands-pathlab-refactor-plan.md \
  docs/plans/2026-04-02-openhands-pathlab-migration-checklist.md \
  docs/auto-research-code-review-2026-04-01.md \
  docs/plans/2026-04-02-auto-research-platform-design.md
git commit -m "docs: freeze auto research migration contracts"
```

### Task 2: Bootstrap the OpenHands fork as the new platform shell

**Files:**
- Create: `../pathlab-openhands/.openhands/setup.sh`
- Create: `../pathlab-openhands/.openhands/pre-commit.sh`
- Create: `../pathlab-openhands/openhands/pathscientist/__init__.py`
- Create: `../pathlab-openhands/openhands/pathscientist/config.py`
- Create: `../pathlab-openhands/openhands/pathscientist/contracts.py`
- Create: `../pathlab-openhands/tests/pathscientist/test_contracts.py`
- Modify: `../pathlab-openhands/README.md`
- Modify: `../pathlab-openhands/pyproject.toml`

**Step 1: Write the failing contract tests**

Define tests for the PathScientist package import path and configuration object.

```python
def test_pathscientist_package_imports():
    import openhands.pathscientist
    assert openhands.pathscientist is not None
```

**Step 2: Run test to verify it fails**

Run: `pytest ../pathlab-openhands/tests/pathscientist/test_contracts.py -v`
Expected: FAIL because the package and config modules do not yet exist.

**Step 3: Create the package skeleton**

Add a minimal package with:
- versioned package init,
- refactor-time configuration,
- explicit runtime contracts.

```python
@dataclass
class PathLabResearchConfig:
    project_mode: str = "pathscientist"
    locale: str = "en-US"
```

**Step 4: Run test to verify it passes**

Run: `pytest ../pathlab-openhands/tests/pathscientist/test_contracts.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git -C ../pathlab-openhands add .openhands/setup.sh \
  .openhands/pre-commit.sh \
  openhands/pathscientist/__init__.py \
  openhands/pathscientist/config.py \
  openhands/pathscientist/contracts.py \
  tests/pathscientist/test_contracts.py \
  README.md pyproject.toml
git -C ../pathlab-openhands commit -m "feat: bootstrap pathscientist package in openhands fork"
```

### Task 3: Rebuild the runtime layer around one workspace and sandbox contract

**Files:**
- Create: `../pathlab-openhands/openhands/pathscientist/runtime/__init__.py`
- Create: `../pathlab-openhands/openhands/pathscientist/runtime/workspace.py`
- Create: `../pathlab-openhands/openhands/pathscientist/runtime/sandbox_base.py`
- Create: `../pathlab-openhands/openhands/pathscientist/runtime/apptainer.py`
- Create: `../pathlab-openhands/openhands/pathscientist/runtime/docker.py`
- Create: `../pathlab-openhands/openhands/pathscientist/runtime/local.py`
- Create: `../pathlab-openhands/tests/pathscientist/test_runtime_contract.py`
- Reference: `server/backend/auto_research/sandbox_base.py`
- Reference: `server/backend/auto_research/apptainer_sandbox.py`
- Reference: `server/backend/auto_research/sandbox.py`
- Reference: `server/backend/auto_research/code_agent.py`

**Step 1: Write the failing runtime tests**

Add tests for:
- shared `workspace_dir`,
- shared `run_cwd`,
- env propagation,
- artifact path semantics,
- local fallback parity.

```python
def test_local_runtime_exposes_output_dir(tmp_path):
    runtime = build_runtime_contract(workspace_dir=tmp_path, output_dir=tmp_path / "out")
    assert runtime.env_vars["OUTPUT_DIR"].endswith("out")
```

**Step 2: Run test to verify it fails**

Run: `pytest ../pathlab-openhands/tests/pathscientist/test_runtime_contract.py -v`
Expected: FAIL because the runtime layer does not yet exist.

**Step 3: Port and normalize runtime code**

Port the current sandbox logic, but normalize it into three explicit backends plus one contract builder.

```python
@dataclass
class RuntimeContract:
    workspace_dir: str
    run_cwd: str
    output_dir: str
    data_mounts: dict[str, str]
    env_vars: dict[str, str]
```

**Step 4: Run test to verify it passes**

Run: `pytest ../pathlab-openhands/tests/pathscientist/test_runtime_contract.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git -C ../pathlab-openhands add openhands/pathscientist/runtime \
  tests/pathscientist/test_runtime_contract.py
git -C ../pathlab-openhands commit -m "feat: add pathscientist runtime contract"
```

### Task 4: Port domain assets: skills, templates, literature, and know-how

**Files:**
- Create: `../pathlab-openhands/openhands/pathscientist/domain/__init__.py`
- Create: `../pathlab-openhands/openhands/pathscientist/domain/literature.py`
- Create: `../pathlab-openhands/openhands/pathscientist/domain/knowhow.py`
- Create: `../pathlab-openhands/openhands/pathscientist/domain/skills/__init__.py`
- Create: `../pathlab-openhands/openhands/pathscientist/domain/templates/__init__.py`
- Copy: `server/backend/auto_research/skills/*.yaml` -> `../pathlab-openhands/openhands/pathscientist/domain/skills/`
- Copy: `server/backend/auto_research/templates/*` -> `../pathlab-openhands/openhands/pathscientist/domain/templates/`
- Create: `../pathlab-openhands/tests/pathscientist/test_domain_assets.py`

**Step 1: Write the failing tests**

Add tests that prove:
- skills load,
- templates resolve,
- know-how retrieval returns structured data,
- literature adapters expose normalized source records.

```python
def test_skill_registry_loads_yaml_assets():
    registry = load_skills()
    assert "mil_classification" in registry
```

**Step 2: Run test to verify it fails**

Run: `pytest ../pathlab-openhands/tests/pathscientist/test_domain_assets.py -v`
Expected: FAIL because the domain package and copied assets are not wired up.

**Step 3: Port the assets with thin adapters**

Keep the first pass conservative:
- copy YAML/templates largely unchanged,
- wrap them with new loaders and path resolution,
- do not rewrite domain logic yet.

```python
def get_template_content(name: str) -> str:
    return (TEMPLATES_DIR / name).read_text(encoding="utf-8")
```

**Step 4: Run test to verify it passes**

Run: `pytest ../pathlab-openhands/tests/pathscientist/test_domain_assets.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git -C ../pathlab-openhands add openhands/pathscientist/domain \
  tests/pathscientist/test_domain_assets.py
git -C ../pathlab-openhands commit -m "feat: port pathscientist domain assets"
```

### Task 5: Rebuild storage around project, session, run, artifact, and draft entities

**Files:**
- Create: `../pathlab-openhands/openhands/pathscientist/storage/__init__.py`
- Create: `../pathlab-openhands/openhands/pathscientist/storage/models.py`
- Create: `../pathlab-openhands/openhands/pathscientist/storage/repository.py`
- Create: `../pathlab-openhands/openhands/pathscientist/evidence.py`
- Create: `../pathlab-openhands/tests/pathscientist/test_artifacts.py`
- Reference: `server/backend/database/models.py`
- Reference: `server/backend/database/repositories/auto_research.py`

**Step 1: Write the failing tests**

Add tests that prove:
- a session persists normalized config,
- a run persists logs and metrics,
- artifacts can be listed by run,
- claims can link to evidence.

```python
def test_run_artifact_manifest_roundtrip(repo):
    run_id = repo.create_run(...)
    repo.add_artifact(run_id, kind="metrics", path="/tmp/metrics.json")
    assert repo.list_artifacts(run_id)[0].kind == "metrics"
```

**Step 2: Run test to verify it fails**

Run: `pytest ../pathlab-openhands/tests/pathscientist/test_artifacts.py -v`
Expected: FAIL because the storage layer does not yet exist.

**Step 3: Implement the storage model**

Create a new storage package instead of embedding this data in generic OpenHands models.

```python
class ResearchSession(...): ...
class ExperimentRun(...): ...
class Artifact(...): ...
class PaperDraft(...): ...
```

**Step 4: Run test to verify it passes**

Run: `pytest ../pathlab-openhands/tests/pathscientist/test_artifacts.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git -C ../pathlab-openhands add openhands/pathscientist/storage \
  openhands/pathscientist/evidence.py \
  tests/pathscientist/test_artifacts.py
git -C ../pathlab-openhands commit -m "feat: add pathscientist storage and evidence"
```

### Task 6: Replace the single-script experiment agent with a repo-scale code agent adapter

**Files:**
- Create: `../pathlab-openhands/openhands/pathscientist/agents/__init__.py`
- Create: `../pathlab-openhands/openhands/pathscientist/agents/code_agent.py`
- Create: `../pathlab-openhands/openhands/pathscientist/agents/interactive_agent.py`
- Create: `../pathlab-openhands/openhands/pathscientist/prompts.py`
- Create: `../pathlab-openhands/tests/pathscientist/test_agents.py`
- Reference: `server/backend/auto_research/code_agent.py`
- Reference: `server/backend/auto_research/interactive_agent.py`

**Step 1: Write the failing tests**

Add tests for:
- multi-file workspace edits,
- patch-mode vs full-file mode,
- traceback-guided repair loop,
- interactive tool loop using one workspace contract.

```python
def test_code_agent_can_modify_two_files_in_workspace(tmp_path):
    result = run_code_agent_task(tmp_path, files=["train.py", "config.yaml"])
    assert result.modified_files == {"train.py", "config.yaml"}
```

**Step 2: Run test to verify it fails**

Run: `pytest ../pathlab-openhands/tests/pathscientist/test_agents.py -v`
Expected: FAIL because the new agent adapter does not yet exist.

**Step 3: Implement the repo-scale adapter**

Port the good parts of the current code agent:
- ratchet behavior,
- diff mode,
- fix loop,
- quick check,
- skill constraints,
- interactive ReAct fallback,

but redesign the agent so it works against a workspace with multiple files rather than only `train.py`.

```python
@dataclass
class CodeAgentResult:
    modified_files: list[str]
    artifacts: list[dict]
    metrics: dict
```

**Step 4: Run test to verify it passes**

Run: `pytest ../pathlab-openhands/tests/pathscientist/test_agents.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git -C ../pathlab-openhands add openhands/pathscientist/agents \
  openhands/pathscientist/prompts.py \
  tests/pathscientist/test_agents.py
git -C ../pathlab-openhands commit -m "feat: add repo-scale pathscientist code agents"
```

### Task 7: Add the orchestrator: intake, grounding, experiment loop, evidence, paper

**Files:**
- Create: `../pathlab-openhands/openhands/pathscientist/orchestrator.py`
- Create: `../pathlab-openhands/openhands/pathscientist/sessions.py`
- Create: `../pathlab-openhands/openhands/pathscientist/agents/planner.py`
- Create: `../pathlab-openhands/openhands/pathscientist/agents/result_analyst.py`
- Create: `../pathlab-openhands/openhands/pathscientist/agents/paper_writer.py`
- Create: `../pathlab-openhands/tests/pathscientist/test_orchestrator.py`
- Reference: `server/backend/auto_research/nodes.py`
- Reference: `server/backend/auto_research/builder.py`
- Reference: `server/backend/auto_research/verifier.py`

**Step 1: Write the failing orchestration tests**

Add tests that prove one session can move through:
- intake,
- grounding,
- experiment loop,
- evidence consolidation,
- paper generation.

```python
def test_session_routes_from_grounding_to_experiment():
    session = build_session(phase="grounding")
    assert next_phase(session) == "experiment"
```

**Step 2: Run test to verify it fails**

Run: `pytest ../pathlab-openhands/tests/pathscientist/test_orchestrator.py -v`
Expected: FAIL because the new orchestrator package does not yet exist.

**Step 3: Implement the staged orchestrator**

Do not port the current graph one-to-one; instead build explicit stage methods and keep graph orchestration as an optional inner detail.

```python
PHASE_INTAKE = "intake"
PHASE_GROUNDING = "grounding"
PHASE_EXPERIMENT = "experiment"
PHASE_EVIDENCE = "evidence"
PHASE_PAPER = "paper"
```

**Step 4: Run test to verify it passes**

Run: `pytest ../pathlab-openhands/tests/pathscientist/test_orchestrator.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git -C ../pathlab-openhands add openhands/pathscientist/orchestrator.py \
  openhands/pathscientist/sessions.py \
  openhands/pathscientist/agents/planner.py \
  openhands/pathscientist/agents/result_analyst.py \
  openhands/pathscientist/agents/paper_writer.py \
  tests/pathscientist/test_orchestrator.py
git -C ../pathlab-openhands commit -m "feat: add staged pathscientist orchestrator"
```

### Task 8: Expose product surfaces: API, CLI hooks, and report outputs

**Files:**
- Create: `../pathlab-openhands/openhands/pathscientist/api/__init__.py`
- Create: `../pathlab-openhands/openhands/pathscientist/api/schemas.py`
- Create: `../pathlab-openhands/openhands/pathscientist/api/router.py`
- Create: `../pathlab-openhands/tests/pathscientist/test_api.py`
- Modify: `../pathlab-openhands/README.md`
- Modify: `../pathlab-openhands/.openhands/setup.sh`
- Modify: `../pathlab-openhands/.openhands/pre-commit.sh`

**Step 1: Write the failing API tests**

Add tests that prove the fork can:
- start a PathLab research session,
- list runs and artifacts,
- fetch report and paper outputs,
- expose session metadata for a future UI.

```python
def test_get_session_artifacts(client):
    response = client.get("/api/pathlab-research/sessions/s1/artifacts")
    assert response.status_code == 200
```

**Step 2: Run test to verify it fails**

Run: `pytest ../pathlab-openhands/tests/pathscientist/test_api.py -v`
Expected: FAIL because no PathLab-specific router exists yet.

**Step 3: Implement the product surface**

Expose a minimal but complete surface:
- start session,
- get session,
- get runs,
- get artifacts,
- get report,
- get paper draft.

```python
@router.get("/sessions/{session_id}/artifacts")
async def get_session_artifacts(...):
    ...
```

**Step 4: Run test to verify it passes**

Run: `pytest ../pathlab-openhands/tests/pathscientist/test_api.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git -C ../pathlab-openhands add openhands/pathscientist/api \
  tests/pathscientist/test_api.py \
  README.md .openhands/setup.sh .openhands/pre-commit.sh
git -C ../pathlab-openhands commit -m "feat: expose pathscientist api surfaces"
```

### Task 9: Add cutover adapters back to the current PathLab repo

**Files:**
- Create: `server/backend/auto_research/openhands_adapter.py`
- Create: `server/tests/test_openhands_adapter.py`
- Modify: `server/backend/auto_research/server.py`
- Modify: `server/backend/auto_research/cli.py`
- Modify: `docs/auto-research-plan.md`

**Step 1: Write the failing adapter tests**

Add tests that prove the current PathLab backend can:
- proxy a request into the new OpenHands-based platform,
- read back session state,
- preserve backward-compatible response fields where required.

```python
def test_current_server_can_proxy_to_openhands_platform(client):
    response = client.post("/api/auto-research/start", json={"research_question": "improve auc"})
    assert response.status_code == 200
```

**Step 2: Run test to verify it fails**

Run: `cd server && pytest tests/test_openhands_adapter.py -v`
Expected: FAIL because the adapter does not yet exist.

**Step 3: Implement the adapter**

Create a transitional adapter so current users can keep using the old surface while the new platform becomes the real backend.

```python
class OpenHandsResearchAdapter:
    async def start_session(self, request):
        ...
```

**Step 4: Run test to verify it passes**

Run: `cd server && pytest tests/test_openhands_adapter.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add server/backend/auto_research/openhands_adapter.py \
  server/tests/test_openhands_adapter.py \
  server/backend/auto_research/server.py \
  server/backend/auto_research/cli.py \
  docs/auto-research-plan.md
git commit -m "feat: add openhands migration adapter for auto research"
```

### Task 10: Prove end-to-end behavior and define the cutover gate

**Files:**
- Create: `../pathlab-openhands/tests/pathscientist/test_smoke.py`
- Create: `../pathlab-openhands/tests/pathscientist/test_cutover_gate.py`
- Modify: `docs/plans/2026-04-02-openhands-pathlab-migration-checklist.md`
- Modify: `docs/plans/2026-04-02-openhands-pathlab-refactor-plan.md`

**Step 1: Write the failing smoke tests**

Add smoke coverage for:
- one local backend session,
- one interactive write-and-run session,
- one report and paper draft export,
- one adapter-backed request from the current PathLab API.

```python
def test_local_session_generates_report_and_artifacts(tmp_path):
    result = run_minimal_session(tmp_path)
    assert result.report_path.exists()
    assert result.artifacts
```

**Step 2: Run smoke tests to verify they fail**

Run: `pytest ../pathlab-openhands/tests/pathscientist/test_smoke.py -v`
Expected: FAIL until all previous tasks are complete.

**Step 3: Define the cutover gate**

Document the exact go/no-go rules:
- runtime parity proven,
- artifacts persisted,
- paper writer grounded in evidence,
- adapter path stable,
- no known blocker from the migration checklist remains open.

```md
Cut over only when Milestones A-E are complete and all smoke tests pass.
```

**Step 4: Run the full verification suite**

Run: `pytest ../pathlab-openhands/tests/pathscientist -v && cd server && pytest tests/test_openhands_adapter.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git -C ../pathlab-openhands add tests/pathscientist/test_smoke.py \
  tests/pathscientist/test_cutover_gate.py
git -C ../pathlab-openhands commit -m "test: add end-to-end pathscientist smoke coverage"

git add docs/plans/2026-04-02-openhands-pathlab-migration-checklist.md \
  docs/plans/2026-04-02-openhands-pathlab-refactor-plan.md
git commit -m "docs: define openhands cutover gate for auto research"
```

## Recommended Execution Order

Execute tasks in this exact order:
1. Task 1: freeze prototype and contracts
2. Task 2: bootstrap OpenHands fork shell
3. Task 3: runtime contract
4. Task 4: domain assets
5. Task 5: storage and evidence
6. Task 6: repo-scale code agents
7. Task 7: orchestrator and paper writer
8. Task 8: API and product surfaces
9. Task 9: current PathLab adapter
10. Task 10: smoke tests and cutover gate

## Anti-Goals During Refactor

Do not do these before Milestone D:
- migrate every existing PathLab backend feature into the OpenHands fork,
- build a large custom web UI,
- add distributed tree search,
- generalize beyond computational pathology,
- remove the current prototype before the adapter path is stable.

## Definition Of Done

This refactor is done when all of the following are true:
- the OpenHands fork is the primary runtime for PathLab research sessions,
- the new PathScientist package owns runtime, domain, storage, orchestration, and paper generation,
- the code agent operates on a real workspace with multi-file semantics,
- all backends honor one runtime contract,
- sessions persist artifacts and evidence links,
- one session can generate both report and paper draft outputs,
- the current PathLab API can proxy to the new platform during transition,
- smoke tests validate the full cutover path.

## Why This Plan Is Better Than In-Place Refactoring The Current Prototype

- It upgrades the weakest part first: repo-scale runtime and workspace semantics.
- It preserves your current domain advantage: pathology-specific skills, templates, and evaluation logic.
- It avoids entangling research logic with generic coding-platform internals.
- It gives you a reversible migration path instead of a one-shot rewrite.
- It creates a platform that can later support richer coding, experimentation, and paper workflows without another full rewrite.
