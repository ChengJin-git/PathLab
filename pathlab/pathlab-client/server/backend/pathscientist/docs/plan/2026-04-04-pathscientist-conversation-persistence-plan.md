# PathScientist Conversation Persistence Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add OpenHands-style per-conversation persistence to PathScientist so each session has a durable conversation record, resumable runtime state, and inspectable event history.

**Architecture:** Reuse OpenHands SDK's native persistence model instead of inventing a second conversation log format. PathScientist should treat OpenHands conversation persistence as the source of truth for session history: one conversation directory per conversation UUID, one `base_state.json` snapshot for mutable session state, and one append-only `events/` log with one JSON file per event. PathScientist-specific metadata such as loaded skill, tracker state, iteration workflow state, and session paths should be bridged into OpenHands persistence so the system can resume cleanly and later expose the same records through API endpoints. Keep `tags` limited to small searchable string metadata and store all structured resume-critical state in `agent_state`.

**Tech Stack:** Python 3.12, OpenHands SDK 1.16.1, LocalConversation, ConversationState, EventLog, LocalFileStore, pytest

---

## OpenHands Persistence Model to Mirror

This plan intentionally follows the behavior already present in OpenHands SDK:

- conversation root = `<persistence_base>/<conversation_uuid_hex>/`
- mutable snapshot = `base_state.json`
- append-only event history = `events/event-00000-<event_id>.json`
- file-backed locking for event append
- conversation resume via `ConversationState.create(...)`
- runtime compatibility check via `agent.verify(...)`

For PathScientist, do **not** create a second custom event log next to this. Extend it, inspect it, and mirror PathScientist metadata into it.

## Key SDK Behavior (verified from source)

**`BaseConversation.get_persistence_dir(persistence_base_dir, conversation_id)`** computes:

```python
str(Path(persistence_base_dir) / conversation_id.hex)
```

So when you pass `persistence_dir=X` to `LocalConversation(...)`, the actual on-disk directory becomes `X/<uuid_hex>/`. `ConversationID` is `uuid.UUID`. This means:

- Pass `persistence_root` (e.g. `conversations/`) as `persistence_dir`, **not** the final `conversation_dir`.
- The SDK will append `conversation_id.hex` automatically.
- `conversation.state.persistence_dir` returns the final resolved path including the UUID.

## Two Identifiers: session_id vs conversation_id

- **`session_id`** (12-char hex, already exists): The key for `SessionRegistry` — tools resolve their workspace/tracker/config/iteration_state through it. Continues to serve this role unchanged.
- **`conversation_id`** (`uuid.UUID`, new): The key for OpenHands persistence and resume. Stored in `PathScientistSession`, passed to `LocalConversation`.

`session_id` remains the primary key for SessionRegistry tool resolution; `conversation_id` is solely for OpenHands persistence and resume. Do not merge them.

## Implementation Rules

- Use OpenHands persistence as the canonical source of conversation truth.
- Keep workspace, output, and conversation persistence directories distinct.
- Use a real UUID for `conversation_id`; do not overload the current short `session_id`.
- Use `tags` only for small searchable metadata with lowercase alphanumeric keys; keep all structured runtime state in `ConversationState.agent_state`.
- Persist complete runtime reconstruction state, not just headline summaries: tracker history, iteration counters, workflow gate hashes, and last run metadata must survive restart.
- Treat `session_id` as process-local only. Generate a fresh one on resume and do not depend on a persisted `session_id` for correctness.
- Do not gate resume on prompt text; gate it on persisted state and agent/tool compatibility.

## Success Criteria

- every PathScientist run gets a stable `conversation_id`
- every persisted conversation writes `base_state.json` and `events/*.json`
- PathScientist can resume a prior conversation by `conversation_id`
- loaded skill, workspace/output paths, tracker history, best metric summary, last run metadata, and full iteration workflow state survive process restart
- a human can inspect any conversation from disk without replaying the whole agent loop

### Task 1: Add Persistence Contract Tests and Test Fixtures

**Files:**
- Create: `server/pathscientist_tests/test_conversation_persistence.py`
- Create: `server/pathscientist_tests/persistence_helpers.py`
- Reference: `server/backend/pathscientist/agent.py`
- Reference: `server/backend/pathscientist/runtime/session.py`
- Reference: `server/backend/pathscientist/config.py`

**Step 1: Write test fixture helpers**

