# Vendor OpenHands SDK into PathScientist

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Copy the subset of `openhands-sdk` and `openhands-tools` that PathScientist actually uses into a vendored package under `pathscientist/_vendor/`, so PathScientist no longer depends on the `openhands-sdk` / `openhands-tools` pip packages and can modify the agent loop (stop-to-ask, task-mode switching, etc.) without fighting the upstream API.

**Architecture:** Preserve the OpenHands module layout under a new root (`pathscientist._vendor.openhands.sdk.*`, `pathscientist._vendor.openhands.tools.*`). Rewrite internal imports. All PathScientist code shifts from `from openhands.sdk.X import Y` to `from pathscientist._vendor.openhands.sdk.X import Y`. No behavior change in the first pass — vendor-as-is, tests stay green, then start customizing.

**Tech Stack:** Python 3.12, libcst or regex for import rewriting, pytest for verification.

---

## Motivation

1. **Control the agent loop.** Current `LocalConversation.run()` runs `step()` → FINISHED/STUCK/ERROR without ever pausing. To add "stop and ask user" or "switch task mode mid-session" we need to own this loop.
2. **Kill external churn.** SDK upstream can break our API surface. Vendoring freezes the contract we rely on.
3. **Shrink deployment surface.** Drop `openhands-sdk` + `openhands-tools` from `requirements.txt`; only keep their runtime dependencies (litellm, pydantic, etc.).

## Non-goals

- Keeping bidirectional compatibility with upstream OpenHands.
- Re-upstreaming changes to OpenHands.
- Maintaining modules we don't actually use (MCP, plugins, subagents, ACP, browser, gemini tools, etc.).

## Known Import Surface (audited 2026-04-05)

PathScientist currently imports these 15 symbols from OpenHands across 12 files:

```python
# sdk.agent.agent             → Agent
# sdk.context.agent_context   → AgentContext
# sdk.context.condenser       → LLMSummarizingCondenser
# sdk.context.skills.skill    → Skill
# sdk.context.skills.trigger  → KeywordTrigger
# sdk.conversation            → LocalConversation
# sdk.llm                     → LLM, TextContent
# sdk.tool                    → Tool, register_tool
# sdk.tool.schema             → Action, Observation
# sdk.tool.tool               → ToolAnnotations, ToolDefinition, ToolExecutor
# sdk.workspace.local         → LocalWorkspace
# sdk.workspace.models        → CommandResult
# tools.file_editor           → FileEditorTool
# tools.terminal              → TerminalTool
```

Transitively these pull in the full `event/`, `io/`, `hooks/`, `context/view/`, `context/prompts/` subtrees plus most of `llm/` and `conversation/`.

## Scope of Vendoring

### In scope — SDK modules (~20k LOC, trimmed from 37k)

