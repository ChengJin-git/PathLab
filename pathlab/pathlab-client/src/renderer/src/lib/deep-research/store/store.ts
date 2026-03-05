// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { nanoid } from "nanoid";
import { toast } from "sonner";
import { create } from "zustand";
import { useShallow } from "zustand/react/shallow";
import {
  addMessage as apiAddMessage,
  chatWithAI as chatWithStandardAI,
  createConversation as apiCreateConversation,
  getConversation as apiGetConversation,
  updateMessage as apiUpdateMessage,
} from "../../../api";
import type { ChatMessage as StandardChatMessage } from "../../../api/chat";
import i18n from "../../../i18n";
import { sanitizeConfigBlocksForAI } from "../../chatMessageParser";

import {
  analyzeResearchStartIntentWithLLM,
  chatStream,
  generateFixedReplyWithLLM,
  generatePodcast,
  getBackgroundJobStatus,
  resumeBackgroundJobStream,
  stopResearch,
} from "../api/chat";
import type { ChatEvent, TokenUsageEvent } from "../api/types";
import type { Citation, Message, Resource } from "../messages";
import { mergeMessage } from "../messages";
import { parseJSON } from "../utils";
import {
  clearLogBuffer,
  downloadLogs,
  exportLogsAsText,
  getLogBuffer,
  pushLog,
} from "../utils/log-collector";

import { getChatStreamSettings } from "./settings-store";

// Types for token usage and response timing
export interface TokenUsageSummary {
  totalPromptTokens: number;
  totalCompletionTokens: number;
  totalTokens: number;
  totalCalls: number;
  byAgent: Record<
    string,
    {
      prompt_tokens: number;
      completion_tokens: number;
      total_tokens: number;
      calls: number;
    }
  >;
}

export interface ResponseTiming {
  startTime: number;
  endTime: number | null;
  durationMs: number | null;
}

const STORE_PERSIST_KEY = "pathlab.deep_research.store.v1";
const CONVERSATION_CACHE_KEY = "pathlab.deep_research.conversation_cache.v1";
const MAX_PERSISTED_MESSAGES = 400;
const MAX_CACHED_CONVERSATIONS = 60;
const DEEP_RESEARCH_TASK_START_EVENT = "pathlab:deep-research-task-start";
const DEEP_RESEARCH_TASK_FINISH_EVENT = "pathlab:deep-research-task-finish";
const BACKEND_REBUILD_RETRY_MAX = 3;
const BACKEND_REBUILD_RETRY_DELAY_MS = 1500;
const DEEP_RESEARCH_DEBUG_STORAGE_KEY = "pathlab.deep_research.debug";
const DEEP_RESEARCH_DEBUG_QUERY_KEY = "dr_debug";
const backendRebuildRetryCounts = new Map<string, number>();
const backendLoadSeqByConversation = new Map<string, number>();
let latestRequestedConversationId: string | null = null;

export function isDeepResearchDebugEnabled(): boolean {
  if (typeof window === "undefined") return false;
  try {
    const params = new URLSearchParams(window.location.search);
    const queryFlag = params.get(DEEP_RESEARCH_DEBUG_QUERY_KEY);
    if (queryFlag === "1" || queryFlag === "true") {
      localStorage.setItem(DEEP_RESEARCH_DEBUG_STORAGE_KEY, "1");
      return true;
    }
    if (queryFlag === "0" || queryFlag === "false") {
      localStorage.setItem(DEEP_RESEARCH_DEBUG_STORAGE_KEY, "0");
      return false;
    }
    return localStorage.getItem(DEEP_RESEARCH_DEBUG_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function setDeepResearchDebugEnabled(enabled: boolean) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(DEEP_RESEARCH_DEBUG_STORAGE_KEY, enabled ? "1" : "0");
  } catch {
    // Ignore storage errors.
  }
}

function deepResearchDebugLog(scope: string, message: string, payload?: unknown) {
  pushLog("debug", scope, message, payload);
  if (!isDeepResearchDebugEnabled()) return;
  if (payload === undefined) {
    console.log(`[DeepResearch][Debug][${scope}] ${message}`);
    return;
  }
  console.log(`[DeepResearch][Debug][${scope}] ${message}`, payload);
}

function formatConsoleErrorPayload(payload: unknown): string {
  if (payload === undefined) return "";
  if (payload instanceof Error) {
    return JSON.stringify(
      {
        name: payload.name,
        message: payload.message,
        stack: payload.stack,
        cause: (payload as Error & { cause?: unknown }).cause,
      },
      null,
      2,
    );
  }
  if (typeof payload === "string") return payload;
  if (typeof payload === "number" || typeof payload === "boolean") return String(payload);
  try {
    return JSON.stringify(payload, null, 2);
  } catch {
    return String(payload);
  }
}

function deepResearchConsoleError(scope: string, message: string, payload?: unknown) {
  pushLog("error", scope, message, payload);
  const base = `[DeepResearch][${scope}] ${message}`;
  if (payload === undefined) {
    console.error(base);
    return;
  }
  const formatted = formatConsoleErrorPayload(payload);
  if (formatted) {
    console.error(`${base}\n${formatted}`);
  } else {
    console.error(base, payload);
  }
}

function tr(
  key: string,
  defaultValue: string,
  params?: Record<string, string | number>,
): string {
  return i18n.t(`chat.research.${key}`, { ...params, defaultValue }) as string;
}

function getAlignedAIChatErrorFallback(): string {
  return i18n.t("aiChat.aiErrorFallback", {
    defaultValue: "Sorry, I encountered an error. Please try again.",
  }) as string;
}

function pickDeepResearchErrorMessage(raw: unknown): string {
  if (typeof raw === "string" && raw.trim().length > 0) {
    return raw.trim();
  }
  return getAlignedAIChatErrorFallback();
}

type DeepResearchTaskStatus = "running" | "success" | "error" | "cancelled";
type GenerationPhase = "idle" | "thinking" | "streaming" | "pdf_waiting";

interface DeepResearchTaskEventDetail {
  taskId: string;
  title?: string;
  conversationId?: string | null;
  status?: DeepResearchTaskStatus;
  error?: string;
}

interface PersistedStoreState {
  threadId: string;
  conversationId: string | null;
  messageIds: string[];
  messages: Array<[string, Message]>;
  messageBackendIds: Array<[string, number]>;
  researchIds: string[];
  researchPlanIds: Array<[string, string]>;
  researchReportIds: Array<[string, string]>;
  researchActivityIds: Array<[string, string[]]>;
  researchQueries: Array<[string, string]>;
  researchCitations: Array<[string, Citation[]]>;
  researchRunStatus?: Array<[string, DeepResearchTaskStatus]>;
  restartPlanShownResearchIds?: string[];
  planActionLocks?: Array<[string, "accepted" | "replan"]>;
  ongoingResearchId: string | null;
  openResearchId: string | null;
  backgroundJobId?: string | null;
  backgroundJobCursor?: number;
  tokenUsage?: TokenUsageSummary | null;
  sessionTokenUsage?: {
    totalTokens: number;
    totalCalls: number;
    totalPromptTokens: number;
    totalCompletionTokens: number;
  };
  responseTiming?: ResponseTiming | null;
}

interface PersistedConversationState {
  threadId: string;
  messageIds: string[];
  messages: Array<[string, Message]>;
  messageBackendIds: Array<[string, number]>;
  researchIds: string[];
  researchPlanIds: Array<[string, string]>;
  researchReportIds: Array<[string, string]>;
  researchActivityIds: Array<[string, string[]]>;
  researchQueries: Array<[string, string]>;
  researchCitations: Array<[string, Citation[]]>;
  researchRunStatus?: Array<[string, DeepResearchTaskStatus]>;
  restartPlanShownResearchIds?: string[];
  planActionLocks?: Array<[string, "accepted" | "replan"]>;
  ongoingResearchId: string | null;
  openResearchId: string | null;
  backgroundJobId?: string | null;
  backgroundJobCursor?: number;
  tokenUsage?: TokenUsageSummary | null;
  sessionTokenUsage?: {
    totalTokens: number;
    totalCalls: number;
    totalPromptTokens: number;
    totalCompletionTokens: number;
  };
  responseTiming?: ResponseTiming | null;
  updatedAt: number;
}

type PersistedConversationCache = Record<string, PersistedConversationState>;

function emitDeepResearchTaskEvent(
  eventName: string,
  detail: DeepResearchTaskEventDetail,
) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(eventName, { detail }));
}

function isAbortLikeError(error: unknown): boolean {
  if (error instanceof DOMException && error.name === "AbortError") {
    return true;
  }
  if (error instanceof Error && error.name === "AbortError") {
    return true;
  }
  if (error instanceof Error && /aborted/i.test(error.message)) {
    return true;
  }
  return false;
}

function isDeepResearchExecutionAgent(agent?: string): boolean {
  return (
    agent === "researcher" ||
    agent === "analyst" ||
    agent === "reporter" ||
    agent === "coder"
  );
}

function deriveDeepResearchTaskTitle(
  content: string | undefined,
  interruptFeedback: string | undefined,
): string {
  const fallback = "Deep Research";
  const state = useStore.getState();

  // For explicit "Start research", prefer the prior user research query
  // instead of the confirmation utterance like "Great! Let's start."
  if (interruptFeedback === "accepted") {
    const reversedIds = [...state.messageIds].reverse();
    for (const id of reversedIds) {
      const msg = state.messages.get(id);
      if (!msg || msg.role !== "user") continue;
      const text = (msg.content ?? "").trim();
      if (!text) continue;
      return text.slice(0, 80);
    }
  }

  const direct = (content ?? "").trim();
  if (direct && direct !== "[REPLAY]") {
    return direct.slice(0, 80);
  }
  return fallback;
}

function looksLikePlannerPayload(candidate: string): boolean {
  const probe = candidate.toLowerCase();
  return (
    probe.includes("\"step_type\"") ||
    probe.includes("\"need_search\"") ||
    probe.includes("\"has_enough_context\"") ||
    (probe.includes("\"thought\"") && probe.includes("\"steps\"")) ||
    (probe.includes("\"title\"") && probe.includes("\"steps\""))
  );
}