Create `persistence_helpers.py` with shared helpers used by all persistence tests. Keep it as a normal helper module rather than a pytest `conftest.py`, because the current test suite uses explicit helper imports and explicit `sys.path` setup.

```python
"""Shared fixtures for conversation persistence tests.

These tests verify persistence layout and resume contracts without depending on
real LLM calls. Avoid `conversation.send_message()` in these tests; append a
synthetic event directly when you only need to verify OpenHands file layout.
"""
import os
import sys
from pathlib import Path
from uuid import UUID

from openhands.sdk.event import MessageEvent
from openhands.sdk.llm import Message, TextContent

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"

from pathscientist.config import PathScientistConfig


def make_test_config(tmp_path: Path, **overrides) -> PathScientistConfig:
    """Minimal config suitable for test: no GPU, no sandbox, tmp workspace."""
    return PathScientistConfig(
        workspace_dir=str(tmp_path / "workspace"),
        output_dir=str(tmp_path / "output"),
        gpu_ids=[],
        sandbox_mode="local",
        max_iterations=2,
        primary_metric="auc",
        **overrides,
    )


def build_test_conversation(tmp_path: Path, **config_overrides):
    """Create a PathScientist conversation with persistence enabled.

    Returns (conversation, session) tuple.
    """
    from pathscientist.agent import create_agent, create_conversation

    config = make_test_config(tmp_path, **config_overrides)
    agent, workspace, tracker, session = create_agent(config, research_question="test")
    conversation = create_conversation(agent, workspace, session)
    return conversation, session


def resume_test_conversation(tmp_path: Path, conversation_id: UUID):
    """Re-open an existing conversation by UUID (resume path).

    Returns (conversation, session) so tests can validate both the OpenHands
    state and the rebuilt PathScientist runtime state.
    """
    from pathscientist.agent import resume_conversation

    config = make_test_config(tmp_path)
    return resume_conversation(config, conversation_id)


def append_test_message_event(conversation, text: str = "hello") -> None:
    """Append a synthetic user message event for persistence-layout tests.

    This exercises the event store without requiring a real agent run.
    """
    conversation.state.events.append(
        MessageEvent(
            source="user",
            llm_message=Message(
                role="user",
                content=[TextContent(text=text)],
            ),
        )
    )
```

**Step 2: Write the failing tests**

```python
from pathlib import Path
from persistence_helpers import (
    append_test_message_event,
    build_test_conversation,
    resume_test_conversation,
)


def test_create_conversation_writes_openhands_layout(tmp_path):
    conversation, session = build_test_conversation(tmp_path)
    append_test_message_event(conversation, "hello")
    # SDK computes: persistence_root / conversation_id.hex
    conv_dir = session.persistence_root / session.conversation_id.hex
    assert (conv_dir / "base_state.json").exists()
    assert (conv_dir / "events").exists()
    assert any((conv_dir / "events").glob("event-*.json"))


def test_base_state_persists_tags_and_agent_state(tmp_path):
    conversation, session = build_test_conversation(tmp_path)
    conversation.state.agent_state = {"loaded_skill": "mil_classification"}
    conv_dir = session.persistence_root / session.conversation_id.hex
    payload = (conv_dir / "base_state.json").read_text()
    assert "mil_classification" in payload


def test_reopen_same_conversation_recovers_existing_events(tmp_path):
    first, session = build_test_conversation(tmp_path)
    append_test_message_event(first, "first turn")
    reopened, _ = resume_test_conversation(tmp_path, session.conversation_id)
    assert len(reopened.state.events) >= 1
```

**Step 3: Run test to verify it fails**

Run: `cd server && pytest pathscientist_tests/test_conversation_persistence.py -v`

Expected:

- failure because `create_conversation()` does not currently pass `persistence_dir`
- failure because `PathScientistSession` does not yet expose conversation persistence paths
- failure because `create_agent()` does not return `session`
- failure because `resume_conversation()` does not exist

**Step 4: Commit**

```bash
git add server/pathscientist_tests/test_conversation_persistence.py \
  server/pathscientist_tests/persistence_helpers.py
git commit -m "test: add pathscientist conversation persistence contracts and fixtures"
```

### Task 2: Add Session-Level Conversation Identity and Layout

**Files:**
- Modify: `server/backend/pathscientist/runtime/session.py`
- Modify: `server/backend/pathscientist/config.py`
- Create: `server/backend/pathscientist/persistence/__init__.py`
- Create: `server/backend/pathscientist/persistence/layout.py`
- Test: `server/pathscientist_tests/test_conversation_persistence.py`

