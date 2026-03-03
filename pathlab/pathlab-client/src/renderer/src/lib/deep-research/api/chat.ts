/**
 * Deep Research Chat API - adapted for PathLab frontend.
 * Communicates directly with deep-research backend (bypassing gateway SSE conversion).
 */
import type { MCPServerMetadata } from "../mcp";
import type { Resource } from "../messages";
import { fetchStream } from "../sse";
import { parseJSON } from "../utils";
import { sleep } from "../utils";
import { getDeepResearchLocale } from "../../../i18n/locale";
import i18n from "../../../i18n";

import { resolveServiceURL, getAuthHeaders } from "./resolve-service-url";
import type { ChatEvent } from "./types";

function isAbortError(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === "AbortError") ||
    (error instanceof Error && error.name === "AbortError")
  );
}

function tr(
  key: string,
  defaultValue: string,
  params?: Record<string, string | number>,
): string {
  return i18n.t(`chat.research.${key}`, { ...params, defaultValue }) as string;
}

function mapHttpStatusToMessage(status: number, detail?: string): string {
  if (status === 503 || status === 502 || status === 504) {
    return tr(
      "aiServiceUnavailable",
      "AI service is temporarily unavailable ({status}). Please retry in a moment and check backend model status.",
      { status },
    );
  }
  if (status === 401 || status === 403) {
    return tr(
      "authFailed",
      "Authentication failed ({status}). Please re-login and check your API/auth settings.",
      { status },
    );
  }
  return detail
    ? tr(
      "requestFailedWithDetail",
      "Request failed ({status}): {detail}",
      { status, detail },
    )
    : tr("requestFailed", "Request failed with status {status}", { status });
}

async function readErrorDetail(response: Response): Promise<string> {
  try {
    const text = await response.text();
    if (!text) return "";
    try {
      const parsed = JSON.parse(text) as { detail?: unknown; message?: unknown; error?: unknown };
      return (
        (typeof parsed.detail === "string" && parsed.detail) ||
        (typeof parsed.message === "string" && parsed.message) ||
        (typeof parsed.error === "string" && parsed.error) ||
        text
      );
    } catch {
      return text;
    }
  } catch {
    return "";
  }
}

async function cancelBackgroundJob(jobId: string): Promise<void> {
  try {
    await fetch(resolveServiceURL(`jobs/${jobId}/cancel`), {
      method: "POST",
      headers: {
        ...getAuthHeaders(),
      },
    });
  } catch (error) {
    console.warn("[DeepResearch] Failed to cancel background job:", error);
  }
}

