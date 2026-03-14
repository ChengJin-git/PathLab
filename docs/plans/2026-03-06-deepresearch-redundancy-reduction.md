# DeepResearch Redundancy Reduction Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Remove the remaining active-path redundancy in DeepResearch frontend and backend so the system has one supported stream contract, one LLM settings resolution flow, and one message/render parsing flow.

**Architecture:** The dead UI modules already removed stay out of scope. The remaining work is structural: move frontend protocol parsing and render decisions into shared selectors/utilities, lazy-load heavyweight export code, and collapse duplicated gateway stream/model-probing logic into shared helpers. On the backend, keep `/agent/research/chat/stream` as the canonical stream path and make tests reflect the DB-backed runtime instead of the removed in-memory job model.

**Tech Stack:** Electron + React + TypeScript, FastAPI + SQLAlchemy + httpx + pytest, LangGraph DeepResearch server.

**Resolved Before This Revision:** `report-style-dialog.tsx`, `toaster.tsx`, `evaluation-dialog.tsx`, `research-stats-bar.tsx`, `site-header.tsx`, and `welcome.tsx` have already been removed. `input-box.tsx` no longer carries the old unused `size` prop.

---

### Task 1: Collapse frontend render eligibility and training-link protocol logic

**Files:**
- Create: `pathlab/pathlab-client/src/renderer/src/lib/deep-research/utils/training-link.ts`
- Create: `pathlab/pathlab-client/src/renderer/src/lib/deep-research/selectors/render-decision.ts`
- Modify: `pathlab/pathlab-client/src/renderer/src/lib/deep-research/store/store.ts`
- Modify: `pathlab/pathlab-client/src/renderer/src/pages/DeepResearch/components/message-list-item.tsx`
- Modify: `pathlab/pathlab-client/src/renderer/src/pages/DeepResearch/components/message-list-view.tsx`
- Modify: `pathlab/pathlab-client/src/renderer/src/pages/DeepResearch/components/blocks/message-content.tsx`
- Modify: `pathlab/pathlab-client/src/renderer/src/pages/DeepResearch/components/cards/research-card.tsx`
- Modify: `pathlab/pathlab-client/src/renderer/src/pages/DeepResearch/components/cards/plan-card.tsx`

**Step 1: Extract `TRAINING_CHAT_LINK` helpers**

Create one shared utility with:

```ts
export function parseTrainingChatLink(
  content: string,
): { conversationId: string; title?: string } | null

export function removeTrainingChatLinkBlock(content: string): string

export function findTrainingChatLink(
  messages: Iterable<{ content?: string }>,
): { conversationId: string; title?: string } | null
```

Move all training-link parsing/removal/find logic out of `message-content.tsx` and `research-card.tsx`.

**Step 2: Extract one render/classification selector**

Create a selector/helper that returns the render decision for a message ID:

```ts
type RenderDecision = {
  canRender: boolean
  isLocaleOnly: boolean
  isEmptyContent: boolean
  isPlannerLikeMessage: boolean
  shouldRenderResearchCard: boolean
}
```

This helper must replace duplicated checks currently split between `useRenderableMessageIds()`, `MessageListView`, and `MessageListItem`.

**Step 3: Remove duplicate “research started” loops from `PlanCard`**

Promote the “research started / attached research completed” predicate into the shared selector layer so `PlanCard` stops re-implementing near-identical loops twice.

**Step 4: Delete dead locals created by the old flow**

Remove locals that should disappear after extraction, such as:
- unused `researchPlanIds`
- `showRestartPlanAfterResearchCard`
- the debug-only duplicate hidden/renderable scan in `MessageListView` if it is no longer needed
- the dead cleanup return from `handleToggleResearch`

**Step 5: Run lint and build**

Run:

```bash
cd pathlab/pathlab-client && npm run lint
cd pathlab/pathlab-client && npm run build
```

Expected: frontend compiles cleanly and selector extraction does not introduce type errors.

**Step 6: Commit**

```bash
git add pathlab/pathlab-client/src/renderer/src/lib/deep-research pathlab/pathlab-client/src/renderer/src/pages/DeepResearch/components
git commit -m "Refactor: unify deep research render selectors"
```

### Task 2: Collapse citation and credible-link parsing to one pass per render

**Files:**
- Create: `pathlab/pathlab-client/src/renderer/src/lib/deep-research/selectors/credible-links.ts`
- Modify: `pathlab/pathlab-client/src/renderer/src/components/deep-research/link.tsx`
- Modify: `pathlab/pathlab-client/src/renderer/src/components/deep-research/markdown.tsx`
- Modify: `pathlab/pathlab-client/src/renderer/src/components/deep-research/citation.tsx`

**Step 1: Precompute credible links once**

Add a helper such as:

```ts
export function buildCredibleLinkSet(toolCalls: ToolCallRuntime[] | undefined): Set<string>
```