**Step 1: Write the failing focused test**

```python
from uuid import UUID


def test_session_contains_conversation_identity_and_paths(tmp_path):
    cfg = make_test_config(tmp_path)
    session = cfg.create_session("improve auc")
    # conversation_id must be a real UUID
    UUID(str(session.conversation_id))
    # persistence_root is where the SDK will look for conversation dirs
    assert session.persistence_root.exists()
    # The SDK will create conversation_dir = persistence_root / conversation_id.hex
    # Session exposes it for convenience but does NOT mkdir it (SDK does that)
    assert session.persistence_root.is_dir()
```

**Step 2: Run test to verify it fails**

Run: `cd server && pytest pathscientist_tests/test_conversation_persistence.py::test_session_contains_conversation_identity_and_paths -v`

Expected: FAIL because current session tracks only `session_id`, workspace, and output.

**Step 3: Write minimal implementation**

Implement:

```python
# server/backend/pathscientist/persistence/layout.py
from pathlib import Path
from uuid import UUID


def get_persistence_root(base_dir: str | Path) -> Path:
    """Return the root directory for all conversation persistence.

    Each conversation will be stored under persistence_root/<conversation_id_hex>/
    by the OpenHands SDK (BaseConversation.get_persistence_dir).
    """
    root = Path(base_dir).expanduser().resolve() / "conversations"
    root.mkdir(parents=True, exist_ok=True)
    return root
```

Extend `PathScientistSession` with:

```python
from uuid import UUID, uuid4

@dataclass
class PathScientistSession:
    session_id: str = ...
    conversation_id: UUID = field(default_factory=uuid4)
    research_question: str = ""
    workspace_dir: Path = ...
    output_dir: Path = ...
    persistence_root: Path = ...  # base dir; SDK appends conversation_id.hex
```

In `create()`, compute `persistence_root` via `get_persistence_root(base)`.

Add config fields:

- `conversation_persistence_dir: str = ""` — override for persistence root
- `resume_conversation_id: str = ""` — UUID hex to resume

**Step 4: Run test to verify it passes**

Run: `cd server && pytest pathscientist_tests/test_conversation_persistence.py::test_session_contains_conversation_identity_and_paths -v`

Expected: PASS

**Step 5: Commit**

```bash
git add \
  server/backend/pathscientist/runtime/session.py \
  server/backend/pathscientist/config.py \
  server/backend/pathscientist/persistence/__init__.py \
  server/backend/pathscientist/persistence/layout.py \
  server/pathscientist_tests/test_conversation_persistence.py
git commit -m "feat: add conversation identity and persistence layout"
```

### Task 3: Wire `LocalConversation` Persistence into PathScientist

**Files:**
- Modify: `server/backend/pathscientist/agent.py`
- Modify: `server/backend/pathscientist/run.py`
- Modify: `server/backend/pathscientist/cli.py`
- Test: `server/pathscientist_tests/test_conversation_persistence.py`

**Step 1: Write the failing focused test**

```python
def test_create_conversation_uses_session_persistence_dir(tmp_path):
    conversation, session = build_test_conversation(tmp_path)
    # SDK resolves: persistence_root / conversation_id.hex
    expected_dir = str(session.persistence_root / session.conversation_id.hex)
    assert conversation.state.persistence_dir == expected_dir
    assert conversation.id == session.conversation_id
```

**Step 2: Run test to verify it fails**

Run: `cd server && pytest pathscientist_tests/test_conversation_persistence.py::test_create_conversation_uses_session_persistence_dir -v`

Expected: FAIL because current `create_conversation()` does not pass `persistence_dir` or `conversation_id`.

**Step 3: Write minimal implementation**

Change `create_conversation()` signature to accept the session and wire OpenHands persistence:

```python
from openhands.sdk.conversation import LocalConversation


def create_conversation(agent: Agent, workspace: Workspace, session: PathScientistSession):
    """Create a LocalConversation with OpenHands persistence enabled."""
    return LocalConversation(
        agent=agent,
        workspace=workspace.sdk_workspace,
        persistence_dir=str(session.persistence_root),  # SDK appends /<conv_id_hex>/
        conversation_id=session.conversation_id,
        stuck_detection=True,
        visualizer=None,
        delete_on_close=False,
        tags={
            "project": "pathscientist",
        },
    )
```

