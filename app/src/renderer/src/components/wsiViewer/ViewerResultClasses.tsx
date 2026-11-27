import { useId } from "react";
import { Loader2 } from "lucide-react";
import { Checkbox } from "../ui/checkbox";
import { Radio } from "../ui/radio";
import { useViewerText } from "./viewerText";

export function ViewerResultClasses({
  classes,
  colors,
  segmentation,
  classIndex,
  onClass,
  hiddenClasses,
  onToggle,
  counts,
  loading,
}: {
  classes: string[];
  colors: string[];
  segmentation: boolean;
  classIndex: number;
  onClass: (index: number) => void;
  hiddenClasses: number[];
  onToggle: (index: number) => void;
  counts?: Record<number, number>;
  loading: boolean;
}) {
  const { t } = useViewerText();
  const group = useId();
  return (
    <section
      className="viewer-class-legend"
      aria-label={t(segmentation ? "segmentationClasses" : "detectionClasses")}
    >
      <header>
        <h3 className="viewer-result-caption">
          {t(segmentation ? "segmentationClasses" : "detectionClasses")}
        </h3>
        {loading ? (
          <Loader2
            size={12}
            className="animate-spin"
            aria-label={t("loadingClasses")}
          />
        ) : (
          <span>{classes.length || "—"}</span>
        )}
      </header>
      {classes.length > 0 ? (
        <div
          className="viewer-class-list"
          role={segmentation ? "radiogroup" : "group"}
          aria-label={t("visibleClasses")}
        >
          {classes.map((label, index) => {
            const selected = segmentation
              ? index === classIndex
              : !hiddenClasses.includes(index);
            return (
              <label
                key={`${index}:${label}`}
                className="viewer-class-row"
                data-selected={selected}
              >
                <span
                  className="viewer-class-swatch"
                  style={{ background: colors[index] || "#e11d48" }}
                  aria-hidden="true"
                />
                <span className="viewer-class-name" title={label}>
                  {label.replace(/_+/g, " ")}
                </span>
                {!segmentation && counts && (
                  <span
                    className="viewer-class-count"
                    title={t("classCountHint")}
                  >
                    {counts[index] || 0}
                  </span>
                )}
                {segmentation ? (
                  <Radio
                    name={group}
                    aria-label={label}
                    checked={selected}
                    onChange={() => onClass(index)}
                  />
                ) : (
                  <Checkbox
                    aria-label={label}
                    checked={selected}
                    onCheckedChange={() => onToggle(index)}
                  />
                )}
              </label>
            );
          })}
        </div>
      ) : (
        !loading && (
          <p className="viewer-class-empty">{t("classNamesMissing")}</p>
        )
      )}
      {classes.length > 0 && (
        <p className="viewer-class-hint">
          {t(segmentation ? "segmentationClassHint" : "detectionClassHint")}
        </p>
      )}
    </section>
  );
}
