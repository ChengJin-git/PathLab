# Thinking UX — Streaming Progress During Model Inference

**Date**: 2026-06-10  
**Status**: Approved — ready for implementation  
**Scope**: Backend SSE layer + Frontend chat state machine  

---

## Problem

Users report that the chat interface feels "stuck" during the `thinking` phase. Two root causes:

1. **Thinking model silence**: Models like Qwen3 (`qwen/qwen3.5-plus-02-15`, the current default) produce `reasoning_content` tokens before any `content` tokens. `_stream_from_openai_compatible` in `chat_llm_client.py` only handles `delta["content"]` (line 113), so the entire reasoning phase produces zero SSE events. The client receives nothing for potentially 5–30 seconds.

2. **Prefill latency**: Long system prompts require all input tokens to be processed before the first output token arrives. This compounds the silence for all model types.

The current UI shows only a static `Loader2` spinner during this entire window — no signal that the model is working.

**Hard constraint**: The model's raw `reasoning_content` must never be forwarded to the client. It can contain references to system prompt structure, internal block names (`[TASK_CONFIG]`, `[WEB_SEARCH]`, etc.), and other implementation details that must not be exposed.

---

## Goals

1. Eliminate the "dead/stuck" feeling during model prefill and reasoning phases.
2. Keep the client alive during the silence window (reset the existing 60-second silence abort timer).
3. No visible elapsed time in the UI — the animation alone conveys liveness.
4. Zero exposure of system prompt content or model reasoning text.
5. Graceful degradation: non-thinking models and old frontend versions unaffected.

---

## Non-Goals

- Showing `pre_gen_status` phase text to the user — these events are silent liveness signals only.
- Displaying elapsed seconds in the UI (`thinking_pulse` is backend-only bookkeeping).
- Prompt caching optimization (separate concern).
- Streaming any actual reasoning content.
- Changes to conversation persistence or message structure.

---

## Decisions

| Question | Decision |
|---|---|
| Show `pre_gen_status` as visible UI text? | No — silent signal only, no label change |
| 600ms throttle for thinking pulses? | Keep for now, revisit if needed |
| Show elapsed timer in frontend? | No — backend emits `elapsed_ms` for potential future use, frontend ignores the value |

---

## Design

### New SSE Event Types

Two new event types added to the existing SSE stream. Neither contains any model-generated text.

```
data: {"type": "pre_gen_status", "phase": "context_load"}
data: {"type": "pre_gen_status", "phase": "llm_start"}
data: {"type": "thinking_pulse", "elapsed_ms": 600}
data: {"type": "thinking_pulse", "elapsed_ms": 1200}
data: {"content": "first output token..."}
```

#### `pre_gen_status`

Emitted by the chat route handler at two orchestration checkpoints before the LLM call. Purpose: confirms the SSE stream is alive during the context-build phase. No visible UI change on receipt.

- `phase: "context_load"` — immediately after request validation, before system prompt assembly
- `phase: "llm_start"` — after all context is assembled, immediately before the LLM call

Values are backend-hardcoded strings. No user input or prompt content is present.

#### `thinking_pulse`

Emitted by `_stream_from_openai_compatible` when `delta["reasoning_content"]` tokens arrive. The reasoning text is discarded; only elapsed milliseconds since the first reasoning token is sent. Purpose: resets the client-side silence abort timer.

- Throttled: at most one pulse per 600ms using monotonic time comparison
- First pulse fires immediately when the first `reasoning_content` token arrives
- Frontend receives but does not display `elapsed_ms`

---

## Backend Changes

### `server/gateway/routes/chat_llm_client.py`

In `_stream_from_openai_compatible`, add `reasoning_content` handling immediately after the `content` check. Use monotonic-time throttle (not count-based):

