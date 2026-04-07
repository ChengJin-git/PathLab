# Gateway Startup and Runtime Hygiene Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce PathLab architectural drift by moving bundled training-recommendation runtime artifacts out of the source tree and extracting low-risk Gateway app assembly/startup helpers without changing runtime behavior.

**Architecture:** Keep the current `gateway.main` public entrypoint and service behavior intact, but move assembly/runtime helpers behind focused modules so the main file stops owning every concern directly. Runtime-generated caches for bundled training recommendation data should follow the same uploads-backed contract already used by PDF cache/vector store state.

**Tech Stack:** Python 3.10+, FastAPI, async SQLAlchemy, pytest, Electron + Python sidecar packaging layout.

---

### Task 1: Lock runtime artifact paths behind a stable knowledge-path API

**Files:**
- Modify: `pathlab/pathlab-client/server/gateway/knowledge/chat/__init__.py`
- Modify: `pathlab/pathlab-client/server/gateway/routes/chat_training_recommendation.py`
- Test: `pathlab/pathlab-client/server/tests/test_training_recommendation_paths.py`

- [ ] **Step 1: Write the failing test**

```python
from gateway.knowledge import chat as chat_knowledge


def test_training_recommendation_runtime_dirs_live_under_uploads(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "backend.common.config.Config.get_uploads_dir",
        lambda: tmp_path / "uploads",
    )

    cache_dir = chat_knowledge.get_training_rag_cache_dir()
    vector_dir = chat_knowledge.get_training_rag_vectorstore_dir()

    assert cache_dir == tmp_path / "uploads" / "pdf_cache" / "training_recommendation" / "cache"
    assert vector_dir == tmp_path / "uploads" / "pdf_cache" / "training_recommendation" / "vector_store"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest pathlab/pathlab-client/server/tests/test_training_recommendation_paths.py -q`
Expected: FAIL because the helper functions do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
def get_training_rag_runtime_dir() -> Path:
    return Config.get_uploads_dir() / "pdf_cache" / "training_recommendation"


def get_training_rag_cache_dir() -> Path:
    path = get_training_rag_runtime_dir() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_training_rag_vectorstore_dir() -> Path:
    path = get_training_rag_runtime_dir() / "vector_store"
    path.mkdir(parents=True, exist_ok=True)
    return path
```

- [ ] **Step 4: Switch bundled training recommendation code to the new helpers**

Update `chat_training_recommendation.py` to import the helper functions instead of source-tree constants so the runtime cache path is resolved lazily from uploads.

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest pathlab/pathlab-client/server/tests/test_training_recommendation_paths.py -q`
Expected: PASS.


### Task 2: Extract Gateway app assembly helpers out of `gateway.main`

**Files:**
- Create: `pathlab/pathlab-client/server/gateway/app_setup.py`
- Modify: `pathlab/pathlab-client/server/gateway/main.py`
- Test: `pathlab/pathlab-client/server/tests/test_gateway_app_setup.py`

- [ ] **Step 1: Write the failing tests**

```python
from fastapi import FastAPI
from gateway.app_setup import include_api_routers, mount_static_routes


def test_include_api_routers_registers_expected_paths():
    app = FastAPI()
    include_api_routers(app)
    paths = {route.path for route in app.routes}
    assert "/health" not in paths
    assert "/settings" in paths


def test_mount_static_routes_mounts_avatars_only_when_renderer_dist_missing(tmp_path, monkeypatch):
    app = FastAPI()
    monkeypatch.setattr("backend.common.config.Config.get_uploads_dir", lambda: tmp_path / "uploads")

    mount_static_routes(app, renderer_dist=tmp_path / "missing-renderer")

    mounted = {route.path for route in app.routes}
    assert "/avatars" in mounted
    assert "/assets" not in mounted
    assert "/images" not in mounted
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest pathlab/pathlab-client/server/tests/test_gateway_app_setup.py -q`
Expected: FAIL because `gateway.app_setup` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Create `gateway/app_setup.py` with focused helpers for:
- including the existing router list
- mounting `/avatars`
- optionally mounting `/images` and `/assets` when renderer dist exists

- [ ] **Step 4: Refactor `gateway.main` to use the new helpers**

Keep `app = FastAPI(..., lifespan=lifespan)` in `gateway.main`, but replace inline router/static registration with `mount_static_routes(app)` and `include_api_routers(app)` so app assembly is isolated from startup orchestration.

- [ ] **Step 5: Re-run tests to verify they pass**

Run: `python -m pytest pathlab/pathlab-client/server/tests/test_gateway_app_setup.py -q`
Expected: PASS.


### Task 3: Verify no runtime behavior regressions in the touched seams

**Files:**
- Test: `pathlab/pathlab-client/server/tests/test_training_recommendation_paths.py`
- Test: `pathlab/pathlab-client/server/tests/test_gateway_app_setup.py`
- Test: `pathlab/pathlab-client/server/tests/test_settings.py`

- [ ] **Step 1: Run targeted pytest coverage for touched seams**

Run: `python -m pytest pathlab/pathlab-client/server/tests/test_training_recommendation_paths.py pathlab/pathlab-client/server/tests/test_gateway_app_setup.py pathlab/pathlab-client/server/tests/test_settings.py -q`
Expected: PASS.

- [ ] **Step 2: Run Python diagnostics/build-oriented validation**

Run: `python -m compileall pathlab/pathlab-client/server/gateway`
Expected: PASS without syntax errors.

- [ ] **Step 3: Inspect the resulting diff for behavior-preserving scope**

Confirm the change set only:
- moves bundled training-recommendation runtime writes under uploads-backed directories
- extracts app assembly helpers from `gateway.main`
- leaves service routes, health endpoint, and startup behavior unchanged
