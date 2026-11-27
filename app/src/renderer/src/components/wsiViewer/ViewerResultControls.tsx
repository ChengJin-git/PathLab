import { useId } from "react";
import { Layers2, Scan, ScanLine } from "lucide-react";
import * as Switch from "@radix-ui/react-switch";
import * as Slider from "@radix-ui/react-slider";
import type { AvailableHeatmap } from "../../api/heatmap";
import { useViewerText } from "./viewerText";

function LayerToggle({
  label,
  checked,
  onChange,
  icon: Icon,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  icon: typeof Layers2;
}) {
  const id = useId();
  return (
    <div className="viewer-result-layer-row">
      <label htmlFor={id}>
        <Icon size={16} strokeWidth={1.5} aria-hidden="true" />
        <span>{label}</span>
      </label>
      <Switch.Root
        id={id}
        className="viewer-switch"
        checked={checked}
        onCheckedChange={onChange}
        aria-label={label}
      >
        <Switch.Thumb className="viewer-switch-thumb" />
      </Switch.Root>
    </div>
  );
}

function ResultRange({
  label,
  value,
  onChange,
  step,
  formatted,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  step: number;
  formatted: string;
}) {
  const id = useId();
  return (
    <div className="viewer-result-range">
      <div className="viewer-result-range-heading">
        <span id={id}>{label}</span>
        <output>{formatted}</output>
      </div>
      <Slider.Root
        className="viewer-result-slider"
        min={0}
        max={1}
        step={step}
        value={[value]}
        onValueChange={(values) => onChange(values[0])}
      >
        <Slider.Track className="viewer-result-slider-track">
          <Slider.Range className="viewer-result-slider-range" />
        </Slider.Track>
        <Slider.Thumb
          className="viewer-result-slider-thumb"
          aria-labelledby={id}
          aria-valuetext={formatted}
        />
      </Slider.Root>
    </div>
  );
}

export function ViewerResultControls({
  entry,
  showHeatmap,
  setShowHeatmap,
  showMask,
  setShowMask,
  showBoxes,
  setShowBoxes,
  opacity,
  setOpacity,
  threshold,
  setThreshold,
}: {
  entry: AvailableHeatmap;
  showHeatmap: boolean;
  setShowHeatmap: (value: boolean) => void;
  showMask: boolean;
  setShowMask: (value: boolean) => void;
  showBoxes: boolean;
  setShowBoxes: (value: boolean) => void;
  opacity: number;
  setOpacity: (value: number) => void;
  threshold: number;
  setThreshold: (value: number) => void;
}) {
  const { t } = useViewerText();
  const segmentation = entry.task_type === "patch_segmentation";
  const detection = entry.task_type === "patch_detection";
  const attention = entry.has_heatmap && !segmentation;
  const wsiAttention = attention && entry.data_type !== "patch";
  if (!segmentation && !detection && !attention) return null;
  return (
    <section className="viewer-result-controls" aria-label={t("resultLayers")}>
      <h3 className="viewer-result-caption">{t("resultLayers")}</h3>
      {attention && (
        <LayerToggle
          label={t("heatmap")}
          icon={Layers2}
          checked={wsiAttention ? showHeatmap : showMask}
          onChange={wsiAttention ? setShowHeatmap : setShowMask}
        />
      )}
      {segmentation && (
        <LayerToggle
          label={t("mask")}
          icon={ScanLine}
          checked={showMask}
          onChange={setShowMask}
        />
      )}
      {detection && (
        <LayerToggle
          label={t("detectionBoxes")}
          icon={Scan}
          checked={showBoxes}
          onChange={setShowBoxes}
        />
      )}
      {(showMask || showHeatmap) && (
        <ResultRange
          label={t("opacity")}
          value={opacity}
          onChange={setOpacity}
          step={0.05}
          formatted={`${Math.round(opacity * 100)}%`}
        />
      )}
      {(showBoxes || (showMask && segmentation)) && (
        <ResultRange
          label={t("threshold")}
          value={threshold}
          onChange={setThreshold}
          step={0.01}
          formatted={threshold.toFixed(2)}
        />
      )}
    </section>
  );
}