export async function* chatStream(
  userMessage: string,
  params: {
    thread_id: string;
    conversation_id?: string;
    resources?: Array<Resource>;
    auto_accepted_plan: boolean;
    enable_clarification?: boolean;
    max_clarification_rounds?: number;
    max_plan_iterations: number;
    max_step_num: number;
    max_search_results?: number;
    interrupt_feedback?: string;
    enable_deep_thinking?: boolean;
    enable_background_investigation: boolean;
    enable_web_search?: boolean;
    report_style?: "academic" | "popular_science" | "news" | "social_media" | "strategic_investment";
    mcp_settings?: {
      servers: Record<
        string,
        MCPServerMetadata & {
          enabled_tools: string[];
          add_to_agents: string[];
        }
      >;
    };
  },
  options: { abortSignal?: AbortSignal } = {},
) {
  const requestBody = {
    messages: [{ role: "user", content: userMessage }],
    locale: getDeepResearchLocale(),
    ...params,
  };

  const shouldUseBackgroundJob = params.interrupt_feedback === "accepted";

  if (shouldUseBackgroundJob) {
    let jobId: string | null = null;
    try {
      const createResp = await fetch(resolveServiceURL("jobs"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...getAuthHeaders(),
        },
        body: JSON.stringify(requestBody),
      });
      if (!createResp.ok) {
        const detail = await readErrorDetail(createResp);
        console.error("[DeepResearch] Failed to create background job", {
          status: createResp.status,
          detail,
          requestBody,
        });
        throw new Error(mapHttpStatusToMessage(createResp.status, detail));
      }
      const created = (await createResp.json()) as { job_id: string };
      jobId = created.job_id;
      if (!jobId) {
        throw new Error("Background job did not return job_id");
      }

      let cursor = 0;
      while (true) {
        if (options.abortSignal?.aborted) {
          await cancelBackgroundJob(jobId);
          return;
        }
        const eventsResp = await fetch(
          resolveServiceURL(`jobs/${jobId}/events?cursor=${cursor}&wait_ms=15000`),
          {
            method: "GET",
            headers: {
              ...getAuthHeaders(),
            },
            signal: options.abortSignal,
          },
        );
        if (!eventsResp.ok) {
          const detail = await readErrorDetail(eventsResp);
          console.error("[DeepResearch] Failed to poll background job events", {
            jobId,
            status: eventsResp.status,
            detail,
            cursor,
          });
          throw new Error(mapHttpStatusToMessage(eventsResp.status, detail));
        }
        const payload = (await eventsResp.json()) as {
          events: Array<{ event: string; data: unknown }>;
          next_cursor: number;
          status?: string;
          error?: string | null;
          done: boolean;
        };
        let sawErrorEvent = false;
        let lastErrorFromEvent: string | null = null;
        for (const item of payload.events || []) {
          if (item.event === "error" && item.data && typeof item.data === "object") {
            const err = (item.data as { error?: unknown }).error;
            if (typeof err === "string" && err.trim()) {
              sawErrorEvent = true;
              lastErrorFromEvent = err.trim();
            }
          }
          yield {
            type: item.event === "message" ? "message_chunk" : item.event,
            data: item.data,
          } as ChatEvent;
        }
        cursor = payload.next_cursor ?? cursor;
        if (payload.done) {
          if (payload.status === "failed") {
            const err =
              lastErrorFromEvent ||
              (typeof payload.error === "string" && payload.error.trim()
                ? payload.error.trim()
                : tr("deepResearchFailed", "Deep research failed."));
            console.error("[DeepResearch] Background job failed", {
              jobId,
              cursor,
              sawErrorEvent,
              error: err,
              payloadError: payload.error,
            });
            if (!sawErrorEvent) {
              throw new Error(err);
            }
          }
          return;
        }
        await sleep(80);
      }
    } catch (e) {
      if (options.abortSignal?.aborted || isAbortError(e)) {
        if (jobId) {
          await cancelBackgroundJob(jobId);
        }
        return;
      }
      console.warn("[DeepResearch] Background job mode unavailable, fallback to stream:", e);
    }
  }

  try {
    const stream = fetchStream(resolveServiceURL("chat/stream"), {
      headers: {
        ...getAuthHeaders(),
      },
      body: JSON.stringify(requestBody),
      signal: options.abortSignal,
    });

    for await (const event of stream) {
      yield {
        type: event.event === "message" ? "message_chunk" : event.event,
        data: JSON.parse(event.data),
      } as ChatEvent;
    }
  } catch (e) {
    if (options.abortSignal?.aborted || isAbortError(e)) {
      return;
    }
    console.error("[DeepResearch] Chat stream error:", e);
    throw e;
  }
}

// Podcast generation
export async function generatePodcast(content: string): Promise<string> {
  const res = await fetch(resolveServiceURL("podcast/generate"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...getAuthHeaders(),
    },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) {
    throw new Error(`Failed to generate podcast: ${res.statusText}`);
  }
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

// Report evaluation
export async function evaluateReport(params: {
  content: string;
  query: string;
  report_style?: string;
  use_llm?: boolean;
}) {
  const res = await fetch(resolveServiceURL("report/evaluate"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...getAuthHeaders(),
    },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    throw new Error(`Failed to evaluate report: ${res.statusText}`);
  }
  return res.json();
}

// Replay utilities (kept for compatibility but not used via gateway)
export async function fetchReplayTitle() {
  return undefined;
}

/**
 * Send a server-side stop request to gracefully terminate an in-progress
 * deep-research LangGraph run. This complements AbortController (client-side)
 * by also setting stop_requested=True on the LangGraph state so the server
 * finishes the current step cleanly and does not continue.
 */
export async function stopResearch(threadId: string): Promise<void> {
  try {
    await fetch(resolveServiceURL("chat/stop"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...getAuthHeaders(),
      },
      body: JSON.stringify({ thread_id: threadId }),
    });
  } catch (error) {
    console.warn("[DeepResearch] Failed to send server-side stop request:", error);
  }
}



let fastForwardReplaying = false;
export function fastForwardReplay(value: boolean) {
  fastForwardReplaying = value;
}

export interface ResearchIntentDecision {
  startNewResearch: boolean;
  confidence: number;
  reason: string;
  raw: string;
}

const INTENT_CLASSIFIER_PROMPT = [
  "You are an intent classifier for a Deep Research chat UI.",
  "Your task: decide whether the user's latest message asks to START A NEW research topic/run.",
  "Return STRICT JSON only with this schema:",
  '{"start_new_research": boolean, "confidence": number, "reason": string}',
  "Decision rules:",
  "- true: user wants another/new research topic or asks to run deep research again.",
  "- false: follow-up questions on existing report, training/data upload/config requests, clarifications, or normal chat.",
  "- if uncertain, return true with confidence <= 0.6 (fail closed).",
].join("\n");

