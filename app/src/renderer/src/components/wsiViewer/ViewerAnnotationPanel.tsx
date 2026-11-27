import { useState, type ReactNode } from "react";
import {
  Check,
  ChevronDown,
  ChevronRight,
  SlidersHorizontal,
  FolderPlus,
  Square,
  PenLine,
  Ruler,
  Trash2,
  Copy,
  Share2,
  Merge,
  Scissors,
  CheckCircle2,
  Loader2,
  Focus,
} from "lucide-react";
import * as Menu from "@radix-ui/react-dropdown-menu";
import * as Switch from "@radix-ui/react-switch";
import { Button } from "../ui/button";
import { Select } from "../ui/select";
import { Input } from "../ui/input";
import { Tooltip } from "../ui/tooltip";
import { ViewerRegionList } from "./ViewerRegionList";
import { useViewerText, type ViewerTextKey } from "./viewerText";
import type { useViewerAnnotations } from "./useViewerAnnotations";
import type {
  ViewerContext,
  AnnotationLayer,
  Geometry,
  ViewerCapabilities,
} from "../../api/viewer";
import type { ViewerTool } from "./ViewerCanvas";

export function ViewerDisclosure({
  title,
  children,
  open,
  onOpen,
}: {
  title: string;
  children: ReactNode;
  open: boolean;
  onOpen: () => void;
}) {
  return (
    <section className="viewer-disclosure">
      <button
        className="viewer-disclosure-heading"
        aria-expanded={open}
        onClick={onOpen}
      >
        <span>{title}</span>
        <ChevronRight size={15} className={open ? "rotate-90" : ""} />
      </button>
      {open && <div className="viewer-disclosure-body">{children}</div>}
    </section>
  );
}
export function ViewerAnnotationPanel({
  annotation,
  context,
  layer,
  onLayer,
  label,
  onLabel,
  color,
  onColor,
  tool,
  onTool,
  onFocus,
  onDerive,
  onPublish,
  onReference,
  onMeasure,
  onGeometry,
  showReference,
  onShowReference,
  measurement,
  busy,
  capabilities,
  method,
  onMethod,
  promptModel,
  onPromptModel,
  points,
  onClearPoints,
  onUndoPoint,
  onAssist,
  featureId,
  onFeature,
  onSimilar,
  planReason,
  onPlan,
}: {
  annotation: ReturnType<typeof useViewerAnnotations>;
  context?: ViewerContext;
  layer: AnnotationLayer;
  onLayer: (v: AnnotationLayer) => void;
  label: string;
  onLabel: (v: string) => void;
  color: string;
  onColor: (v: string) => void;
  tool: ViewerTool;
  onTool: (v: ViewerTool) => void;
  onFocus: (g: Geometry) => void;
  onDerive: () => void;
  onPublish: () => void;
  onReference: () => void;
  onMeasure: () => void;
  onGeometry: (v: "union" | "split") => void;
  showReference: boolean;
  onShowReference: (v: boolean) => void;
  measurement: string;
  busy: boolean;
  capabilities?: ViewerCapabilities;
  method: string;
  onMethod: (v: string) => void;
  promptModel: string;
  onPromptModel: (v: string) => void;
  points: number[][];
  onClearPoints: () => void;
  onUndoPoint: () => void;
  onAssist: () => void;
  featureId: string;
  onFeature: (v: string) => void;
  onSimilar: () => void;
  planReason: string;
  onPlan: () => void;
}) {
  const { t } = useViewerText();
  const [section, setSection] = useState<"assist" | "similar" | null>("assist");
  const chosen = annotation.selected.length,
    disabled = busy || annotation.saving || annotation.pendingEdit;
  const menuItem = (
    key: ViewerTextKey,
    Icon: typeof Square,
    action: () => void,
    off = false,
  ) => (
    <Menu.Item className="viewer-menu-item" disabled={off} onSelect={action}>
      <Icon size={16} />
      {t(key)}
    </Menu.Item>
  );
  const start = (next: ViewerTool) => {
    onTool(next);
  };
  return (
    <div className="viewer-annotation-panel">
      <div className="viewer-inspector-heading">
        <Select
          ariaLabel={t("annotations")}
          value={layer}
          disabled={annotation.saving}
          className="viewer-layer-select"
          onChange={(value) => onLayer(value as AnnotationLayer)}
          options={[
            { value: "personal", label: t("personal") },
            ...(context?.can_shared
              ? [{ value: "shared", label: t("shared") }]
              : []),
          ]}
        />
        <Menu.Root>
          <Tooltip content={t("annotationSettings")}>
            <Menu.Trigger
              className="viewer-icon"
              aria-label={t("annotationSettings")}
            >
              <SlidersHorizontal size={17} />
            </Menu.Trigger>
          </Tooltip>
          <Menu.Portal>
            <Menu.Content className="viewer-menu" align="end" sideOffset={8}>
              {menuItem("derive", FolderPlus, onDerive, annotation.total === 0)}
            </Menu.Content>
          </Menu.Portal>
        </Menu.Root>
      </div>
      <div className="viewer-save-state" role="status">
        {annotation.saving ? (
          <Loader2 size={12} className="animate-spin" />
        ) : annotation.pendingEdit ? (
          <span className="viewer-pending-dot" />
        ) : (
          <Check size={12} />
        )}
        <span>
          {t(
            annotation.saving
              ? "saving"
              : annotation.pendingEdit
                ? "pendingSave"
                : "autoSaved",
          )}
        </span>
      </div>
      <div className="viewer-inspector-scroll">
        {(annotation.total > 0 || tool !== "select") && (
          <section className="viewer-property-section">
            <div className="viewer-section-caption">
              {t(chosen ? "selectedStyle" : "drawingStyle")}
            </div>
            <div className="viewer-label-editor">
              <label className="viewer-color-well" title={t("annotationColor")}>
                <span style={{ background: color }} />
                <input
                  type="color"
                  aria-label={t("annotationColor")}
                  value={color}
                  onChange={(e) => onColor(e.target.value)}
                />
              </label>
              <Input
                aria-label={t("label")}
                value={label}
                placeholder={t("label")}
                maxLength={100}
                onChange={(e) => onLabel(e.target.value)}
              />
              {chosen > 0 && (
                <Tooltip content={t("applyLabel")}>
                  <button
                    className="viewer-icon"
                    aria-label={t("applyLabel")}
                    disabled={disabled}
                    onClick={() => void annotation.relabel(label, color)}
                  >
                    <Check size={17} />
                  </button>
                </Tooltip>
              )}
            </div>
          </section>
        )}
        {chosen > 0 && (
          <section className="viewer-selection-section">
            <div className="viewer-selection-heading">
              <span>
                {chosen} {t("selectedCount")}
              </span>
              <button onClick={() => annotation.setSelected([])}>
                {t("deselect")}
              </button>
            </div>
            <div className="viewer-selection-actions">
              <Button
                variant="secondary"
                size="sm"
                disabled={disabled}
                onClick={onMeasure}
              >
                <Ruler size={14} />
                {t("measure")}
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={disabled}
                onClick={() => void annotation.remove()}
              >
                <Trash2 size={14} />
                {t("removeShort")}
              </Button>
              <Menu.Root>
                <Menu.Trigger
                  className="viewer-secondary-button"
                  disabled={disabled}
                >
                  {t("selectionActions")}
                  <ChevronDown size={13} />
                </Menu.Trigger>
                <Menu.Portal>
                  <Menu.Content
                    className="viewer-menu"
                    align="end"
                    sideOffset={8}
                  >
                    {context?.can_shared &&
                      menuItem(
                        layer === "personal" ? "publish" : "copy",
                        layer === "personal" ? Share2 : Copy,
                        onPublish,
                      )}
                    {context?.can_manage &&
                      context.data_type === "patch" &&
                      menuItem("finalize", CheckCircle2, onReference)}
                    <Menu.Separator className="viewer-menu-separator" />
                    {menuItem(
                      "merge",
                      Merge,
                      () => onGeometry("union"),
                      chosen < 2,
                    )}
                    {menuItem(
                      "split",
                      Scissors,
                      () => onGeometry("split"),
                      chosen !== 1,
                    )}
                  </Menu.Content>
                </Menu.Portal>
              </Menu.Root>
            </div>
            {measurement && <p className="viewer-measurement">{measurement}</p>}
          </section>
        )}
        {annotation.total === 0 && !annotation.loading ? (
          <div className="viewer-annotation-empty">
            <div className="viewer-empty-symbol">
              <Square size={27} strokeWidth={1.3} />
              <PenLine size={17} strokeWidth={1.5} />
            </div>
            <h2>{t("startAnnotating")}</h2>
            <p>{t("annotationEmptyHint")}</p>
            <Button
              className="viewer-start-button"
              variant="default"
              onClick={() => start("rect")}
            >
              <Square size={15} />
              {t("drawRegion")}
            </Button>
            <span className="viewer-empty-secondary">
              {t(
                layer === "personal"
                  ? "annotationSaveHint"
                  : "teamAnnotationHint",
              )}
            </span>
          </div>
        ) : (
          <ViewerRegionList annotation={annotation} onFocus={onFocus} />
        )}
        <div className="viewer-reference-row">
          <div>
            <span>{t("groundTruth")}</span>
            <p>{t("referenceHint")}</p>
          </div>
          <Switch.Root
            className="viewer-switch"
            checked={showReference}
            onCheckedChange={onShowReference}
            aria-label={t("groundTruth")}
          >
            <Switch.Thumb className="viewer-switch-thumb" />
          </Switch.Root>
        </div>
          <>
            <ViewerDisclosure
              title={t("assistance")}
              open={section === "assist"}
              onOpen={() => setSection(section === "assist" ? null : "assist")}
            >
              <p className="viewer-assist-hint">{t(chosen ? "assistSelectedScope" : "assistVisibleScope")}</p>
              <Select
                ariaLabel={t("assistance")}
                value={method}
                onChange={(value) => { onMethod(value); onClearPoints(); onTool("select"); }}
                options={[
                  ...(["grabcut", "wand", "scribble", "nuclei"] as const).map(
                    (key) => ({ value: key, label: t(key) }),
                  ),
                  ...(capabilities?.prompt_models.length
                    ? [{ value: "model", label: t("model") }]
                    : []),
                ]}
              />
              {method === "model" && (
                <Select
                  ariaLabel={t("model")}
                  value={promptModel}
                  onChange={onPromptModel}
                  options={(capabilities?.prompt_models || []).map((item) => ({
                    value: item.id,
                    label: item.name,
                  }))}
                />
              )}
              {(method === "scribble" || method === "wand" || method === "model") &&
                <p className="viewer-assist-hint">{t("assistPointsHint")}</p>}
              {method !== "nuclei" && <div className="viewer-prompt-buttons">
                <button
                  aria-pressed={tool === "positive"}
                  disabled={disabled}
                  onClick={() => onTool("positive")}
                >
                  <span className="viewer-keep-dot" />
                  {t("positive")}
                </button>
                <button
                  aria-pressed={tool === "negative"}
                  disabled={disabled}
                  onClick={() => onTool("negative")}
                >
                  <span className="viewer-exclude-dot" />
                  {t("negative")}
                </button>
                {points.length > 0 && (
                  <>
                    <button type="button" disabled={disabled} onClick={onUndoPoint}>{t("undoPoint")}</button>
                    <button type="button" disabled={disabled} onClick={onClearPoints}>{t("clearPoints")}</button>
                  </>
                )}
              </div>}
              <Button
                variant="secondary"
                disabled={disabled}
                onClick={onAssist}
              >
                {busy ? (
                  <Loader2 size={15} className="animate-spin" />
                ) : (
                  <Focus size={15} />
                )}{" "}
                {t("run")}
              </Button>
            </ViewerDisclosure>
            <ViewerDisclosure
              title={t("similar")}
              open={section === "similar"}
              onOpen={() =>
                setSection(section === "similar" ? null : "similar")
              }
            >
              {capabilities?.features.some((item) => item.image_similarity) ? (
                <>
                  <p className="viewer-assist-hint">
                    {t(chosen === 0 ? "similarChooseHint" : chosen === 1 ? "similarReadyHint" : "similarOneHint")}
                  </p>
                  {chosen === 0 && <Button
                    variant="secondary"
                    disabled={disabled}
                    onClick={() => onTool("rect")}
                  >
                    <Square size={15} />
                    {t("similarDrawExample")}
                  </Button>}
                  {chosen > 1 && <Button
                    variant="secondary"
                    disabled={disabled}
                    onClick={() => onTool("select")}
                  >{t("select")}</Button>}
                  {capabilities.features.filter((item) => item.image_similarity).length > 1 && <Select
                    ariaLabel={t("featureModel")}
                    value={featureId}
                    onChange={onFeature}
                    options={capabilities.features
                      .filter((item) => item.image_similarity)
                      .map((item, index) => ({
                        value: item.id,
                        label: `${item.model_id}${capabilities.features.filter((f) => f.model_id === item.model_id).length > 1 ? " (" + (index + 1) + ")" : ""}`,
                      }))}
                  />}
                  <Button
                    variant="secondary"
                    disabled={disabled || !featureId || chosen !== 1}
                    onClick={onSimilar}
                  >
                    {busy ? <Loader2 size={15} className="animate-spin" /> : <Focus size={15} />}
                    {t("similarSearch")}
                  </Button>
                </>
              ) : (
                <div className="viewer-capability-note">
                  <p>
                    {t(
                      capabilities?.features.length
                        ? "feature_coordinates_missing"
                        : "features_missing",
                    )}
                  </p>
                  <Button variant="secondary" size="sm" onClick={onPlan}>
                    {t("chat")}
                  </Button>
                </div>
              )}
              {planReason && (
                <div className="viewer-capability-note">
                  <p>{planReason}</p>
                  <Button variant="secondary" size="sm" onClick={onPlan}>
                    {t("chat")}
                  </Button>
                </div>
              )}
            </ViewerDisclosure>
          </>
      </div>
    </div>
  );
}
