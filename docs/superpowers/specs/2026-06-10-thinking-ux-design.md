# Thinking UX — Streaming Progress During Model Inference

**Date**: 2026-06-10  
**Status**: Draft — pending user review before implementation  
**Scope**: Backend SSE layer + Frontend chat state machine  

---

## Problem

Users report that the chat interface feels "stuck" during the `thinking` phase. The root causes are:

1. **Thinking model silence**: Models like Qwen3 (`qwen/qwen3.5-plus-02-15`, the current default) produce `reasoning_content` tokens before any `content` tokens. `_stream_from_openai_compatible` in `chat_llm_client.py` only handles `delta["content"]` (line 113), so the entire reasoning phase produces zero SSE events. The client receives nothing for potentially 5–30 seconds.

2. **Prefill latency**: Long system prompts require the model to process all input tokens before producing the first output token. This compounds the silence for all models.

The current UI shows only a static `Loader2` spinner during this entire window, giving users no signal that work is happening.

**Constraint**: The model's raw `reasoning_content` must never be forwarded to the client. It can contain references to system prompt structure, internal block names (`[TASK_CONFIG]`, `[WEB_SEARCH]`, etc.), and other implementation details.

---

## Goals

1. Eliminate the "dead" feeling during model prefill and reasoning phases.
2. Give users a live elapsed-time signal while the model thinks.
3. Show meaningful orchestration progress before the LLM is called.
4. Zero exposure of system prompt content or model reasoning text.
5. Graceful degradation: non-thinking models and old frontend versions unaffected.

---

## Non-Goals

- Streaming actual reasoning content to the user (violates the constraint above).
- Prompt caching optimization (separate concern, can be added later).
- Changes to conversation persistence or message structure.

---

## Design

### New SSE Event Types

Two new event types are added to the existing SSE stream. Both contain no model-generated text.

```
data: {"type": "pre_gen_status", "phase": "context_load"}
data: {"type": "pre_gen_status", "phase": "llm_start"}
data: {"type": "thinking_pulse", "elapsed_ms": 1200}
data: {"type": "thinking_pulse", "elapsed_ms": 1800}
data: {"content": "first output token..."}
```

#### `pre_gen_status`

Emitted by the chat route handler in `chat.py` at two points during orchestration:
- `phase: "context_load"` — immediately after receiving the request, before building system prompt and context
- `phase: "llm_start"` — immediately before making the LLM API call

The `phase` values are backend-hardcoded strings. No user input or prompt content appears in this event.

#### `thinking_pulse`

Emitted by `_stream_from_openai_compatible` in `chat_llm_client.py` when `delta["reasoning_content"]` tokens are received from the model. The content of `reasoning_content` is discarded; only elapsed milliseconds since the first reasoning token is emitted.

Throttled to at most one pulse every 600ms to avoid flooding the client.

### Backend Changes

#### `server/gateway/routes/chat_llm_client.py`

In `_stream_from_openai_compatible`, add reasoning_content handling alongside the existing content handling:

```python
thinking_start: float | None = None
last_pulse_ms: int = -600  # ensure first pulse fires immediately

# Inside the delta processing block:
reasoning = delta.get("reasoning_content")
if reasoning is not None:
    if thinking_start is None:
        thinking_start = time.monotonic()
    elapsed_ms = int((time.monotonic() - thinking_start) * 1000)
    if elapsed_ms - last_pulse_ms >= 600:
        last_pulse_ms = elapsed_ms
        yield f"data: {json.dumps({'type': 'thinking_pulse', 'elapsed_ms': elapsed_ms})}\n\n"
    # reasoning text is intentionally not yielded
```

#### `server/gateway/routes/chat.py`

In the main `/chat` handler, yield `pre_gen_status` events at two orchestration checkpoints. The exact injection points are:

1. After request validation, before `_build_system_prompt` / context assembly:
   ```python
   yield make_sse_event({"type": "pre_gen_status", "phase": "context_load"})
   ```

2. After context is fully assembled, immediately before the first `_stream_from_openai_compatible` call:
   ```python
   yield make_sse_event({"type": "pre_gen_status", "phase": "llm_start"})
   ```

`make_sse_event` is a thin helper:
```python
def make_sse_event(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
```

### Frontend Changes

#### `src/renderer/src/api/chat.ts`

Two new optional callbacks on `chatWithAI`:

```typescript
onThinkingPulse?: (elapsedMs: number) => void,
onPreGenStatus?: (phase: 'context_load' | 'llm_start') => void,
```

In `handleSseLine`, alongside the existing event handlers:

```typescript
if (parsed.type === 'thinking_pulse' && onThinkingPulse) {
  onThinkingPulse(parsed.elapsed_ms as number)
}
if (parsed.type === 'pre_gen_status' && onPreGenStatus) {
  onPreGenStatus(parsed.phase as 'context_load' | 'llm_start')
}
```

#### `src/renderer/src/pages/AIChatPage.tsx`

Add state for elapsed thinking time:

