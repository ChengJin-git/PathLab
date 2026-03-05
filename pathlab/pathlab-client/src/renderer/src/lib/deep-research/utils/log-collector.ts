// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

export interface LogEntry {
  timestamp: string; // ISO 8601
  level: "debug" | "info" | "warn" | "error";
  scope: string;
  message: string;
  payload?: unknown;
}

const MAX_ENTRIES = 2000;
const buffer: LogEntry[] = [];

// --- File persistence via Electron IPC ---
const FLUSH_INTERVAL_MS = 3000;
let flushCursor = 0; // index of next entry to flush
let flushTimer: ReturnType<typeof setInterval> | undefined;

function getDrLogsApi(): { append: (text: string) => Promise<boolean> } | undefined {
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return (window as any).api?.drLogs as
      | { append: (text: string) => Promise<boolean> }
      | undefined;
  } catch {
    return undefined;
  }
}

function formatEntry(e: LogEntry): string {
  const payloadStr =
    e.payload !== undefined ? ` | ${JSON.stringify(e.payload)}` : "";
  return `[${e.timestamp}] [${e.level.toUpperCase()}] [${e.scope}] ${e.message}${payloadStr}`;
}

async function flushToFile(): Promise<void> {
  if (flushCursor >= buffer.length) return;
  const api = getDrLogsApi();
  if (!api) return;
  const lines = buffer
    .slice(flushCursor)
    .map(formatEntry)
    .join("\n") + "\n";
  flushCursor = buffer.length;
  try {
    await api.append(lines);
  } catch {
    // Silently ignore – IPC may not be available (e.g. pure browser mode)
  }
}

function ensureFlushTimer(): void {
  if (flushTimer !== undefined) return;
  flushTimer = setInterval(() => void flushToFile(), FLUSH_INTERVAL_MS);
}

// --- Public API ---

export function pushLog(
  level: LogEntry["level"],
  scope: string,
  message: string,
  payload?: unknown,
): void {
  const entry: LogEntry = {
    timestamp: new Date().toISOString(),
    level,
    scope,
    message,
    ...(payload !== undefined && { payload }),
  };
  buffer.push(entry);
  if (buffer.length > MAX_ENTRIES) {
    buffer.shift();
    if (flushCursor > 0) flushCursor--;
  }
  ensureFlushTimer();
}

export function getLogBuffer(): readonly LogEntry[] {
  return buffer;
}

export function exportLogsAsText(): string {
  return buffer.map(formatEntry).join("\n");
}

export function downloadLogs(): void {
  const text = exportLogsAsText();
  const blob = new Blob([text], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `deep-research-logs-${new Date().toISOString().replace(/[:.]/g, "-")}.txt`;
  a.click();
  URL.revokeObjectURL(url);
}

export function clearLogBuffer(): void {
  buffer.length = 0;
  flushCursor = 0;
}
