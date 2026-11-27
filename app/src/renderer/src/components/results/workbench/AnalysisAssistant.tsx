import { useEffect, useRef, useState } from "react";
import {
  ArrowUp,
  Loader2,
  Square,
  X,
  Plus,
  MessageSquare,
  ArrowUpRight,
} from "lucide-react";
import {
  resultGet,
  resultSend,
  type AnalysisConfig,
  type AnalysisRun,
  type AssistantResponse,
} from "../../../api/resultWorkbench";
import { useResultText } from "./text";
import { Button } from "../../ui/button";
import { Card } from "../../ui/card";

export default function AnalysisAssistant({
  config,
  run,
  scopeKey,
  onConfig,
  onRun,
  onClose,
  onHandoff,
}: {
  config: AnalysisConfig;
  run?: AnalysisRun;
  scopeKey: string;
  onConfig: (config: AnalysisConfig) => void;
  onRun: (run: AnalysisRun) => void;
  onClose: () => void;
  onHandoff: (goal: string) => void;
}) {
  const { text, language, split } = useResultText();
  const storageKey = `results-assistant:${scopeKey}`;
  const [conversation, setConversation] = useState<AssistantResponse | null>(
    null,
  );
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  const currentContext = useRef("");
  currentContext.current = JSON.stringify(config);
  const scroll = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const id = localStorage.getItem(storageKey);
    const abort = new AbortController();
    if (id)
      resultGet<AssistantResponse>(`/assistant/${id}`, {}, abort.signal)
        .then(setConversation)
        .catch(() => localStorage.removeItem(storageKey));
    return () => {
      abort.abort();
      controller.current?.abort();
    };
  }, [storageKey]);
  useEffect(() => {
    if (scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight;
  }, [conversation, busy]);
  const send = async () => {
    if (!input.trim() || busy) return;
    const message = input.trim();
    const contextAtSend = currentContext.current;
    const abort = new AbortController();
    controller.current = abort;
    setBusy(true);
    setError("");
    try {
      const response = await resultSend<AssistantResponse>(
        "/assistant",
        {
          message,
          config,
          analysis_id: run?.analysis_id,
          language,
          conversation_id: conversation?.conversation_id,
          version: conversation?.version,
        },
        "POST",
        abort.signal,
      );
      setConversation(response);
      localStorage.setItem(storageKey, response.conversation_id);
      setInput("");
      if (currentContext.current === contextAtSend) {
        if (response.config) onConfig(response.config);
        if (response.run) onRun(response.run);
      }
    } catch (e) {
      if (!abort.signal.aborted) setError(String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card
      aria-label={text("assistant")}
      className="flex h-[min(78vh,850px)] min-h-96 flex-col overflow-hidden xl:sticky xl:top-4"
    >
      <header className="flex items-center justify-between border-b border-[color:var(--surface-border)] px-4 py-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold">
          <MessageSquare size={15} className="text-slate-400" />
          {text("assistant")}
        </h2>
        <div className="flex gap-1">
          <Button
            variant="ghost"
            size="icon"
            title={text("newConversation")}
            aria-label={text("newConversation")}
            className="h-8 w-8"
            disabled={busy}
            onClick={() => {
              controller.current?.abort();
              setConversation(null);
              localStorage.removeItem(storageKey);
              setError("");
            }}
          >
            <Plus size={15} />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            aria-label={text("close")}
            onClick={onClose}
          >
            <X size={16} />
          </Button>
        </div>
      </header>
      <div
        ref={scroll}
        className="flex-1 space-y-5 overflow-y-auto p-4"
        aria-live="polite"
      >
        {!conversation?.messages?.length && (
          <>
            <p className="text-sm leading-6 text-slate-500">
              {text("assistantHint")}
            </p>
            <div className="rounded-2xl bg-[color:var(--surface-muted)] p-4 text-xs text-slate-500">
              <p className="mb-2 leading-5">{text("assistantContext")}</p>
              {config.source_ids.length} {text("selected")} ·{" "}
              {split(config.split)} · {text(config.unit)}
            </div>
            <div className="flex flex-col items-start gap-2">
              {(
                [
                  "assistantExplain",
                  "assistantCalibration",
                  "assistantCompare",
                ] as const
              ).map((key) => (
                <Button
                  key={key}
                  variant="outline"
                  size="sm"
                  onClick={() => setInput(text(key))}
                >
                  {text(key)}
                </Button>
              ))}
            </div>
          </>
        )}
        {conversation?.messages.map((message, i) => (
          <div
            key={i}
            className={
              message.role === "user"
                ? "ml-5 rounded-2xl bg-[color:var(--surface-muted)] px-4 py-3 text-sm leading-6 text-slate-900"
                : "text-sm leading-7 text-slate-700"
            }
          >
            <p className="whitespace-pre-wrap break-words">{message.content}</p>
            {message.analysis_id && (
              <p
                className="mt-2 text-xs font-medium text-primary-700"
                title={message.analysis_id}
              >
                {text("submittedAnalysis")}
              </p>
            )}
            {message.action === "handoff" && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => onHandoff(message.handoff || message.content)}
                className="mt-3 gap-1.5"
              >
                {text("handoff")} <ArrowUpRight size={13} />
              </Button>
            )}
          </div>
        ))}
        {busy && (
          <p
            role="status"
            className="flex items-center gap-2 text-xs text-slate-500"
          >
            <Loader2 size={14} className="animate-spin" />
            {text("thinking")}
          </p>
        )}
        {error && (
          <p role="alert" className="text-xs text-red-600">
            {error}
          </p>
        )}
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
        className="border-t border-[color:var(--surface-border)] p-3"
      >
        <textarea
          aria-label={text("assistant")}
          className="w-full resize-none rounded-2xl border border-[color:var(--surface-border-strong)] bg-[color:var(--surface-elevated)] p-3 text-sm leading-6 shadow-[var(--shadow-soft)] focus:outline-none focus:ring-4 focus:ring-primary-500/20"
          rows={3}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={text("assistantPlaceholder")}
          onKeyDown={(e) => {
            if (
              e.key === "Enter" &&
              !e.shiftKey &&
              !e.nativeEvent.isComposing
            ) {
              e.preventDefault();
              void send();
            }
          }}
        />
        <div className="mt-2 flex items-center justify-between">
          <span className="text-[11px] text-slate-400">
            {config.source_ids.length} {text("sources")}
          </span>
          {busy ? (
            <Button
              variant="secondary"
              size="icon"
              type="button"
              onClick={() => controller.current?.abort()}
              aria-label={text("stop")}
            >
              <Square size={16} />
            </Button>
          ) : (
            <Button
              size="icon"
              type="submit"
              disabled={!input.trim()}
              aria-label={text("send")}
            >
              <ArrowUp size={18} />
            </Button>
          )}
        </div>
      </form>
    </Card>
  );
}