Compute it in `markdown.tsx` and pass it down. `Link` must stop scanning `toolCalls` per anchor instance.

**Step 2: Stop double citation URL matching**

Refactor the citation render path so `Markdown` resolves the citation match/index once and passes that information into `CitationLink`, rather than having `CitationLink` normalize and search the same URL again.

**Step 3: Remove dead citation exports**

Delete `CitationList` and `CitationBadge` if they still have no renderer call sites after the refactor.

**Step 4: Run lint**

Run:

```bash
cd pathlab/pathlab-client && npm run lint
```

Expected: no prop/type issues from the new citation/link signatures.

**Step 5: Commit**

```bash
git add pathlab/pathlab-client/src/renderer/src/components/deep-research pathlab/pathlab-client/src/renderer/src/lib/deep-research/selectors
git commit -m "Refactor: collapse deep research citation parsing"
```

### Task 3: Slim the heavyweight DeepResearch frontend utility modules

**Files:**
- Modify: `pathlab/pathlab-client/src/renderer/src/pages/DeepResearch/components/use-report-exporter.ts`
- Modify: `pathlab/pathlab-client/src/renderer/src/pages/DeepResearch/components/research-block.tsx`
- Modify: `pathlab/pathlab-client/src/renderer/src/pages/DeepResearch/components/blocks/tool-calls.tsx`
- Modify: `pathlab/pathlab-client/src/renderer/src/pages/DeepResearch/components/messages-block.tsx`
- Modify: `pathlab/pathlab-client/src/renderer/src/pages/DeepResearch/components/research-activities-block.tsx`
- Modify: `pathlab/pathlab-client/src/renderer/src/pages/DeepResearch/components/research-report-block.tsx`

**Step 1: Lazy-load export dependencies**

Move `docx`, `html2canvas`, `jspdf`, and any other export-only dependencies behind dynamic `import()` inside the export handlers.

**Step 2: Extract one shared report HTML builder**

Replace repeated markdown -> sanitized HTML -> citation-footnotes generation in `use-report-exporter.ts` with one shared helper.

**Step 3: Remove repeated filtering and dead props**

- `tool-calls.tsx`: remove repeated `page` filtering after `pageResults` is already derived.
- `messages-block.tsx`: remove unused imports/translation locals if they remain.
- `research-activities-block.tsx`: remove `isLast` / `ongoing` if still passed but not consumed.
- `research-report-block.tsx`: remove `editing` if still not consumed.

**Step 4: Keep the export path off the initial render hot path**

After lazy-loading `use-report-exporter.ts` internals, verify `research-block.tsx` no longer forces export-only libraries into the initial DeepResearch page render path.

**Step 5: Run lint and build**

Run:

```bash
cd pathlab/pathlab-client && npm run lint
cd pathlab/pathlab-client && npm run build
```

Expected: exporter path still works, and the page no longer eagerly loads export-only code on initial render.

**Step 6: Commit**

```bash
git add pathlab/pathlab-client/src/renderer/src/pages/DeepResearch/components
git commit -m "Refactor: lazy load deep research export path"
```

### Task 4: Unify gateway LLM settings resolution and model probing

**Files:**
- Create: `pathlab/pathlab-client/server/gateway/utils/llm_settings.py`
- Modify: `pathlab/pathlab-client/server/gateway/routes/research_chat.py`
- Modify: `pathlab/pathlab-client/server/gateway/routes/chat.py`
- Modify: `pathlab/pathlab-client/server/gateway/routes/settings.py`

**Step 1: Add one shared OpenAI-compatible `/models` probe**

Implement:

```python
async def probe_openai_compatible_models(
    base_url: str,
    api_key: str | None = None,
    timeout_seconds: float = 3.0,
) -> tuple[bool, str | None, str | None]:
    ...
```

Return `(online, first_model, error_message)`.

**Step 2: Add one shared LLM override resolver**

Implement:

```python
async def resolve_llm_override_from_settings() -> dict | None:
    ...
```

This resolver must encode the same fallback policy for chat and research.

**Step 3: Replace duplicated call sites**

- `settings.py`: use the shared probe in `/check-vllm`
- `chat.py`: replace `_check_local_vllm_available` or reduce it to a thin wrapper
- `research_chat.py`: replace `_auto_detect_vllm_model` and `_resolve_llm_override_from_settings`

**Step 4: Verify consistent fallback behavior**

Manual checks:
- local vLLM online -> chat and research both pick local
- local vLLM offline + OpenRouter configured -> chat and research both fallback
- neither configured -> both return the intended configuration error

**Step 5: Commit**

```bash
git add pathlab/pathlab-client/server/gateway/utils/llm_settings.py pathlab/pathlab-client/server/gateway/routes/research_chat.py pathlab/pathlab-client/server/gateway/routes/chat.py pathlab/pathlab-client/server/gateway/routes/settings.py
git commit -m "Refactor: unify llm settings for chat and research"
```