export async function analyzeResearchStartIntentWithLLM(
  message: string,
  {
    threadId,
    abortSignal,
  }: {
    threadId: string;
    abortSignal?: AbortSignal;
  },
): Promise<ResearchIntentDecision> {
  const trimmed = message.trim();
  if (!trimmed) {
    return {
      startNewResearch: false,
      confidence: 0,
      reason: "empty message",
      raw: "",
    };
  }

  const classifierInput = [
    INTENT_CLASSIFIER_PROMPT,
    "",
    "USER_MESSAGE:",
    trimmed,
  ].join("\n");

  let raw = "";
  try {
    const stream = chatStream(
      classifierInput,
      {
        thread_id: `${threadId}_intent_guard`,
        auto_accepted_plan: false,
        enable_clarification: false,
        max_clarification_rounds: 1,
        max_plan_iterations: 1,
        max_step_num: 1,
        max_search_results: 1,
        enable_deep_thinking: false,
        enable_background_investigation: false,
        enable_web_search: false,
      },
      { abortSignal },
    );

    for await (const event of stream) {
      if (event.type !== "message_chunk") {
        continue;
      }
      const data = event.data as { content?: string; finish_reason?: string };
      if (data.content) {
        raw += data.content;
      }
      if (data.finish_reason === "stop") {
        break;
      }
      if (raw.length > 4000) {
        raw = raw.slice(0, 4000);
        break;
      }
    }
  } catch (error) {
    if (abortSignal?.aborted || isAbortError(error)) {
      return {
        startNewResearch: false,
        confidence: 0,
        reason: "aborted",
        raw,
      };
    }
    console.warn("[DeepResearch] intent classifier failed:", error);
    return {
      startNewResearch: false,
      confidence: 0,
      reason: "classifier unavailable",
      raw,
    };
  }

  const parsed = parseJSON<{
    start_new_research?: boolean;
    confidence?: number;
    reason?: string;
  } | null>(raw, null);

  return {
    startNewResearch: parsed?.start_new_research === true,
    confidence:
      typeof parsed?.confidence === "number" && Number.isFinite(parsed.confidence)
        ? parsed.confidence
        : 0,
    reason: typeof parsed?.reason === "string" ? parsed.reason : "no_reason",
    raw,
  };
}

export async function generateFixedReplyWithLLM(
  fixedReply: string,
  {
    threadId,
    abortSignal,
  }: {
    threadId: string;
    abortSignal?: AbortSignal;
  },
): Promise<{ reply: string; raw: string; usedLLM: boolean }> {
  const normalized = fixedReply.trim();
  if (!normalized) {
    return { reply: fixedReply, raw: "", usedLLM: false };
  }

  const prompt = [
    "You are an assistant in a Deep Research chat UI.",
    "Reply to the user with EXACTLY the sentence below and nothing else.",
    "Do not add markdown, prefix/suffix, explanation, or extra punctuation.",
    "",
    "TARGET_REPLY:",
    normalized,
  ].join("\n");

  let raw = "";
  try {
    const stream = chatStream(
      prompt,
      {
        thread_id: `${threadId}_fixed_reply_guard`,
        auto_accepted_plan: false,
        enable_clarification: false,
        max_clarification_rounds: 1,
        max_plan_iterations: 1,
        max_step_num: 1,
        max_search_results: 1,
        enable_deep_thinking: false,
        enable_background_investigation: false,
        enable_web_search: false,
      },
      { abortSignal },
    );

    for await (const event of stream) {
      if (event.type !== "message_chunk") {
        continue;
      }
      const data = event.data as { content?: string; finish_reason?: string };
      if (data.content) {
        raw += data.content;
      }
      if (data.finish_reason === "stop") {
        break;
      }
      if (raw.length > 4000) {
        raw = raw.slice(0, 4000);
        break;
      }
    }
  } catch (error) {
    if (abortSignal?.aborted || isAbortError(error)) {
      return { reply: normalized, raw, usedLLM: false };
    }
    console.warn("[DeepResearch] fixed reply generation failed:", error);
    return { reply: normalized, raw, usedLLM: false };
  }

  const trimmedRaw = raw.trim();
  if (!trimmedRaw) {
    return { reply: normalized, raw, usedLLM: false };
  }

  const unwrapped = trimmedRaw.replace(/^["'`\s]+|["'`\s]+$/g, "");
  if (trimmedRaw === normalized || unwrapped === normalized || trimmedRaw.includes(normalized)) {
    return { reply: normalized, raw, usedLLM: true };
  }
  return { reply: normalized, raw: trimmedRaw, usedLLM: false };
}
