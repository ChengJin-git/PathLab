# PathScientist Code Agent Gap Closure Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the gap between the current PathScientist code agent and mature open-source code agents by first fixing runtime correctness, then adding session-safe orchestration, repo-scale grounding, and checkpointed recovery.

**Architecture:** Keep OpenHands SDK as the core agent loop, but move critical workflow guarantees out of the prompt and into runtime state. Introduce explicit session identity, session-scoped tool dependencies, authoritative run artifacts, and guarded experiment policy so the agent becomes safe for concurrent sessions and repeatable experiments. After correctness is stable, add repo-map and checkpoint capabilities that are common in stronger open-source code agents.

**Tech Stack:** Python 3.12, OpenHands SDK 1.16.1, OpenHands tools, git-backed LocalWorkspace, pytest

---

## Scope

This plan focuses only on code-agent maturity gaps found in the review:

- per-session isolation
- removal of global tool cross-session leakage
- stale metrics and output correctness
- hard workflow enforcement for validate -> quick check -> full run
- real metrics history and iteration budget
- repo-scale grounding
- checkpoint and rollback ergonomics

Out of scope here:

- SSE streaming
- API routes
- front-end integration
- literature/paper-writer orchestration

Those remain tracked in `server/backend/pathscientist/docs/plan/2026-04-03-code-agent-implementation-plan.md`.

## Success Criteria

Implementation of this plan is complete when all of the following are true:

- two sessions with the same research question never share a workspace or output directory
- tool resolution is session-scoped and safe under concurrent agents
- a failed run can never report metrics from a previous successful run
- `get_metrics` reflects real committed/reverted history rather than prompt-only intent
- full runs are blocked unless the current file revision passed validation and quick check first
- the agent can inspect a repo-level map before editing non-trivial code paths
- the runtime supports named checkpoints and safe restore semantics

### Task 1: Add Regression Harness for Reviewed Failures

**Files:**
- Create: `server/pathscientist_tests/test_agent_runtime_regressions.py`
- Reference: `server/backend/pathscientist/agent.py`
- Reference: `server/backend/pathscientist/config.py`
- Reference: `server/backend/pathscientist/tools/run_experiment.py`
- Reference: `server/backend/pathscientist/tools/metrics.py`

**Step 1: Write the failing tests**

Add the following regression tests:

```python
def test_same_question_creates_distinct_session_workspaces():
    ...


def test_failed_run_does_not_reuse_previous_metrics():
    ...


def test_metrics_tool_reflects_real_history_after_commit_and_revert():
    ...


def test_full_run_requires_quick_check_for_current_revision():
    ...
```

**Step 2: Run test to verify it fails**

Run: `cd server && pytest pathscientist_tests/test_agent_runtime_regressions.py -v`

Expected:

- workspace isolation test fails because current workspace path is derived from hashed question
- stale-metrics test fails because `run_experiment` reuses old `metrics.json`
- metrics-history test fails because `MetricsTracker.record()` is not wired
- quick-check policy test fails because the runtime does not enforce it

**Step 3: Commit the red test harness**

```bash
git add server/pathscientist_tests/test_agent_runtime_regressions.py
git commit -m "test: add pathscientist runtime regression harness"
```

### Task 2: Introduce Explicit Session Identity and Workspace Isolation

**Files:**
- Create: `server/backend/pathscientist/runtime/session.py`
- Modify: `server/backend/pathscientist/config.py`
- Modify: `server/backend/pathscientist/agent.py`
- Modify: `server/backend/pathscientist/cli.py`
- Modify: `server/backend/pathscientist/run.py`
- Test: `server/pathscientist_tests/test_agent_runtime_regressions.py`

**Step 1: Write the failing focused test**

Extract the isolation case into a focused assertion:

```python
def test_same_question_creates_distinct_session_workspaces():
    cfg = PathScientistConfig()
    a = cfg.create_session("same question")
    b = cfg.create_session("same question")
    assert a.workspace_dir != b.workspace_dir
    assert a.output_dir != b.output_dir
```

**Step 2: Run the focused test to verify it fails**

Run: `cd server && pytest pathscientist_tests/test_agent_runtime_regressions.py::test_same_question_creates_distinct_session_workspaces -v`

Expected: FAIL because both sessions currently resolve to the same hashed directory.

**Step 3: Write minimal implementation**

Implement:

- `PathScientistSession` dataclass in `server/backend/pathscientist/runtime/session.py`
- `session_id` generation via `uuid.uuid4().hex`
- `PathScientistConfig.create_session(research_question)` that returns explicit workspace/output paths
- `create_agent()` consumes a session object instead of deriving paths ad hoc
- CLI and runner print session id and resolved paths

Do not keep workspace identity tied to `md5(research_question)`.

**Step 4: Run the focused test to verify it passes**

Run: `cd server && pytest pathscientist_tests/test_agent_runtime_regressions.py::test_same_question_creates_distinct_session_workspaces -v`

Expected: PASS

**Step 5: Commit**

```bash
git add \
  server/backend/pathscientist/runtime/session.py \
  server/backend/pathscientist/config.py \
  server/backend/pathscientist/agent.py \
  server/backend/pathscientist/cli.py \
  server/backend/pathscientist/run.py \
  server/pathscientist_tests/test_agent_runtime_regressions.py
git commit -m "feat: isolate pathscientist sessions and workspaces"
```

### Task 3: Remove Global Cross-Session Tool Leakage

**Files:**
- Create: `server/backend/pathscientist/runtime/session_registry.py`
- Modify: `server/backend/pathscientist/agent.py`
- Modify: `server/backend/pathscientist/tools/run_experiment.py`
- Modify: `server/backend/pathscientist/tools/ratchet.py`
- Modify: `server/backend/pathscientist/tools/metrics.py`
- Modify: `server/backend/pathscientist/tools/workspace_info.py`
- Modify: `server/backend/pathscientist/tools/skill_browser.py`
- Test: `server/pathscientist_tests/test_tool_session_registry.py`

**Step 1: Write the failing test**

```python
def test_two_agents_resolve_tools_to_their_own_session_runtime():
    agent_a, workspace_a, tracker_a = create_agent(...)
    agent_b, workspace_b, tracker_b = create_agent(...)
    assert workspace_a.root != workspace_b.root
    assert resolve_run_experiment_runtime(agent_a) is workspace_a
    assert resolve_run_experiment_runtime(agent_b) is workspace_b
```

**Step 2: Run test to verify it fails**

Run: `cd server && pytest pathscientist_tests/test_tool_session_registry.py -v`

Expected: FAIL because current `register_tool(...)` usage closes over process-global `workspace` and `tracker`.

**Step 3: Write minimal implementation**

Implement a session-scoped dependency registry:

- register tool classes once by stable names
- pass `session_id` through `Tool(name=..., params={"session_id": ...})`
- each tool `create(...)` resolves `workspace`, `tracker`, and session state from `session_registry`
- remove per-agent closure-based `register_tool(...)` calls from `create_agent()`

This keeps OpenHands global tool registration but makes actual resources session-local.

**Step 4: Run test to verify it passes**

Run: `cd server && pytest pathscientist_tests/test_tool_session_registry.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add \
  server/backend/pathscientist/runtime/session_registry.py \
  server/backend/pathscientist/agent.py \
  server/backend/pathscientist/tools/run_experiment.py \
  server/backend/pathscientist/tools/ratchet.py \
  server/backend/pathscientist/tools/metrics.py \
  server/backend/pathscientist/tools/workspace_info.py \
  server/backend/pathscientist/tools/skill_browser.py \
  server/pathscientist_tests/test_tool_session_registry.py
git commit -m "refactor: resolve pathscientist tools from session registry"
```

### Task 4: Make Run Artifacts Authoritative and Eliminate Stale Metrics

**Files:**
- Create: `server/backend/pathscientist/runtime/run_artifacts.py`
- Modify: `server/backend/pathscientist/tools/run_experiment.py`
- Modify: `server/backend/pathscientist/config.py`
- Modify: `server/backend/pathscientist/runtime/workspace.py`
- Test: `server/pathscientist_tests/test_agent_runtime_regressions.py`

**Step 1: Write the failing focused test**

```python
def test_failed_run_does_not_reuse_previous_metrics():
    successful = run_experiment(...)
    failed = run_experiment(...)
    assert successful.metrics["test"]["auc"] == 0.9
    assert failed.exit_code != 0
    assert failed.metrics == {}
```

**Step 2: Run test to verify it fails**

Run: `cd server && pytest pathscientist_tests/test_agent_runtime_regressions.py::test_failed_run_does_not_reuse_previous_metrics -v`

Expected: FAIL because the second run reads the previous `metrics.json`.

**Step 3: Write minimal implementation**

Implement authoritative per-run output handling:

- allocate `output/runs/<run_id>/` for every run
- inject that run dir as `OUTPUT_DIR`
- read metrics only from that run dir
- expose `run_id` and `run_dir` in `RunExperimentObservation`
- optionally update `output/latest/` only after a successful run
- never read root-level `metrics.json` from a previous attempt

**Step 4: Run test to verify it passes**

Run: `cd server && pytest pathscientist_tests/test_agent_runtime_regressions.py::test_failed_run_does_not_reuse_previous_metrics -v`

Expected: PASS

**Step 5: Commit**

```bash
git add \
  server/backend/pathscientist/runtime/run_artifacts.py \
  server/backend/pathscientist/tools/run_experiment.py \
  server/backend/pathscientist/config.py \
  server/backend/pathscientist/runtime/workspace.py \
  server/pathscientist_tests/test_agent_runtime_regressions.py
git commit -m "fix: isolate run outputs and prevent stale metrics reuse"
```

### Task 5: Move Iteration Policy Out of the Prompt and Into Runtime State

**Files:**
- Create: `server/backend/pathscientist/runtime/iteration_state.py`
- Modify: `server/backend/pathscientist/agent.py`
- Modify: `server/backend/pathscientist/tools/validate_script.py`
- Modify: `server/backend/pathscientist/tools/run_experiment.py`
- Modify: `server/backend/pathscientist/tools/ratchet.py`
- Modify: `server/backend/pathscientist/tools/metrics.py`
- Modify: `server/backend/pathscientist/prompts/system_prompt.j2`
- Test: `server/pathscientist_tests/test_agent_runtime_regressions.py`
- Test: `server/pathscientist_tests/test_iteration_policy.py`

**Step 1: Write the failing tests**

Add focused policy tests:

```python
def test_full_run_requires_quick_check_for_current_revision():
    ...


def test_run_requires_validation_for_current_revision():
    ...


def test_metrics_tool_reflects_real_history_after_commit_and_revert():
    ...


def test_max_iterations_is_enforced_by_runtime():
    ...
```

**Step 2: Run tests to verify they fail**

Run: `cd server && pytest pathscientist_tests/test_agent_runtime_regressions.py pathscientist_tests/test_iteration_policy.py -v`

Expected:

- full run is currently allowed without a successful quick check
- validation is currently prompt-only
- `get_metrics` does not reflect real iteration state
- `max_iterations` is not enforced by runtime

**Step 3: Write minimal implementation**

Implement `IterationState` with these fields:

- `iteration_index`
- `current_file_hash`
- `last_validated_hash`
- `last_quick_check_hash`
- `last_full_run_hash`
- `last_run_id`
- `history`
- `remaining_budget`

Required behavior:

- `validate_script` defaults to validating the workspace file, not only caller-provided text
- `run_experiment(full)` is rejected unless the same file hash passed validation and quick check
- `ratchet_commit` and `ratchet_revert` finalize the iteration and call `tracker.record(...)`
- `get_metrics` reads from tracker state updated by real commit/revert outcomes
- once `remaining_budget == 0`, the runtime blocks new iterations

Keep the prompt guidance, but make the runtime authoritative.

**Step 4: Run tests to verify they pass**

Run: `cd server && pytest pathscientist_tests/test_agent_runtime_regressions.py pathscientist_tests/test_iteration_policy.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add \
  server/backend/pathscientist/runtime/iteration_state.py \
  server/backend/pathscientist/agent.py \
  server/backend/pathscientist/tools/validate_script.py \
  server/backend/pathscientist/tools/run_experiment.py \
  server/backend/pathscientist/tools/ratchet.py \
  server/backend/pathscientist/tools/metrics.py \
  server/backend/pathscientist/prompts/system_prompt.j2 \
  server/pathscientist_tests/test_agent_runtime_regressions.py \
  server/pathscientist_tests/test_iteration_policy.py
git commit -m "feat: enforce runtime iteration policy for code agent"
```

### Task 6: Add Repo-Scale Grounding with a Repo Map Tool

**Files:**
- Create: `server/backend/pathscientist/tools/repo_map.py`
- Create: `server/backend/pathscientist/runtime/project_index.py`
- Modify: `server/backend/pathscientist/agent.py`
- Modify: `server/backend/pathscientist/prompts/system_prompt.j2`
- Test: `server/pathscientist_tests/test_repo_map_tool.py`

**Step 1: Write the failing test**