```typescript
const [thinkingElapsedMs, setThinkingElapsedMs] = useState(0)
```

Reset on each new generation start (in `executeChatGeneration`, alongside `setGenerationPhase("thinking")`):

```typescript
setThinkingElapsedMs(0)
```

Wire the two new callbacks in the `chatWithAI` call inside `executeChatGeneration`:

```typescript
// onThinkingPulse (14th positional arg or named)
(elapsedMs) => setThinkingElapsedMs(elapsedMs),
// onPreGenStatus (15th positional arg or named)
(_phase) => { /* no-op for now; phase info available if needed */ },
```

#### `ThinkingIndicator` component

New component at `src/renderer/src/components/chat/ThinkingIndicator.tsx`:

```tsx
interface ThinkingIndicatorProps {
  elapsedMs: number
}

export function ThinkingIndicator({ elapsedMs }: ThinkingIndicatorProps) {
  const { t } = useTranslation()
  const elapsedSec = Math.floor(elapsedMs / 1000)

  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
      <Loader2 className="h-4 w-4 animate-spin" />
      <span>
        {elapsedMs > 0
          ? t('aiChat.thinkingWithTime', { seconds: elapsedSec })
          : t('aiChat.thinking')}
      </span>
    </div>
  )
}
```

i18n keys added to all three locale files:
- `aiChat.thinkingWithTime`: `"正在深度思考... 已用 {{seconds}} 秒"` / `"Thinking deeply... {{seconds}}s elapsed"`
- `aiChat.thinking` already exists (current spinner label)

Replace existing `isLoading` spinner in the message list render with `<ThinkingIndicator elapsedMs={thinkingElapsedMs} />`.

---

## Data Flow Diagram

```
User sends message
      │
      ▼
Backend: chat.py handler starts
      │
      ├──► yield pre_gen_status {phase: "context_load"}
      │    Frontend: spinner visible (no elapsed shown yet)
      │
      │    [build system prompt, context, PDF retrieval, etc.]
      │
      ├──► yield pre_gen_status {phase: "llm_start"}
      │    Frontend: spinner still visible
      │
      ▼
Backend: _stream_from_openai_compatible begins
      │
      │    Model prefill (silence from model API)
      │    [no events during pure prefill]
      │
      │    [if thinking model: reasoning_content tokens arrive]
      ├──► yield thinking_pulse {elapsed_ms: 600}
      │    Frontend: "正在深度思考... 已用 0 秒"
      ├──► yield thinking_pulse {elapsed_ms: 1200}
      │    Frontend: "正在深度思考... 已用 1 秒"
      ├──► yield thinking_pulse {elapsed_ms: 3600}
      │    Frontend: "正在深度思考... 已用 3 秒"
      │
      │    [first content token from model]
      ├──► yield content {"content": "..."}
      │    Frontend: phase → "streaming", ThinkingIndicator removed
      │
      ▼
Stream complete
```

---

## Backward Compatibility

| Scenario | Behavior |
|---|---|
| Non-thinking model (no `reasoning_content`) | No `thinking_pulse` events emitted. Frontend shows existing spinner. Zero change. |
| Old frontend (callbacks not passed) | New SSE events arrive and are silently ignored by `handleSseLine` (falls through without matching). Zero impact. |
| Model with thinking disabled | Same as non-thinking model above. |
| `thinkingElapsedMs === 0` on first render | `ThinkingIndicator` shows static "思考中..." label, identical to current behavior. |

---

## Security Checklist

- [x] `reasoning_content` field value never appears in any SSE response
- [x] `thinking_pulse` payload contains only `elapsed_ms` (integer, no strings)
- [x] `pre_gen_status` payload contains only `phase` (backend-hardcoded enum value)
- [x] No system prompt text, no internal block names, no tool names in any new event
- [x] New callbacks are optional; no new required surface area

---

## Files Changed

**Backend:**
- `server/gateway/routes/chat_llm_client.py` — add `reasoning_content` handling in `_stream_from_openai_compatible`
- `server/gateway/routes/chat.py` — emit two `pre_gen_status` events in main handler

**Frontend:**
- `src/renderer/src/api/chat.ts` — two new optional callbacks on `chatWithAI`
- `src/renderer/src/pages/AIChatPage.tsx` — `thinkingElapsedMs` state + wire callbacks
- `src/renderer/src/components/chat/ThinkingIndicator.tsx` — new component
- `src/renderer/src/locales/zh-CN.json` — add `aiChat.thinkingWithTime`
- `src/renderer/src/locales/zh-HK.json` — add `aiChat.thinkingWithTime`
- `src/renderer/src/locales/en-US.json` — add `aiChat.thinkingWithTime`

---

## Open Questions for User Review

1. Should `pre_gen_status` phases be shown as visible text in the UI (e.g., "正在加载上下文...") or just used to confirm the stream is alive without changing the displayed label?
2. Is 600ms throttle interval for thinking pulses appropriate, or should it be faster/slower?
3. Should the elapsed timer be shown in whole seconds or tenths-of-seconds?
