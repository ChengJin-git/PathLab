import type { AutoResearchEvent } from "../../types/autoresearch";
import { isPublicResearchMessage } from "./researchState";

export interface ResearchMessage {
  id?: string;
  type?: string;
  text?: string;
  metadata?: { pathlabInternal?: boolean };
  content?: {
    id?: string;
    type: string;
    text?: string;
    action?: string;
    status?: string;
    description?: string;
    language?: string;
  }[];
}

export function activityKey(event: AutoResearchEvent): string {
  const message = event.message as unknown as ResearchMessage | undefined;
  if (event.kind === "message" && message?.id) return `message:${message.id}`;
  if (event.kind === "command" && event.command_id)
    return `command:${event.command_id}`;
  if (event.kind === "job" && event.job_id) return `job:${event.job_id}`;
  if (event.kind === "native_work") return "native_work";
  return `event:${event.seq}`;
}

export function messageText(event: AutoResearchEvent): string {
  const message = event.message as unknown as ResearchMessage | undefined;
  return (
    message?.text ||
    message?.content
      ?.filter((part) => part.type === "text")
      .map((part) => part.text || "")
      .join("\n") ||
    ""
  );
}

export function isTimelineEvent(event: AutoResearchEvent): boolean {
  return [
    "message",
    "command",
    "job",
    "dataset",
    "literature",
    "error",
    "report",
    "study",
    "research_decision",
    "native_work",
  ].includes(event.kind);
}

/** Snapshot updates replace the same logical item without moving or erasing it. */
export function mergeResearchEvents(
  ...batches: AutoResearchEvent[][]
): AutoResearchEvent[] {
  const items = new Map<string, AutoResearchEvent>();
  for (const event of batches.flat()) {
    if (["heartbeat", "internal"].includes(event.kind)) continue;
    if (
      event.kind === "message" &&
      !isPublicResearchMessage(event.message as unknown as ResearchMessage)
    )
      continue;
    const key = activityKey(event);
    const old = items.get(key);
    const first = Math.min(
      Number(old?.activity_seq ?? old?.seq ?? Infinity),
      Number(event.activity_seq ?? event.seq ?? Infinity),
    );
    if (old && (event.seq || 0) < (old.seq || 0)) {
      items.set(key, { ...event, ...old, activity_seq: first });
      continue;
    }
    const merged: AutoResearchEvent = { ...old, ...event, activity_seq: first };
    if (old && event.kind === "command") {
      merged.text = event.text || old.text;
      merged.action = event.action || old.action;
    }
    items.set(key, merged);
  }
  return [...items.values()].sort(
    (a, b) => Number(a.activity_seq) - Number(b.activity_seq),
  );
}

export type TimelineEntry =
  | {
      key: string;
      type: "message" | "command" | "summary";
      event: AutoResearchEvent;
    }
  | { key: string; type: "process"; events: AutoResearchEvent[] };

export function researchTimeline(events: AutoResearchEvent[]): TimelineEntry[] {
  const result: TimelineEntry[] = [];
  const process = (event: AutoResearchEvent) => {
    const last = result.at(-1);
    if (last?.type === "process") last.events.push(event);
    else
      result.push({
        key: `process:${activityKey(event)}`,
        type: "process",
        events: [event],
      });
  };
  for (const event of mergeResearchEvents(events)) {
    const key = activityKey(event);
    if (event.kind === "message") {
      if (messageText(event).trim())
        result.push({ key, type: "message", event });
      const message = event.message as unknown as ResearchMessage;
      if (message.content?.some((part) => part.type === "activity")) process(event);
    } else if (
      event.kind === "command" &&
      event.action === "message" &&
      event.text
    ) {
      result.push({ key, type: "command", event });
    } else if (["report", "study", "research_decision"].includes(event.kind)) {
      result.push({ key, type: "summary", event });
    } else if (
      ["job", "dataset", "literature", "error"].includes(
        event.kind,
      )
    )
      process(event);
  }
  return result;
}