| Module | Why needed |
|---|---|
| `sdk/agent/{agent.py, base.py, utils.py}` | Agent class + LLM completion helpers |
| `sdk/conversation/` (full) | LocalConversation + EventLog + ConversationState + StuckDetector |
| `sdk/event/` (full) | Event types, LLMConvertibleEvent machinery |
| `sdk/llm/` (most) | LLM wrapper, retry, streaming, litellm bridge, message types |
| `sdk/tool/{tool.py, schema.py, registry.py, spec.py, builtins/{finish,think}.py}` | Tool protocol + builtin Think/Finish |
| `sdk/context/{agent_context.py, condenser/, prompts/, skills/, view/}` | Skill injection + LLMSummarizingCondenser + prompt templates |
| `sdk/io/{base.py, local.py, memory.py}` | FileStore abstraction |
| `sdk/workspace/{base.py, local.py, workspace.py, models.py}` | LocalWorkspace |
| `sdk/hooks/` (minimal) | Needed by LocalConversation (even if we don't use hooks) |
| `sdk/utils/{async_utils, command, json, models, paging, redact, truncate, visualize, pydantic_diff, cipher, async_executor}` | Used throughout |
| `sdk/security/{analyzer, confirmation_policy, risk}` | Referenced by Agent/ConversationState |
| `sdk/logger/` | Logger factory used everywhere |
| `sdk/critic/base.py`, `sdk/agent/critic_mixin.py` | Imported by Agent (CriticMixin) — keep default pass-through |

### In scope — Tools modules (~5k LOC)

| Module | Why needed |
|---|---|
| `tools/terminal/` (full) | TerminalTool we register |
| `tools/file_editor/` (full) | FileEditorTool we register |

### Out of scope — NOT vendored

| Module | Reason |
|---|---|
| `sdk/agent/acp_agent.py`, `sdk/agent/parallel_executor.py` | Not used |
| `sdk/mcp/` | No MCP in PathScientist |
| `sdk/plugin/` | No plugins |
| `sdk/subagent/` | No subagents |
| `sdk/secret/`, `sdk/settings/`, `sdk/banner.py` | Not used |
| `sdk/skills/` (vs `sdk/context/skills`) | External skills fetch, not used |
| `sdk/observability/laminar.py` | Telemetry dep we don't need — stub it out |
| `sdk/git/` | Workspace.py has its own git calls |
| `sdk/io/cache.py` | Optional cache layer — drop if LocalFileStore can work without it |
| `sdk/testing/` | Not needed for vendored code |
| `tools/apply_patch/`, `tools/browser_use/`, `tools/delegate/`, `tools/gemini/`, `tools/glob/`, `tools/grep/`, `tools/planning_file_editor/`, `tools/preset/`, `tools/task/`, `tools/task_tracker/`, `tools/tom_consult/` | Not used |

### External pip deps still needed

- `litellm` (LLM backend)
- `pydantic>=2` (models everywhere)
- `tenacity` (retry logic)
- `jinja2` (prompt templates)
- `rich` (visualizer — gated behind optional import)
- `filelock` (FileStore locks)
- `httpx` (via litellm)

## Directory Layout

```
server/backend/pathscientist/
├── _vendor/
│   ├── __init__.py
│   ├── openhands/
│   │   ├── __init__.py
│   │   ├── sdk/
│   │   │   ├── __init__.py
│   │   │   ├── agent/
│   │   │   ├── conversation/
│   │   │   ├── context/
│   │   │   ├── event/
│   │   │   ├── llm/
│   │   │   ├── tool/
│   │   │   ├── io/
│   │   │   ├── workspace/
│   │   │   ├── hooks/
│   │   │   ├── security/
│   │   │   ├── logger/
│   │   │   ├── critic/
│   │   │   └── utils/
│   │   └── tools/
│   │       ├── __init__.py
│   │       ├── terminal/
│   │       └── file_editor/
│   └── README.md
```

Import rewrite rule: `from openhands.sdk.X` → `from pathscientist._vendor.openhands.sdk.X`.

## Success Criteria

- `pip uninstall openhands-sdk openhands-tools` leaves PathScientist working.
- All 35 existing tests in `backend/pathscientist/tests/` still pass.
- `grep -rE "^(from|import) openhands" server/backend/pathscientist/ --exclude-dir="_vendor"` returns empty.
- End-to-end feature extraction smoke test (Qwen + vLLM) still works.
- `requirements.txt` no longer lists `openhands-sdk` or `openhands-tools`.

---

## Task 1: Write Audit Script and Generate Import Closure

**Files:**
- Create: `scripts/vendor_audit.py`
- Create: `_vendor/AUDIT.txt` (artifact)

**Step 1:** Write `scripts/vendor_audit.py` that:

```python
# For each import in PathScientist, walk the SDK's AST to collect
# the transitive set of openhands modules that need to be vendored.
```

Seeds: the 15 known imports listed above. Traverse AST `ast.ImportFrom` nodes with module prefix `openhands.`.

**Step 2:** Run it:

```bash
cd server/backend/pathscientist
.venv/bin/python scripts/vendor_audit.py > _vendor/AUDIT.txt
```

**Step 3:** Manually review `AUDIT.txt`. Expected closure size: ~80-120 Python files. Verify none of the "out of scope" modules (mcp, plugin, subagent, browser_use, etc.) appear.

**Step 4:** Commit:

```bash
git add server/backend/pathscientist/scripts/vendor_audit.py \
        server/backend/pathscientist/_vendor/AUDIT.txt
git commit -m "chore: audit openhands SDK import closure for vendoring"
```

---

## Task 2: Copy SDK Modules Verbatim

**Files:**
- Create: `_vendor/openhands/sdk/**` (copied from venv)
- Create: `_vendor/openhands/tools/{terminal,file_editor}/` (copied from venv)
- Create: `_vendor/__init__.py`, `_vendor/openhands/__init__.py`
- Create: `_vendor/README.md`
- Create: `scripts/vendor_copy.py`

**Step 1:** Write `scripts/vendor_copy.py` that reads `_vendor/AUDIT.txt` and copies each listed file from `.venv/lib/python3.12/site-packages/openhands/` into `_vendor/openhands/`.

**Step 2:** Run it. Do NOT edit files yet — verbatim copy.

**Step 3:** Write `_vendor/README.md` recording:
- upstream version (`openhands-sdk==1.16.1`, `openhands-tools==X.Y.Z`)
- copy date (2026-04-05)
- module list and reasons
- policy: "never edit in-place without recording the change in a follow-up commit"

**Step 4:** Verify:

```bash
find server/backend/pathscientist/_vendor -name "*.py" | wc -l
# expect ~100-150 files
```

**Step 5:** Commit:

```bash
git add server/backend/pathscientist/_vendor/
git commit -m "vendor: copy openhands-sdk 1.16.1 subset (verbatim)"
```

---

## Task 3: Rewrite Vendor-Internal Imports

**Files:**
- Modify: `_vendor/openhands/**/*.py` (every file)
- Create: `scripts/rewrite_imports.py`

**Step 1:** Write `scripts/rewrite_imports.py`:

```python
# For each .py file under _vendor/openhands/:
#   replace: from openhands.X  → from pathscientist._vendor.openhands.X
#   replace: import openhands.X → import pathscientist._vendor.openhands.X
# Preserve line numbers and whitespace.
```

Use regex (predictable) or libcst (safer). Print summary: N files touched, M lines changed.

**Step 2:** Run it on `_vendor/`:

```bash
.venv/bin/python scripts/rewrite_imports.py _vendor/
```

**Step 3:** Verify no stray imports remain:

```bash
grep -rE "^(from|import) openhands" server/backend/pathscientist/_vendor/ | wc -l
# expect 0
```

**Step 4:** Sanity-check: try importing the top-level modules:

```bash
.venv/bin/python -c "
import pathscientist._vendor.openhands.sdk.agent.agent
import pathscientist._vendor.openhands.sdk.conversation
import pathscientist._vendor.openhands.sdk.llm
print('ok')
"
```

If ImportError, trace the chain and fix each missing module (add to vendor set if critical, or stub/drop).

**Step 5:** Commit:

```bash
git add server/backend/pathscientist/_vendor/ \
        server/backend/pathscientist/scripts/rewrite_imports.py
git commit -m "vendor: rewrite internal imports to pathscientist._vendor namespace"
```

---

## Task 4: Stub Optional Dependencies

**Files:**
- Modify: `_vendor/openhands/sdk/observability/laminar.py`
- Modify: any file importing laminar or other excluded modules

**Step 1:** Replace `observability/laminar.py` with no-op stubs:

```python
def observe(name=None, span_type=None):
    def decorator(fn): return fn
    return decorator

def start_active_span(*args, **kwargs): pass
def end_active_span(): pass
def should_enable_observability(): return False
```

Keep the public API identical so callers don't break.

**Step 2:** For each vendored file that imports from `openhands.sdk.plugin`, `openhands.sdk.mcp`, `openhands.sdk.subagent`, `openhands.sdk.secret`, etc. (out-of-scope modules):
- If the import is only for type hints → remove, use `Any`
- If it's used at runtime → either add the module to vendor set, or stub the needed symbols

Document each decision in the commit message.

**Step 3:** Re-verify top-level imports work:

```bash
.venv/bin/python -c "
from pathscientist._vendor.openhands.sdk.conversation.impl.local_conversation import LocalConversation
from pathscientist._vendor.openhands.tools.terminal import TerminalTool
from pathscientist._vendor.openhands.tools.file_editor import FileEditorTool
print('ok')
"
```

**Step 4:** Commit:

```bash
git add server/backend/pathscientist/_vendor/
git commit -m "vendor: stub telemetry and drop unused optional deps"
```

---

## Task 5: Point PathScientist At the Vendored Copy

**Files to modify** (use `scripts/rewrite_imports.py` with a different target):

- `backend/pathscientist/agent.py`
- `backend/pathscientist/knowledge.py`
- `backend/pathscientist/persistence/resume.py`
- `backend/pathscientist/persistence/state_bridge.py`
- `backend/pathscientist/runtime/workspace.py`
- `backend/pathscientist/tools/checkpoint.py`
- `backend/pathscientist/tools/metrics.py`
- `backend/pathscientist/tools/ratchet.py`
- `backend/pathscientist/tools/run_experiment.py`
- `backend/pathscientist/tools/skill_browser.py`
- `backend/pathscientist/tools/validate_script.py`
- `backend/pathscientist/tools/workspace_info.py`
- `backend/pathscientist/tests/persistence_helpers.py`

**Step 1:** Run the rewrite script with scope = pathscientist proper (not `_vendor/`):

```bash
.venv/bin/python scripts/rewrite_imports.py backend/pathscientist/ --exclude _vendor
```

**Step 2:** Run the full PathScientist test suite:

```bash
cd server/backend/pathscientist
OPENHANDS_SUPPRESS_BANNER=1 .venv/bin/python -m pytest tests/ -v
```

All 35 tests (from `test_seed_assets`, `test_iteration_policy`, `test_checkpoints`, `test_agent_runtime_regressions`, `test_conversation_persistence`, `test_conversation_resume`) must pass.

**Step 3:** Verify no stray external imports:

```bash
grep -rE "^(from|import) openhands" server/backend/pathscientist/ \
  --include="*.py" --exclude-dir="_vendor" --exclude-dir=".venv"
# expect empty
```

**Step 4:** Commit:

```bash
git add server/backend/pathscientist/
git commit -m "refactor: switch pathscientist to vendored openhands SDK"
```

---

## Task 6: Drop `openhands-sdk` and `openhands-tools` from Requirements

**Files:**
- Modify: `server/requirements.txt`
- Modify: `server/backend/pathscientist/start.sh` (update install hint)

**Step 1:** Remove `openhands-sdk` and `openhands-tools` lines from `server/requirements.txt`.

**Step 2:** Verify direct deps are listed: `litellm`, `pydantic`, `tenacity`, `jinja2`, `rich`, `filelock`, `httpx`. Add any that are missing.

**Step 3:** Create a fresh venv and verify tests still pass without `openhands-sdk` installed:

```bash
cd server/backend/pathscientist
rm -rf .venv_vendor_test
uv venv .venv_vendor_test --python 3.12
.venv_vendor_test/bin/pip install -r ../../requirements.txt
OPENHANDS_SUPPRESS_BANNER=1 .venv_vendor_test/bin/python -m pytest tests/ -v
```

If any test fails with `ModuleNotFoundError: openhands`, the vendor set is incomplete — return to Task 3/4 to patch.

**Step 4:** Once green, delete the test venv:

```bash
rm -rf .venv_vendor_test
```

**Step 5:** Commit:

```bash
git add server/requirements.txt server/backend/pathscientist/start.sh
git commit -m "chore: drop openhands-sdk pip dependency in favor of vendored copy"
```

---

## Task 7: End-to-End Smoke Test

**Files:** none

**Step 1:** Run a real feature-extraction session against vLLM Qwen:

```bash
cd server/backend/pathscientist
bash start.sh -q "Extract features from WSIs in .../test_data/WSIs using UNI extractor, save to .../test_data/feature_test_output" \
  --data-mount ".../WSIs:/data/wsi" \
  --data-mount ".../feature_test_output:/output" \
  --max-iter 1 --gpu 0 --timeout 1200
```

**Step 2:** Verify:
- Agent starts without ImportError
- Conversation persisted to `conversations/<uuid>/`
- Features written to `DATA_OUTPUT_DIR`
- `ratchet_commit` succeeds
- Final log contains "Done: 2/2 WSIs"

**Step 3:** If anything breaks, diagnose whether it's:
- A vendoring gap (missing module) → patch Task 3/4
- A real regression (behavior changed) → investigate specific vendored file

**Step 4:** Record outcome in a follow-up note. No commit needed unless fixing issues.

---

## Post-Vendor: Customization Opportunities

Once vendored, these become feasible without upstream coordination:

1. **Pausable agent loop:** Add `ConversationExecutionStatus.WAITING_FOR_USER` state and hook point in `LocalConversation.run()` for the agent to request user input mid-session.
2. **Task-mode switching:** Allow the agent to change its own `system_prompt_kwargs` mid-conversation and re-render the system prompt (currently frozen at `init_state()`).
3. **Custom iteration budget:** Replace the hardcoded `max_iteration_per_run=500` and "max iterations reached" error with PathScientist's `IterationState` policy.
4. **Drop unused event types:** Remove `CondensationRequest` handling if we don't use condensation, etc.

These are **follow-up plans**, not part of this vendoring plan.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Transitive import closure is bigger than expected | Task 1 audit catches this; iterate until closure stabilizes |
| Vendored code has bugs that only manifest at runtime | Task 5 runs full test suite; Task 7 smoke test catches integration issues |
| Removed dep `openhands-tools` is implicitly pulled by another package | Task 6 clean-venv install verifies this |
| Upstream SDK has critical bugfix we now miss | Acceptable — explicit cutoff; fix in-place when we hit it |
| Module `sdk/io/cache.py` is needed by `LocalFileStore` | Task 3 will reveal this via ImportError; just add it back |

## Execution Order

Strict order: Task 1 → 2 → 3 → 4 → 5 → 6 → 7. No parallelization.

Each task ends with a clean test pass.