Also:

- Update `create_agent()` return signature: `tuple[Agent, Workspace, MetricsTracker, PathScientistSession]` (add session to return)
- Update callers in `cli.py` and `run.py` to unpack the 4th return value
- Print `conversation_id` and resolved persistence path in CLI and runner startup logs

**Step 4: Run test to verify it passes**

Run: `cd server && pytest pathscientist_tests/test_conversation_persistence.py::test_create_conversation_uses_session_persistence_dir -v`

Expected: PASS

**Step 5: Commit**

```bash
git add \
  server/backend/pathscientist/agent.py \
  server/backend/pathscientist/run.py \
  server/backend/pathscientist/cli.py \
  server/pathscientist_tests/test_conversation_persistence.py
git commit -m "feat: persist pathscientist conversations through openhands localconversation"
```

### Task 4: Persist PathScientist Runtime Metadata into `agent_state`

**Files:**
- Create: `server/backend/pathscientist/persistence/__init__.py` (already exists from Task 2)
- Create: `server/backend/pathscientist/persistence/state_bridge.py`
- Modify: `server/backend/pathscientist/runtime/session_registry.py`
- Modify: `server/backend/pathscientist/tools/run_experiment.py`
- Modify: `server/backend/pathscientist/tools/metrics.py`
- Modify: `server/backend/pathscientist/tools/ratchet.py`
- Modify: `server/backend/pathscientist/tools/skill_browser.py`
- Test: `server/pathscientist_tests/test_conversation_persistence.py`

**Step 1: Write the failing tests**

```python
def test_loaded_skill_is_persisted_in_agent_state(tmp_path):
    conversation, session = build_test_conversation(tmp_path)
    # Simulate a skill load through the state bridge
    from pathscientist.persistence.state_bridge import update_agent_state
    update_agent_state(conversation, loaded_skill="mil_classification")
    reopened, _ = resume_test_conversation(tmp_path, session.conversation_id)
    assert reopened.state.agent_state["loaded_skill"] == "mil_classification"


def test_tracker_state_is_persisted_in_agent_state(tmp_path):
    conversation, session = build_test_conversation(tmp_path)
    from pathscientist.persistence.state_bridge import update_agent_state
    update_agent_state(conversation, tracker_state={
        "primary_metric": "auc",
        "best_value": 0.88,
        "iteration": 2,
        "history": [
            {"iteration": 0, "metrics": {"auc": 0.81}, "committed": True},
            {"iteration": 1, "metrics": {"auc": 0.88}, "committed": True},
        ],
    })
    reopened, _ = resume_test_conversation(tmp_path, session.conversation_id)
    assert reopened.state.agent_state["tracker_state"]["best_value"] == 0.88
    assert reopened.state.agent_state["tracker_state"]["history"][1]["iteration"] == 1


def test_iteration_state_persisted_in_agent_state(tmp_path):
    conversation, session = build_test_conversation(tmp_path)
    from pathscientist.persistence.state_bridge import update_agent_state
    update_agent_state(conversation, iteration_state={
        "iteration_index": 2,
        "remaining_budget": 3,
        "current_file_hash": "abc123",
        "last_validated_hash": "abc123",
        "last_quick_check_hash": "abc123",
        "last_run_id": "run001",
        "history": [{"iteration": 0, "metrics": {"auc": 0.8}, "committed": True}],
    })
    reopened, _ = resume_test_conversation(tmp_path, session.conversation_id)
    assert reopened.state.agent_state["iteration_state"]["iteration_index"] == 2
    assert reopened.state.agent_state["iteration_state"]["last_quick_check_hash"] == "abc123"
```

**Step 2: Run test to verify it fails**

Run: `cd server && pytest pathscientist_tests/test_conversation_persistence.py -k agent_state -v`

Expected: FAIL because PathScientist tools currently keep most of this state only in memory, and they do not persist the full tracker / workflow gate state needed for resume.

**Step 3: Write minimal implementation**

Create the state bridge:

