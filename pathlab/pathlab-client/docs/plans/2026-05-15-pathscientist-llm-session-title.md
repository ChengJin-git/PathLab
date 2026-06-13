# PathScientist LLM Session Title Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add concise `gpt-5.5`-generated PathScientist session titles while preserving the full research question in API and UI.

**Architecture:** The Gateway owns title generation because it already creates and hydrates session records. `SessionRecord.summary()` will return both `title` and `question`; session creation will try a short auxiliary `gpt-5.5` call and fall back to a deterministic title on failure. Persisted legacy sessions get a deterministic concise title derived from their question so the history list stays fast; new web sessions use the gpt-5.5 helper at creation time.

**Tech Stack:** FastAPI Gateway, PathScientist `llm_client.build_chat_llm`/`invoke_chat_llm`, pytest, React/Vite TypeScript.

---

### Task 1: Backend Title API Contract

**Files:**
- Modify: `pathlab/pathlab-client/server/tests/test_pathscientist_routes.py`
- Modify: `pathlab/pathlab-client/server/gateway/routes/pathscientist.py`

**Step 1: Write failing tests**
- Add a test asserting `POST /pathscientist/sessions` returns `title` shorter than the original long question.
- Add a test asserting `GET /pathscientist/sessions` legacy summaries expose `title`.
- Stub the LLM title function so tests do not call the network.

**Step 2: Run tests to verify RED**
- Run: `cd pathlab/pathlab-client/server && backend/pathscientist/.venv/bin/python -m pytest tests/test_pathscientist_routes.py -q`
- Expected: failures because `title` does not exist yet.

**Step 3: Implement minimal backend**
- Add `title: str` to `SessionRecord`.
- Add `title` to `summary()` and registry payloads.
- Generate title in `PathScientistSessionManager.start()`; use deterministic concise fallback in `_scan_persisted_conversations()` for legacy history performance.

**Step 4: Verify GREEN**
- Run the same pytest command.
- Expected: all route tests pass.

### Task 2: LLM Title Generator

**Files:**
- Modify: `pathlab/pathlab-client/server/gateway/routes/pathscientist.py`
- Test: `pathlab/pathlab-client/server/tests/test_pathscientist_routes.py`

**Step 1: Write failing tests**
- Test prompt sanitization: strip quotes/punctuation and clamp title length.
- Test fallback if the LLM helper raises.

**Step 2: Implement helper**
- Add `_fallback_session_title(question)` for deterministic summaries.
- Add `_generate_session_title(question, config=None)` that calls `build_chat_llm(..., llm_model='gpt-5.5')` and `invoke_chat_llm(...)` with a strict prompt.
- Use `extract_text()` and sanitize to one line, <= 72 chars.

**Step 3: Verify**
- Run route tests.

### Task 3: Frontend Title Display

**Files:**
- Modify: `pathlab/pathlab-client/src/renderer/src/types/pathscientist.ts`
- Modify: `pathlab/pathlab-client/src/renderer/src/pages/PathScientistSessionsPage.tsx`
- Modify: `pathlab/pathlab-client/src/renderer/src/pages/PathScientistSessionPage.tsx`

**Step 1: Update types**
- Add optional `title?: string` to `PathScientistSessionSummary`.

**Step 2: Update UI**
- List cards use `session.title || session.question` as the main title.
- Detail header uses title as `<h1>` and shows full question under a “Research question” label.

**Step 3: Verify**
- Run TypeScript check and renderer build.

### Task 4: Dev Server Verification

**Files:**
- Runtime only.

**Step 1: Restart dev Gateway**
- Restart the 6100 dev Gateway so it serves the updated route code.

**Step 2: Smoke test**
- Verify `/pathscientist/sessions` returns items with `title`.
- Verify `/api/pathscientist/sessions` through Vite proxy also returns `title`.
