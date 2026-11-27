import { useId, useState } from "react";
import { ChevronDown } from "lucide-react";
import type { AvailableHeatmap } from "../../api/heatmap";
import { useViewerText } from "./viewerText";

/** Keep source class names intact in data and accessible descriptions. */
function displayLabel(label: string) {
  return label.replace(/_+/g, " ");
}

function percentage(value: number) {
  if (value === 0) return "0%";
  if (value < 0.001) return "<0.1%";
  return `${(value * 100).toFixed(1)}%`;
}

function ProbabilityRow({ label, value }: { label: string; value: number }) {
  return (
    <li
      className="viewer-probability-row"
      aria-label={`${label}: ${percentage(value)}`}
    >
      <div className="viewer-probability-label">
        <span title={label}>{displayLabel(label)}</span>
        <span title={`${value * 100}%`}>{percentage(value)}</span>
      </div>
      <div className="viewer-probability-track" aria-hidden="true">
        <span style={{ width: `${value * 100}%` }} />
      </div>
    </li>
  );
}

export function ViewerPrediction({ entry }: { entry: AvailableHeatmap }) {
  const { t } = useViewerText();
  const [expanded, setExpanded] = useState(false);
  const detailsId = useId();
  const probabilities = Object.entries(entry.probs || {})
    .filter(
      ([, value]) =>
        typeof value === "number" &&
        Number.isFinite(value) &&
        value >= 0 &&
        value <= 1,
    )
    .sort((a, b) => b[1] - a[1]);
  const label = entry.prediction || probabilities[0]?.[0];
  if (!label) return null;
  const probability = probabilities.find(([name]) => name === label)?.[1];
  const others = probabilities.filter(([name]) => name !== label);
  // Show the strongest alternative. A third class earns space when it carries
  // meaningful mass; very small probabilities remain available on disclosure.
  const visibleCount =
    others.length <= 2 ? others.length : others[1][1] >= 0.01 ? 2 : 1;
  const visible = others.slice(0, visibleCount),
    hidden = others.slice(visibleCount);
  const remaining = hidden.reduce((sum, [, value]) => sum + value, 0);
  return (
    <section className="viewer-prediction" aria-label={t("predictionSummary")}>
      <div className="viewer-result-caption">
        {t(entry.prediction ? "modelPrediction" : "highestProbability")}
      </div>
      <div className="viewer-prediction-primary">
        <h2 title={label}>{displayLabel(label)}</h2>
        {probability !== undefined && (
          <span
            className="viewer-prediction-value"
            title={`${probability * 100}%`}
          >
            {percentage(probability)}
          </span>
        )}
      </div>
      {probability !== undefined && (
        <div
          className="viewer-probability-track viewer-probability-primary"
          aria-hidden="true"
        >
          <span style={{ width: `${probability * 100}%` }} />
        </div>
      )}
      {visible.length > 0 && (
        <ul
          className="viewer-probability-list"
          aria-label={t("otherProbabilities")}
        >
          {visible.map(([label, value]) => (
            <ProbabilityRow key={label} label={label} value={value} />
          ))}
        </ul>
      )}
      {hidden.length > 0 && (
        <>
          <button
            className="viewer-probability-disclosure"
            aria-expanded={expanded}
            aria-controls={detailsId}
            onClick={() => setExpanded((value) => !value)}
          >
            <span>
              {expanded
                ? t("collapseClasses")
                : t("moreClasses").replace("{count}", String(hidden.length))}
              <ChevronDown size={13} aria-hidden="true" />
            </span>
            {!expanded && (
              <span
                className="viewer-remaining-probability"
                title={t("combinedProbability")}
              >
                {percentage(remaining)}
              </span>
            )}
          </button>
          <ul
            id={detailsId}
            hidden={!expanded}
            className="viewer-probability-details"
            aria-label={t("remainingClasses")}
          >
            {hidden.map(([label, value]) => (
              <ProbabilityRow key={label} label={label} value={value} />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