```python
# Initialize before the streaming loop
thinking_start: float | None = None
last_pulse_at: float = 0.0
_THINKING_PULSE_INTERVAL = 0.6  # seconds

# Inside the delta processing block, after existing content handling:
reasoning = delta.get("reasoning_content")
if reasoning is not None:
    now = time.monotonic()
    if thinking_start is None:
        thinking_start = now
        last_pulse_at = now - _THINKING_PULSE_INTERVAL  # fire immediately
    if now - last_pulse_at >= _THINKING_PULSE_INTERVAL:
        last_pulse_at = now
        elapsed_ms = int((now - thinking_start) * 1000)
        yield f"data: {json.dumps({'type': 'thinking_pulse', 'elapsed_ms': elapsed_ms})}\n\n"
    # reasoning text intentionally not yielded
```

Note: `_call_ai_complete` (the non-streaming path used for title generation) does not yield SSE events. No change needed there, but ensure the non-streaming response parser also does not forward `reasoning_content`.

### `server/gateway/routes/chat.py`

The chat handler is an async generator that yields SSE lines. Emit `pre_gen_status` at two points within the generator:

**Point 1** — after request parsing and auth, before context/system-prompt assembly:
```python
yield f"data: {json.dumps({'type': 'pre_gen_status', 'phase': 'context_load'}, ensure_ascii=False)}\n\n"
```

**Point 2** — after all context is built, immediately before calling `_stream_from_openai_compatible` (or equivalent):
```python
yield f"data: {json.dumps({'type': 'pre_gen_status', 'phase': 'llm_start'}, ensure_ascii=False)}\n\n"
```

These two yields must be placed inside the outermost generator that is consumed by the SSE response. If there is an intermediate wrapper (`stream_with_persistence` or similar), ensure the yields are in the correct scope so they reach the client.

---

## Frontend Changes

### `src/renderer/src/api/chat.ts`

Add two optional callbacks to `chatWithAI`. Because the function already has 13 positional parameters, append these as a trailing options object rather than more positional args:

**Option A (minimal change)** — add as two more optional positional parameters at positions 14–15. Acceptable given the function is called from a single site (`AIChatPage.tsx`).

**Option B (preferred if time allows)** — convert the last N callbacks into a `ChatEventHandlers` options object. This is a clean-up that pays off long-term but is not required for this feature to ship.

Whichever option is chosen, `handleSseLine` gains two new branches:

```typescript
if (parsed.type === 'thinking_pulse' && onThinkingPulse) {
  onThinkingPulse(parsed.elapsed_ms as number)
}
if (parsed.type === 'pre_gen_status' && onPreGenStatus) {
  onPreGenStatus(parsed.phase as 'context_load' | 'llm_start')
}
```

### `src/renderer/src/pages/AIChatPage.tsx`

**Do not add `thinkingElapsedMs` state.** The elapsed value is not displayed.

Instead, wire `onThinkingPulse` to reset the existing silence abort timer. In `executeChatGeneration`, pass the callback:

```typescript
// onThinkingPulse: reset silence timer so pulses keep the connection alive
() => startSilenceTimer(),
// onPreGenStatus: no-op for now
(_phase) => {},
```

Note: the `startSilenceTimer` closure is already defined inside `executeChatGeneration` (line ~1704). The callback can reference it directly.

**Generation ID guard**: wrap the `onThinkingPulse` callback with a generation ID check to discard stale pulses if a new generation starts before the old one finishes:

```typescript
const capturedGenId = ++generationIdRef.current
// ...
(elapsedMs) => {
  if (generationIdRef.current !== capturedGenId) return
  startSilenceTimer()
},
```

(The existing code already increments `generationIdRef.current` via `const currentGenerationId = ++generationIdRef.current` at line ~1694 — capture this value.)

### Animated Thinking Indicator

Replace the current static `Loader2` spinner shown during `isLoading` with a CSS-animated typing indicator (three bouncing dots). No text label changes. No elapsed time display.

The visual transition is:
- **`thinking` phase**: animated dots indicator (conveys "something is happening")
- **`streaming` phase**: dots disappear, streamed text appears character by character

The dots animation is pure CSS (`@keyframes` bounce with staggered delays on three `<span>` elements). No JS timer, no state updates.

