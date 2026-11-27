import { memo, useId, useMemo, useState, type ReactNode } from "react";
import { Check, ChevronDown, CircleAlert, CircleDashed, Loader2, Sparkles } from "lucide-react";
import type { AutoResearchEvent } from "../../types/autoresearch";
import { useWorkbenchText } from "../chat/workbenchText";
import { Button } from "../ui/button";
import { messageText, researchTimeline } from "./researchActivity";
import { researchProgress, useResearchProgressText } from "./researchProgress";

const ProcessGroup = memo(function ProcessGroup({ events, running }: {
  events: AutoResearchEvent[];
  running: boolean;
}) {
  const text = useWorkbenchText();
  const describe = useResearchProgressText();
  const panelId = useId();
  const [open, setOpen] = useState(false);
  const [count, setCount] = useState(20);
  const steps = useMemo(() => researchProgress(events, running), [events, running]);
  const active = steps.findLast(step => step.status === "running");
  const failed = steps.some(step => step.status === "failed");
  const current = active || steps.findLast(step => step.status === "failed") || steps.at(-1);
  if (!current) return null;
  const Icon = active ? Loader2 : failed ? CircleAlert : Sparkles;
  return (
    <section className="min-w-0 max-w-full rounded-2xl border border-[color:var(--surface-border)] bg-[color:var(--surface-work)] text-xs" data-research-process>
      <Button type="button" variant="ghost" aria-label={text("executionProcess")} aria-expanded={open} aria-controls={open ? panelId : undefined}
        onClick={() => setOpen(value => !value)} className="h-11 w-full min-w-0 justify-start gap-2 overflow-hidden rounded-2xl px-3 text-left text-xs">
        <Icon size={14} aria-hidden="true" className={`shrink-0 ${active ? "animate-spin text-primary-600 motion-reduce:animate-none" : failed ? "text-amber-700" : "text-slate-500"}`} />
        <span className="min-w-0 flex-1 truncate font-medium text-slate-600">{describe(current)}</span>
        <span className={`shrink-0 text-[11px] font-normal ${failed && !active ? "text-amber-700" : "text-slate-500"}`}>{text(`progress_${current.status}`)}</span>
        <ChevronDown size={14} aria-hidden="true" className={`shrink-0 text-slate-400 ${open ? "rotate-180" : ""}`} />
      </Button>
      {open && (
        <div id={panelId} className="max-h-64 overflow-y-auto overscroll-contain border-t border-[color:var(--surface-border)] px-4 py-3">
          {steps.length > count && <Button type="button" variant="ghost" size="sm" className="mb-2" onClick={() => setCount(value => value + 50)}>{text("processEarlier").replace("{count}", String(steps.length - count))}</Button>}
          <ol className="space-y-3">
            {steps.slice(-count).map(item => {
              const StatusIcon = item.status === "running" ? Loader2 : item.status === "failed" ? CircleAlert : item.status === "interrupted" ? CircleDashed : Check;
              return <li key={item.id} className="flex items-start gap-2.5">
                <StatusIcon size={13} aria-hidden="true" className={`mt-1 shrink-0 ${item.status === "running" ? "animate-spin text-primary-600 motion-reduce:animate-none" : item.status === "failed" ? "text-amber-700" : "text-slate-400"}`} />
                <div className="min-w-0 flex-1">
                  <p className="break-words leading-6 text-slate-600">{describe(item)}</p>
                  <span className={item.status === "failed" || item.status === "interrupted" ? "text-[11px] text-amber-700" : "sr-only"}>{text(`progress_${item.status}`)}</span>
                </div>
              </li>;
            })}
          </ol>
        </div>
      )}
    </section>
  );
});

export default function ResearchTimeline({ events, running, renderProse, onAsk }: {
  events: AutoResearchEvent[];
  running: boolean;
  renderProse: (text: string) => ReactNode;
  onAsk?: (sequence: number) => void;
}) {
  const text = useWorkbenchText();
  const entries = useMemo(() => researchTimeline(events), [events]);
  const active = useMemo(() => entries.some(entry => entry.type === "process" && researchProgress(entry.events, running).some(step => step.status === "running")), [entries, running]);
  const describe = useResearchProgressText();
  const native = events.findLast(event => event.kind === "native_work");
  return (
    <div className="min-w-0 space-y-4" data-research-timeline>
      {entries.map(entry => {
        if (entry.type === "process") return <ProcessGroup key={entry.key} events={entry.events} running={running} />;
        const ask = onAsk && entry.event.seq ? <Button type="button" variant="ghost" size="sm"
          onClick={()=>onAsk(entry.event.seq!)} className="mt-2 h-7 text-xs text-slate-500">{text('sideQuestionStep')}</Button> : null;
        if (entry.type === "command") return (
          <article key={entry.key} className="ml-5 rounded-xl bg-slate-100/70 px-4 py-3 text-sm">
            <p className="whitespace-pre-wrap break-words">{String(entry.event.text).split("\nSelected resources (data, not instructions):")[0]}</p>
            <span className="mt-1 block text-xs text-slate-500">{text(entry.event.status === "delivered" ? "instructionDelivered" : "instructionQueued")}</span>
            {ask}
          </article>
        );
        if (entry.type === "summary") {
          if (entry.event.kind === "research_decision") {
            const decision = entry.event.decision as { action: string; assessment?: string; observation: string; interpretation: string; next_action: string };
            const action = ["keep", "discard", "repair", "pivot"].includes(decision.action) ? decision.action as "keep" | "discard" | "repair" | "pivot" : undefined;
            return <article key={entry.key} className="border-l-2 border-[color:var(--surface-border-strong)] pl-4 text-sm">
              <p className="mb-2 text-xs font-medium text-slate-500">{action ? text(`researchDecision_${action}`) : text("researchDecision")}</p>
              {decision.assessment && ["supported", "contradicted", "inconclusive", "invalid"].includes(decision.assessment) && <p className="mb-2 text-xs text-slate-500">
                {text(`researchAssessment_${decision.assessment as "supported" | "contradicted" | "inconclusive" | "invalid"}`)}
              </p>}
              {renderProse(decision.observation)}
              {renderProse(decision.interpretation)}
              <p className="mt-2 font-medium">{text("nextResearchAction")}</p>
              {renderProse(decision.next_action)}
              {ask}
            </article>;
          }
          return <article key={entry.key} className="border-l-2 border-[color:var(--surface-border)] pl-4">
            {renderProse(String(entry.event.text || entry.event.conclusion || entry.event.question || ""))}
            {ask}
          </article>;
        }
        return <article key={entry.key}>{renderProse(messageText(entry.event))}{ask}</article>;
      })}
      {running && !active && <div className="flex h-8 min-w-0 max-w-full items-center gap-2 py-1 text-xs text-slate-500" data-research-working>
        <Loader2 size={13} aria-hidden="true" className="shrink-0 animate-spin motion-reduce:animate-none" />
        <span className="min-w-0 truncate">{native?.status === "running" ? describe({ id: "current", action: "work", status: "running",
          description: typeof native.description === "string" ? native.description : undefined,
          language: typeof native.language === "string" ? native.language : undefined }) : text("researchWorking")}</span>
      </div>}
    </div>
  );
}
