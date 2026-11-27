import type { DatasetSummary } from "../../api/wsi";
import { getTaskMetadata } from "../../constants/training";
import { useDatasetText } from "./text";
export default function DatasetOverview({
  dataset,
  onEdit,
  onLabels,
}: {
  dataset: DatasetSummary;
  onEdit?: () => void;
  onLabels?: () => void;
}) {
  const text = useDatasetText();
  return (
    <section className="mb-4 rounded-xl border border-slate-200 bg-white px-5 py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-slate-900">
            {text("overview")}
          </h3>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">
            {dataset.description || text("empty")}
          </p>
        </div>
        <div className="flex gap-4 text-xs text-slate-600">
          {onEdit && (
            <button onClick={onEdit} className="hover:text-slate-900">
              {text("edit")}
            </button>
          )}
          {onLabels && (
            <button
              onClick={onLabels}
              className="font-medium hover:text-slate-900"
            >
              {text("append")}
            </button>
          )}
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2">
        {dataset.tasks.map((task) => (
          <span key={task.task_type} className="text-xs text-slate-600">
            <span className="font-medium text-slate-800">
              {text(getTaskMetadata(task.task_type).taskFamily)}
            </span>{" "}
            <span className="ml-1">
              {task.labelled_count}/{task.sample_count} · {text(task.status)}
            </span>
          </span>
        ))}
      </div>
      {!!Object.keys(dataset.metadata).length && (
        <details className="mt-3 border-t border-slate-100 pt-3">
          <summary className="cursor-pointer text-xs text-slate-500">
            {text("details")}
          </summary>
          <dl className="mt-3 grid gap-3 text-xs sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(dataset.metadata)
              .filter(([, value]) => value !== "")
              .map(([key, value]) => (
                <div key={key}>
                  <dt className="text-slate-500">{key}</dt>
                  <dd className="mt-1 break-words text-slate-800">
                    {typeof value === "object"
                      ? JSON.stringify(value)
                      : String(value)}
                  </dd>
                </div>
              ))}
          </dl>
        </details>
      )}
    </section>
  );
}
