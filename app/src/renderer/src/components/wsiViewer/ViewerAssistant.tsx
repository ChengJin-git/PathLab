import { useEffect, useRef, useState } from "react";
import {
  ArrowUp,
  Square,
  MessageCircle,
  Ruler,
  ScanSearch,
  ArrowUpRight,
} from "lucide-react";
import { Button } from "../ui/button";
import {
  askViewer,
  type ViewerReply,
  type ViewerContext,
  type ViewerCapabilities,
  type Geometry,
  type AnnotationLayer,
} from "../../api/viewer";
import { useViewerText, type ViewerTextKey } from "./viewerText";
import { Select } from "../ui/select";

export function ViewerAssistant({
  context,
  capabilities,
  layer,
  taskId,
  selected,
  selection,
  featureId,
  onFeature,
  onReply,
  onPlan,
}: {
  context: ViewerContext;
  capabilities?: ViewerCapabilities;
  layer: AnnotationLayer;
  taskId?: string;
  selected: string[];
  selection?: Geometry;
  featureId: string;
  onFeature: (id: string) => void;
  onReply: (reply: ViewerReply) => void;
  onPlan: (goal: string) => void;
}) {
  const { t, language } = useViewerText();
  const [message, setMessage] = useState(""),
    [history, setHistory] = useState<{ role: string; content: string }[]>([]),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [handoff, setHandoff] = useState("");
  const controller = useRef<AbortController>();
  useEffect(() => () => controller.current?.abort(), []);
  const submit = async () => {
    if (!message.trim() || busy) return;
    const goal = message;
    setMessage("");
    setBusy(true);
    setError("");
    setHandoff("");
    controller.current = new AbortController();
    setHistory((previous) => [...previous, { role: "user", content: goal }]);
    try {
      const reply = await askViewer(
        context.wsi_id,
        {
          message: goal,
          language,
          layer,
          task_id: taskId,
          feature_id: featureId || undefined,
          selected_ids: selected,
          selection,
          history: history.slice(-12),
        },
        controller.current.signal,
      );
      setHistory((previous) => [
        ...previous,
        {
          role: "assistant",
          content:
            reply.action === "handoff" &&
            reply.reason &&
            reply.reason !== "complex_request"
              ? t(reply.reason as ViewerTextKey)
              : reply.message || t("handoffOnly"),
        },
      ]);
      if (reply.action === "handoff") setHandoff(goal);
      else onReply(reply);
    } catch (e) {
      if (!controller.current.signal.aborted)
        setError(t("assistant_unavailable"));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="viewer-panel-content flex-1 overflow-y-auto">
        {!history.length && (
          <div className="viewer-assistant-intro">
            <div className="viewer-assistant-symbol">
              <MessageCircle size={22} strokeWidth={1.5} />
            </div>
            <h2>{t("assistantIntro")}</h2>
            <p>{t("assistantScope")}</p>
            <div className="viewer-suggestions">
              <button onClick={() => setMessage(t("measureQuestion"))}>
                <Ruler size={14} />
                {t("measureQuestion")}
              </button>
              <button onClick={() => setMessage(t("locateQuestion"))}>
                <ScanSearch size={14} />
                {t("locateQuestion")}
              </button>
            </div>
          </div>
        )}
        {capabilities?.features.length ? (
          <label className="viewer-field">
            {t("featureModel")}
            <Select
              ariaLabel={t("featureModel")}
              value={featureId}
              onChange={onFeature}
              className="w-full"
              triggerClassName="text-xs"
              options={capabilities.features.map((item, index) => ({
                value: item.id,
                label: `${item.model_id} (${index + 1})`,
              }))}
            />
          </label>
        ) : null}
        {history.map((item, index) => (
          <div
            key={index}
            className={
              item.role === "user" ? "viewer-chat-user" : "viewer-chat-answer"
            }
          >
            {item.content}
          </div>
        ))}
        {error && (
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
        )}
        {(handoff || error) && (
          <div className="viewer-handoff">
            <p className="text-xs leading-6 text-slate-500">{t("handoff")}</p>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => onPlan(handoff || message || t("defaultGoal"))}
            >
              {t("mainPage")}
              <ArrowUpRight size={14} />
            </Button>
          </div>
        )}
      </div>
      <form
        className="viewer-composer"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <textarea
          aria-label={t("question")}
          placeholder={t("question")}
          value={message}
          maxLength={3000}
          onChange={(e) => setMessage(e.target.value)}
          rows={3}
        />
        <button
          type={busy ? "button" : "submit"}
          aria-label={t(busy ? "stop" : "send")}
          disabled={!busy && !message.trim()}
          onClick={busy ? () => controller.current?.abort() : undefined}
        >
          {busy ? <Square size={15} /> : <ArrowUp size={17} />}
        </button>
      </form>
    </div>
  );
}
