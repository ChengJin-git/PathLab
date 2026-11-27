import { useTranslation } from "react-i18next";
import { Button } from "./ui/button";

interface Props {
  instruction: string;
  onInstruction: (value: string) => void;
  selected: boolean;
  busy: boolean;
  suggestion: string;
  onRequest: () => void;
  onApply: () => void;
  onDiscard: () => void;
  onUndo?: () => void;
}

export default function ReportPolishPanel(props: Props) {
  const { t } = useTranslation();
  return (
    <section className="space-y-3 rounded-lg border bg-gray-50 p-4">
      <h2 className="text-sm font-semibold">{t("reports.polish")}</h2>
      <p className="text-xs text-gray-500">
        {t(props.selected ? "reports.polishSelection" : "reports.polishWhole")}
      </p>
      <textarea
        aria-label={t("reports.polishInstruction")}
        placeholder={t("reports.polishPlaceholder")}
        value={props.instruction}
        disabled={props.busy}
        onChange={(e) => props.onInstruction(e.target.value)}
        maxLength={4000}
        rows={2}
        className="w-full rounded-lg border bg-white p-3 text-sm"
      />
      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          disabled={props.busy || !props.instruction.trim()}
          onClick={props.onRequest}
        >
          {t("reports.suggest")}
        </Button>
        {props.onUndo && (
          <Button variant="ghost" disabled={props.busy} onClick={props.onUndo}>
            {t("reports.undo")}
          </Button>
        )}
      </div>
      {props.suggestion && (
        <div className="space-y-3">
          <h3 className="text-sm font-medium">{t("reports.suggestion")}</h3>
          <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-lg border bg-white p-3 font-sans text-sm leading-6">
            {props.suggestion}
          </pre>
          <div className="flex gap-2">
            <Button disabled={props.busy} onClick={props.onApply}>
              {t("reports.apply")}
            </Button>
            <Button
              variant="outline"
              disabled={props.busy}
              onClick={props.onDiscard}
            >
              {t("reports.discard")}
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}
