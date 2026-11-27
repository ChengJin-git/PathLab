import { ChevronLeft, ChevronRight, Trash2 } from "lucide-react";
import { Checkbox } from "../ui/checkbox";
import type { ViewerRegion } from "../../api/viewer";
import type { useViewerAnnotations } from "./useViewerAnnotations";
import { useViewerText } from "./viewerText";

export function ViewerRegionList({
  annotation,
  onFocus,
}: {
  annotation: ReturnType<typeof useViewerAnnotations>;
  onFocus: (region: ViewerRegion) => void;
}) {
  const { t } = useViewerText();
  const disabled = annotation.saving || annotation.pendingEdit;
  return (
    <>
      <div className="viewer-list-heading">
        <span>
          {annotation.total} {t("objects")}
        </span>
      </div>
      {annotation.viewportLimited && (
        <p className="viewer-subtle">{t("viewportLimited")}</p>
      )}
      <div className="viewer-region-list" aria-busy={annotation.loading}>
        {annotation.listRegions.map((region) => (
          <div
            key={region.id}
            className={
              "viewer-result-row " +
              (annotation.selected.includes(region.id)
                ? "viewer-region-selected"
                : "")
            }
          >
            <Checkbox
              aria-label={`${t("select")} ${region.label}`}
              checked={annotation.selected.includes(region.id)}
              disabled={annotation.saving}
              onCheckedChange={(checked) =>
                annotation.setSelected(
                  checked
                    ? [...new Set([...annotation.selected, region.id])]
                    : annotation.selected.filter((id) => id !== region.id),
                )
              }
            />
            <button
              className="min-w-0 flex-1 text-left"
              onClick={(event) => {
                annotation.setSelected(
                  event.shiftKey
                    ? [...new Set([...annotation.selected, region.id])]
                    : [region.id],
                );
                onFocus(region);
              }}
            >
              <span>
                <i
                  className="mr-2 inline-block h-2 w-2 rounded-full"
                  style={{ background: region.color }}
                />
                {region.label}
              </span>
            </button>
            <span className="viewer-subtle">
              {Math.round(region.width)} × {Math.round(region.height)}
            </span>
            <button
              className="viewer-icon viewer-delete"
              aria-label={`${t("deleteRegion")} ${region.label}`}
              disabled={disabled}
              onClick={() => void annotation.remove([region.id])}
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
        {!annotation.listRegions.length && !annotation.loading && (
          <p className="text-xs text-slate-400">{t("emptyAnnotations")}</p>
        )}
      </div>
      {(annotation.previousPage || annotation.nextPage) && (
        <div className="viewer-pagination">
          <button
            className="viewer-icon"
            aria-label={t("previousPage")}
            disabled={
              !annotation.previousPage ||
              annotation.loading ||
              annotation.saving
            }
            onClick={annotation.previousPage}
          >
            <ChevronLeft size={15} />
          </button>
          <span>
            {t("page")} {annotation.page} /{" "}
            {Math.max(1, Math.ceil(annotation.total / 50))}
          </span>
          <button
            className="viewer-icon"
            aria-label={t("nextPage")}
            disabled={
              !annotation.nextPage || annotation.loading || annotation.saving
            }
            onClick={annotation.nextPage}
          >
            <ChevronRight size={15} />
          </button>
        </div>
      )}
    </>
  );
}
