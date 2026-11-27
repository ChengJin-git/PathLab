import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchImagePrediction,
  getPredictionMaskUrl,
  getPatchCAMImageUrl,
  type AvailableHeatmap,
  type HeatmapData,
} from "../../api/heatmap";
import { useViewerText, type ViewerTextKey } from "./viewerText";
import type { Geometry } from "../../api/viewer";
import { Select } from "../ui/select";
import { useDebounce } from "../../lib/hooks/useDebounce";
import { useAuth } from "../../contexts/AuthContext";
import { ChartNoAxesCombined, ArrowUpRight } from "lucide-react";
import { Button } from "../ui/button";
import { ViewerAttentionPatches } from "./ViewerAttentionPatches";
import { ViewerPrediction } from "./ViewerPrediction";
import { ViewerResultControls } from "./ViewerResultControls";
import { ViewerResultClasses } from "./ViewerResultClasses";

const resultTypeLabels: Record<string, ViewerTextKey> = {
  wsi_classification: "wholeSlideClassification",
  patch_classification: "imageClassification",
  patch_segmentation: "segmentation",
  patch_detection: "detection",
  wsi_survival: "survivalAnalysis",
};

export function ViewerResults({
  viewer,
  id,
  entries,
  selected,
  onSelected,
  heatmap,
  opacity,
  setOpacity,
  showHeatmap,
  setShowHeatmap,
  threshold,
  setThreshold,
  onFocus,
  onPlan,
  action,
}: {
  viewer: any;
  id: string;
  entries: AvailableHeatmap[];
  selected: string;
  onSelected: (key: string) => void;
  heatmap: HeatmapData | null;
  opacity: number;
  setOpacity: (n: number) => void;
  showHeatmap: boolean;
  setShowHeatmap: (v: boolean) => void;
  threshold: number;
  setThreshold: (n: number) => void;
  onFocus: (geometry: Geometry) => void;
  onPlan: () => void;
  action?: { type: "attention" | "filter"; serial: number };
}) {
  const { t } = useViewerText();
  const { user } = useAuth();
  const entry = entries.find(
    (e) => `${e.task_id}:${e.fold_key || ""}` === selected,
  );
  const [showMask, setShowMask] = useState(false),
    [showBoxes, setShowBoxes] = useState(false),
    [classIndex, setClassIndex] = useState(0);
  const [hiddenClasses, setHiddenClasses] = useState<number[]>([]);
  const spatial =
    entry?.task_type === "patch_segmentation" ||
    entry?.task_type === "patch_detection";
  const delayedThreshold = useDebounce(threshold, 180);
  const currentHeatmap =
    showHeatmap &&
    entry?.data_type !== "patch" &&
    heatmap?.wsi_id === id &&
    heatmap.task_id === entry?.task_id &&
    (heatmap.fold_key || "") === (entry?.fold_key || "")
      ? heatmap
      : null;
  useEffect(() => {
    setShowMask(false);
    setShowBoxes(false);
    setClassIndex(0);
    setHiddenClasses([]);
  }, [selected, id]);
  useEffect(() => {
    if (action?.type === "filter") setShowBoxes(true);
    if (action?.type === "attention" && entry?.data_type === "patch")
      setShowMask(true);
  }, [action?.serial]);
  const prediction = useQuery({
    queryKey: [
      "viewer-prediction",
      user?.id,
      id,
      entry?.task_id,
      entry?.fold_key,
      delayedThreshold,
    ],
    queryFn: ({ signal }) =>
      fetchImagePrediction(
        id,
        entry!.task_id!,
        delayedThreshold,
        entry?.fold_key || undefined,
        signal,
      ),
    enabled:
      !!entry?.task_id &&
      (showBoxes ||
        (showMask && entry.task_type === "patch_segmentation") ||
        (spatial && !entry.classes?.length)),
  });
  const classes = prediction.data?.class_names?.length
    ? prediction.data.class_names
    : prediction.data?.classes?.length
      ? prediction.data.classes
      : entry?.classes || [];
  const colors = prediction.data?.class_colors?.length
    ? prediction.data.class_colors
    : entry?.class_colors || [];
  const imageUrl =
    entry?.task_id && showMask
      ? entry.task_type === "patch_segmentation"
        ? getPredictionMaskUrl(
            id,
            entry.task_id,
            delayedThreshold,
            classIndex,
            "pred",
            entry.fold_key || undefined,
          )
        : getPatchCAMImageUrl(id, entry.task_id, entry.fold_key || undefined)
      : null;
  useEffect(() => {
    if (!viewer || !imageUrl) return;
    const element = document.createElement("img");
    element.src = imageUrl;
    element.style.opacity = String(opacity);
    element.style.pointerEvents = "none";
    element.id = "viewer-result-image";
    const add = () => {
      const image = viewer.world.getItemAt(0);
      if (image) viewer.addOverlay({ element, location: image.getBounds() });
    };
    if (viewer.world.getItemCount()) add();
    else viewer.addOnceHandler("open", add);
    return () => {
      viewer.removeHandler("open", add);
      try {
        viewer.removeOverlay(element);
      } catch {}
    };
  }, [viewer, imageUrl]);
  useEffect(() => {
    const element = document.getElementById("viewer-result-image");
    if (element) element.style.opacity = String(opacity);
  }, [opacity]);
  const thresholdBoxes = useMemo(
    () =>
      prediction.data?.detection?.prediction.boxes
        .map((box, index) => ({
          box,
          score: prediction.data?.detection?.prediction.scores?.[index] ?? 1,
          classIndex:
            (prediction.data?.detection?.prediction.labels[index] ?? 0) - 1,
          index,
        }))
        .filter((item) => item.score >= threshold) || [],
    [prediction.data, threshold],
  );
  const boxes = useMemo(
    () =>
      thresholdBoxes.filter((item) => !hiddenClasses.includes(item.classIndex)),
    [thresholdBoxes, hiddenClasses],
  );
  const counts = useMemo(
    () =>
      prediction.data?.detection
        ? thresholdBoxes.reduce<Record<number, number>>((result, item) => {
            result[item.classIndex] = (result[item.classIndex] || 0) + 1;
            return result;
          }, {})
        : undefined,
    [thresholdBoxes, prediction.data],
  );
  useEffect(() => {
    if (!viewer || !showBoxes) return;
    const overlays: HTMLDivElement[] = [];
    const image = viewer.world.getItemAt(0);
    if (!image) return;
    boxes.slice(0, 500).forEach(({ box, classIndex }) => {
      const [x, y, right, bottom] = box;
      const el = document.createElement("div");
      el.style.cssText = `border:1.5px solid ${colors[classIndex] || "#e11d48"};pointer-events:none`;
      el.dataset.resultClass = String(classIndex);
      viewer.addOverlay({
        element: el,
        location: image.imageToViewportRectangle(x, y, right - x, bottom - y),
      });
      overlays.push(el);
    });
    return () =>
      overlays.forEach((el) => {
        try {
          viewer.removeOverlay(el);
        } catch {}
      });
  }, [viewer, boxes, showBoxes, colors]);
  if (!entries.length)
    return (
      <div className="viewer-empty">
        <ChartNoAxesCombined size={28} strokeWidth={1.3} />
        <h2 className="font-medium text-slate-700">{t("emptyResults")}</h2>
        <p>{t("emptyResultsHint")}</p>
        <Button
          variant="secondary"
          size="sm"
          className="gap-2 shadow-none rounded-lg"
          onClick={onPlan}
        >
          {t("mainPage")}
          <ArrowUpRight size={14} />
        </Button>
      </div>
    );
  return (
    <div className="viewer-panel-content viewer-results-panel">
      <div className="viewer-result-source" title={entry?.task_name}>
        <Select
          ariaLabel={t("chooseResult")}
          showDescription
          value={selected}
          onChange={onSelected}
          className="viewer-result-select"
          dropdownClassName="viewer-result-options"
          options={entries.map((item) => ({
            value: `${item.task_id}:${item.fold_key || ""}`,
            label: item.task_name,
            description: [
              t(resultTypeLabels[item.task_type] || "results"),
              item.fold_key
                ? t("resultFold").replace(
                    "{fold}",
                    item.fold_key.replace(/^fold_/, ""),
                  )
                : null,
            ]
              .filter(Boolean)
              .join(" / "),
          }))}
        />
      </div>
      {entry && (
        <>
          {spatial ? (
            <ViewerResultClasses
              classes={classes}
              colors={colors}
              segmentation={entry.task_type === "patch_segmentation"}
              classIndex={classIndex}
              onClass={(index) => {
                setClassIndex(index);
                setShowMask(true);
              }}
              hiddenClasses={hiddenClasses}
              onToggle={(index) => {
                setHiddenClasses((previous) =>
                  previous.includes(index)
                    ? previous.filter((value) => value !== index)
                    : [...previous, index],
                );
                setShowBoxes(true);
              }}
              counts={counts}
              loading={prediction.isFetching && !classes.length}
            />
          ) : (
            <ViewerPrediction key={`${id}:${selected}`} entry={entry} />
          )}
          <ViewerResultControls
            entry={entry}
            showHeatmap={showHeatmap}
            setShowHeatmap={setShowHeatmap}
            showMask={showMask}
            setShowMask={setShowMask}
            showBoxes={showBoxes}
            setShowBoxes={setShowBoxes}
            opacity={opacity}
            setOpacity={setOpacity}
            threshold={threshold}
            setThreshold={setThreshold}
          />
        </>
      )}
      {prediction.error && <p role="alert">{t("failed")}</p>}
      {currentHeatmap && (
        <ViewerAttentionPatches
          key={`${id}:${selected}:${currentHeatmap.selected_class_idx ?? ""}`}
          id={id}
          heatmap={currentHeatmap}
          onFocus={onFocus}
        />
      )}
      {showBoxes && (
        <div className="space-y-2">
          {boxes.slice(0, 20).map(({ box, score, index, classIndex }) => (
            <button
              className="viewer-result-row"
              key={index}
              onClick={() =>
                onFocus({
                  type: "rect",
                  x: box[0],
                  y: box[1],
                  width: box[2] - box[0],
                  height: box[3] - box[1],
                })
              }
            >
              <i
                className="viewer-class-swatch"
                style={{ background: colors[classIndex] || "#e11d48" }}
                aria-hidden="true"
              />
              {classes[classIndex] ||
                t("classNumber").replace("{number}", String(classIndex + 1))}
              <span>{score.toFixed(2)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
