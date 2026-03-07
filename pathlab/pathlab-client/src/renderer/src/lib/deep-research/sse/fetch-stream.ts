import { type StreamEvent } from "./StreamEvent";
import i18n from "../../../i18n";

const MAX_BUFFER_SIZE = 1024 * 1024; // 1MB default

function tr(
  key: string,
  defaultValue: string,
  params?: Record<string, string | number>,
): string {
  return i18n.t(`chat.research.${key}`, { ...params, defaultValue }) as string;
}

function isNetworkLikeError(error: unknown): boolean {
  const msg = error instanceof Error ? error.message.toLowerCase() : String(error).toLowerCase();
  return (
    (error instanceof TypeError && msg.includes("fetch")) ||
    msg.includes("failed to fetch") ||
    msg.includes("network request failed") ||
    msg.includes("network error")
  );
}

async function buildHttpError(url: string, response: Response): Promise<Error> {
  let detail = "";
  try {
    const text = await response.text();
    if (text) {
      try {
        const parsed = JSON.parse(text) as { detail?: unknown; message?: unknown; error?: unknown };
        detail =
          (typeof parsed.detail === "string" && parsed.detail) ||
          (typeof parsed.message === "string" && parsed.message) ||
          (typeof parsed.error === "string" && parsed.error) ||
          text;
      } catch {
        detail = text;
      }
    }
  } catch {
    // ignore body parse errors
  }

  const status = response.status;
  if (status === 503 || status === 502 || status === 504) {
    return new Error(tr(
      "aiServiceUnavailable",
      "AI service is temporarily unavailable ({status}). Please retry in a moment and check backend model status.",
      { status },
    ));
  }
  if (status === 401 || status === 403) {
    return new Error(tr(
      "authFailed",
      "Authentication failed ({status}). Please re-login and check your API/auth settings.",
      { status },
    ));
  }
  return detail
    ? new Error(
      tr(
        "requestFailedWithDetail",
        "Request failed ({status}): {detail}",
        { status, detail },
      ),
    )
    : new Error(
      tr("requestFailed", "Request failed with status {status}", { status }),
    );
}

export async function* fetchStream(
  url: string,
  init: RequestInit,
): AsyncIterable<StreamEvent> {
  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
      },
      ...init,
    });
  } catch (error) {
    if (isNetworkLikeError(error)) {
      throw new Error(tr(
        "networkUnavailable",
        "Cannot connect to server. Please check your network connection and ensure the backend is running.",
      ));
    }
    throw error;
  }
  if (response.status !== 200) {
    throw await buildHttpError(url, response);
  }
  const reader = response.body
    ?.pipeThrough(new TextDecoderStream())
    .getReader();
  if (!reader) {
    throw new Error("Response body is not readable");
  }

  try {
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        if (buffer.trim()) {
          const event = parseEvent(buffer.trim());
          if (event) {
            yield event;
          }
        }
        break;
      }

      buffer += value;

      if (buffer.length > MAX_BUFFER_SIZE) {
        throw new Error(
          `Buffer overflow - received ${(buffer.length / 1024 / 1024).toFixed(2)}MB of data without proper event boundaries.`
        );
      }

      let newlineIndex;
      while ((newlineIndex = buffer.indexOf("\n\n")) !== -1) {
        const chunk = buffer.slice(0, newlineIndex);
        buffer = buffer.slice(newlineIndex + 2);

        if (chunk.trim()) {
          const event = parseEvent(chunk);
          if (event) {
            yield event;
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

function parseEvent(chunk: string) {
  let resultEvent = "message";
  let resultData: string | null = null;
  for (const line of chunk.split("\n")) {
    const pos = line.indexOf(": ");
    if (pos === -1) {
      continue;
    }
    const key = line.slice(0, pos);
    const value = line.slice(pos + 2);
    if (key === "event") {
      resultEvent = value;
    } else if (key === "data") {
      resultData = value;
    }
  }
  if (resultEvent === "message" && resultData === null) {
    return undefined;
  }
  return {
    event: resultEvent,
    data: resultData,
  } as StreamEvent;
}