### Task 5: Collapse DeepResearch gateway stream paths and request normalization

**Files:**
- Modify: `pathlab/pathlab-client/server/gateway/routes/research_chat.py`
- Modify: `pathlab/pathlab-client/server/gateway/models.py`
- Modify: `pathlab/pathlab-client/server/backend/deep-research/src/server/chat_request.py`
- Verify callers: `pathlab/pathlab-client/src/renderer/src/lib/deep-research/api/resolve-service-url.ts`

**Step 1: Keep one supported stream contract**

Treat `/agent/research/chat/stream` as the only supported DeepResearch stream path.

**Step 2: Delete or hard-deprecate `/agent/research/stream`**

If nothing still calls it, remove the route. If it must remain briefly, replace the full bespoke SSE conversion stack with a minimal wrapper that delegates to the canonical path.

**Step 3: Extract one request-body normalizer**

Move this logic into one helper:
- accept `message` or `messages`
- require `messages`
- normalize `thread_id`
- inject `llm_override`

Use it for both raw stream and job-creation entry points.

**Step 4: Extract one stream transport helper**

Factor out shared logic for:
- in-proc vs external transport
- non-200 mapping
- SSE chunk forwarding

Use that helper in:
- raw stream path
- background job ingestion path
- any temporary legacy wrapper, if it still exists

**Step 5: Commit**

```bash
git add pathlab/pathlab-client/server/gateway/routes/research_chat.py pathlab/pathlab-client/server/gateway/models.py pathlab/pathlab-client/server/backend/deep-research/src/server/chat_request.py
git commit -m "Refactor: collapse deep research stream contract"
```

### Task 6: Align backend tests and helper layers with the real runtime

**Files:**
- Modify: `pathlab/pathlab-client/server/gateway/tests/test_research_chat_jobs.py`
- Modify: `pathlab/pathlab-client/server/backend/deep-research/src/server/app.py`
- Modify: `pathlab/pathlab-client/server/backend/deep-research/src/server/mcp_request.py`
- Modify: `pathlab/pathlab-client/server/backend/deep-research/src/server/mcp_validators.py`
- Modify: `pathlab/pathlab-client/server/backend/deep-research/src/server/mcp_utils.py`

**Step 1: Rewrite research job tests against the current DB-backed model**

Stop using `_background_jobs` / `_background_jobs_lock`. Test against:
- `_running_tasks`
- `ResearchJobRepository`
- DB-backed event retrieval

**Step 2: Deduplicate the `app.py` checkpointer streaming branches**

Extract a helper like:

```python
async def _yield_stream_with_graph(
    graph,
    workflow_input,
    workflow_config,
    thread_id,
):
    ...
```

Use it for:
- global postgres
- per-request postgres
- global mongo
- per-request mongo
- no-checkpointer path

**Step 3: Collapse duplicate MCP validation**

Choose one validation boundary. Either:
- keep validation in `mcp_request.py` and remove duplicate transport-specific checks from `mcp_validators.py`, or
- keep `validate_mcp_server_config()` as the source of truth and make the request model delegate to it

`mcp_utils.py` must not re-introduce validation already guaranteed at the request boundary.

**Step 4: Run backend tests**

Run:

```bash
cd pathlab/pathlab-client/server && uv run pytest gateway/tests/test_research_chat_jobs.py -q
```

Expected: tests now match the actual runtime architecture instead of the removed in-memory model.

**Step 5: Commit**

```bash
git add pathlab/pathlab-client/server/gateway/tests/test_research_chat_jobs.py pathlab/pathlab-client/server/backend/deep-research/src/server
git commit -m "Refactor: align deep research backend helpers and tests"
```

### Task 7: Final verification

**Files:**
- Verify only

**Step 1: Frontend lint**

Run:

```bash
cd pathlab/pathlab-client && npm run lint
```

Expected: PASS.

**Step 2: Frontend production build**

Run:

```bash
cd pathlab/pathlab-client && npm run build
```

Expected: PASS.

**Step 3: Backend targeted tests**

Run:

```bash
cd pathlab/pathlab-client/server && uv run pytest gateway/tests/test_research_chat_jobs.py -q
```

Expected: PASS.

**Step 4: DeepResearch smoke check**

Manual checks:
- Open DeepResearch page.
- Start one research run.
- Confirm the frontend still streams through `/agent/research/chat/stream`.
- Confirm a training handoff still creates exactly one linked AI chat.
- Confirm chat and research both choose local vLLM / OpenRouter using the same fallback policy.
- Confirm `check-vllm` still detects a local model.

**Step 5: Final commit**

```bash
git add .
git commit -m "Chore: reduce deep research redundancy"
```