```python
# server/backend/pathscientist/persistence/state_bridge.py
"""Bridge between PathScientist runtime state and OpenHands agent_state persistence.

Tools call update_agent_state() to persist runtime metadata. On resume,
restore_from_agent_state() rebuilds PathScientist runtime objects.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openhands.sdk.conversation.impl.local_conversation import LocalConversation


def update_agent_state(conversation: LocalConversation, **patch: Any) -> None:
    """Merge key-value pairs into conversation.state.agent_state.

    OpenHands auto-persists to base_state.json on assignment, but requires
    reassignment (not mutation) to trigger the __setattr__ hook.
    """
    state = dict(conversation.state.agent_state)
    state.update(patch)
    conversation.state.agent_state = state


def read_agent_state(conversation: LocalConversation, key: str, default: Any = None) -> Any:
    """Read a value from persisted agent_state."""
    return conversation.state.agent_state.get(key, default)
```

Add serializer helpers so the persisted payload is stable and complete:

```python
def dump_tracker_state(tracker: MetricsTracker) -> dict[str, Any]:
    return {
        "primary_metric": tracker.primary_metric,
        "best_value": tracker.best_value,
        "iteration": tracker.iteration,
        "history": tracker.history,
    }


def dump_iteration_state(iteration_state: IterationState) -> dict[str, Any]:
    return {
        "max_iterations": iteration_state.max_iterations,
        "iteration_index": iteration_state.iteration_index,
        "remaining_budget": iteration_state.remaining_budget,
        "current_file_hash": iteration_state.current_file_hash,
        "last_validated_hash": iteration_state.last_validated_hash,
        "last_quick_check_hash": iteration_state.last_quick_check_hash,
        "last_run_id": iteration_state.last_run_id,
        "history": iteration_state.history,
    }
```

**Wiring tools to the conversation object:**

Add `conversation` as an optional field on `SessionDeps`:

```python
@dataclass
class SessionDeps:
    workspace: Any
    tracker: Any
    config: Any
    iteration_state: Any = None
    conversation: Any = None  # LocalConversation — set after create_conversation()
```

In `agent.py`, after creating the conversation, store it back:

```python
conversation = create_conversation(agent, workspace, session)
deps = get_session(session.session_id)
deps.conversation = conversation
```

Tools then persist metadata through:

```python
deps = get_session(self.session_id)
if deps.conversation:
    update_agent_state(deps.conversation, best_metric={...})
```

**Values to persist from each tool:**

| Runtime point | Keys persisted |
|------|---------------|
| After `create_agent` | `workspace_dir`, `output_dir`, `research_question`, `primary_metric` |
| `SkillBrowserTool` (load) | `loaded_skill` |
| Tracker mutation (`MetricsTracker.record`) | `tracker_state`, `best_metric` |
| Run metadata update | `last_run_id`, `last_run_dir`, `last_metrics`, `last_commit` |
| Iteration workflow mutation | full `iteration_state` snapshot |

**IterationState persistence:**

Persist the full workflow gate state after every mutation, not just after `record_iteration()`. In practice this means persisting after:

- `mark_validated(...)`
- `mark_quick_check_passed(...)`
- `record_iteration(...)`
- any explicit `last_run_id` update during experiment execution

For example:

```python
update_agent_state(deps.conversation, iteration_state={
    **dump_iteration_state(deps.iteration_state),
})
```

Do not write a second JSON file for these values; use OpenHands `agent_state`.

**Step 4: Run test to verify it passes**

Run: `cd server && pytest pathscientist_tests/test_conversation_persistence.py -k agent_state -v`

Expected: PASS

**Step 5: Commit**

```bash
git add \
  server/backend/pathscientist/persistence/state_bridge.py \
  server/backend/pathscientist/runtime/session_registry.py \
  server/backend/pathscientist/tools/run_experiment.py \
  server/backend/pathscientist/tools/metrics.py \
  server/backend/pathscientist/tools/ratchet.py \
  server/backend/pathscientist/tools/skill_browser.py \
  server/pathscientist_tests/test_conversation_persistence.py
git commit -m "feat: persist pathscientist runtime metadata in openhands agent state"
```

### Task 5: Add Resume and Inspection Helpers

**Files:**
- Create: `server/backend/pathscientist/persistence/history.py`
- Create: `server/backend/pathscientist/persistence/resume.py`
- Modify: `server/backend/pathscientist/agent.py`
- Modify: `server/backend/pathscientist/cli.py`
- Modify: `server/backend/pathscientist/run.py`
- Test: `server/pathscientist_tests/test_conversation_resume.py`

**Step 1: Write the failing tests**