function extractPlannerTitle(content: string | undefined): string | null {
  const trimmed = (content ?? "").trim();
  if (!trimmed) return null;

  const fencedMatch = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const candidate = fencedMatch ? fencedMatch[1]?.trim() ?? "" : trimmed;
  const looksLikeJsonEnvelope = /^[\[{]/.test(candidate);
  if (fencedMatch || looksLikeJsonEnvelope || looksLikePlannerPayload(candidate)) {
    const parsed = parseJSON<{ title?: string } | null>(candidate, null);
    const title = typeof parsed?.title === "string" ? parsed.title.trim() : "";
    if (title) {
      return title;
    }
  }

  const titleMatch = candidate.match(/"title"\s*:\s*"([\s\S]*?)"/);
  const fallbackTitle = titleMatch?.[1]?.trim() ?? "";
  return fallbackTitle || null;
}

function getCurrentPlannerTitleFromState(): string | null {
  const state = useStore.getState();
  const candidatePlanIds: string[] = [];
  const preferredResearchId =
    state.openResearchId ??
    state.ongoingResearchId ??
    state.researchIds[state.researchIds.length - 1];

  if (preferredResearchId) {
    const planId = state.researchPlanIds.get(preferredResearchId);
    if (planId) {
      candidatePlanIds.push(planId);
    }
  }

  for (const messageId of [...state.messageIds].reverse()) {
    const msg = state.messages.get(messageId);
    if (msg?.agent === "planner") {
      candidatePlanIds.push(messageId);
    }
  }

  for (const planId of candidatePlanIds) {
    const msg = state.messages.get(planId);
    const title = extractPlannerTitle(msg?.content);
    if (title) {
      return title;
    }
  }
  return null;
}

function loadPersistedState(): PersistedStoreState | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const raw = localStorage.getItem(STORE_PERSIST_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as PersistedStoreState;
    if (!parsed.threadId || !Array.isArray(parsed.messageIds) || !Array.isArray(parsed.messages)) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

function loadConversationCache(): PersistedConversationCache {
  if (typeof window === "undefined") {
    return {};
  }
  try {
    const raw = localStorage.getItem(CONVERSATION_CACHE_KEY);
    if (!raw) {
      return {};
    }
    const parsed = JSON.parse(raw) as PersistedConversationCache;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function saveConversationCache(cache: PersistedConversationCache) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    localStorage.setItem(CONVERSATION_CACHE_KEY, JSON.stringify(cache));
  } catch {
    // Ignore quota/serialization errors to keep chat responsive.
  }
}

function trimConversationCache(
  cache: PersistedConversationCache,
): PersistedConversationCache {
  const entries = Object.entries(cache);
  if (entries.length <= MAX_CACHED_CONVERSATIONS) {
    return cache;
  }
  const trimmed = [...entries]
    .sort((a, b) => (b[1].updatedAt ?? 0) - (a[1].updatedAt ?? 0))
    .slice(0, MAX_CACHED_CONVERSATIONS);
  return Object.fromEntries(trimmed);
}

const persistedState = loadPersistedState();
const INITIAL_THREAD_ID = persistedState?.threadId || nanoid();
const DEFAULT_SESSION_TOKEN_USAGE = {
  totalTokens: 0,
  totalCalls: 0,
  totalPromptTokens: 0,
  totalCompletionTokens: 0,
};

export const useStore = create<{
  responding: boolean;
  generationPhase: GenerationPhase;
  threadId: string | undefined;
  conversationId: string | null;
  messageIds: string[];
  messages: Map<string, Message>;
  messageBackendIds: Map<string, number>;
  researchIds: string[];
  researchPlanIds: Map<string, string>;
  researchReportIds: Map<string, string>;
  researchActivityIds: Map<string, string[]>;
  researchQueries: Map<string, string>;
  researchCitations: Map<string, Citation[]>;
  researchRunStatus: Map<string, DeepResearchTaskStatus>;
  restartPlanShownResearchIds: Set<string>;
  planActionLocks: Map<string, "accepted" | "replan">;
  cancelledResearchIds: Set<string>;
  ongoingResearchId: string | null;
  openResearchId: string | null;
  backgroundJobId: string | null;
  backgroundJobCursor: number;
  activeResearchJobs: Map<string, { jobId: string; status: string; currentStage?: string }>;
  tokenUsage: TokenUsageSummary | null;
  sessionTokenUsage: { totalTokens: number; totalCalls: number; totalPromptTokens: number; totalCompletionTokens: number };
  responseTiming: ResponseTiming | null;

  appendMessage: (message: Message) => void;
  updateMessage: (message: Message) => void;
  updateMessages: (messages: Message[]) => void;
  openResearch: (researchId: string | null) => void;
  closeResearch: () => void;
  setOngoingResearch: (researchId: string | null) => void;
  setCitations: (researchId: string, citations: Citation[]) => void;
  setResearchRunStatus: (researchId: string, status: DeepResearchTaskStatus) => void;
  setRestartPlanShown: (researchId: string, shown: boolean) => void;
  setPlanActionLock: (
    messageId: string,
    action: "accepted" | "replan" | null,
  ) => void;
  setResearchCancelled: (researchId: string, cancelled: boolean) => void;
  setTokenUsage: (usage: TokenUsageSummary | null) => void;
  accumulateSessionTokens: (usage: TokenUsageSummary) => void;
  setResponseTiming: (timing: ResponseTiming | null) => void;
  setActiveResearchJobs: (jobs: Map<string, { jobId: string; status: string; currentStage?: string }>) => void;
  setBackgroundJob: (jobId: string | null, cursor?: number) => void;
  setConversationId: (conversationId: string | null) => void;
  setMessageBackendId: (messageId: string, backendId: number) => void;
}>((set) => ({
  responding: false,
  generationPhase: "idle",
  threadId: INITIAL_THREAD_ID,
  conversationId: persistedState?.conversationId ?? null,
  messageIds: persistedState?.messageIds ?? [],
  messages: new Map<string, Message>(persistedState?.messages ?? []),
  messageBackendIds: new Map<string, number>(persistedState?.messageBackendIds ?? []),
  researchIds: persistedState?.researchIds ?? [],
  researchPlanIds: new Map<string, string>(persistedState?.researchPlanIds ?? []),
  researchReportIds: new Map<string, string>(persistedState?.researchReportIds ?? []),
  researchActivityIds: new Map<string, string[]>(persistedState?.researchActivityIds ?? []),
  researchQueries: new Map<string, string>(persistedState?.researchQueries ?? []),
  researchCitations: new Map<string, Citation[]>(persistedState?.researchCitations ?? []),
  researchRunStatus: new Map<string, DeepResearchTaskStatus>(
    persistedState?.researchRunStatus ?? [],
  ),
  restartPlanShownResearchIds: new Set<string>(
    persistedState?.restartPlanShownResearchIds ?? [],
  ),
  planActionLocks: new Map<string, "accepted" | "replan">(
    persistedState?.planActionLocks ?? [],
  ),
  cancelledResearchIds: (() => {
    const derived = new Set<string>();
    for (const [rid, status] of persistedState?.researchRunStatus ?? []) {
      if (status === "cancelled") {
        derived.add(rid);
      }
    }
    return derived;
  })(),
  ongoingResearchId: persistedState?.ongoingResearchId ?? null,
  openResearchId: persistedState?.openResearchId ?? null,
  backgroundJobId: persistedState?.backgroundJobId ?? null,
  backgroundJobCursor: persistedState?.backgroundJobCursor ?? 0,
  activeResearchJobs: new Map(),
  tokenUsage: persistedState?.tokenUsage ?? null,
  sessionTokenUsage: persistedState?.sessionTokenUsage ?? DEFAULT_SESSION_TOKEN_USAGE,
  responseTiming: persistedState?.responseTiming ?? null,

  appendMessage(message: Message) {
    set((state) => {
      // Prevent duplicate message IDs in the array to avoid React key warnings
      const newMessageIds = state.messageIds.includes(message.id)
        ? state.messageIds
        : [...state.messageIds, message.id];
      return {
        messageIds: newMessageIds,
        messages: new Map(state.messages).set(message.id, message),
      };
    });
  },
  updateMessage(message: Message) {
    set((state) => ({
      messages: new Map(state.messages).set(message.id, message),
    }));
  },
  updateMessages(messages: Message[]) {
    set((state) => {
      const newMessages = new Map(state.messages);
      messages.forEach((m) => newMessages.set(m.id, m));
      return { messages: newMessages };
    });
  },
  openResearch(researchId: string | null) {
    set({ openResearchId: researchId });
  },
  closeResearch() {
    set({ openResearchId: null });
  },
  setOngoingResearch(researchId: string | null) {
    set({ ongoingResearchId: researchId });
  },
  setCitations(researchId: string, citations: Citation[]) {
    set((state) => ({
      researchCitations: new Map(state.researchCitations).set(researchId, citations),
    }));
  },
  setResearchRunStatus(researchId: string, status: DeepResearchTaskStatus) {
    set((state) => ({
      researchRunStatus: new Map(state.researchRunStatus).set(researchId, status),
    }));
  },
  setRestartPlanShown(researchId: string, shown: boolean) {
    set((state) => {
      const next = new Set(state.restartPlanShownResearchIds);
      if (shown) {
        next.add(researchId);
      } else {
        next.delete(researchId);
      }
      return { restartPlanShownResearchIds: next };
    });
  },
  setPlanActionLock(messageId: string, action: "accepted" | "replan" | null) {
    set((state) => {
      const next = new Map(state.planActionLocks);
      if (action == null) {
        next.delete(messageId);
      } else {
        next.set(messageId, action);
      }
      return { planActionLocks: next };
    });
  },
  setResearchCancelled(researchId: string, cancelled: boolean) {
    set((state) => {
      const next = new Set(state.cancelledResearchIds);
      if (cancelled) {
        next.add(researchId);
      } else {
        next.delete(researchId);
      }
      return { cancelledResearchIds: next };
    });
  },
  setTokenUsage(usage: TokenUsageSummary | null) {
    set({ tokenUsage: usage });
  },
  accumulateSessionTokens(usage: TokenUsageSummary) {
    set((state) => ({
      sessionTokenUsage: {
        totalTokens: state.sessionTokenUsage.totalTokens + usage.totalTokens,
        totalCalls: state.sessionTokenUsage.totalCalls + usage.totalCalls,
        totalPromptTokens: state.sessionTokenUsage.totalPromptTokens + usage.totalPromptTokens,
        totalCompletionTokens: state.sessionTokenUsage.totalCompletionTokens + usage.totalCompletionTokens,
      },
    }));
  },
  setResponseTiming(timing: ResponseTiming | null) {
    set({ responseTiming: timing });
  },
  setActiveResearchJobs(jobs: Map<string, { jobId: string; status: string; currentStage?: string }>) {
    set({ activeResearchJobs: jobs });
  },
  setBackgroundJob(jobId: string | null, cursor?: number) {
    set({ backgroundJobId: jobId, backgroundJobCursor: cursor ?? 0 });
  },
  setConversationId(conversationId: string | null) {
    set({ conversationId });
  },
  setMessageBackendId(messageId: string, backendId: number) {
    set((state) => ({
      messageBackendIds: new Map(state.messageBackendIds).set(messageId, backendId),
    }));
  },
}));

function persistStoreState() {
  if (typeof window === "undefined") {
    return;
  }
  const state = useStore.getState();
  const retainedIds = state.messageIds.slice(-MAX_PERSISTED_MESSAGES);
  const retainedMessages: Array<[string, Message]> = retainedIds
    .map((id) => [id, state.messages.get(id)] as const)
    .filter((entry): entry is [string, Message] => entry[1] != null);

  const snapshot: PersistedStoreState = {
    threadId: state.threadId || INITIAL_THREAD_ID,
    conversationId: state.conversationId,
    messageIds: retainedIds,
    messages: retainedMessages,
    messageBackendIds: Array.from(state.messageBackendIds.entries()),
    researchIds: state.researchIds,
    researchPlanIds: Array.from(state.researchPlanIds.entries()),
    researchReportIds: Array.from(state.researchReportIds.entries()),
    researchActivityIds: Array.from(state.researchActivityIds.entries()),
    researchQueries: Array.from(state.researchQueries.entries()),
    researchCitations: Array.from(state.researchCitations.entries()),
    researchRunStatus: Array.from(state.researchRunStatus.entries()),
    restartPlanShownResearchIds: Array.from(state.restartPlanShownResearchIds),
    planActionLocks: Array.from(state.planActionLocks.entries()),
    ongoingResearchId: state.ongoingResearchId,
    openResearchId: state.openResearchId,
    backgroundJobId: state.backgroundJobId,
    backgroundJobCursor: state.backgroundJobCursor,
    tokenUsage: state.tokenUsage,
    sessionTokenUsage: state.sessionTokenUsage,
    responseTiming: state.responseTiming,
  };

  try {
    localStorage.setItem(STORE_PERSIST_KEY, JSON.stringify(snapshot));
  } catch {
    // Ignore quota/serialization errors to keep chat responsive.
  }
  deepResearchDebugLog("persist", "store snapshot saved", {
    conversationId: state.conversationId,
    retainedMessageCount: snapshot.messageIds.length,
    researchCount: snapshot.researchIds.length,
    planCount: snapshot.researchPlanIds.length,
    reportCount: snapshot.researchReportIds.length,
  });

  if (state.conversationId) {
    const cache = loadConversationCache();
    cache[state.conversationId] = {
      threadId: snapshot.threadId,
      messageIds: snapshot.messageIds,
      messages: snapshot.messages,
      messageBackendIds: snapshot.messageBackendIds,
      researchIds: snapshot.researchIds,
      researchPlanIds: snapshot.researchPlanIds,
      researchReportIds: snapshot.researchReportIds,
      researchActivityIds: snapshot.researchActivityIds,
      researchQueries: snapshot.researchQueries,
      researchCitations: snapshot.researchCitations,
      researchRunStatus: snapshot.researchRunStatus,
      restartPlanShownResearchIds: snapshot.restartPlanShownResearchIds,
      planActionLocks: snapshot.planActionLocks,
      ongoingResearchId: snapshot.ongoingResearchId,
      openResearchId: snapshot.openResearchId,
      backgroundJobId: snapshot.backgroundJobId,
      backgroundJobCursor: snapshot.backgroundJobCursor,
      tokenUsage: snapshot.tokenUsage,
      sessionTokenUsage: snapshot.sessionTokenUsage,
      responseTiming: snapshot.responseTiming,
      updatedAt: Date.now(),
    };
    saveConversationCache(trimConversationCache(cache));
    deepResearchDebugLog("persist", "conversation cache saved", {
      conversationId: state.conversationId,
      cacheSize: Object.keys(cache).length,
      updatedAt: cache[state.conversationId]?.updatedAt,
    });
  }
}

let persistTimer: ReturnType<typeof setTimeout> | null = null;
// When true, suppress debounced persist to prevent saving intermediate
// (empty) state while loadConversationFromBackend is between clearing
// the old conversation and applying the backend-rebuilt state.
let _suppressPersist = false;

useStore.subscribe(() => {
  if (persistTimer) {
    clearTimeout(persistTimer);
  }
  if (_suppressPersist) return;
  persistTimer = setTimeout(() => {
    persistStoreState();
    persistTimer = null;
  }, 250);
});

if (typeof window !== "undefined" && !(window as typeof window & { __pathlabDrPersistBound?: boolean }).__pathlabDrPersistBound) {
  (window as typeof window & { __pathlabDrPersistBound?: boolean }).__pathlabDrPersistBound = true;
  const flushPersistedState = () => {
    if (persistTimer) {
      clearTimeout(persistTimer);
      persistTimer = null;
    }
    persistStoreState();
  };
  window.addEventListener("beforeunload", flushPersistedState);
  window.addEventListener("pagehide", flushPersistedState);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      flushPersistedState();
    }
  });
}

function getThreadId(): string {
  return useStore.getState().threadId || INITIAL_THREAD_ID;
}

const RESEARCH_META_BLOCK_START = "[PATHLAB_RESEARCH_META]";
const RESEARCH_META_BLOCK_END = "[/PATHLAB_RESEARCH_META]";

const TOOL_CALLS_BLOCK_START = "[PATHLAB_TOOL_CALLS]";
const TOOL_CALLS_BLOCK_END = "[/PATHLAB_TOOL_CALLS]";

/** Max length for a single tool_call result when serializing. */
const TOOL_RESULT_MAX_LEN = 8000;

interface PersistedToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
  result?: string;
}

function serializeToolCalls(toolCalls: import("../messages").ToolCallRuntime[]): string {
  const compact: PersistedToolCall[] = toolCalls.map((tc) => {
    const entry: PersistedToolCall = { id: tc.id, name: tc.name, args: tc.args };
    if (tc.result != null) {
      entry.result =
        tc.result.length > TOOL_RESULT_MAX_LEN
          ? tc.result.slice(0, TOOL_RESULT_MAX_LEN) + "…[truncated]"
          : tc.result;
    }
    return entry;
  });
  return `${TOOL_CALLS_BLOCK_START}\n${JSON.stringify(compact)}\n${TOOL_CALLS_BLOCK_END}`;
}

function extractPersistedToolCalls(raw: string): {
  content: string;
  toolCalls: import("../messages").ToolCallRuntime[] | undefined;
} {
  const start = raw.indexOf(TOOL_CALLS_BLOCK_START);
  if (start < 0) return { content: raw, toolCalls: undefined };
  const end = raw.indexOf(TOOL_CALLS_BLOCK_END, start);
  if (end < 0) return { content: raw.slice(0, start).trimEnd(), toolCalls: undefined };
  const jsonText = raw.slice(start + TOOL_CALLS_BLOCK_START.length, end).trim();
  const cleaned = raw.slice(0, start).trimEnd() + raw.slice(end + TOOL_CALLS_BLOCK_END.length);
  try {
    const parsed = JSON.parse(jsonText) as PersistedToolCall[];
    if (!Array.isArray(parsed)) return { content: cleaned, toolCalls: undefined };
    return {
      content: cleaned,
      toolCalls: parsed.map((tc) => ({
        id: tc.id,
        name: tc.name,
        args: tc.args ?? {},
        result: tc.result,
      })),
    };
  } catch {
    return { content: cleaned, toolCalls: undefined };
  }
}

type ResearchMetaKind = "research_root" | "plan" | "activity" | "report";

interface PersistedResearchMeta {
  version: 1;
  researchId: string;
  kind: ResearchMetaKind;
  agent?: Message["agent"];
  query?: string;
  status?: string;
  planActionLock?: "accepted" | "replan";
}

function extractDeepResearchRunStatus(
  metadata: Record<string, unknown> | null | undefined,
): DeepResearchTaskStatus | null {
  if (!metadata || typeof metadata !== "object") {
    return null;
  }
  const deepResearch = metadata.deep_research;
  if (!deepResearch || typeof deepResearch !== "object") {
    return null;
  }
  const status = (deepResearch as { status?: unknown }).status;
  if (
    status === "running" ||
    status === "success" ||
    status === "error" ||
    status === "cancelled"
  ) {
    return status;
  }
  return null;
}

function extractDeepResearchPlanActionLock(
  metadata: Record<string, unknown> | null | undefined,
): "accepted" | "replan" | null {
  if (!metadata || typeof metadata !== "object") {
    return null;
  }
  const deepResearch = metadata.deep_research;
  if (!deepResearch || typeof deepResearch !== "object") {
    return null;
  }
  const action = (deepResearch as { plan_action_lock?: unknown }).plan_action_lock;
  if (action === "accepted" || action === "replan") {
    return action;
  }
  return null;
}

function extractPersistedResearchMeta(raw: string): {
  content: string;
  meta: PersistedResearchMeta | null;
} {
  const markerIndex = raw.lastIndexOf(RESEARCH_META_BLOCK_START);
  if (markerIndex < 0) {
    return { content: raw, meta: null };
  }
  const endIndex = raw.indexOf(RESEARCH_META_BLOCK_END, markerIndex);
  if (endIndex < 0) {
    // Closing tag missing (truncated persistence). Still strip the partial
    // meta block so raw tags never leak into the UI.
    return { content: raw.slice(0, markerIndex).trimEnd(), meta: null };
  }
  const jsonStart = markerIndex + RESEARCH_META_BLOCK_START.length;
  const jsonText = raw.slice(jsonStart, endIndex).trim();
  const cleaned = raw.slice(0, markerIndex).trimEnd();
  try {
    const parsed = JSON.parse(jsonText) as PersistedResearchMeta;
    if (!parsed || parsed.version !== 1 || !parsed.researchId || !parsed.kind) {
      return { content: cleaned, meta: null };
    }
    return { content: cleaned, meta: parsed };
  } catch {
    return { content: cleaned, meta: null };
  }
}

function buildResearchMetaForMessage(message: Message): PersistedResearchMeta | null {
  if (message.role === "user") {
    return null;
  }
  const state = useStore.getState();
  let researchId: string | null = null;
  let kind: ResearchMetaKind | null = null;

  if (state.researchIds.includes(message.id)) {
    researchId = message.id;
    kind = "research_root";
  }
  if (!researchId) {
    for (const [rid, planId] of state.researchPlanIds.entries()) {
      if (planId === message.id) {
        researchId = rid;
        kind = "plan";
        break;
      }
    }
  }
  if (!researchId) {
    for (const [rid, reportId] of state.researchReportIds.entries()) {
      if (reportId === message.id) {
        researchId = rid;
        kind = "report";
        break;
      }
    }
  }
  if (!researchId) {
    for (const [rid, activityIds] of state.researchActivityIds.entries()) {
      if (activityIds.includes(message.id)) {
        researchId = rid;
        kind = "activity";
        break;
      }
    }
  }
  if (!researchId || !kind) {
    return null;
  }
  const runStatus = state.researchRunStatus.get(researchId);
  const planActionLock = state.planActionLocks.get(message.id);
  return {
    version: 1,
    researchId,
    kind,
    agent: message.agent,
    query: kind === "research_root" ? state.researchQueries.get(researchId) : undefined,
    status: runStatus,
    planActionLock,
  };
}

function withPersistedResearchMeta(content: string, message: Message): string {
  const { content: step1 } = extractPersistedResearchMeta(content || "");
  const { content: cleanedContent } = extractPersistedToolCalls(step1);
  const meta = buildResearchMetaForMessage(message);
  if (!meta) {
    return cleanedContent;
  }
  let result = `${cleanedContent}\n\n${RESEARCH_META_BLOCK_START}\n${JSON.stringify(meta)}\n${RESEARCH_META_BLOCK_END}`;
  // Persist tool_calls for activity messages so they survive reload.
  if (message.toolCalls?.length) {
    result += `\n${serializeToolCalls(message.toolCalls)}`;
  }
  return result;
}

// Coordinator messages contain special block tags used by the UI for guided flows.
// These messages must NOT be absorbed into research activity lists on reload,
// as they would then be filtered out by useRenderableMessageIds (researcher messages
// bound to a research are hidden inside the ResearchCard, not the main chat view).
const COORDINATOR_BLOCK_MARKERS = [
  "[OPTIONS]",
  "[TASK_CONFIG]",
  "[DATASET_REGISTRATION]",
  "[METADATA_UPLOAD]",
  "[NAVIGATE]",
  "[TRAINING_CHAT_LINK]",
  "[ANALYSIS_CONFIG]",
  "[METRIC_CONFIG]",
  "[CHART_CONFIG]",
  "[QUICK_ANALYSIS_CONFIG]",
  "[CANCEL_TASK]",
  "[RENAME_TASK]",
  "[TASK_HISTORY_CONFIG]",
];

// Error messages persisted by the catch block lack PATHLAB_RESEARCH_META and
// coordinator block markers.  Detect them by pattern so they are not absorbed
// into research activities during backend rebuild.
const ERROR_MESSAGE_PATTERNS = [
  /^.{0,20}(?:failed|error|错误|失败).{0,60}(?:network|connection|timeout|server|请求|网络|连接|超时)/i,
  /^Deep research failed/i,
  /^Research failed/i,
];

function isLikelyCoordinatorContent(content: string): boolean {
  if (!content) return false;
  if (COORDINATOR_BLOCK_MARKERS.some((marker) => content.includes(marker))) {
    return true;
  }
  // Short messages that match error patterns are coordinator error bubbles.
  const trimmed = content.trim();
  if (trimmed.length < 200) {
    return ERROR_MESSAGE_PATTERNS.some((re) => re.test(trimmed));
  }
  return false;
}

