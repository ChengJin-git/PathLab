import { useTranslation } from "react-i18next";
import type { StorageInspection } from "../../../api/storage";
export function InspectionProgress({
  value,
  onCancel,
}: {
  value?: StorageInspection;
  onCancel?: () => void;
}) {
  const { i18n } = useTranslation();
  const zh = i18n.language.startsWith("zh");
  if (!value) return null;
  const active = ["queued", "running"].includes(value.status);
  const total = value.total;
  const progress = total
    ? Math.min(100, (100 * (value.processed || 0)) / total)
    : undefined;
  const stages: Record<string, string> = {
    queued: "等待检查",
    preparing: "准备检查",
    database: "检查记录",
    "external-health": "检查文件可访问性",
    coordinates: "坐标",
    masks: "掩膜",
    features_cache: "特征",
    training: "训练数据",
    models: "模型",
    logs: "日志",
    wsi_files: "原始文件",
    ai_result_bundles: "AI 结果",
    complete: "完成",
  };
  return (
    <div
      role="status"
      className="my-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600"
    >
      <div className="flex items-center justify-between gap-3">
        <span>
          {zh
            ? value.status === "completed"
              ? "已完成"
              : value.status === "cancelled"
                ? "已取消"
                : value.status === "failed"
                  ? "检查失败"
                  : value.stage === "directory"
                    ? "扫描目录"
                    : stages[value.stage || value.status] || value.status
            : value.stage || value.status}{" "}
          {value.total != null
            ? `${value.processed || 0} / ${value.total}`
            : value.processed
              ? `${value.processed.toLocaleString()}`
              : ""}
        </span>
        {active && onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="shrink-0 underline"
          >
            {zh ? "取消" : "Cancel"}
          </button>
        )}
      </div>
      {active && (
        <progress
          aria-label={zh ? "扫描进度" : "Inspection progress"}
          className="mt-2 h-1.5 w-full accent-indigo-600"
          max={100}
          value={progress}
        />
      )}
      <p className="mt-2 text-slate-500">
        {active
          ? zh
            ? "检查期间可以离开页面。"
            : "You can leave this page while the check runs."
          : value.finished_at
            ? new Date(value.finished_at * 1000).toLocaleString()
            : ""}
      </p>
    </div>
  );
}