No new i18n keys required for this change.

---

## Data Flow (Updated)

```
User sends message
      │
      ▼
Backend: chat.py handler starts
      │
      ├──► yield pre_gen_status {phase: "context_load"}
      │    Frontend: silence timer resets, animated dots visible
      │    [build system prompt, retrieve context, PDF retrieval, etc.]
      │
      ├──► yield pre_gen_status {phase: "llm_start"}
      │    Frontend: silence timer resets, animated dots still visible
      │
      ▼
Backend: LLM API call begins
      │
      │    [pure prefill — model API silent, no events]
      │
      │    [if thinking model: reasoning_content tokens arrive]
      ├──► yield thinking_pulse {elapsed_ms: 0}      (first token)
      │    Frontend: silence timer resets
      ├──► yield thinking_pulse {elapsed_ms: 600}
      │    Frontend: silence timer resets
      ├──► yield thinking_pulse {elapsed_ms: 1200}
      │    Frontend: silence timer resets
      │
      │    [first content token from model]
      ├──► yield content {"content": "..."}
      │    Frontend: phase → "streaming", dots removed, text appears
      │
      ▼
Stream complete
```

---

## Backward Compatibility

| Scenario | Behavior |
|---|---|
| Non-thinking model (no `reasoning_content`) | No `thinking_pulse` emitted. Frontend shows animated dots (same as before this change), transition to content as usual. |
| Old frontend (callbacks not passed) | New SSE events arrive, `handleSseLine` falls through without matching — silently ignored. |
| Model with `reasoning_content` disabled | Same as non-thinking model. |

---

## Security Checklist

- [x] `reasoning_content` field value never appears in any SSE response
- [x] `thinking_pulse` contains only `elapsed_ms` (integer — no strings, no content)
- [x] `pre_gen_status` contains only `phase` (backend-hardcoded enum — no user input, no prompt fragments)
- [x] No system prompt text, internal block names, or tool names in any new event
- [x] New callbacks are optional; no new required interface surface

---

## Oracle Review Findings Addressed

| Finding | Resolution |
|---|---|
| Throttle should be time-based, first pulse immediate | Fixed: use `last_pulse_at = now - interval` init pattern |
| `chatWithAI` positional arg explosion | Noted; Option B (options object) preferred if time allows, not blocking |
| Reset timing: before `chatWithAI` call, not in callback | Addressed: no state to reset (no `thinkingElapsedMs` state) |
| Generation ID guard for stale callbacks | Added to `onThinkingPulse` wiring |
| Non-streaming path leakage | Confirmed `_call_ai_complete` returns text only, no SSE emission |
| `pre_gen_status` injection scope | Caller must ensure yields are in the outermost SSE generator |
| Tests | See below |

---

## Files Changed

**Backend:**
- `server/gateway/routes/chat_llm_client.py` — add `reasoning_content` handling, monotonic-time throttle
- `server/gateway/routes/chat.py` — emit `pre_gen_status` at two orchestration points

**Frontend:**
- `src/renderer/src/api/chat.ts` — `onThinkingPulse` and `onPreGenStatus` callbacks
- `src/renderer/src/pages/AIChatPage.tsx` — wire callbacks, generation ID guard
- `src/renderer/src/components/chat/ThinkingIndicator.tsx` — new animated dots component (replaces static spinner during `thinking` phase)

**No i18n changes required.**

---

## Tests to Add

**Backend** (`server/tests/`):
- Verify `_stream_from_openai_compatible` emits `thinking_pulse` when `reasoning_content` present
- Verify `reasoning_content` value is never present in emitted SSE lines
- Verify throttle fires at most once per 600ms

**Frontend** (`test/unit/`):
- Verify `handleSseLine` calls `onThinkingPulse` for `thinking_pulse` events
- Verify `ThinkingIndicator` renders animated dots (no elapsed text)
- Verify stale generation ID guard prevents callback on cancelled generation