function parsePlannerContent(content: string): {
  title?: string;
  thought?: string;
  steps?: unknown[];
} | null {
  const trimmed = content.trim();
  if (!trimmed) {
    return null;
  }
  // Handle markdown fenced JSON first.
  const fencedMatch = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const candidate = fencedMatch ? fencedMatch[1]?.trim() ?? "" : trimmed;
  const looksLikeJsonEnvelope = /^[\[{]/.test(candidate);
  const hasPlannerHints = looksLikePlannerPayload(candidate);
  if (!fencedMatch && !looksLikeJsonEnvelope && !hasPlannerHints) {
    return null;
  }

  const parsed = parseJSON<{
    title?: string;
    thought?: string;
    steps?: unknown[];
    has_enough_context?: unknown;
    locale?: unknown;
  } | null>(candidate, null);

  if (parsed && typeof parsed === "object") {
    const hasStepsArray = Array.isArray(parsed.steps);
    if (
      hasStepsArray ||
      hasPlannerHints ||
      typeof parsed.thought === "string" ||
      typeof parsed.title === "string"
    ) {
      return {
        title: typeof parsed.title === "string" ? parsed.title : "",
        thought: typeof parsed.thought === "string" ? parsed.thought : candidate,
        steps: Array.isArray(parsed.steps) ? parsed.steps : [],
      };
    }
  }

  // Heuristic fallback for legacy planner text that is not strict JSON.
  const probe = candidate.toLowerCase();
  const looksLikePlanner =
    (probe.includes("\"steps\"") || probe.includes("'steps'")) &&
    (probe.includes("has_enough_context") || probe.includes("step_type")) &&
    (probe.includes("\"thought\"") || probe.includes("'thought'"));
  if (!looksLikePlanner) {
    return null;
  }
  return {
    title: "",
    thought: candidate,
    steps: [],
  };
}

function isLikelyReportContent(content: string): boolean {
  const trimmed = content.trim();
  if (trimmed.length < 150) {
    return false;
  }
  const headingCount =
    (trimmed.match(/(?:^|\n)#{1,4}\s+/g)?.length ?? 0) +
    (trimmed.match(/(?:^|\n)(?:概述|详细分析|关键要点|总结|建议|结论)\s*/g)?.length ?? 0);
  const paragraphCount = trimmed.split(/\n\s*\n/).filter((p) => p.trim().length > 20).length;
  return headingCount >= 1 || paragraphCount >= 3;
}

function isLikelyResearchActivityContent(content: string): boolean {
  const trimmed = content.trim();
  if (trimmed.length < 120) {
    return false;
  }
  const probe = trimmed.toLowerCase();
  return (
    probe.includes("search") ||
    probe.includes("搜索") ||
    probe.includes("query") ||
    probe.includes("tool") ||
    probe.includes("source") ||
    probe.includes("citation") ||
    probe.includes("http://") ||
    probe.includes("https://")
  );
}

function isGuaranteedFollowUpIntent(content: string | undefined): boolean {
  const text = (content ?? "").trim();
  if (!text) return false;

  // Structured blocks generated by Deep Research follow-up actions.
  if (
    text.includes("[RESEARCH_REPORT_CONTEXT]") ||
    text.includes("[DATASET_REGISTRATION]") ||
    text.includes("[TASK_CONFIG]")
  ) {
    return true;
  }

  // Common short option replies from post-report guidance.
  const normalized = text.toLowerCase();
  const shortFollowUpHints = [
    "使用 ai 训练深度学习模型",
    "分析相关病理图像数据",
    "导出报告",
    "针对报告内容提问",
    "use ai to train",
    "train a deep learning model",
    "training config",
    "upload dataset",
  ];
  if (
    text.length <= 80 &&
    shortFollowUpHints.some((hint) => normalized.includes(hint.toLowerCase()))
  ) {
    return true;
  }

  return false;
}

const RESEARCH_META_BLOCK_RE =
  /\n?\[PATHLAB_RESEARCH_META\][\s\S]*?(?:\[\/PATHLAB_RESEARCH_META\]|$)/g;

function sanitizeForStandardAIChat(content: string): string {
  const withoutResearchMeta = content.replace(RESEARCH_META_BLOCK_RE, "").trim();
  return sanitizeConfigBlocksForAI(withoutResearchMeta);
}

function buildStandardAIChatMessagesFromStore(): StandardChatMessage[] {
  const state = useStore.getState();
  const messages: StandardChatMessage[] = [];
  for (const id of state.messageIds) {
    const message = state.messages.get(id);
    if (!message) continue;
    if (message.role !== "user" && message.role !== "assistant") continue;
    const content = sanitizeForStandardAIChat(message.content ?? "");
    if (!content) continue;
    messages.push({
      role: message.role,
      content,
    });
  }
  return messages;
}

async function sendMessageViaStandardAIChat(
  conversationId: string | null,
  options: { abortSignal?: AbortSignal } = {},
): Promise<void> {
  const startTime = Date.now();
  useStore.getState().setTokenUsage(null);
  useStore.getState().setResponseTiming({
    startTime,
    endTime: null,
    durationMs: null,
  });
  setGenerationPhase("thinking");
  setResponding(true);

  const assistantMessageId = nanoid();
  let assistantMessage: Message = {
    id: assistantMessageId,
    threadId: getThreadId(),
    role: "assistant",
    agent: "coordinator",
    content: "",
    contentChunks: [],
    isStreaming: true,
  };
  appendMessage(assistantMessage);

  const chatMessages = buildStandardAIChatMessagesFromStore();
  let receivedAnyChunk = false;
  let finalized = false;
  const finalizeAssistantMessage = async () => {
    if (finalized) return;
    finalized = true;
    assistantMessage = {
      ...assistantMessage,
      isStreaming: false,
      finishReason: "stop",
    };
    useStore.getState().updateMessage(assistantMessage);
    if (conversationId) {
      await persistMessage(assistantMessage);
    }
  };

  try {
    if (chatMessages.length === 0) {
      throw new Error("No available chat history for AI chat fallback.");
    }
    await chatWithStandardAI(
      chatMessages,
      (chunk) => {
        if (!receivedAnyChunk) {
          receivedAnyChunk = true;
          setGenerationPhase("streaming");
        }
        if (chunk === "__CLEAR_CONTENT__") {
          assistantMessage = {
            ...assistantMessage,
            content: "",
            contentChunks: [],
          };
          useStore.getState().updateMessage(assistantMessage);
          return;
        }
        assistantMessage = {
          ...assistantMessage,
          content: `${assistantMessage.content}${chunk}`,
          contentChunks: [...assistantMessage.contentChunks, chunk],
        };
        useStore.getState().updateMessage(assistantMessage);
      },
      undefined,
      undefined,
      options.abortSignal,
      () => setGenerationPhase("pdf_waiting"),
    );
    await finalizeAssistantMessage();
  } catch (error) {
    const aborted = options.abortSignal?.aborted || isAbortLikeError(error);
    const rawError = error instanceof Error ? error.message : String(error);
    if (aborted) {
      assistantMessage = {
        ...assistantMessage,
        content:
          assistantMessage.content.trim().length > 0
            ? assistantMessage.content
            : tr("generationCancelled", "Generation cancelled."),
        contentChunks:
          assistantMessage.content.trim().length > 0
            ? assistantMessage.contentChunks
            : [tr("generationCancelled", "Generation cancelled.")],
      };
      useStore.getState().updateMessage(assistantMessage);
      await finalizeAssistantMessage();
      return;
    }

    const fallbackError = pickDeepResearchErrorMessage(rawError);
    deepResearchConsoleError("aichat-fallback", "sendMessage caught error", {
      conversationId,
      rawError,
      error:
        error instanceof Error
          ? {
            name: error.name,
            message: error.message,
            stack: error.stack,
            cause: (error as Error & { cause?: unknown }).cause,
          }
          : error,
    });
    assistantMessage = {
      ...assistantMessage,
      content:
        assistantMessage.content.trim().length > 0
          ? assistantMessage.content
          : fallbackError,
      contentChunks:
        assistantMessage.content.trim().length > 0
          ? assistantMessage.contentChunks
          : [fallbackError],
    };
    useStore.getState().updateMessage(assistantMessage);
    await finalizeAssistantMessage();
    toast(fallbackError);
  } finally {
    const endTime = Date.now();
    useStore.getState().setResponseTiming({
      startTime,
      endTime,
      durationMs: endTime - startTime,
    });
    setGenerationPhase("idle");
    setResponding(false);
  }
}

async function ensureConversationId(seedContent?: string): Promise<string | null> {
  const existing = useStore.getState().conversationId;
  if (existing) {
    return existing;
  }
  try {
    const title = seedContent?.trim()
      ? seedContent.trim().slice(0, 50)
      : "Deep Research";
    const created = await apiCreateConversation(title || "Deep Research", "deep_research");
    useStore.getState().setConversationId(created.conversation_id);
    // Keep deep-research thread stable per conversation so interrupt resume works
    // even after page reload/navigation.
    useStore.setState({ threadId: created.conversation_id });
    return created.conversation_id;
  } catch (error) {
    console.warn("[DeepResearch] Failed to create conversation:", error);
    return null;
  }
}

async function persistMessage(message: Message): Promise<void> {
  const state = useStore.getState();
  const conversationId = state.conversationId;
  if (!conversationId) {
    return;
  }
  const role = message.role === "user" ? "user" : "assistant";
  const persistedContent =
    role === "assistant"
      ? withPersistedResearchMeta(message.content || "", message)
      : (message.content || "");

  // Skip persisting empty activity stubs (no text, no tool_calls).
  // These arise when a research step fails silently.
  const backendId = state.messageBackendIds.get(message.id);
  if (backendId == null && role === "assistant") {
    const { content: textOnly } = extractPersistedResearchMeta(persistedContent);
    const { content: realText } = extractPersistedToolCalls(textOnly);
    if (!realText.trim() && !message.toolCalls?.length) {
      const meta = buildResearchMetaForMessage(message);
      if (meta?.kind === "activity") {
        return; // skip empty activity stub
      }
    }
  }
  try {
    if (backendId != null) {
      await apiUpdateMessage(conversationId, backendId, persistedContent);
      return;
    }
    const saved = await apiAddMessage(conversationId, role, persistedContent);
    useStore.getState().setMessageBackendId(message.id, saved.id);
  } catch (error) {
    console.warn("[DeepResearch] Failed to persist message:", error);
  }
}

async function persistRunUsageMetadata(
  status: DeepResearchTaskStatus,
  error?: string,
): Promise<void> {
  const state = useStore.getState();
  const conversationId = state.conversationId;
  if (!conversationId) {
    return;
  }

  const latestAssistantId = [...state.messageIds]
    .reverse()
    .find((id) => state.messages.get(id)?.role === "assistant");
  if (!latestAssistantId) {
    return;
  }

  const backendId = state.messageBackendIds.get(latestAssistantId);
  const latestAssistantMessage = state.messages.get(latestAssistantId);
  if (backendId == null || !latestAssistantMessage) {
    return;
  }

  // NOTE: The metadata object (token_usage, response_timing, status) is intentionally
  // omitted because apiUpdateMessage only supports updating content, not metadata.
  // The run usage data is preserved in localStorage via persistStoreState() instead.

  try {
    // Keep persisted research meta block when updating metadata.
    // Otherwise the latest assistant message may lose card bindings after refresh.
    const persistedContent = withPersistedResearchMeta(
      latestAssistantMessage.content || "",
      latestAssistantMessage,
    );
    await apiUpdateMessage(
      conversationId,
      backendId,
      persistedContent,
    );
  } catch (persistError) {
    console.warn("[DeepResearch] Failed to persist run usage metadata:", persistError);
  }
}

export async function loadConversationFromBackend(conversationId: string): Promise<void> {
  latestRequestedConversationId = conversationId;
  const loadSeq = (backendLoadSeqByConversation.get(conversationId) ?? 0) + 1;
  backendLoadSeqByConversation.set(conversationId, loadSeq);
  const isStaleLoad = () =>
    latestRequestedConversationId !== conversationId ||
    backendLoadSeqByConversation.get(conversationId) !== loadSeq;
  deepResearchDebugLog("loadConversation", "start", {
    conversationId,
    loadSeq,
  });

  let _eagerReconnectFired = false;
  const currentStore = useStore.getState();
  const isContextSwitch = currentStore.conversationId !== conversationId;

  // If the store already holds live stream data for this conversation
  // (i.e. not a context switch and still actively responding), skip
  // reloading from cache/backend to avoid overwriting in-flight data.
  if (!isContextSwitch && currentStore.responding) {
    deepResearchDebugLog("loadConversation", "skipped — store has live stream data", {
      conversationId,
      responding: true,
    });
    return;
  }

  try {
    const cache = loadConversationCache();
    const cached = cache[conversationId];
    const resolvedConversationThreadId =
      cached?.threadId || conversationId || getThreadId();
    if (cached && !isStaleLoad()) {
      const cachedResearchIds = cached.researchIds ?? [];
      const cachedRootSet = new Set(cachedResearchIds);
      const cachedPlanIds = (cached.researchPlanIds ?? []).filter(([rid]) =>
        cachedRootSet.has(rid),
      );
      const cachedReportIds = (cached.researchReportIds ?? []).filter(([rid]) =>
        cachedRootSet.has(rid),
      );
      const cachedActivityIds = (cached.researchActivityIds ?? []).filter(([rid]) =>
        cachedRootSet.has(rid),
      );
      const cachedQueries = (cached.researchQueries ?? []).filter(([rid]) =>
        cachedRootSet.has(rid),
      );
      const cachedCitations = (cached.researchCitations ?? []).filter(([rid]) =>
        cachedRootSet.has(rid),
      );
      const cachedRunStatus = (cached.researchRunStatus ?? []).filter(([rid]) =>
        cachedRootSet.has(rid),
      );
      const cachedPlanActionLocks = (cached.planActionLocks ?? []).filter(([msgId]) =>
        (cached.messageIds ?? []).includes(msgId),
      );
      const cachedRestartPlanShownResearchIds = (cached.restartPlanShownResearchIds ?? []).filter(
        (rid) => cachedRootSet.has(rid),
      );
      // Clear isStreaming on all cached messages — the stream is no longer
      // active, and stale isStreaming=true prevents tool calls from rendering.
      const cachedMessages = new Map<string, Message>(cached.messages ?? []);
      for (const [id, msg] of cachedMessages) {
        if (msg.isStreaming) {
          cachedMessages.set(id, { ...msg, isStreaming: false });
        }
      }
      useStore.setState({
        conversationId,
        threadId: resolvedConversationThreadId,
        messageIds: cached.messageIds ?? [],
        messages: cachedMessages,
        messageBackendIds: new Map<string, number>(cached.messageBackendIds ?? []),
        researchIds: cachedResearchIds,
        researchPlanIds: new Map<string, string>(cachedPlanIds),
        researchReportIds: new Map<string, string>(cachedReportIds),
        researchActivityIds: new Map<string, string[]>(cachedActivityIds),
        researchQueries: new Map<string, string>(cachedQueries),
        researchCitations: new Map<string, Citation[]>(cachedCitations),
        researchRunStatus: new Map<string, DeepResearchTaskStatus>(cachedRunStatus),
        restartPlanShownResearchIds: new Set<string>(cachedRestartPlanShownResearchIds),
        planActionLocks: new Map<string, "accepted" | "replan">(cachedPlanActionLocks),
        cancelledResearchIds: new Set<string>(),
        ongoingResearchId: cached.ongoingResearchId ?? null,
        openResearchId: cached.openResearchId ?? null,
        backgroundJobId: cached.backgroundJobId ?? null,
        backgroundJobCursor: cached.backgroundJobCursor ?? 0,
        tokenUsage: cached.tokenUsage ?? null,
        sessionTokenUsage: cached.sessionTokenUsage ?? DEFAULT_SESSION_TOKEN_USAGE,
        responseTiming: cached.responseTiming ?? null,
        responding: false,
        generationPhase: "idle",
      });
      deepResearchDebugLog("loadConversation", "applied cached state", {
        conversationId,
        cachedMessageCount: cached.messageIds?.length ?? 0,
        cachedResearchCount: cachedResearchIds.length,
        cachedPlanCount: cachedPlanIds.length,
        cachedReportCount: cachedReportIds.length,
      });

      // Migrate un-persisted messages from cache to backend DB.
      // When the user switches away during streaming, the finally-block's
      // message persistence is skipped (stale guard).  persistStoreState()
      // saved messages + research mappings to localStorage cache, but they
      // never reached the backend.  Without this migration, the backend
      // rebuild (below) would overwrite the cached state and activities/
      // reports would disappear.
      {
        const storeState = useStore.getState();
        const unpersistedIds = (cached.messageIds ?? []).filter((id: string) => {
          if (storeState.messageBackendIds.has(id)) return false;
          const msg = storeState.messages.get(id);
          return msg && msg.role !== "user";
        });
        if (unpersistedIds.length > 0 && !isStaleLoad()) {
          deepResearchDebugLog("loadConversation", "migrating un-persisted cached messages to backend", {
            conversationId,
            count: unpersistedIds.length,
          });
          // Store already has cached research state, so buildResearchMetaForMessage works.
          for (const id of unpersistedIds) {
            const msg = storeState.messages.get(id);
            if (!msg) continue;
            try {
              const persistedContent = withPersistedResearchMeta(msg.content || "", msg);
              const saved = await apiAddMessage(conversationId, "assistant", persistedContent);
              useStore.getState().setMessageBackendId(id, saved.id);
            } catch (e) {
              console.warn("[DeepResearch] Failed to migrate cached message to backend:", e);
            }
          }
        }
      }

      // Eagerly reconnect to background job right after cache restore.
      // When the user navigated away mid-research, some activity messages
      // were cached without tool calls (stream events hadn't arrived yet).
      // The background job's event history (research_job_events table) has
      // ALL events.  Replaying from cursor=0 rebuilds those incomplete
      // messages.  We remove them first so mergeTextMessage's content-append
      // logic doesn't duplicate text.
      //
      // This runs BEFORE the backend rebuild so the user sees activities
      // immediately instead of waiting for backendLooksIncomplete retries.
      const cachedJobId = cached.backgroundJobId;
      const cachedOngoingResearch = cached.ongoingResearchId;
      if (cachedOngoingResearch && cachedJobId && !isStaleLoad()) {
        const stNow = useStore.getState();
        const aIds = stNow.researchActivityIds.get(cachedOngoingResearch) ?? [];
        const pId = stNow.researchPlanIds.get(cachedOngoingResearch);
        const rId = stNow.researchReportIds.get(cachedOngoingResearch);
        const toRemove = aIds.filter((id) => id !== pId && id !== rId);
        if (toRemove.length > 0) {
          const rmSet = new Set(toRemove);
          const newMsgs = new Map(stNow.messages);
          const newMsgIds = stNow.messageIds.filter((id) => !rmSet.has(id));
          for (const id of toRemove) newMsgs.delete(id);
          const keptActs = aIds.filter((id) => !rmSet.has(id));
          const newRA = new Map(stNow.researchActivityIds);
          newRA.set(cachedOngoingResearch, keptActs);
          useStore.setState({ messages: newMsgs, messageIds: newMsgIds, researchActivityIds: newRA });
          deepResearchDebugLog("loadConversation", "cleared activity messages for full event replay", {
            conversationId, removedCount: toRemove.length,
          });
        }
        deepResearchDebugLog("loadConversation", "eager background job reconnect (cursor=0)", {
          conversationId, jobId: cachedJobId, cachedCursor: cached.backgroundJobCursor ?? 0,
        });
        // Fire-and-forget — resumeBackgroundResearch has its own stale guard
        _eagerReconnectFired = true;
        void reconnectToBackgroundJob(cachedJobId, 0);
      }
    } else if (isContextSwitch && !isStaleLoad()) {
      // Force-persist the outgoing conversation's state to cache BEFORE clearing
      // the store.  Without this, an ongoing research stream would lose all
      // in-memory state (messages, research mappings, backgroundJobId) because:
      //   1. _suppressPersist prevents the debounced persist from firing
      //   2. The store is about to be overwritten with the new conversation
      //   3. The stream's finally-block cannot persist because the store is stale
      // By persisting here, the cache retains backgroundJobId + ongoingResearchId
      // so reconnectToBackgroundJob can resume when the user navigates back.
      if (persistTimer) {
        clearTimeout(persistTimer);
        persistTimer = null;
      }
      persistStoreState();

      // Clear state immediately if switching conversations and no cache is available.
      // This prevents the previous conversation's content (and research cards) from
      // visually leaking into the new conversation view while fetching.
      // Suppress persist during the clearing → backend-fetch → apply cycle so the
      // empty intermediate state is never written to the conversation cache.
      _suppressPersist = true;
      useStore.setState({
        conversationId,
        // Keep threadId or generate new? Usually keep to allow continuity if needed,
        // but for a new conversation load, we effectively reset.
        threadId: resolvedConversationThreadId,
        messageIds: [],
        messages: new Map(),
        messageBackendIds: new Map(),
        researchIds: [],
        researchPlanIds: new Map(),
        researchReportIds: new Map(),
        researchActivityIds: new Map(),
        researchQueries: new Map(),
        researchCitations: new Map(),
        researchRunStatus: new Map(),
        restartPlanShownResearchIds: new Set(),
        planActionLocks: new Map(),
        cancelledResearchIds: new Set(),
        ongoingResearchId: null,
        openResearchId: null,
        backgroundJobId: null,
        backgroundJobCursor: 0,
        tokenUsage: null,
        // sessionTokenUsage: Keep? No, scope to conversation usually.
        sessionTokenUsage: DEFAULT_SESSION_TOKEN_USAGE,
        responseTiming: null,
        responding: false,
        generationPhase: "idle",
      });
    }

    const conv = await apiGetConversation(conversationId);
    if (isStaleLoad()) {
      return;
    }
    const messageIds: string[] = [];
    const messages = new Map<string, Message>();
    const messageBackendIds = new Map<string, number>();
    const researchIds: string[] = [];
    const researchIdSet = new Set<string>();
    const researchPlanIds = new Map<string, string>();
    const researchReportIds = new Map<string, string>();
    const researchActivityIds = new Map<string, string[]>();
    const researchQueries = new Map<string, string>();
    const researchCitations = new Map<string, Citation[]>();
    const researchRunStatus = new Map<string, DeepResearchTaskStatus>();
    const planActionLocks = new Map<string, "accepted" | "replan">();
    let latestRunStatusWithoutResearch: DeepResearchTaskStatus | null = null;
    let lastUserContent = "";
    let pendingPlanMessageId: string | null = null;
    let pendingPlanQuery = "";
    let inferredResearchId: string | null = null;

    const ensureResearch = (researchId: string) => {
      if (!researchIdSet.has(researchId)) {
        researchIdSet.add(researchId);
        researchIds.push(researchId);
      }
      if (!researchActivityIds.has(researchId)) {
        researchActivityIds.set(researchId, []);
      }
    };
    const pushActivity = (researchId: string, messageId: string) => {
      const current = researchActivityIds.get(researchId) ?? [];
      if (!current.includes(messageId)) {
        researchActivityIds.set(researchId, [...current, messageId]);
      }
    };

    const orderedMessages = [...(conv.messages ?? [])].sort((a, b) => a.id - b.id);
    for (const m of orderedMessages) {
      const id = String(m.id);
      const { content: rawCleanedContent, meta } = extractPersistedResearchMeta(m.content || "");
      const { content: cleanedContent, toolCalls: restoredToolCalls } = extractPersistedToolCalls(rawCleanedContent);
      const plannerPayload = m.role === "assistant" ? parsePlannerContent(cleanedContent) : null;
      const inferredPlanner = plannerPayload != null;
      const inferredReport = !inferredPlanner && isLikelyReportContent(cleanedContent);
      // Planner content detection is the most reliable signal (distinctive JSON
      // format) and MUST override meta.agent.  Without this, a planner message
      // persisted with the wrong agent (e.g. "researcher") would render as a
      // plain bubble instead of PlanCard after reload.
      const inferredAgent: Message["agent"] | undefined = inferredPlanner
        ? "planner"
        : meta?.agent
          ? meta.agent
          : inferredReport
            ? "reporter"
            : isLikelyCoordinatorContent(cleanedContent)
              ? "coordinator"
              : m.role === "assistant"
                ? "researcher"
                : undefined;
      messageIds.push(id);
      messageBackendIds.set(id, m.id);
      messages.set(id, {
        id,
        threadId: resolvedConversationThreadId,
        role: m.role,
        agent: inferredAgent,
        content: cleanedContent,
        contentChunks: [cleanedContent],
        isStreaming: false,
        ...(restoredToolCalls ? { toolCalls: restoredToolCalls } : {}),
      });

      if (m.role === "user") {
        lastUserContent = cleanedContent;
      }
      const deepResearchRunStatus = extractDeepResearchRunStatus(
        m.metadata as Record<string, unknown> | null | undefined,
      );
      const deepResearchPlanActionLock = extractDeepResearchPlanActionLock(
        m.metadata as Record<string, unknown> | null | undefined,
      );
      if (deepResearchPlanActionLock) {
        planActionLocks.set(id, deepResearchPlanActionLock);
      }
      // Recover plan action lock from persisted research meta when backend
      // metadata lacks it (apiUpdateMessage only writes content, not metadata).
      if (!planActionLocks.has(id) && meta?.planActionLock) {
        planActionLocks.set(id, meta.planActionLock);
      }

      if (meta) {
        ensureResearch(meta.researchId);
        if (deepResearchRunStatus && deepResearchRunStatus !== "running") {
          researchRunStatus.set(meta.researchId, deepResearchRunStatus);
        }
        // Recover status from persisted research meta when backend metadata lacks it.
        if (
          !researchRunStatus.has(meta.researchId) &&
          meta.status &&
          (meta.status === "running" || meta.status === "success" || meta.status === "error" || meta.status === "cancelled")
        ) {
          researchRunStatus.set(meta.researchId, meta.status as DeepResearchTaskStatus);
        }
        if (meta.kind === "research_root" && meta.query) {
          researchQueries.set(meta.researchId, meta.query);
        }
        // Ensure plan binding is set when content is detected as planner output,
        // regardless of what meta.kind says.  This covers cases where meta.kind
        // was "research_root" or "activity" but the message is actually a plan.
        if (inferredPlanner && !researchPlanIds.has(meta.researchId)) {
          researchPlanIds.set(meta.researchId, id);
          pushActivity(meta.researchId, id);
        }
        // Backward compatibility:
        // Some legacy records persisted planner output as research_root.
        // Treat such root-planner messages as plan binding so plan-card lock
        // and restart flows can be reconstructed after refresh.
        if (meta.kind === "research_root" && meta.agent === "planner") {
          researchPlanIds.set(meta.researchId, id);
          pushActivity(meta.researchId, id);
        }
        if (meta.kind === "plan") {
          researchPlanIds.set(meta.researchId, id);
          pushActivity(meta.researchId, id);
          // Clear the fallback pending plan so the legacy heuristic below does
          // not create a phantom research from a stale content-inferred planner
          // message (e.g. the coordinator JSON that also looks like planner output).
          pendingPlanMessageId = null;
        }
        if (meta.kind === "report") {
          researchReportIds.set(meta.researchId, id);
        }
        if (meta.kind === "activity" || meta.kind === "report" || meta.kind === "research_root") {
          pushActivity(meta.researchId, id);
        }
        // Even with meta, track planner for the legacy fallback path so that
        // subsequent messages WITHOUT meta can still form research bindings.
        if (inferredPlanner) {
          pendingPlanMessageId = id;
          pendingPlanQuery = lastUserContent;
        }
        continue;
      }

      // Fallback for legacy persisted messages without PATHLAB_RESEARCH_META.
      if (m.role !== "assistant") {
        continue;
      }
      // Coordinator-like messages (option buttons, task configs, error messages, etc.)
      // must not be absorbed into research activities. They live in the main chat view
      // as standalone assistant bubbles and would be hidden if added to researchActivityIds.
      if (inferredAgent === "coordinator" || isLikelyCoordinatorContent(cleanedContent)) {
        continue;
      }
      if (inferredPlanner) {
        pendingPlanMessageId = id;
        pendingPlanQuery = lastUserContent;
        inferredResearchId = null;
        continue;
      }
      if (!pendingPlanMessageId) {
        continue;
      }
      const looksLikeResearchStarted =
        inferredReport ||
        isLikelyResearchActivityContent(cleanedContent) ||
        cleanedContent.trim().length > 20;
      // An empty-content placeholder message right after a pending plan is likely
      // a research root created by ensureResearchCardFromAcceptedPlan.
      const looksLikeEmptyResearchRoot =
        !looksLikeResearchStarted &&
        pendingPlanMessageId &&
        cleanedContent.trim().length === 0 &&
        !inferredPlanner;
      if (!looksLikeResearchStarted && !looksLikeEmptyResearchRoot) {
        continue;
      }
      if (!inferredResearchId) {
        // Check if this plan is already bound to a research via the meta path.
        // If so, add to that existing research instead of creating a duplicate.
        let existingResearchForPlan: string | null = null;
        for (const [rid, planId] of researchPlanIds.entries()) {
          if (planId === pendingPlanMessageId) {
            existingResearchForPlan = rid;
            break;
          }
        }
        if (existingResearchForPlan) {
          inferredResearchId = existingResearchForPlan;
        } else {
          inferredResearchId = id;
          ensureResearch(inferredResearchId);
          researchPlanIds.set(inferredResearchId, pendingPlanMessageId);
          pushActivity(inferredResearchId, pendingPlanMessageId);
          if (pendingPlanQuery) {
            researchQueries.set(inferredResearchId, pendingPlanQuery);
          }
        }
      }
      pushActivity(inferredResearchId, id);
      if (deepResearchRunStatus && deepResearchRunStatus !== "running") {
        researchRunStatus.set(inferredResearchId, deepResearchRunStatus);
      }
      if (inferredReport) {
        researchReportIds.set(inferredResearchId, id);
      }
      if (!inferredResearchId && deepResearchRunStatus && deepResearchRunStatus !== "running") {
        latestRunStatusWithoutResearch = deepResearchRunStatus;
      }
    }

    // Backward-compatibility fallback:
    // For legacy conversations without persisted report meta, recover a report candidate
    // from activities so old reports do not disappear from history.
    for (const researchId of researchIds) {
      if (researchReportIds.has(researchId)) {
        continue;
      }
      const activityIds = researchActivityIds.get(researchId) ?? [];
      const candidates = activityIds
        .map((id) => messages.get(id))
        .filter(
          (m): m is Message =>
            !!m &&
            m.role === "assistant" &&
            m.agent !== "planner" &&
            (m.content?.trim().length ?? 0) > 80,
        );
      if (candidates.length === 0) {
        continue;
      }
      // Prefer explicit reporter output, otherwise pick the longest assistant content.
      const reporter = candidates.find((m) => m.agent === "reporter");
      if (reporter) {
        researchReportIds.set(researchId, reporter.id);
        continue;
      }
      const best = candidates.reduce((acc, cur) =>
        (cur.content?.length ?? 0) > (acc.content?.length ?? 0) ? cur : acc,
      );
      researchReportIds.set(researchId, best.id);
    }

    // Prune phantom research entries that were created from empty interrupt
    // messages (the legacy heuristic `looksLikeEmptyResearchRoot` matches them).
    // A research with zero execution evidence should not exist — the user never
    // clicked "Start Research", so only PlanCards should render.
    // BUT: never prune a research that has a plan with an "accepted" action lock —
    // that means the user did click Start and execution is (or was) in progress.
    // Also check cached backgroundJobId: if the conversation had an active
    // background job, the research was running and should not be pruned.
    const cachedHasBackgroundJob = !!(cached?.backgroundJobId);
    for (let i = researchIds.length - 1; i >= 0; i--) {
      const rid = researchIds[i]!;
      const hasReport = researchReportIds.has(rid);
      const hasStatus = researchRunStatus.has(rid);
      const activities = researchActivityIds.get(rid) ?? [];
      const hasNonPlannerActivity = activities.some((actId) => {
        if (actId === rid) return false; // the research root itself doesn't count
        const msg = messages.get(actId);
        if (!msg) return false;
        if (msg.agent === "planner") return false;
        // An activity with actual content is real execution evidence.
        return (msg.content?.trim().length ?? 0) > 0;
      });
      // A plan with an "accepted" lock means the user started execution.
      const planId = researchPlanIds.get(rid);
      const hasPlanAccepted = planId != null && planActionLocks.get(planId) === "accepted";
      if (!hasReport && !hasStatus && !hasNonPlannerActivity && !hasPlanAccepted && !cachedHasBackgroundJob) {
        // Remove this phantom research.
        researchIds.splice(i, 1);
        researchPlanIds.delete(rid);
        researchReportIds.delete(rid);
        researchActivityIds.delete(rid);
        researchQueries.delete(rid);
      }
    }

    // Normalize persisted research IDs to current conversation message IDs.
    // Persisted meta keeps original local message IDs, but backend history uses
    // backend-assigned message IDs after reload. Without normalization, research
    // cards lose their anchor and fall back to plain message rendering.
    const validMessageIds = new Set(messageIds);
    const normalizedResearchIds: string[] = [];
    const normalizedResearchQueries = new Map<string, string>();
    const normalizedResearchPlanIds = new Map<string, string>();
    const normalizedResearchReportIds = new Map<string, string>();
    const normalizedResearchActivityIds = new Map<string, string[]>();
    const normalizedResearchCitations = new Map<string, Citation[]>();
    const normalizedResearchRunStatus = new Map<string, DeepResearchTaskStatus>();
    const normalizedRestartPlanShownResearchIds = new Set<string>();
    const normalizedPlanActionLocks = new Map<string, "accepted" | "replan">();
    const cachedRestartPlanShownList = cached?.restartPlanShownResearchIds ?? [];
    const cachedRestartPlanShownSet = new Set(cachedRestartPlanShownList);
    for (const [messageId, action] of planActionLocks.entries()) {
      if (validMessageIds.has(messageId)) {
        normalizedPlanActionLocks.set(messageId, action);
      }
    }

    const currentOpenResearchId = useStore.getState().openResearchId;
    const currentOngoingResearchId = useStore.getState().ongoingResearchId;
    let normalizedOpenResearchId: string | null = null;
    let normalizedOngoingResearchId: string | null = null;

    const pickResearchAnchor = (researchId: string): string | null => {
      if (validMessageIds.has(researchId)) {
        return researchId;
      }
      const planId = researchPlanIds.get(researchId);
      const reportId = researchReportIds.get(researchId);
      const activities = researchActivityIds.get(researchId) ?? [];
      const firstNonPlanner = activities.find((id) => {
        const msg = messages.get(id);
        return msg && msg.agent !== "planner";
      });
      return firstNonPlanner ?? reportId ?? planId ?? activities[0] ?? null;
    };

    for (const oldResearchId of researchIds) {
      const normalizedResearchId = pickResearchAnchor(oldResearchId);
      if (!normalizedResearchId || !validMessageIds.has(normalizedResearchId)) {
        continue;
      }
      if (!normalizedResearchIds.includes(normalizedResearchId)) {
        normalizedResearchIds.push(normalizedResearchId);
      }

      // Only attempt to preserve open/ongoing state if we are loading the SAME conversation.
      // If we switched conversations (isContextSwitch=true), we should not map the old
      // conversation's IDs to the new one.
      if (!isContextSwitch) {
        if (oldResearchId === currentOpenResearchId) {
          normalizedOpenResearchId = normalizedResearchId;
        }
        if (oldResearchId === currentOngoingResearchId) {
          normalizedOngoingResearchId = normalizedResearchId;
        }
      }

      // MERGE instead of overwrite: when multiple old researchIds normalize to
      // the same new ID (e.g., plan under "725" and activities under a nanoid that
      // also normalizes to "725"), we must merge their data, not discard the first.

      const query = researchQueries.get(oldResearchId);
      if (query != null && !normalizedResearchQueries.has(normalizedResearchId)) {
        normalizedResearchQueries.set(normalizedResearchId, query);
      }

      const planId = researchPlanIds.get(oldResearchId);
      if (planId && validMessageIds.has(planId) && !normalizedResearchPlanIds.has(normalizedResearchId)) {
        normalizedResearchPlanIds.set(normalizedResearchId, planId);
      }

      const reportId = researchReportIds.get(oldResearchId);
      if (reportId && validMessageIds.has(reportId) && !normalizedResearchReportIds.has(normalizedResearchId)) {
        normalizedResearchReportIds.set(normalizedResearchId, reportId);
      }

      const newActivityIds = (researchActivityIds.get(oldResearchId) ?? []).filter((id) =>
        validMessageIds.has(id),
      );
      if (newActivityIds.length) {
        const existing = normalizedResearchActivityIds.get(normalizedResearchId) ?? [];
        const merged = [...existing];
        for (const id of newActivityIds) {
          if (!merged.includes(id)) {
            merged.push(id);
          }
        }
        normalizedResearchActivityIds.set(normalizedResearchId, merged);
      }

      const citations = useStore.getState().researchCitations.get(oldResearchId);
      if (citations?.length && !normalizedResearchCitations.has(normalizedResearchId)) {
        normalizedResearchCitations.set(normalizedResearchId, citations);
      }
      const runStatus = researchRunStatus.get(oldResearchId);
      if (runStatus) {
        normalizedResearchRunStatus.set(normalizedResearchId, runStatus);
      }
      if (cachedRestartPlanShownSet.has(oldResearchId)) {
        normalizedRestartPlanShownResearchIds.add(normalizedResearchId);
      }
    }

    // Post-normalization merge: fold plan-less fragment researches into the
    // nearest preceding research that has a plan.  This handles the common case
    // of an interrupted research where the reconnected stream created messages
    // under a new researchId (e.g., a LangGraph run ID) that doesn't share the
    // plan binding of the original research.
    for (let i = normalizedResearchIds.length - 1; i > 0; i--) {
      const rid = normalizedResearchIds[i]!;
      if (normalizedResearchPlanIds.has(rid) || normalizedResearchReportIds.has(rid)) {
        continue; // has its own plan or report — not a fragment
      }
      // Find the nearest preceding research with a plan to merge into.
      let targetIdx = -1;
      for (let j = i - 1; j >= 0; j--) {
        if (normalizedResearchPlanIds.has(normalizedResearchIds[j]!)) {
          targetIdx = j;
          break;
        }
      }
      if (targetIdx < 0) continue;
      const targetRid = normalizedResearchIds[targetIdx]!;

      // Merge activities
      const targetActivities = normalizedResearchActivityIds.get(targetRid) ?? [];
      const fragmentActivities = normalizedResearchActivityIds.get(rid) ?? [];
      const merged = [...targetActivities];
      for (const id of fragmentActivities) {
        if (!merged.includes(id)) merged.push(id);
      }
      normalizedResearchActivityIds.set(targetRid, merged);
      normalizedResearchActivityIds.delete(rid);

      // Merge citations
      if (!normalizedResearchCitations.has(targetRid) && normalizedResearchCitations.has(rid)) {
        normalizedResearchCitations.set(targetRid, normalizedResearchCitations.get(rid)!);
      }
      normalizedResearchCitations.delete(rid);

      // Carry over run status (prefer non-running terminal status)
      const fragmentStatus = normalizedResearchRunStatus.get(rid);
      if (fragmentStatus && fragmentStatus !== "running") {
        normalizedResearchRunStatus.set(targetRid, fragmentStatus);
      }
      normalizedResearchRunStatus.delete(rid);
      normalizedResearchQueries.delete(rid);

      // Remap open/ongoing IDs
      if (normalizedOpenResearchId === rid) normalizedOpenResearchId = targetRid;
      if (normalizedOngoingResearchId === rid) normalizedOngoingResearchId = targetRid;

      normalizedResearchIds.splice(i, 1);
      deepResearchDebugLog("loadConversation", "merged fragment research into target", {
        fragmentRid: rid,
        targetRid,
        mergedActivityCount: merged.length,
      });
    }

    if (
      latestRunStatusWithoutResearch &&
      normalizedResearchIds.length > 0
    ) {
      const fallbackResearchId = normalizedResearchIds[normalizedResearchIds.length - 1]!;
      if (!normalizedResearchRunStatus.has(fallbackResearchId)) {
        normalizedResearchRunStatus.set(fallbackResearchId, latestRunStatusWithoutResearch);
      }
    }

    // If restart-plan UI state existed in cache but research IDs were remapped
    // (or inferred differently) after backend reload, keep that intent on the
    // latest normalized research card so refresh does not lose the restart lock.
    if (
      cachedRestartPlanShownList.length > 0 &&
      normalizedRestartPlanShownResearchIds.size === 0 &&
      normalizedResearchIds.length > 0
    ) {
      normalizedRestartPlanShownResearchIds.add(
        normalizedResearchIds[normalizedResearchIds.length - 1]!,
      );
    }

    const rebuiltState = {
      conversationId,
      threadId: resolvedConversationThreadId,
      messageIds,
      messages,
      messageBackendIds,
      researchIds: normalizedResearchIds,
      researchPlanIds: normalizedResearchPlanIds,
      researchReportIds: normalizedResearchReportIds,
      researchActivityIds: normalizedResearchActivityIds,
      researchQueries: normalizedResearchQueries,
      researchCitations: normalizedResearchCitations,
      researchRunStatus: normalizedResearchRunStatus,
      restartPlanShownResearchIds: normalizedRestartPlanShownResearchIds,
      planActionLocks: normalizedPlanActionLocks,
      cancelledResearchIds: (() => {
        const derived = new Set<string>();
        for (const [rid, status] of normalizedResearchRunStatus.entries()) {
          if (status === "cancelled") {
            derived.add(rid);
          }
        }
        return derived;
      })(),
      ongoingResearchId: normalizedOngoingResearchId,
      // If normalization lost the open research ID but the user had a panel open,
      // fall back to the last research in the rebuilt state so the panel stays open.
      openResearchId:
        normalizedOpenResearchId ??
        (currentOpenResearchId && normalizedResearchIds.length > 0
          ? normalizedResearchIds[normalizedResearchIds.length - 1]!
          : null),
      tokenUsage: cached?.tokenUsage ?? null,
      sessionTokenUsage: cached?.sessionTokenUsage ?? DEFAULT_SESSION_TOKEN_USAGE,
      responseTiming: cached?.responseTiming ?? null,
      responding: false,
      generationPhase: "idle" as const,
    };
    deepResearchDebugLog("loadConversation", "rebuilt backend state", {
      conversationId,
      backendMessageCount: messageIds.length,
      backendResearchCount: normalizedResearchIds.length,
      backendPlanCount: normalizedResearchPlanIds.size,
      backendReportCount: normalizedResearchReportIds.size,
    });

    // Count only non-empty cached messages/activities.  Empty stubs (mid-stream
    // messages with no text and no tool calls) are never persisted to backend by
    // persistMessage(), so including them inflates cachedCount and causes
    // backendLooksIncomplete to be permanently true — preventing the backend
    // rebuild from ever being applied.
    const cachedMsgMap = new Map<string, Message>(cached?.messages ?? []);
    const isNonEmptyCachedMsg = (id: string): boolean => {
      const msg = cachedMsgMap.get(id);
      if (!msg) return false;
      if ((msg.content ?? "").replace(/\[PATHLAB_RESEARCH_META\][\s\S]*?(?:\[\/PATHLAB_RESEARCH_META\]|$)/g, "").trim()) return true;
      if (msg.toolCalls?.length) return true;
      // User messages are always meaningful
      if (msg.role === "user") return true;
      return false;
    };
    const cachedMessageCount = (cached?.messageIds ?? []).filter(isNonEmptyCachedMsg).length;
    const cachedResearchCount = cached?.researchIds?.length ?? 0;
    const cachedPlanCount = cached?.researchPlanIds?.length ?? 0;
    const cachedReportCount = cached?.researchReportIds?.length ?? 0;
    const cachedActivityCount = (cached?.researchActivityIds ?? []).reduce(
      (sum, [, ids]) => sum + (Array.isArray(ids) ? ids.filter(isNonEmptyCachedMsg).length : 0),
      0,
    );
    const backendMessageCount = messageIds.length;
    const backendResearchCount = normalizedResearchIds.length;
    const backendPlanCount = normalizedResearchPlanIds.size;
    const backendReportCount = normalizedResearchReportIds.size;
    const backendActivityCount = Array.from(normalizedResearchActivityIds.values()).reduce(
      (sum, ids) => sum + ids.length,
      0,
    );
    const messageIdSet = new Set(messageIds);
    const cachedPlanIdsSet = new Set(
      (cached?.researchPlanIds ?? [])
        .map(([, planId]) => planId)
        .filter((planId) => messageIdSet.has(planId)),
    );
    const cachedReportIdsSet = new Set(
      (cached?.researchReportIds ?? [])
        .map(([, reportId]) => reportId)
        .filter((reportId) => messageIdSet.has(reportId)),
    );
    const backendPlanIdsSet = new Set(Array.from(normalizedResearchPlanIds.values()));
    const backendReportIdsSet = new Set(Array.from(normalizedResearchReportIds.values()));
    const backendPlanCoverage = Array.from(cachedPlanIdsSet).filter((id) =>
      backendPlanIdsSet.has(id),
    ).length;
    const backendReportCoverage = Array.from(cachedReportIdsSet).filter((id) =>
      backendReportIdsSet.has(id),
    ).length;
    const backendPlanCoverageDropped =
      cachedPlanIdsSet.size > 0 && backendPlanCoverage === 0;
    const backendReportCoverageDropped =
      cachedReportIdsSet.size > 0 && backendReportCoverage === 0;
    const backendLooksIncomplete =
      cached != null &&
      (
        backendMessageCount < cachedMessageCount ||
        backendResearchCount < cachedResearchCount ||
        backendPlanCount < cachedPlanCount ||
        backendActivityCount < cachedActivityCount ||
        backendPlanCoverageDropped ||
        backendReportCoverageDropped ||
        (cachedReportCount > 0 && backendReportCount === 0)
      );

    // When eager event-replay reconnect is in progress, skip the entire
    // backend rebuild comparison and apply — the reconnect is rebuilding
    // messages from the complete event history and applying the rebuilt state
    // would overwrite that in-progress reconstruction.
    if (_eagerReconnectFired) {
      deepResearchDebugLog("loadConversation", "skipping backend rebuild apply — eager reconnect in progress", {
        conversationId,
      });
      backendRebuildRetryCounts.delete(conversationId);
      return;
    }

    if (backendLooksIncomplete) {
      const attempt = backendRebuildRetryCounts.get(conversationId) ?? 0;
      deepResearchDebugLog("loadConversation", "backend rebuild looks incomplete", {
        conversationId,
        attempt,
        cachedMessageCount,
        backendMessageCount,
        cachedResearchCount,
        backendResearchCount,
        cachedPlanCount,
        backendPlanCount,
        cachedReportCount,
        backendReportCount,
        cachedActivityCount,
        backendActivityCount,
      });
      if (attempt < BACKEND_REBUILD_RETRY_MAX) {
        backendRebuildRetryCounts.set(conversationId, attempt + 1);
        // Keep richer cached state for this paint and retry backend sync shortly.
        if (typeof window !== "undefined" && !isStaleLoad()) {
          window.setTimeout(() => {
            if (latestRequestedConversationId === conversationId) {
              void loadConversationFromBackend(conversationId);
            }
          }, BACKEND_REBUILD_RETRY_DELAY_MS);
        }
        return;
      }
    } else {
      backendRebuildRetryCounts.delete(conversationId);
    }

    if (isStaleLoad()) {
      deepResearchDebugLog("loadConversation", "stale load ignored", {
        conversationId,
        loadSeq,
      });
      return;
    }
    useStore.setState(rebuiltState);
    deepResearchDebugLog("loadConversation", "applied rebuilt state", {
      conversationId,
      messageCount: rebuiltState.messageIds.length,
      researchCount: rebuiltState.researchIds.length,
    });

    // Check if there is an unfinished background job that needs reconnection.
    // Use cached values because rebuiltState does not carry backgroundJobId.
    // Skip if eager reconnect already fired from the cache-restore path above.
    const restoredJobId = cached?.backgroundJobId;
    const restoredOngoingResearch = rebuiltState.ongoingResearchId;
    if (restoredOngoingResearch && restoredJobId && !_eagerReconnectFired) {
      const storeNow = useStore.getState();
      const activityIds = storeNow.researchActivityIds.get(restoredOngoingResearch) ?? [];
      const planId = storeNow.researchPlanIds.get(restoredOngoingResearch);
      const reportId = storeNow.researchReportIds.get(restoredOngoingResearch);
      // Keep plan and report; remove all other activity messages
      const idsToRemove = activityIds.filter((id) => id !== planId && id !== reportId);
      if (idsToRemove.length > 0) {
        const removeSet = new Set(idsToRemove);
        const newMessages = new Map(storeNow.messages);
        const newMessageIds = storeNow.messageIds.filter((id) => !removeSet.has(id));
        for (const id of idsToRemove) newMessages.delete(id);
        // Clear activity IDs (keep only plan); replay will re-add via appendResearchActivity
        const keptActivities = activityIds.filter((id) => !removeSet.has(id));
        const newResearchActivityIds = new Map(storeNow.researchActivityIds);
        newResearchActivityIds.set(restoredOngoingResearch, keptActivities);
        useStore.setState({
          messages: newMessages,
          messageIds: newMessageIds,
          researchActivityIds: newResearchActivityIds,
        });
        deepResearchDebugLog("loadConversation", "cleared activity messages for full replay", {
          conversationId,
          removedCount: idsToRemove.length,
        });
      }

      deepResearchDebugLog("loadConversation", "triggering background job reconnection (full replay from cursor=0)", {
        conversationId,
        jobId: restoredJobId,
        cachedCursor: cached?.backgroundJobCursor ?? 0,
        ongoingResearchId: restoredOngoingResearch,
      });
      // Async reconnect from cursor=0 — do not block the load
      void reconnectToBackgroundJob(restoredJobId, 0);
    }
  } catch (error) {
    console.warn("[DeepResearch] Failed to load conversation:", error);
    deepResearchDebugLog("loadConversation", "failed", {
      conversationId,
      error: error instanceof Error ? error.message : String(error),
    });
  } finally {
    _suppressPersist = false;
  }
}

export async function sendMessage(
  content?: string,
  {
    interruptFeedback,
    resources,
  }: {
    interruptFeedback?: string;
    resources?: Array<Resource>;
  } = {},
  options: { abortSignal?: AbortSignal } = {},
) {
  const conversationId = await ensureConversationId(content);
  const isStaleConversation = () => useStore.getState().conversationId !== conversationId;
  const stateBefore = useStore.getState();
  const hasExistingResearch = stateBefore.researchIds.length > 0;
  const hasCompletedResearch = stateBefore.researchIds.some((researchId) => {
    const status = stateBefore.researchRunStatus.get(researchId);
    return (
      stateBefore.researchReportIds.has(researchId) ||
      status === "success"
    );
  });
  const beforeResearchIds = new Set(stateBefore.researchIds);
  const beforeIds = new Set(useStore.getState().messageIds);
  const taskId = `deep_research_${conversationId ?? getThreadId()}`;
  const normalizedTitle = deriveDeepResearchTaskTitle(content, interruptFeedback);
  const plannerTitleAtStart =
    interruptFeedback === "accepted" ? getCurrentPlannerTitleFromState() : null;

  // When interruptFeedback is set (e.g. plan accept/replan), the user content
  // is the resolved original query that already exists in the conversation.
  // Skip creating a duplicate user message to avoid double-persisting.
  if (content != null && !interruptFeedback) {
    const threadId = getThreadId();
    const userMessage: Message = {
      id: nanoid(),
      threadId,
      role: "user",
      content: content,
      contentChunks: [content],
      resources,
    };
    appendMessage(userMessage);
    if (conversationId) {
      await persistMessage(userMessage);
    }
  }

  const shouldRouteToStandardAIChat =
    hasCompletedResearch &&
    (content ?? "").trim().length > 0;
  if (shouldRouteToStandardAIChat) {
    deepResearchDebugLog("routing", "switching to standard AIChat after completed research", {
      conversationId,
      interruptFeedback: interruptFeedback ?? null,
      contentPreview: (content ?? "").slice(0, 120),
    });
    await sendMessageViaStandardAIChat(conversationId, options);
    return;
  }

  const blockedBySecondResearchAccepted =
    hasCompletedResearch && interruptFeedback === "accepted";
  const guaranteedFollowUp = isGuaranteedFollowUpIntent(content);
  let blockedBySecondResearchIntent = false;
  let secondResearchIntentScore = 0;
  let secondResearchIntentReason = "";
  let secondResearchDecisionRaw = "";

  if (
    hasCompletedResearch &&
    interruptFeedback !== "accepted" &&
    (content ?? "").trim().length > 0 &&
    !guaranteedFollowUp
  ) {
    const intentDecision = await analyzeResearchStartIntentWithLLM(content ?? "", {
      threadId: getThreadId(),
      abortSignal: options.abortSignal,
    });
    secondResearchDecisionRaw = intentDecision.raw;
    secondResearchIntentScore = intentDecision.confidence;
    secondResearchIntentReason = intentDecision.reason;
    // Fail-closed: only allow when classifier confidently says it's NOT a new research request.
    const allowFollowUp =
      intentDecision.startNewResearch === false &&
      intentDecision.confidence >= 0.65;
    blockedBySecondResearchIntent = !allowFollowUp;
    deepResearchDebugLog("guard", "llm intent analysis completed", {
      conversationId,
      startNewResearch: intentDecision.startNewResearch,
      confidence: intentDecision.confidence,
      reason: intentDecision.reason,
      allowFollowUp,
      raw: intentDecision.raw,
    });
  }
  if (hasCompletedResearch && guaranteedFollowUp) {
    deepResearchDebugLog("guard", "skip second-research guard for guaranteed follow-up", {
      conversationId,
      interruptFeedback: interruptFeedback ?? null,
      contentPreview: (content ?? "").slice(0, 120),
    });
  }

  if (blockedBySecondResearchAccepted || blockedBySecondResearchIntent) {
    const threadId = getThreadId();
    const singleResearchPerConversationMessage = tr(
      "singleResearchPerConversation",
      "为了确保 research 质量，当前对话仅支持一次 Deep Research。如需发起新的研究课题，请新开一个对话。",
    );
    const fixedReplyResult = await generateFixedReplyWithLLM(
      singleResearchPerConversationMessage,
      {
        threadId,
        abortSignal: options.abortSignal,
      },
    );
    const rejectionMessage: Message = {
      id: nanoid(),
      threadId,
      role: "assistant",
      agent: "coordinator",
      content: fixedReplyResult.reply,
      contentChunks: [fixedReplyResult.reply],
      isStreaming: false,
    };
    appendMessage(rejectionMessage);
    if (conversationId) {
      await persistMessage(rejectionMessage);
    }
    deepResearchDebugLog("guard", "blocked second research in same conversation", {
      conversationId,
      hasExistingResearch,
      hasCompletedResearch,
      interruptFeedback: interruptFeedback ?? null,
      blockedBySecondResearchAccepted,
      blockedBySecondResearchIntent,
      intentConfidence: secondResearchIntentScore,
      intentReason: secondResearchIntentReason,
      intentRaw: secondResearchDecisionRaw,
      usedLLMFixedReply: fixedReplyResult.usedLLM,
      fixedReplyRaw: fixedReplyResult.raw,
      contentPreview: (content ?? "").slice(0, 120),
    });
    return;
  }

  if (interruptFeedback === "accepted") {
    ensureResearchCardFromAcceptedPlan();
  }

  const settings = getChatStreamSettings();
  const stream = chatStream(
    content ?? "[REPLAY]",
    {
      thread_id: conversationId ?? getThreadId(),
      conversation_id: conversationId ?? undefined,
      interrupt_feedback: interruptFeedback,
      resources,
      auto_accepted_plan: settings.autoAcceptedPlan,
      enable_clarification: settings.enableClarification ?? false,
      max_clarification_rounds: settings.maxClarificationRounds ?? 3,
      enable_deep_thinking: settings.enableDeepThinking ?? false,
      enable_background_investigation:
        settings.enableBackgroundInvestigation ?? true,
      enable_web_search: settings.enableWebSearch ?? true,
      max_plan_iterations: settings.maxPlanIterations,
      max_step_num: settings.maxStepNum,
      max_search_results: settings.maxSearchResults,
      report_style: settings.reportStyle,
      mcp_settings: settings.mcpSettings,
    },
    options,
  );

  // Reset token usage and start response timing
  useStore.getState().setTokenUsage(null);
  const startTime = Date.now();
  useStore.getState().setResponseTiming({ startTime, endTime: null, durationMs: null });

  setGenerationPhase("thinking");
  setResponding(true);

  let messageId: string | undefined;
  let receivedAnyEvent = false;
  const pendingUpdates = new Map<string, Message>();
  let updateTimer: NodeJS.Timeout | undefined;
  let deepResearchTaskStatus: DeepResearchTaskStatus = "success";
  let deepResearchTaskError: string | undefined;
  let deepResearchTaskStarted = false;
  let latestDeepResearchTaskTitle = plannerTitleAtStart ?? normalizedTitle;
  let lastEmittedTaskTitle: string | null = null;
  let abortedByUser = false;
  let errorMessageShown = false;
  let enteredStreamingPhase = false;
  let localBackgroundJobId: string | null = null;
  let localBackgroundJobCursor = 0;
  const isExplicitResearchStart = interruptFeedback === "accepted";

  const ensureDeepResearchTaskStarted = (titleOverride?: string) => {
    if (titleOverride?.trim()) {
      latestDeepResearchTaskTitle = titleOverride.trim();
    }
    if (deepResearchTaskStarted) return;
    deepResearchTaskStarted = true;
    lastEmittedTaskTitle = latestDeepResearchTaskTitle;
    emitDeepResearchTaskEvent(DEEP_RESEARCH_TASK_START_EVENT, {
      taskId,
      title: latestDeepResearchTaskTitle,
      conversationId,
      status: "running",
    });
  };

  if (isExplicitResearchStart) {
    ensureDeepResearchTaskStarted(plannerTitleAtStart ?? undefined);
  }

  const scheduleUpdate = () => {
    if (updateTimer) return; // Throttle: skip if already scheduled
    updateTimer = setTimeout(() => {
      updateTimer = undefined;
      // Guard: if the user switched conversations while the timer was pending,
      // discard the batched updates to prevent writing stale data into the
      // new conversation's store state.
      if (isStaleConversation()) {
        pendingUpdates.clear();
        return;
      }
      // Batch update message status
      if (pendingUpdates.size > 0) {
        useStore.getState().updateMessages(Array.from(pendingUpdates.values()));
        pendingUpdates.clear();
      }
    }, 16); // ~60fps
  };

  try {
    for await (const event of stream) {
      if (isStaleConversation()) {
        deepResearchDebugLog("stream", "conversation switched, discarding remaining events", {
          originalConversationId: conversationId,
          currentConversationId: useStore.getState().conversationId,
        });
        // Flush any pending throttled updates before exiting — these hold
        // messages that belong to the original conversation and are needed
        // for persistence even though we are about to stop processing.
        if (updateTimer) {
          clearTimeout(updateTimer);
          updateTimer = undefined;
        }
        if (pendingUpdates.size > 0) {
          // Store may already represent a different conversation at this point,
          // so do NOT call updateMessages. Just clear pending to avoid leaking.
          pendingUpdates.clear();
        }
        break;
      }
      receivedAnyEvent = true;
      const { type, data } = event;

      // Handle background job tracking events
      if (type === "job_created" && data && typeof data === "object" && "job_id" in data) {
        localBackgroundJobId = (data as { job_id: string }).job_id;
        localBackgroundJobCursor = 0;
        useStore.getState().setBackgroundJob(localBackgroundJobId, 0);
        continue;
      }
      if (type === "cursor_update" && data && typeof data === "object" && "cursor" in data) {
        localBackgroundJobCursor = (data as { cursor: number }).cursor;
        useStore.getState().setBackgroundJob(
          useStore.getState().backgroundJobId,
          localBackgroundJobCursor,
        );
        continue;
      }

      if (
        !enteredStreamingPhase &&
        (type === "message_chunk" ||
          type === "tool_calls" ||
          type === "tool_call_chunks" ||
          type === "tool_call_result" ||
          type === "interrupt")
      ) {
        enteredStreamingPhase = true;
        setGenerationPhase("streaming");
      }
      let message: Message | undefined;
      const eventAgent =
        data && typeof data === "object" && "agent" in data && typeof data.agent === "string"
          ? data.agent
          : undefined;

      // Only create a background task once the graph enters actual research execution
      // (not when it is still in planner-only phase).
      if (!deepResearchTaskStarted && isDeepResearchExecutionAgent(eventAgent)) {
        ensureDeepResearchTaskStarted();
      }

      // Handle citations event: store citations for the current research
      if (type === "citations") {
        const ongoingResearchId = useStore.getState().ongoingResearchId;
        if (ongoingResearchId && data.citations) {
          useStore.getState().setCitations(ongoingResearchId, data.citations);
        }
        continue;
      }

      // Handle token_usage event: store token usage summary
      if (type === "token_usage") {
        const tokenData = data as TokenUsageEvent["data"];
        const usage: TokenUsageSummary = {
          totalPromptTokens: tokenData.total_prompt_tokens,
          totalCompletionTokens: tokenData.total_completion_tokens,
          totalTokens: tokenData.total_tokens,
          totalCalls: tokenData.total_calls,
          byAgent: tokenData.by_agent,
        };
        useStore.getState().setTokenUsage(usage);
        useStore.getState().accumulateSessionTokens(usage);
        continue;
      }

      // Handle error event explicitly to avoid creating malformed messages.
      if (event.type === "error") {
        deepResearchTaskStatus = "error";
        const err = event.data.error;
        const detail =
          event.data &&
            typeof event.data === "object" &&
            "detail" in event.data &&
            typeof (event.data as { detail?: unknown }).detail === "string"
            ? (event.data as { detail: string }).detail.trim()
            : "";
        const rawError =
          detail ||
          (typeof err === "string"
            ? err
            : tr("deepResearchError", "Deep research error"));
        deepResearchTaskError = pickDeepResearchErrorMessage(rawError);
        deepResearchConsoleError("stream", "received backend error event", {
          conversationId,
          taskId,
          interruptFeedback: interruptFeedback ?? null,
          eventData: event.data,
          rawError,
        });
        deepResearchDebugLog("stream", "received error event", {
          rawError,
        });

        // Display error as a chat message (like the normal AI chat page does)
        // so the user sees a permanent, readable error in the conversation.
        const errorMessage: Message = {
          id: nanoid(),
          threadId: getThreadId(),
          role: "assistant",
          agent: "coordinator",
          content: deepResearchTaskError,
          contentChunks: [deepResearchTaskError],
          isStreaming: false,
        };
        appendMessage(errorMessage);
        errorMessageShown = true;

        // Stop consuming further events for this run to avoid hanging
        // when backend keeps the stream open after an error event.
        break;
      }
      if (event.type === "cancelled") {
        deepResearchTaskStatus = "cancelled";
        const cancelledResearchId = useStore.getState().ongoingResearchId;
        if (cancelledResearchId) {
          useStore.getState().setResearchCancelled(cancelledResearchId, true);
        }
        continue;
      }

      // Handle tool_call_result specially: use the message that contains the tool call
      if (type === "tool_call_result") {
        message = findMessageByToolCallId(data.tool_call_id);
        if (message) {
          // Use the found message's ID, not data.id
          messageId = message.id;
        } else {
          // Shouldn't happen, but handle gracefully
          if (process.env.NODE_ENV === "development") {
            console.warn(`Tool call result without matching message: ${data.tool_call_id}`);
          }
          continue; // Skip this event
        }
      } else {
        // Fallback to the closure's messageId if data doesn't carry a stable id for chunks.
        if (data && typeof data === "object" && typeof (data as any).id === "string") {
          messageId = (data as any).id;
        }

        if (!messageId) {
          continue;
        }

        if (!existsMessage(messageId)) {
          message = {
            id: messageId as string,
            threadId: (data as any)?.thread_id,
            agent: (data as any)?.agent,
            role: (data as any)?.role,
            content: "",
            contentChunks: [],
            reasoningContent: "",
            reasoningContentChunks: [],
            isStreaming: true,
            interruptFeedback,
          };
          appendMessage(message);
        }
      }

      message ??= getMessage(messageId as string);
      if (message) {
        const prevAgent = message.agent;
        // Fix stale agent: if the message was created from an event with an
        // unknown/missing agent but a later event for the same message ID
        // carries the correct agent name, propagate it.  This can happen in
        // flat LangGraph graphs where the first streaming chunk arrives with
        // an empty namespace tuple and missing langgraph_node metadata.
        if (
          eventAgent &&
          (eventAgent as string) !== "unknown" &&
          (!message.agent || (message.agent as string) === "unknown")
        ) {
          message = { ...message, agent: eventAgent };
        }
        message = mergeMessage(message, event);
        // When streaming finishes and agent is still unknown, try to infer
        // from content so PlanCard renders correctly.
        if (
          message.finishReason &&
          (!message.agent || (message.agent as string) === "unknown") &&
          message.content &&
          looksLikePlannerPayload(message.content)
        ) {
          message = { ...message, agent: "planner" };
        }
        // Retroactive research binding: when agent was corrected from
        // unknown/missing to an execution agent, appendMessage() at creation
        // time would have skipped the research binding.  Create it now.
        if (
          message.agent &&
          message.agent !== prevAgent &&
          isDeepResearchExecutionAgent(message.agent as string)
        ) {
          if (!getOngoingResearchId()) {
            appendResearch(message.id);
            openResearch(message.id);
          }
          appendResearchActivity(message);
          if (!deepResearchTaskStarted) {
            ensureDeepResearchTaskStarted();
          }
        }
        // Prefer planner's structured title as background-task title.
        if (message.agent === "planner") {
          const plannerTitle = extractPlannerTitle(message.content);
          if (plannerTitle) {
            latestDeepResearchTaskTitle = plannerTitle;
            // Do not start task during plan-only phase.
            // Only emit title update after task is truly started
            // (explicit start research or execution agents running).
            if (deepResearchTaskStarted && plannerTitle !== lastEmittedTaskTitle) {
              lastEmittedTaskTitle = plannerTitle;
              emitDeepResearchTaskEvent(DEEP_RESEARCH_TASK_START_EVENT, {
                taskId,
                title: plannerTitle,
                conversationId,
                status: "running",
              });
            }
          }
        }
        // Collect pending messages for update, instead of updating immediately.
        pendingUpdates.set(message.id, message);
        scheduleUpdate();
      }
    }
    if (options.abortSignal?.aborted) {
      abortedByUser = true;
      deepResearchTaskStatus = "cancelled";
      const cancelledResearchId = useStore.getState().ongoingResearchId;
      if (cancelledResearchId) {
        useStore.getState().setResearchCancelled(cancelledResearchId, true);
      }
      // Fire-and-forget server-side stop so LangGraph terminates cleanly.
      void stopResearch(getThreadId());
    }
    if (!receivedAnyEvent && !options.abortSignal?.aborted) {
      throw new Error("No response events received from deep-research stream.");
    }
    if (deepResearchTaskStatus === "error" && !options.abortSignal?.aborted) {
      throw new Error(
        deepResearchTaskError ||
        tr("deepResearchFailed", "Deep research failed."),
      );
    }
  } catch (error) {
    const aborted = options.abortSignal?.aborted || isAbortLikeError(error);
    abortedByUser = abortedByUser || aborted;
    deepResearchTaskStatus = aborted ? "cancelled" : "error";
    const rawError = error instanceof Error ? error.message : String(error);
    deepResearchTaskError = aborted
      ? rawError
      : pickDeepResearchErrorMessage(rawError);
    if (!aborted) {
      const normalizedError =
        error instanceof Error
          ? {
            name: error.name,
            message: error.message,
            stack: error.stack,
            cause: (error as Error & { cause?: unknown }).cause,
          }
          : error;
      deepResearchConsoleError("stream", "sendMessage caught error", {
        conversationId,
        taskId,
        interruptFeedback: interruptFeedback ?? null,
        rawError,
        error: normalizedError,
      });
      deepResearchDebugLog("stream", "sendMessage caught error", {
        rawError,
      });
    }
    if (!aborted && !errorMessageShown && !isStaleConversation()) {
      // Display the error as a chat message (like the normal AI chat page)
      // so the user sees a permanent, readable error in the conversation.
      const errorContent =
        deepResearchTaskError || getAlignedAIChatErrorFallback();
      const errorMsg: Message = {
        id: nanoid(),
        threadId: getThreadId(),
        role: "assistant",
        agent: "coordinator",
        content: errorContent,
        contentChunks: [errorContent],
        isStreaming: false,
      };
      appendMessage(errorMsg);
    }
    if (deepResearchTaskStatus === "cancelled" && !isStaleConversation()) {
      const cancelledResearchId = useStore.getState().ongoingResearchId;
      if (cancelledResearchId) {
        useStore.getState().setResearchCancelled(cancelledResearchId, true);
      }
    }
    // Update message status.
    // TODO: const isAborted = (error as Error).name === "AbortError";
    if (!isStaleConversation() && messageId != null) {
      const message = getMessage(messageId);
      if (message?.isStreaming) {
        message.isStreaming = false;
        useStore.getState().updateMessage(message);
      }
    }
    if (!isStaleConversation()) {
      useStore.getState().setOngoingResearch(null);
    }
  } finally {
    const stale = isStaleConversation();
    if (!stale) {
      setGenerationPhase("idle");
      setResponding(false);
      // Clear background job tracking now that stream processing is done
      useStore.getState().setBackgroundJob(null, 0);
    }
    if (!stale && abortedByUser) {
      // Ensure any unfinished streaming messages are closed in UI after cancel.
      const state = useStore.getState();
      const updated: Message[] = [];
      for (const id of state.messageIds) {
        const msg = state.messages.get(id);
        if (msg?.isStreaming) {
          updated.push({ ...msg, isStreaming: false });
        }
      }
      if (updated.length > 0) {
        useStore.getState().updateMessages(updated);
      }
      useStore.getState().setOngoingResearch(null);
    }
    if (!stale) {
      // Record response end time
      const endTime = Date.now();
      useStore.getState().setResponseTiming({
        startTime,
        endTime,
        durationMs: endTime - startTime,
      });
    }
    // Ensure all pending updates are processed.
    if (updateTimer) clearTimeout(updateTimer);
    if (!stale && pendingUpdates.size > 0) {
      useStore.getState().updateMessages(Array.from(pendingUpdates.values()));
    }
    if (!stale) {
      // Persist newly generated/updated assistant-side messages to shared conversation storage.
      const state = useStore.getState();
      const currentResearchId =
        state.ongoingResearchId ??
        state.researchIds.find((id) => !beforeResearchIds.has(id)) ??
        state.researchIds[state.researchIds.length - 1] ??
        null;
      if (currentResearchId) {
        useStore.getState().setResearchRunStatus(currentResearchId, deepResearchTaskStatus);
      }
      const newIds = state.messageIds.filter((id) => !beforeIds.has(id));
      const persistedIds = new Set<string>();
      for (const id of newIds) {
        const msg = state.messages.get(id);
        if (!msg || msg.role === "user") continue;
        await persistMessage(msg);
        persistedIds.add(id);
      }
      // Also persist last assistant message in case it was updated in-place.
      const lastId = state.messageIds[state.messageIds.length - 1];
      if (lastId && !persistedIds.has(lastId)) {
        const lastMsg = state.messages.get(lastId);
        if (lastMsg && lastMsg.role !== "user") {
          await persistMessage(lastMsg);
          persistedIds.add(lastId);
        }
      }
      // Re-persist plan and research root messages to ensure PATHLAB_RESEARCH_META is saved.
      // These messages are created before the streaming response and are NOT in newIds,
      // so they would otherwise never get re-persisted with up-to-date metadata.
      if (currentResearchId) {
        const planId = state.researchPlanIds.get(currentResearchId);
        if (planId && !persistedIds.has(planId)) {
          const planMsg = state.messages.get(planId);
          if (planMsg && planMsg.role !== "user") {
            await persistMessage(planMsg);
            persistedIds.add(planId);
          }
        }
        if (!persistedIds.has(currentResearchId)) {
          const rootMsg = state.messages.get(currentResearchId);
          if (rootMsg && rootMsg.role !== "user") {
            await persistMessage(rootMsg);
            persistedIds.add(currentResearchId);
          }
        }
      }
      // Check for empty assistant response and replace with error message
      // so the user sees feedback instead of a silently hidden message.
      {
        const finalState = useStore.getState();
        const lastMsgId = finalState.messageIds[finalState.messageIds.length - 1];
        if (lastMsgId && !abortedByUser) {
          const lastMsg = finalState.messages.get(lastMsgId);
          if (
            lastMsg &&
            lastMsg.role === "assistant" &&
            !(lastMsg.content ?? "").trim() &&
            lastMsg.agent !== "planner" &&
            lastMsg.agent !== "podcast" &&
            !finalState.researchIds.includes(lastMsgId)
          ) {
            const emptyResponseError = tr(
              "emptyResponse",
              "No response received. The backend may have encountered an issue. Please try again.",
            );
            const fixed: Message = {
              ...lastMsg,
              content: emptyResponseError,
              contentChunks: [emptyResponseError],
              isStreaming: false,
            };
            useStore.getState().updateMessage(fixed);
            await persistMessage(fixed);
          }
        }
      }
    }
    // Always emit task finish event to notify Electron task bar
    if (deepResearchTaskStarted) {
      emitDeepResearchTaskEvent(DEEP_RESEARCH_TASK_FINISH_EVENT, {
        taskId,
        title: latestDeepResearchTaskTitle,
        conversationId,
        status: deepResearchTaskStatus,
        error: deepResearchTaskError,
      });
    }
    if (!stale) {
      await persistRunUsageMetadata(deepResearchTaskStatus, deepResearchTaskError);
      // Flush one immediate local snapshot so a manual page refresh right after
      // response completion still has complete research card mappings.
      persistStoreState();
    } else if (localBackgroundJobId && conversationId) {
      // Conversation switched while streaming. Patch the conversation cache
      // with background job info so loadConversationFromBackend can reconnect
      // via reconnectToBackgroundJob when the user returns.
      try {
        const cache = loadConversationCache();
        const existing = cache[conversationId];
        if (existing) {
          existing.backgroundJobId = localBackgroundJobId;
          existing.backgroundJobCursor = localBackgroundJobCursor;
          // Preserve ongoingResearchId so reconnection logic triggers.
          // Use the last known value — it was set in the store before the wipe.
          if (!existing.ongoingResearchId && existing.researchIds?.length) {
            existing.ongoingResearchId =
              existing.researchIds[existing.researchIds.length - 1] ?? null;
          }
          existing.updatedAt = Date.now();
          saveConversationCache(trimConversationCache(cache));
          deepResearchDebugLog("stream", "patched conversation cache for background job reconnection", {
            conversationId,
            backgroundJobId: localBackgroundJobId,
            backgroundJobCursor: localBackgroundJobCursor,
            ongoingResearchId: existing.ongoingResearchId,
          });
        }
      } catch (e) {
        console.warn("[DeepResearch] Failed to patch conversation cache for stale stream:", e);
      }
    }
  }
}

/**
 * Resume polling a background job that was interrupted by navigation/tab close.
 * This is a streamlined version of sendMessage's event processing loop that
 * does not create user messages or call ensureResearchCardFromAcceptedPlan.
 */
export async function resumeBackgroundResearch(
  jobId: string,
  cursor: number,
  options: { abortSignal?: AbortSignal } = {},
) {
  const state = useStore.getState();
  if (state.responding) return; // Already processing

  const conversationId = state.conversationId;
  const isStaleConversation = () => useStore.getState().conversationId !== conversationId;

  setResponding(true);
  setGenerationPhase("streaming");

  let messageId: string | undefined;
  let abortedByUser = false;
  let errorMessageShown = false;
  let deepResearchTaskStatus: DeepResearchTaskStatus = "success";
  let deepResearchTaskError: string | undefined;
  const pendingUpdates = new Map<string, Message>();
  let updateTimer: NodeJS.Timeout | undefined;

  const scheduleUpdate = () => {
    if (updateTimer) return;
    updateTimer = setTimeout(() => {
      updateTimer = undefined;
      if (isStaleConversation()) {
        pendingUpdates.clear();
        return;
      }
      if (pendingUpdates.size > 0) {
        useStore.getState().updateMessages(Array.from(pendingUpdates.values()));
        pendingUpdates.clear();
      }
    }, 16);
  };

  try {
    const stream = resumeBackgroundJobStream(jobId, cursor, options);
    for await (const event of stream) {
      if (isStaleConversation()) {
        deepResearchDebugLog("stream", "resumeBackgroundResearch: conversation switched, discarding", {
          originalConversationId: conversationId,
          currentConversationId: useStore.getState().conversationId,
        });
        if (updateTimer) { clearTimeout(updateTimer); updateTimer = undefined; }
        pendingUpdates.clear();
        break;
      }
      const { type, data } = event;

      // Handle cursor tracking
      if (type === "cursor_update" && data && typeof data === "object" && "cursor" in data) {
        useStore.getState().setBackgroundJob(
          useStore.getState().backgroundJobId,
          (data as { cursor: number }).cursor,
        );
        continue;
      }

      // Handle citations
      if (type === "citations") {
        const ongoingResearchId = useStore.getState().ongoingResearchId;
        if (ongoingResearchId && (data as any).citations) {
          useStore.getState().setCitations(ongoingResearchId, (data as any).citations);
        }
        continue;
      }

      // Handle token_usage
      if (type === "token_usage") {
        const tokenData = (data as TokenUsageEvent["data"]);
        const usage: TokenUsageSummary = {
          totalPromptTokens: tokenData.total_prompt_tokens,
          totalCompletionTokens: tokenData.total_completion_tokens,
          totalTokens: tokenData.total_tokens,
          totalCalls: tokenData.total_calls,
          byAgent: tokenData.by_agent,
        };
        useStore.getState().setTokenUsage(usage);
        useStore.getState().accumulateSessionTokens(usage);
        continue;
      }

      // Handle error
      if (event.type === "error") {
        deepResearchTaskStatus = "error";
        const err = (event.data as any).error;
        const detail =
          event.data &&
          typeof event.data === "object" &&
          "detail" in event.data &&
          typeof (event.data as { detail?: unknown }).detail === "string"
            ? (event.data as { detail: string }).detail.trim()
            : "";
        const rawError =
          detail ||
          (typeof err === "string"
            ? err
            : tr("deepResearchError", "Deep research error"));
        deepResearchTaskError = pickDeepResearchErrorMessage(rawError);
        const errorMessage: Message = {
          id: nanoid(),
          threadId: getThreadId(),
          role: "assistant",
          agent: "coordinator",
          content: deepResearchTaskError,
          contentChunks: [deepResearchTaskError],
          isStreaming: false,
        };
        appendMessage(errorMessage);
        errorMessageShown = true;
        break;
      }

      if (event.type === "cancelled") {
        deepResearchTaskStatus = "cancelled";
        const cancelledResearchId = useStore.getState().ongoingResearchId;
        if (cancelledResearchId) {
          useStore.getState().setResearchCancelled(cancelledResearchId, true);
        }
        continue;
      }

      // Handle tool_call_result
      let message: Message | undefined;
      const eventAgent =
        data && typeof data === "object" && "agent" in data && typeof data.agent === "string"
          ? data.agent
          : undefined;

      if (type === "tool_call_result") {
        message = findMessageByToolCallId((data as any).tool_call_id);
        if (message) {
          messageId = message.id;
        } else {
          continue;
        }
      } else {
        if (data && typeof data === "object" && typeof (data as any).id === "string") {
          messageId = (data as any).id;
        }
        if (!messageId) {
          continue;
        }
        if (!existsMessage(messageId)) {
          message = {
            id: messageId as string,
            threadId: (data as any)?.thread_id,
            agent: (data as any)?.agent,
            role: (data as any)?.role,
            content: "",
            contentChunks: [],
            reasoningContent: "",
            reasoningContentChunks: [],
            isStreaming: true,
          };
          appendMessage(message);
        }
      }

      message ??= getMessage(messageId as string);
      if (message) {
        const prevAgent = message.agent;
        if (
          eventAgent &&
          (eventAgent as string) !== "unknown" &&
          (!message.agent || (message.agent as string) === "unknown")
        ) {
          message = { ...message, agent: eventAgent };
        }
        message = mergeMessage(message, event as ChatEvent);
        if (
          message.finishReason &&
          (!message.agent || (message.agent as string) === "unknown") &&
          message.content &&
          looksLikePlannerPayload(message.content)
        ) {
          message = { ...message, agent: "planner" };
        }
        if (
          message.agent &&
          message.agent !== prevAgent &&
          isDeepResearchExecutionAgent(message.agent as string)
        ) {
          if (!getOngoingResearchId()) {
            appendResearch(message.id);
            openResearch(message.id);
          }
          appendResearchActivity(message);
        }
        pendingUpdates.set(message.id, message);
        scheduleUpdate();
      }
    }
    if (options.abortSignal?.aborted) {
      abortedByUser = true;
      deepResearchTaskStatus = "cancelled";
      const cancelledResearchId = useStore.getState().ongoingResearchId;
      if (cancelledResearchId) {
        useStore.getState().setResearchCancelled(cancelledResearchId, true);
      }
      void stopResearch(getThreadId());
    }
    if (deepResearchTaskStatus === "error" && !options.abortSignal?.aborted) {
      throw new Error(
        deepResearchTaskError ||
        tr("deepResearchFailed", "Deep research failed."),
      );
    }
  } catch (error) {
    const aborted = options.abortSignal?.aborted || isAbortLikeError(error);
    abortedByUser = abortedByUser || aborted;
    deepResearchTaskStatus = aborted ? "cancelled" : "error";
    const rawError = error instanceof Error ? error.message : String(error);
    deepResearchTaskError = aborted
      ? rawError
      : pickDeepResearchErrorMessage(rawError);
    if (!aborted && !errorMessageShown && !isStaleConversation()) {
      const errorContent =
        deepResearchTaskError || getAlignedAIChatErrorFallback();
      const errorMsg: Message = {
        id: nanoid(),
        threadId: getThreadId(),
        role: "assistant",
        agent: "coordinator",
        content: errorContent,
        contentChunks: [errorContent],
        isStreaming: false,
      };
      appendMessage(errorMsg);
    }
    if (deepResearchTaskStatus === "cancelled" && !isStaleConversation()) {
      const cancelledResearchId = useStore.getState().ongoingResearchId;
      if (cancelledResearchId) {
        useStore.getState().setResearchCancelled(cancelledResearchId, true);
      }
    }
    if (!isStaleConversation() && messageId != null) {
      const message = getMessage(messageId);
      if (message?.isStreaming) {
        message.isStreaming = false;
        useStore.getState().updateMessage(message);
      }
    }
    if (!isStaleConversation()) {
      useStore.getState().setOngoingResearch(null);
    }
  } finally {
    const stale = isStaleConversation();
    if (!stale) {
      setGenerationPhase("idle");
      setResponding(false);
      useStore.getState().setBackgroundJob(null, 0);
      if (abortedByUser) {
        const state = useStore.getState();
        const updated: Message[] = [];
        for (const id of state.messageIds) {
          const msg = state.messages.get(id);
          if (msg?.isStreaming) {
            updated.push({ ...msg, isStreaming: false });
          }
        }
        if (updated.length > 0) {
          useStore.getState().updateMessages(updated);
        }
        useStore.getState().setOngoingResearch(null);
      }
      // Finalize pending updates
      if (updateTimer) clearTimeout(updateTimer);
      if (pendingUpdates.size > 0) {
        useStore.getState().updateMessages(Array.from(pendingUpdates.values()));
      }
      // Mark research run status
      const finalState = useStore.getState();
      const currentResearchId =
        finalState.ongoingResearchId ??
        finalState.researchIds[finalState.researchIds.length - 1] ??
        null;
      if (currentResearchId) {
        useStore.getState().setResearchRunStatus(currentResearchId, deepResearchTaskStatus);
      }
      persistStoreState();
    } else {
      // Clean up timers but don't touch the store
      if (updateTimer) clearTimeout(updateTimer);
      pendingUpdates.clear();
    }
  }
}

/**
 * Check background job status and reconnect if it's still running or has
 * unconsumed events. Called from loadConversationFromBackend when a persisted
 * backgroundJobId is found.
 */
async function reconnectToBackgroundJob(jobId: string, cursor: number) {
  try {
    const status = await getBackgroundJobStatus(jobId);
    if (status.status === "interrupted") {
      // Job was interrupted by server restart — notify user
      const rid = useStore.getState().ongoingResearchId;
      if (rid) useStore.getState().setResearchRunStatus(rid, "error");
      useStore.getState().setOngoingResearch(null);
      useStore.getState().setBackgroundJob(null, 0);
      // Add an assistant message to inform the user
      const interruptContent = tr(
        "researchInterrupted",
        "Research was interrupted by a server restart. Your progress has been saved. Please start a new research to continue.",
      );
      const interruptMsg: Message = {
        id: nanoid(),
        threadId: getThreadId(),
        role: "assistant",
        content: interruptContent,
        contentChunks: [interruptContent],
      };
      useStore.getState().appendMessage(interruptMsg);
      persistStoreState();
      return;
    }
    if (status.status === "failed") {
      // Job failed — mark research as error
      const rid = useStore.getState().ongoingResearchId;
      if (rid) useStore.getState().setResearchRunStatus(rid, "error");
      useStore.getState().setOngoingResearch(null);
      useStore.getState().setBackgroundJob(null, 0);
      persistStoreState();
      return;
    }
    // Job is still running or completed with unconsumed events — resume polling
    await resumeBackgroundResearch(jobId, cursor);
  } catch {
    // Job not found (404) — server was likely restarted
    const rid = useStore.getState().ongoingResearchId;
    if (rid) useStore.getState().setResearchRunStatus(rid, "error");
    useStore.getState().setOngoingResearch(null);
    useStore.getState().setBackgroundJob(null, 0);
    persistStoreState();
  }
}

function setResponding(value: boolean) {
  useStore.setState({ responding: value });
}

function setGenerationPhase(phase: GenerationPhase) {
  useStore.setState({ generationPhase: phase });
}

function existsMessage(id: string) {
  return useStore.getState().messageIds.includes(id);
}

function getMessage(id: string) {
  return useStore.getState().messages.get(id);
}

function findMessageByToolCallId(toolCallId: string) {
  return Array.from(useStore.getState().messages.values())
    .reverse()
    .find((message) => {
      if (message.toolCalls) {
        return message.toolCalls.some((toolCall) => toolCall.id === toolCallId);
      }
      return false;
    });
}

function appendMessage(message: Message) {
  if (
    message.agent === "coder" ||
    message.agent === "reporter" ||
    message.agent === "researcher" ||
    message.agent === "analyst"
  ) {
    if (!getOngoingResearchId()) {
      const id = message.id;
      appendResearch(id);
      openResearch(id);
    }
    appendResearchActivity(message);
  }
  useStore.getState().appendMessage(message);
}

// Track which research IDs have already received the post-report guidance message.
// This prevents duplicates when updateMessage is called multiple times for the same message.
const injectedPostReportGuidanceResearchIds = new Set<string>();

function buildPostReportGuidanceContent(): string {
  const heading = tr(
    "postReportGuidanceHeading",
    "报告已生成！接下来您希望做什么？",
  );
  const opt1 = tr("postReportOptionTraining", "使用 AI 训练深度学习模型");
  const opt2 = tr("postReportOptionAnalysis", "分析相关病理图像数据");
  const opt3 = tr("postReportOptionExport", "导出报告（PDF / Markdown）");
  const opt4 = tr("postReportOptionNewResearch", "发起新的研究课题");
  const opt5 = tr("postReportOptionAskQuestion", "针对报告内容提问");
  return `${heading}\n\n[OPTIONS]\n- ${opt1}\n- ${opt2}\n- ${opt3}\n- ${opt4}\n- ${opt5}\n[/OPTIONS]`;
}

function updateMessage(message: Message) {
  const ongoingResearchId = getOngoingResearchId();
  if (
    ongoingResearchId &&
    message.agent === "reporter" &&
    !message.isStreaming
  ) {
    useStore.getState().setOngoingResearch(null);

    // Inject post-report guidance message only once per research run.
    if (!injectedPostReportGuidanceResearchIds.has(ongoingResearchId)) {
      injectedPostReportGuidanceResearchIds.add(ongoingResearchId);
      const guidanceContent = buildPostReportGuidanceContent();
      const guidanceMessage: Message = {
        id: nanoid(),
        threadId: message.threadId ?? getThreadId(),
        role: "assistant",
        agent: "coordinator",
        content: guidanceContent,
        contentChunks: [guidanceContent],
        isStreaming: false,
      };
      // Use a microtask to ensure the reporter message update is committed first.
      Promise.resolve().then(() => {
        appendMessage(guidanceMessage);
        void persistMessage(guidanceMessage);
      });
    }
  }
  useStore.getState().updateMessage(message);
}

function getOngoingResearchId() {
  return useStore.getState().ongoingResearchId;
}

function appendResearch(researchId: string) {
  let planMessage: Message | undefined;
  let userQuery: string | undefined;
  const reversedMessageIds = [...useStore.getState().messageIds].reverse();
  for (const messageId of reversedMessageIds) {
    const message = getMessage(messageId);
    if (
      !planMessage &&
      message?.role === "assistant" &&
      // Use both agent name AND content detection to find the planner message.
      // The agent name may still be "unknown" when a researcher message triggers
      // appendResearch before the planner's agent was corrected.
      (message.agent === "planner" || looksLikePlannerPayload(message.content ?? ""))
    ) {
      planMessage = message;
    }
    if (!userQuery && message?.role === "user") {
      userQuery = message.content;
    }
    if (planMessage && userQuery) {
      break;
    }
  }
  const messageIds = [researchId];
  if (planMessage?.id) {
    messageIds.unshift(planMessage.id);
  }
  const nextResearchPlanIds = new Map(useStore.getState().researchPlanIds);
  if (planMessage?.id) {
    nextResearchPlanIds.set(researchId, planMessage.id);
  }
  useStore.setState({
    ongoingResearchId: researchId,
    researchIds: useStore.getState().researchIds.includes(researchId)
      ? useStore.getState().researchIds
      : [...useStore.getState().researchIds, researchId],
    researchPlanIds: nextResearchPlanIds,
    researchActivityIds: new Map(useStore.getState().researchActivityIds).set(
      researchId,
      messageIds,
    ),
    researchQueries: new Map(useStore.getState().researchQueries).set(
      researchId,
      userQuery ?? "",
    ),
  });
  useStore.getState().setResearchCancelled(researchId, false);
  useStore.getState().setResearchRunStatus(researchId, "running");
  deepResearchDebugLog("researchMapping", "appendResearch", {
    researchId,
    planMessageId: planMessage?.id ?? null,
    userQueryLength: (userQuery ?? "").length,
    researchCount: useStore.getState().researchIds.length,
  });

  // Persist plan<->research binding as soon as research starts.
  // Without this, a quick page refresh may reload from backend history that
  // still lacks metadata, causing research cards to disappear intermittently.
  if (planMessage) {
    void persistMessage(planMessage);
  }
}

function ensureResearchCardFromAcceptedPlan(): string | null {
  const state = useStore.getState();
  if (state.ongoingResearchId) {
    return state.ongoingResearchId;
  }

  const reversedMessageIds = [...state.messageIds].reverse();
  const latestPlanMessage = reversedMessageIds
    .map((id) => state.messages.get(id))
    .find(
      (msg) =>
        msg?.role === "assistant" &&
        (msg.agent === "planner" || looksLikePlannerPayload(msg.content ?? "")),
    );

  if (!latestPlanMessage) {
    return null;
  }

  const existingResearchId = Array.from(state.researchPlanIds.entries()).find(
    ([, planId]) => planId === latestPlanMessage.id,
  )?.[0];
  if (existingResearchId) {
    useStore.getState().setOngoingResearch(existingResearchId);
    openResearch(existingResearchId);
    return existingResearchId;
  }

  const researchRootId = nanoid();
  const placeholderRoot: Message = {
    id: researchRootId,
    threadId: getThreadId(),
    role: "assistant",
    agent: "researcher",
    content: "",
    contentChunks: [],
    isStreaming: false,
  };
  useStore.getState().appendMessage(placeholderRoot);
  appendResearch(researchRootId);
  openResearch(researchRootId);
  void persistMessage(placeholderRoot);
  return researchRootId;
}

function appendResearchActivity(message: Message) {
  const researchId = getOngoingResearchId();
  if (researchId) {
    const researchActivityIds = useStore.getState().researchActivityIds;
    const current = researchActivityIds.get(researchId) ?? [];
    if (!current.includes(message.id)) {
      useStore.setState({
        researchActivityIds: new Map(researchActivityIds).set(researchId, [
          ...current,
          message.id,
        ]),
      });
    }
    if (message.agent === "reporter") {
      useStore.setState({
        researchReportIds: new Map(useStore.getState().researchReportIds).set(
          researchId,
          message.id,
        ),
      });
      useStore.getState().setResearchCancelled(researchId, false);
    }
    deepResearchDebugLog("researchMapping", "appendResearchActivity", {
      researchId,
      messageId: message.id,
      agent: message.agent,
      reportBound: message.agent === "reporter",
      activityCount: useStore.getState().researchActivityIds.get(researchId)?.length ?? 0,
    });
  }
}

export function openResearch(researchId: string | null) {
  useStore.getState().openResearch(researchId);
}

export function closeResearch() {
  useStore.getState().closeResearch();
}

export function resetDeepResearchSession() {
  // Flush any pending persist before clearing so the cache retains the
  // latest stream data for the conversation being left.
  if (persistTimer) {
    clearTimeout(persistTimer);
    persistTimer = null;
  }
  persistStoreState();

  useStore.setState({
    responding: false,
    generationPhase: "idle",
    threadId: nanoid(),
    conversationId: null,
    messageIds: [],
    messages: new Map(),
    messageBackendIds: new Map(),
    researchIds: [],
    researchPlanIds: new Map(),
    researchReportIds: new Map(),
    researchActivityIds: new Map(),
    researchQueries: new Map(),
    researchCitations: new Map(),
    researchRunStatus: new Map(),
    restartPlanShownResearchIds: new Set(),
    planActionLocks: new Map(),
    cancelledResearchIds: new Set(),
    ongoingResearchId: null,
    openResearchId: null,
    tokenUsage: null,
    sessionTokenUsage: { totalTokens: 0, totalCalls: 0, totalPromptTokens: 0, totalCompletionTokens: 0 },
    responseTiming: null,
  });
}

export async function listenToPodcast(researchId: string) {
  const threadId = getThreadId();
  const planMessageId = useStore.getState().researchPlanIds.get(researchId);
  const reportMessageId = useStore.getState().researchReportIds.get(researchId);
  if (planMessageId && reportMessageId) {
    const planMessage = getMessage(planMessageId)!;
    const title = parseJSON(planMessage.content, { title: "Untitled" }).title;
    const reportMessage = getMessage(reportMessageId);
    if (reportMessage?.content) {
      appendMessage({
        id: nanoid(),
        threadId,
        role: "user",
        content: "Please generate a podcast for the above research.",
        contentChunks: [],
      });
      const podCastMessageId = nanoid();
      const podcastObject = { title, researchId };
      const podcastMessage: Message = {
        id: podCastMessageId,
        threadId,
        role: "assistant",
        agent: "podcast",
        content: JSON.stringify(podcastObject),
        contentChunks: [],
        reasoningContent: "",
        reasoningContentChunks: [],
        isStreaming: true,
      };
      appendMessage(podcastMessage);
      // Generating podcast...
      let audioUrl: string | undefined;
      try {
        audioUrl = await generatePodcast(reportMessage.content);
      } catch (e) {
        console.error(e);
        useStore.setState((state) => ({
          messages: new Map(useStore.getState().messages).set(
            podCastMessageId,
            {
              ...state.messages.get(podCastMessageId)!,
              content: JSON.stringify({
                ...podcastObject,
                error: e instanceof Error ? e.message : "Unknown error",
              }),
              isStreaming: false,
            },
          ),
        }));
        toast(
          tr(
            "errorGeneratingPodcast",
            "Error when generating podcast. Please try again.",
          ),
        );
        return;
      }
      useStore.setState((state) => ({
        messages: new Map(useStore.getState().messages).set(podCastMessageId, {
          ...state.messages.get(podCastMessageId)!,
          content: JSON.stringify({ ...podcastObject, audioUrl }),
          isStreaming: false,
        }),
      }));
    }
  }
}

export function getDeepResearchDebugSnapshot() {
  const state = useStore.getState();
  return {
    threadId: state.threadId,
    conversationId: state.conversationId,
    messageCount: state.messageIds.length,
    mappedMessageCount: state.messages.size,
    researchCount: state.researchIds.length,
    researchIds: state.researchIds.slice(-5),
    planBindings: Array.from(state.researchPlanIds.entries()).slice(-5),
    reportBindings: Array.from(state.researchReportIds.entries()).slice(-5),
    ongoingResearchId: state.ongoingResearchId,
    openResearchId: state.openResearchId,
  };
}

export function debugDeepResearchStore(message: string, payload?: unknown) {
  deepResearchDebugLog("store", message, payload);
}

export function flushDeepResearchPersistNow() {
  persistStoreState();
}

/**
 * Re-persist a message to backend so its PATHLAB_RESEARCH_META block is
 * updated (e.g. after planActionLock changes).
 */
export function rePersistMessageToBackend(messageId: string) {
  const msg = useStore.getState().messages.get(messageId);
  if (msg) {
    void persistMessage(msg);
  }
}

export function useResearchMessage(researchId: string) {
  return useStore(
    useShallow((state) => {
      const messageId = state.researchPlanIds.get(researchId);
      return messageId ? state.messages.get(messageId) : undefined;
    }),
  );
}

export function getResearchQuery(researchId: string): string {
  return useStore.getState().researchQueries.get(researchId) ?? "";
}

export function useMessage(messageId: string | null | undefined) {
  return useStore(
    useShallow((state) =>
      messageId ? state.messages.get(messageId) : undefined,
    ),
  );
}

export function useMessageIds() {
  return useStore(useShallow((state) => state.messageIds));
}

export function useRenderableMessageIds() {
  return useStore(
    useShallow((state) => {
      // Pre-compute O(1) lookup indexes to avoid O(n²) Array.from().some/includes
      // on every message during filtering.
      const researchRootSet = new Set(state.researchIds);
      const planBoundSet = new Set<string>();
      const boundToResearchSet = new Set<string>();

      for (const [rid, planId] of state.researchPlanIds) {
        planBoundSet.add(planId);
        if (researchRootSet.has(rid)) boundToResearchSet.add(planId);
      }
      for (const [rid, reportId] of state.researchReportIds) {
        if (researchRootSet.has(rid)) boundToResearchSet.add(reportId);
      }
      for (const [rid, ids] of state.researchActivityIds) {
        if (researchRootSet.has(rid)) {
          for (const id of ids) boundToResearchSet.add(id);
        }
      }
      // Research roots are themselves bound
      for (const rid of state.researchIds) boundToResearchSet.add(rid);

      return state.messageIds.filter((messageId) => {
        const message = state.messages.get(messageId);
        if (!message) return false;

        const isPlanner = message.agent === "planner";
        const isPodcast = message.agent === "podcast";
        const isStartOfResearch = researchRootSet.has(messageId);
        const isPlanBound = !isPlanner && planBoundSet.has(messageId);

        if (isPlanner || isPodcast || isStartOfResearch || isPlanBound) {
          return true;
        }

        const isBoundToResearch = boundToResearchSet.has(message.id);

        if (
          message.agent === "reporter" ||
          message.agent === "researcher" ||
          message.agent === "analyst" ||
          message.agent === "coder"
        ) {
          return isBoundToResearch ? false : !!message.content;
        }

        if (
          message.role === "user" ||
          message.role === "assistant" ||
          message.agent === "coordinator"
        ) {
          return !!message.content;
        }

        return false;
      });
    }),
  );
}

export function useLastInterruptMessage() {
  return useStore(
    useShallow((state) => {
      if (state.messageIds.length >= 2) {
        const lastMessage = state.messages.get(
          state.messageIds[state.messageIds.length - 1]!,
        );
        return lastMessage?.finishReason === "interrupt" ? lastMessage : null;
      }
      return null;
    }),
  );
}

export function useLastFeedbackMessageId() {
  const waitingForFeedbackMessageId = useStore(
    useShallow((state) => {
      if (state.messageIds.length >= 2) {
        const lastMessage = state.messages.get(
          state.messageIds[state.messageIds.length - 1]!,
        );
        if (lastMessage && lastMessage.finishReason === "interrupt") {
          return state.messageIds[state.messageIds.length - 2];
        }
      }
      return null;
    }),
  );
  return waitingForFeedbackMessageId;
}

export function useToolCalls() {
  return useStore(
    useShallow((state) => {
      return state.messageIds
        ?.map((id) => getMessage(id)?.toolCalls)
        .filter((toolCalls) => toolCalls != null)
        .flat();
    }),
  );
}

export function useCitations(researchId: string | null | undefined) {
  return useStore(
    useShallow((state) =>
      researchId ? state.researchCitations.get(researchId) ?? [] : []
    ),
  );
}

export function getCitations(researchId: string): Citation[] {
  return useStore.getState().researchCitations.get(researchId) ?? [];
}

export function useTokenUsage() {
  return useStore(useShallow((state) => state.tokenUsage));
}

export function useSessionTokenUsage() {
  return useStore(useShallow((state) => state.sessionTokenUsage));
}

export function useResponseTiming() {
  return useStore(useShallow((state) => state.responseTiming));
}

export function useGenerationPhase() {
  return useStore(useShallow((state) => state.generationPhase));
}

// Expose debug utilities on window for DevTools console access
if (typeof window !== "undefined") {
  (window as any).__DR_DEBUG_SNAPSHOT = getDeepResearchDebugSnapshot;
  (window as any).__DR_EXPORT_LOGS = exportLogsAsText;
  (window as any).__DR_DOWNLOAD_LOGS = downloadLogs;
  (window as any).__DR_LOG_BUFFER = getLogBuffer;
  (window as any).__DR_CLEAR_LOGS = clearLogBuffer;
}