```python
def test_can_resume_existing_conversation_by_id(tmp_path):
    first, session = build_test_conversation(tmp_path)
    append_test_message_event(first, "first turn")
    resumed, _ = resume_test_conversation(tmp_path, session.conversation_id)
    assert resumed.id == session.conversation_id
    assert len(resumed.state.events) >= 1


def test_resume_rebuilds_session_deps(tmp_path):
    """After resume, tools must be able to resolve their SessionDeps."""
    first, session = build_test_conversation(tmp_path)
    from pathscientist.persistence.state_bridge import update_agent_state
    update_agent_state(first, workspace_dir=str(tmp_path / "workspace"))
    first.close()

    resumed_conv, resumed_session = resume_test_conversation(tmp_path, session.conversation_id)
    from pathscientist.runtime.session_registry import get_session
    deps = get_session(resumed_session.session_id)
    assert deps.workspace is not None
    assert deps.tracker is not None
    assert deps.iteration_state is not None


def test_resume_restores_iteration_state(tmp_path):
    """IterationState fields survive resume."""
    first, session = build_test_conversation(tmp_path)
    from pathscientist.persistence.state_bridge import update_agent_state
    update_agent_state(first, iteration_state={
        "iteration_index": 2,
        "remaining_budget": 3,
        "max_iterations": 5,
        "current_file_hash": "abc123",
        "last_validated_hash": "abc123",
        "last_quick_check_hash": "abc123",
        "last_run_id": "run001",
        "history": [{"iteration": 0, "metrics": {"auc": 0.8}, "committed": True}],
    })
    first.close()

    _, resumed_session = resume_test_conversation(tmp_path, session.conversation_id)
    from pathscientist.runtime.session_registry import get_session
    deps = get_session(resumed_session.session_id)
    assert deps.iteration_state.iteration_index == 2
    assert deps.iteration_state.remaining_budget == 3
    assert deps.iteration_state.last_quick_check_hash == "abc123"


def test_history_reader_returns_summary_from_disk(tmp_path):
    first, session = build_test_conversation(tmp_path)
    append_test_message_event(first, "hello")
    from pathscientist.persistence.history import load_conversation_summary
    conv_dir = session.persistence_root / session.conversation_id.hex
    summary = load_conversation_summary(conv_dir)
    assert summary["conversation_id"] == str(session.conversation_id)
    assert summary["event_count"] >= 1
```

**Step 2: Run test to verify it fails**

Run: `cd server && pytest pathscientist_tests/test_conversation_resume.py -v`

Expected: FAIL because there is no explicit resume or inspection API yet.

**Step 3: Write minimal implementation**

**Resume rebuild sequence** (`persistence/resume.py`):

The resume path must reconstruct the full PathScientist runtime in this order:

1. Read `base_state.json` from the conversation directory (done by OpenHands SDK internally)
2. Extract `agent_state` fields: `workspace_dir`, `output_dir`, `research_question`, `loaded_skill`, `best_metric`, `tracker_state`, `iteration_state`
3. Rebuild `Workspace` from `workspace_dir`
4. Rebuild `MetricsTracker` from `tracker_state` (restore `primary_metric`, `best_value`, `iteration`, and `history`)
5. Rebuild `IterationState` from `iteration_state` dict (restore counters, workflow gate hashes, `last_run_id`, and `history`)
6. Create a fresh `session_id` for SessionRegistry. Do not depend on any persisted `session_id`; it is process-local only.
7. Register rebuilt `SessionDeps` into `SessionRegistry`
8. Create `LocalConversation` with the same `conversation_id` + `persistence_dir` — OpenHands `ConversationState.create()` detects `base_state.json` and enters resume mode, verifying tool compatibility
9. Store `conversation` back into `SessionDeps.conversation`

```python
# server/backend/pathscientist/persistence/resume.py
def resume_conversation(
    config: PathScientistConfig,
    conversation_id: UUID,
) -> tuple[LocalConversation, PathScientistSession]:
    """Resume a previously persisted PathScientist conversation.

    Rebuilds all runtime dependencies (Workspace, MetricsTracker,
    IterationState, SessionRegistry) from persisted agent_state,
    then delegates to OpenHands ConversationState.create() for
    event log recovery and agent compatibility verification.
    """
    ...
```

**Inspection helper** (`persistence/history.py`):

```python
def load_conversation_summary(conversation_dir: Path) -> dict:
    """Read base_state.json + count events for a quick summary.

    Does NOT instantiate an Agent or LocalConversation — pure file read.
    """
    ...


def list_conversations(persistence_root: Path) -> list[dict]:
    """List all persisted conversations under persistence_root."""
    ...
```

