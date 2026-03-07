import { bestEffortParseSilently } from "./json";

export type ToolResultStatus =
  | "success"
  | "no_results"
  | "no_useful_information"
  | "error";

type ToolResultEnvelope = {
  meta?: {
    schema?: string;
    tool?: string;
    status?: ToolResultStatus;
    reason?: string;
    summary?: string;
    valid_for_research?: boolean;
  };
  data?: Record<string, unknown>;
};

export function safeParseToolResult(raw?: string): unknown {
  if (!raw) return undefined;
  try {
    return JSON.parse(raw);
  } catch {
    try {
      return bestEffortParseSilently(raw);
    } catch {
      return undefined;
    }
  }
}

export function asToolResultEnvelope(raw?: string): ToolResultEnvelope | undefined {
  const parsed = safeParseToolResult(raw);
  if (
    parsed &&
    typeof parsed === "object" &&
    !Array.isArray(parsed) &&
    (parsed as ToolResultEnvelope).meta?.schema === "pathlab.tool_result.v1"
  ) {
    return parsed as ToolResultEnvelope;
  }
  return undefined;
}

export function getToolResultStatus(raw?: string, fallback?: "success" | "error") {
  return asToolResultEnvelope(raw)?.meta?.status ?? fallback;
}

export function getToolResultReason(raw?: string) {
  return asToolResultEnvelope(raw)?.meta?.reason;
}

export function getToolResultSummary(raw?: string) {
  return asToolResultEnvelope(raw)?.meta?.summary;
}

export function extractToolResultItems<T = Record<string, unknown>>(raw?: string): T[] {
  const envelope = asToolResultEnvelope(raw);
  const data = envelope?.data;
  if (Array.isArray(data?.results)) return data.results as T[];
  if (Array.isArray(data?.items)) return data.items as T[];
  if (Array.isArray(data?.documents)) return data.documents as T[];

  const parsed = safeParseToolResult(raw);
  if (Array.isArray(parsed)) return parsed as T[];
  if (parsed && typeof parsed === "object") {
    const record = parsed as Record<string, unknown>;
    if (Array.isArray(record.results)) return record.results as T[];
    if (Array.isArray(record.items)) return record.items as T[];
  }
  return [];
}

export function extractToolResultData<T = Record<string, unknown>>(raw?: string): T | undefined {
  const envelope = asToolResultEnvelope(raw);
  if (envelope?.data) return envelope.data as T;
  const parsed = safeParseToolResult(raw);
  if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
    return parsed as T;
  }
  return undefined;
}
