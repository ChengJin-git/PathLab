import type { ChatActivity } from "../../api/chat";

export type ActivityPhase = "prepare" | "search" | "read" | "review" | "respond" | "file" | "research" | "compute" | "plan";
export interface ActivityStep {
  id: string;
  phase: ActivityPhase;
  status: "running" | "completed" | "failed" | "interrupted";
  subject: string;
}

const phases = new Map<ChatActivity["operation"], ActivityPhase>([
  ["search", "search"], ["read", "read"],
  ["summarize", "review"], ["respond", "respond"],
  ["write_file", "file"], ["save_file", "file"],
  ["start_research", "research"], ["run_job", "compute"], ["plan", "plan"],
]);

/** Bounded public actions; system preparation and tool dispatch are not steps. */
export function summarizeChatActivity(items: ChatActivity[], running: boolean) {
  const groups = new Map<string, ActivityStep>();
  let current: ActivityStep | undefined;
  let failed = false;
  let interrupted = false;
  for (const item of items.slice(-12)) {
    const phase = phases.get(item.operation);
    const status = item.status === "completed" || item.status === "failed"
      ? item.status
      : item.status === "running" && running ? "running" : "interrupted";
    failed ||= status === "failed";
    interrupted ||= status === "interrupted";
    if (!phase) continue;
    const subject = ["search", "read", "review", "file"].includes(phase) && typeof item.subject === "string"
      ? item.subject.slice(0, 160) : "";
    const key = `${phase}:${subject}`;
    const step: ActivityStep = { id: key, phase, status, subject };
    if (status === "running") current = step;
    const group = groups.get(key);
    if (!group) groups.set(key, step);
    else {
      // Preserve issues when a later operation in the same phase succeeds.
      if (status === "failed" || group.status === "failed") group.status = "failed";
      else if (status === "running" || group.status === "running") group.status = "running";
      else if (status === "interrupted" || group.status === "interrupted") group.status = "interrupted";
    }
  }
  const steps = [...groups.values()];
  if (!steps.length && items.length) {
    const step: ActivityStep = { id: "prepare", phase: "prepare", subject: "",
      status: failed ? "failed" : running ? "running" : interrupted ? "interrupted" : "completed" };
    steps.push(step);
    if (step.status === "running") current = step;
  }
  return { steps, current, failed, interrupted };
}