**CLI / runner support:**

- `--resume <uuid>` — resume an existing conversation
- `--persistence-dir <path>` — override persistence root
- optional `--list-conversations` — print summary table and exit

Resume behavior:

- If `--resume` is provided, call `resume_conversation()` instead of `create_agent()`
- Let OpenHands `ConversationState.create(...)` perform compatibility verification
- If tool mismatch is detected, fail with clear error

**Step 4: Run test to verify it passes**

Run: `cd server && pytest pathscientist_tests/test_conversation_resume.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add \
  server/backend/pathscientist/persistence/history.py \
  server/backend/pathscientist/persistence/resume.py \
  server/backend/pathscientist/agent.py \
  server/backend/pathscientist/cli.py \
  server/backend/pathscientist/run.py \
  server/pathscientist_tests/test_conversation_resume.py
git commit -m "feat: add conversation resume and inspection helpers"
```

### Task 6 (Optional): Prepare API-Level Read Model for Frontend Session Views

> This task is **optional** — it prepares a read model adapter for future frontend/API integration. Skip if no frontend consumption is planned in the near term.

**Files:**
- Create: `server/backend/pathscientist/persistence/read_model.py`
- Create: `server/pathscientist_tests/test_conversation_read_model.py`
- Reference: `server/backend/pathscientist/persistence/history.py`
- Reference: `server/backend/pathscientist/docs/plan/2026-04-03-code-agent-implementation-plan.md`

**Step 1: Write the failing test**

```python
def test_read_model_exposes_header_and_recent_events(tmp_path):
    summary = build_read_model(tmp_path)
    assert "conversation_id" in summary
    assert "execution_status" in summary
    assert "recent_events" in summary
```

**Step 2: Run test to verify it fails**

Run: `cd server && pytest pathscientist_tests/test_conversation_read_model.py -v`

Expected: FAIL because there is no unified read model yet.

**Step 3: Write minimal implementation**

Create a read model that merges:

- `base_state.json`
- selected `agent_state`
- recent `events/*.json`

Return a small dict for future UI/API use:

```python
{
    "conversation_id": "...",
    "execution_status": "idle",
    "workspace_dir": "...",
    "loaded_skill": "...",
    "best_metric": {...},
    "iteration_state": {...},
    "event_count": 17,
    "recent_events": [...],
}
```

Do not build API routes yet; keep this step as a pure adapter.

**Step 4: Run test to verify it passes**

Run: `cd server && pytest pathscientist_tests/test_conversation_read_model.py -v`

Expected: PASS

**Step 5: Commit**

```bash
git add \
  server/backend/pathscientist/persistence/read_model.py \
  server/pathscientist_tests/test_conversation_read_model.py
git commit -m "feat: add conversation read model for persisted sessions"
```

## Final Verification

Run the full persistence verification suite:

```bash
cd /project/vcompath/storage/ywangrm/PathLab/pathlab/pathlab-client/server
pytest \
  pathscientist_tests/test_conversation_persistence.py \
  pathscientist_tests/test_conversation_resume.py \
  -v
```

Then run the existing asset sanity check:

```bash
cd /project/vcompath/storage/ywangrm/PathLab/pathlab/pathlab-client/server
pytest pathscientist_tests/test_seed_assets.py -v
```

## Notes for Implementation

- OpenHands persistence is already create-or-resume aware; do not duplicate resume logic in a second state store.
- `delete_on_close=False` must be used to preserve conversation state across process restarts.
- Keep conversation persistence separate from experiment output directories.
- Favor `conversation.state.agent_state` over ad hoc sidecar JSON files.
- Keep `tags` minimal and valid: keys must be lowercase alphanumeric only, so structured metadata belongs in `agent_state`.
- Tools access the conversation object through `SessionDeps.conversation` (set after `create_conversation()` in `agent.py`). Do not pass conversation as a tool constructor parameter.
- IterationState must be persisted to `agent_state` after each workflow-state mutation and restored on resume, otherwise the agent may repeat validation / quick-check steps or exceed budget.
- MetricsTracker resume must restore `history` and `iteration`, not just `best_value`, otherwise `get_metrics` becomes inconsistent after restart.
- The frontend/API layer can later expose this through routes modeled after OpenHands `conversation info + events/search`, but that is intentionally not part of this plan (see Task 6 for an optional read model adapter).