```python
def test_repo_map_tool_summarizes_project_tree_and_relevant_files():
    obs = repo_map("metrics tracker")
    assert "tools/metrics.py" in obs.content[0].text
    assert "agent.py" in obs.content[0].text
```

**Step 2: Run test to verify it fails**

Run: `cd server && pytest pathscientist_tests/test_repo_map_tool.py -v`

Expected: FAIL because no repo-map capability exists today.

**Step 3: Write minimal implementation**

Implement a lightweight repo-grounding tool inspired by stronger code agents:

- build a file tree using `rg --files`
- keep a curated include set for `server/backend/pathscientist/**` and tests
- support optional query ranking by filename/path match
- return top relevant files plus compact tree summary
- add prompt guidance: use `repo_map` before changing code outside `train.py`

Do not build a heavy semantic index yet.

**Step 4: Run test to verify it passes**

Run: `cd server && pytest pathscientist_tests/test_repo_map_tool.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add \
  server/backend/pathscientist/tools/repo_map.py \
  server/backend/pathscientist/runtime/project_index.py \
  server/backend/pathscientist/agent.py \
  server/backend/pathscientist/prompts/system_prompt.j2 \
  server/pathscientist_tests/test_repo_map_tool.py
git commit -m "feat: add repo map grounding for pathscientist agent"
```

### Task 7: Add Checkpoints and Safe Restore Semantics

**Files:**
- Create: `server/backend/pathscientist/tools/checkpoint.py`
- Modify: `server/backend/pathscientist/runtime/workspace.py`
- Modify: `server/backend/pathscientist/tools/workspace_info.py`
- Modify: `server/backend/pathscientist/agent.py`
- Modify: `server/backend/pathscientist/prompts/system_prompt.j2`
- Test: `server/pathscientist_tests/test_checkpoints.py`

**Step 1: Write the failing test**

```python
def test_checkpoint_restore_returns_workspace_to_named_snapshot():
    ...


def test_restore_does_not_depend_on_shared_global_workspace_state():
    ...
```

**Step 2: Run test to verify it fails**

Run: `cd server && pytest pathscientist_tests/test_checkpoints.py -v`

Expected: FAIL because the current runtime only has coarse `commit()` / `revert()` behavior.

**Step 3: Write minimal implementation**

Implement lightweight named checkpoints:

- create checkpoint refs before major edits and before experiment runs
- support `create_checkpoint(name)` and `restore_checkpoint(name)`
- surface available checkpoints in `get_workspace_info`
- keep restore scoped to the current session workspace only

Prefer git refs or tags inside the session repo over ad hoc file copies.

**Step 4: Run test to verify it passes**

Run: `cd server && pytest pathscientist_tests/test_checkpoints.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add \
  server/backend/pathscientist/tools/checkpoint.py \
  server/backend/pathscientist/runtime/workspace.py \
  server/backend/pathscientist/tools/workspace_info.py \
  server/backend/pathscientist/agent.py \
  server/backend/pathscientist/prompts/system_prompt.j2 \
  server/pathscientist_tests/test_checkpoints.py
git commit -m "feat: add checkpoint and restore workflow"
```

## Integration Pass

After Tasks 1-7 are complete, run the full verification set:

```bash
cd /project/vcompath/storage/ywangrm/PathLab/pathlab/pathlab-client/server
pytest \
  pathscientist_tests/test_seed_assets.py \
  pathscientist_tests/test_agent_runtime_regressions.py \
  pathscientist_tests/test_tool_session_registry.py \
  pathscientist_tests/test_iteration_policy.py \
  pathscientist_tests/test_repo_map_tool.py \
  pathscientist_tests/test_checkpoints.py \
  -v
```

If LLM-backed smoke coverage is available, then run:

```bash
cd /project/vcompath/storage/ywangrm/PathLab/pathlab/pathlab-client/server
PYTHONPATH=backend python pathscientist_tests/test_smoke_agent.py
PYTHONPATH=backend python pathscientist_tests/test_smoke_skill.py
```

## Recommended Execution Order

Implement strictly in this order:

1. Task 1 - regression harness
2. Task 2 - session identity
3. Task 3 - session-scoped tool registry
4. Task 4 - authoritative run outputs
5. Task 5 - runtime iteration policy
6. Task 6 - repo map
7. Task 7 - checkpoints

Why this order:

- Tasks 2-5 fix correctness and concurrency hazards first
- Task 6 adds mature repo-scale ergonomics only after the core loop is trustworthy
- Task 7 adds usability and recovery after the state model is stable
