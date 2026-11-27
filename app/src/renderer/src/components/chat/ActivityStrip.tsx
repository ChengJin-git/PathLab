import { memo, useId, useMemo, useState } from "react";
import { Check, ChevronDown, CircleAlert, CircleDashed, Loader2, Sparkles } from "lucide-react";
import type { ChatActivity } from "../../api/chat";
import { Button } from "../ui/button";
import { summarizeChatActivity, type ActivityStep } from "./chatActivity";
import { useWorkbenchText } from "./workbenchText";

export default memo(function ActivityStrip({
  items,
  running = false,
}: {
  items: ChatActivity[];
  running?: boolean;
}) {
  const text = useWorkbenchText();
  const [expanded, setExpanded] = useState(false);
  const panelId = useId();
  const { steps, current, failed, interrupted } = useMemo(
    () => summarizeChatActivity(items, running), [items, running],
  );
  if (!steps.length) return null;
  const describe = (step: ActivityStep) => {
    if (step.subject && ["search", "read", "review", "file"].includes(step.phase)) {
      const phase = step.phase as "search" | "read" | "review" | "file";
      return text(step.status === "completed" ? `progressSubjectDone_${phase}`
        : step.status === "running" ? `progressSubject_${phase}` : `progressSubjectStopped_${phase}`)
        .replace("{subject}", () => step.subject);
    }
    if (step.status === "failed" || step.status === "interrupted") return text("progressStopped");
    return text(step.status === "completed" ? `progressDone_${step.phase}` : `progressAction_${step.phase}`);
  };
  const latest = steps.findLast(step => step.status === "failed") || steps.findLast(step => step.subject) || steps.at(-1)!;
  const summary = current ? describe(current) : failed ? text("progressIssue")
    : interrupted ? text("progress_interrupted") : describe(latest);
  const Icon = current ? Loader2 : failed ? CircleAlert : interrupted ? CircleDashed : Sparkles;
  return (
    <div className="mb-3 text-xs text-slate-500" data-chat-activity>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={() => setExpanded(value => !value)}
        aria-label={text("actionsDone")}
        aria-expanded={expanded}
        aria-controls={expanded ? panelId : undefined}
        className="h-auto max-w-full justify-start gap-2 px-2.5 py-2 text-left"
      >
        <Icon size={14} aria-hidden="true" className={`shrink-0 ${current ? "animate-spin text-primary-600 motion-reduce:animate-none" : failed ? "text-amber-700" : "text-slate-500"}`} />
        <span className={`min-w-0 truncate font-medium ${!current && failed ? "text-amber-700" : "text-slate-600"}`}>
          {summary}
        </span>
        <ChevronDown size={13} aria-hidden="true" className={`shrink-0 text-slate-400 ${expanded ? "rotate-180" : ""}`} />
      </Button>
      {expanded && (
        <div id={panelId} className="mt-1 max-w-xl rounded-2xl border border-[color:var(--surface-border)] bg-[color:var(--surface-work)] px-4 py-3">
          <ol className="space-y-3">
            {steps.map(step => {
              const active = step.status === "running";
              const StatusIcon = active ? Loader2 : step.status === "failed" ? CircleAlert : step.status === "interrupted" ? CircleDashed : Check;
              return (
                <li key={step.id} className="flex items-start gap-2.5">
                  <StatusIcon size={13} aria-hidden="true" className={`mt-0.5 shrink-0 ${active ? "animate-spin text-primary-600 motion-reduce:animate-none" : step.status === "failed" ? "text-amber-700" : "text-slate-400"}`} />
                  <div className="min-w-0 flex-1">
                    <p className="break-words text-xs leading-6 text-slate-600">{describe(step)}</p>
                    <span className={step.status === "failed" ? "text-[11px] text-amber-700" : step.status === "interrupted" ? "text-[11px] text-slate-500" : "sr-only"}>
                      {text(`progress_${step.status}`)}
                    </span>
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      )}
    </div>
  );
});
