import { formatMetricName, formatMetricValue } from "../../constants/metrics";

export type MeasuredMetric =
  | number
  | {
      value: number;
      label?: string;
      unit?: string;
      ci_lower?: number | null;
      ci_upper?: number | null;
    };

export default function MetricValues({
  metrics,
  preserveUnits = false,
}: {
  metrics: Record<string, MeasuredMetric>;
  preserveUnits?: boolean;
}) {
  const number = (value: number, key: string) =>
    preserveUnits
      ? new Intl.NumberFormat(undefined, {
          maximumSignificantDigits: 6,
        }).format(value)
      : formatMetricValue(value, key);
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      {Object.entries(metrics).map(([key, metric]) => {
        const entry = typeof metric === "number" ? { value: metric } : metric;
        return (
          <div
            key={key}
            className="min-w-0 rounded-lg border border-gray-200 bg-gray-50/60 p-3"
          >
            <p title={key} className="truncate text-xs text-gray-500">
              {entry.label || (preserveUnits ? key : formatMetricName(key))}
            </p>
            <p className="mt-1 break-words text-lg font-semibold text-gray-900">
              {number(entry.value, key)}
              {entry.unit ? ` ${entry.unit}` : ""}
            </p>
            {entry.ci_lower != null && entry.ci_upper != null && (
              <p className="mt-1 text-xs text-gray-500">
                [{number(entry.ci_lower, key)}, {number(entry.ci_upper, key)}]
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
