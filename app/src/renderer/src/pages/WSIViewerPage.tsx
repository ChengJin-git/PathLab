import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  PanelRight,
  MessageSquare,
  Loader2,
  Layers2,
  ChartNoAxesCombined,
  ScanLine,
  X,
} from "lucide-react";
import WSIViewer from "../components/WSIViewer";
import { fetchAvailableHeatmaps, type HeatmapData } from "../api/heatmap";
import { extractRegions, getWSILabels } from "../api/annotation";
import * as api from "../api/viewer";
import { useAuth } from "../contexts/AuthContext";
import { useBackgroundTask } from "../contexts/BackgroundTaskContext";
import {
  useViewerText,
  type ViewerTextKey,
} from "../components/wsiViewer/viewerText";
import { useViewerAnnotations } from "../components/wsiViewer/useViewerAnnotations";
import {
  ViewerCanvas,
  type ViewerTool,
} from "../components/wsiViewer/ViewerCanvas";
import { ViewerResults } from "../components/wsiViewer/ViewerResults";
import { ViewerAssistant } from "../components/wsiViewer/ViewerAssistant";
import { ViewerAnnotationPanel } from "../components/wsiViewer/ViewerAnnotationPanel";
import { ViewerToolbar } from "../components/wsiViewer/ViewerToolbar";
import * as Tabs from "@radix-ui/react-tabs";
import { useDebounce } from "../lib/hooks/useDebounce";
import { ModalShell } from "../components/ui/modal-shell";
import { Select } from "../components/ui/select";
import "../components/wsiViewer/viewer.css";
import {
  geometryValue as geometry,
  geometryArea,
} from "../components/wsiViewer/viewerGeometry";

type Tab = "results" | "annotations" | "assistant";
export default function WSIViewerPage() {
  const { wsi_id = "" } = useParams();
  return <ViewerWorkspace key={wsi_id} id={wsi_id} />;
}

function ViewerWorkspace({ id }: { id: string }) {
  const { t, language } = useViewerText();
  const { user } = useAuth();
  const navigate = useNavigate(),
    location = useLocation(),
    cache = useQueryClient();
  const { addExtractionTask } = useBackgroundTask();
  const [viewer, setViewer] = useState<any>(null),
    [tab, setTab] = useState<Tab>("results"),
    [side, setSide] = useState(() => window.innerWidth > 640),
    [layer, setLayer] = useState<api.AnnotationLayer>("personal");
  const inspectorToggle = useRef<HTMLButtonElement>(null);
  const [tool, setTool] = useState<ViewerTool>("select"),
    [label, setLabel] = useState(t("unlabelled")),
    [color, setColor] = useState("#6366f1");
  const [bounds, setBounds] = useState<api.Geometry>(),
    [preview, setPreview] = useState<api.Geometry[]>([]),
    [previewLabel, setPreviewLabel] = useState(""),
    [points, setPoints] = useState<number[][]>([]);
  const [selectedResult, setSelectedResult] = useState(""),
    [showHeatmap, setShowHeatmap] = useState(false),
    [heatmap, setHeatmap] = useState<HeatmapData | null>(null),
    [opacity, setOpacity] = useState(0.5),
    [threshold, setThreshold] = useState(0.5);
  const [resultAction, setResultAction] = useState<{
    type: "attention" | "filter";
    serial: number;
  }>();
  const attentionPending = useRef(false);
  const [featureId, setFeatureId] = useState(""),
    [method, setMethod] = useState("grabcut"),
    [promptModel, setPromptModel] = useState("");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [planReason, setPlanReason] = useState(""),
    [showCreate, setShowCreate] = useState(false),
    [datasetName, setDatasetName] = useState(""),
    [taskType, setTaskType] = useState("patch_classification");
  const [showGT, setShowGT] = useState(false),
    [measurement, setMeasurement] = useState<string>(""),
    [proposal, setProposal] = useState<api.ViewerReply | null>(null);
  const context = useQuery({
    queryKey: ["viewer-context", user?.id, id],
    queryFn: ({ signal }) => api.viewerContext(id, signal),
  });
  const catalog = useQuery({
    queryKey: ["viewer-results", user?.id, id],
    queryFn: ({ signal }) => fetchAvailableHeatmaps(id, signal),
    staleTime: 0,
  });
  const capabilities = useQuery({
    queryKey: ["viewer-capabilities", user?.id, id],
    queryFn: ({ signal }) => api.viewerCapabilities(id, signal),
    enabled: tab === "assistant" || tab === "annotations",
  });
  useEffect(() => {
    const features = capabilities.data?.features.filter(
      (item) => item.image_similarity,
    );
    if (features?.length && !features.some((f) => f.id === featureId))
      setFeatureId(features[0].id);
  }, [capabilities.data, featureId]);
  const viewport = useDebounce(bounds, 180),
    annotation = useViewerAnnotations(id, layer, viewport);
  const truth = useQuery({
    queryKey: ["viewer-labels", user?.id, id],
    queryFn: () => getWSILabels(id),
    enabled: showGT,
  });
  const controller = useRef<AbortController>();
  useEffect(() => () => controller.current?.abort(), []);
  const entries = catalog.data || [];
  useEffect(() => {
    if (!selectedResult && entries.length) {
      const state = location.state as {
        selectedTaskId?: string;
        selectedFoldKey?: string;
      } | null;
      const entry =
        entries.find(
          (item) =>
            item.task_id === state?.selectedTaskId &&
            (!state?.selectedFoldKey ||
              item.fold_key === state.selectedFoldKey),
        ) || entries[0];
      setSelectedResult(`${entry.task_id}:${entry.fold_key || ""}`);
    }
  }, [entries, selectedResult]);
  const entry = entries.find(
    (item) => `${item.task_id}:${item.fold_key || ""}` === selectedResult,
  );
  const chosen = annotation.regions.filter((item) =>
    annotation.selected.includes(item.id),
  );
  const selection = chosen[0];
  useEffect(() => {
    if (selection) {
      setLabel(selection.label);
      setColor(selection.color);
    }
  }, [selection?.id]);
  const focus = useCallback(
    (region: api.Geometry) => {
      const image = viewer?.world?.getItemAt(0);
      if (!image) return;
      const pad = Math.max(region.width, region.height) * 0.2;
      viewer.viewport.fitBounds(
        image.imageToViewportRectangle(
          region.x - pad,
          region.y - pad,
          region.width + 2 * pad,
          region.height + 2 * pad,
        ),
        false,
      );
    },
    [viewer],
  );
  const showPreview = (regions: api.Geometry[], title = "") => {
    setPreview(regions.map(geometry));
    setPreviewLabel(title);
    if (regions[0]) focus(regions[0]);
  };
  useEffect(() => {
    if (attentionPending.current && heatmap?.top_patches?.length) {
      attentionPending.current = false;
      showPreview(
        heatmap.top_patches.slice(0, 5).map((p) => ({
          type: "rect",
          x: p.x,
          y: p.y,
          width: heatmap.patch_size,
          height: heatmap.patch_size,
        })),
        t("heatmap"),
      );
    }
  }, [heatmap]);
  const plan = (goal = t("defaultGoal")) => {
    const data = context.data;
    if (!data) return;
    const draft = t("chatDraft")
      .replace("{dataset}", data.dataset_name || "")
      .replace("{slide}", data.name || id)
      .replace("{goal}", goal);
    navigate("/dashboard", {
      state: {
        toolDraft: draft,
        references: [
          ...(data.dataset_id
            ? [{ kind: "dataset", id: data.dataset_id }]
            : []),
          { kind: "slide", id },
        ],
      },
    });
  };
  const act = async (fn: () => Promise<void>) => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      const code = (e as Error).message;
      const known = [
        "region_too_large",
        "region_too_small",
        "need_positive_negative",
        "select_example",
      ];
      setError(known.includes(code) ? t(code as ViewerTextKey) : t("failed"));
    } finally {
      setBusy(false);
    }
  };
  const navigateSlide = (target: string) => {
    if (annotation.saving || busy) return;
    navigate("/wsi/" + target, { state: location.state });
  };
  useEffect(() => {
    if (!context.data) return;
    for (const target of [context.data.previous, context.data.next])
      if (target)
        void cache.prefetchQuery({
          queryKey: ["viewer-results", user?.id, target],
          queryFn: ({ signal }) => fetchAvailableHeatmaps(target, signal),
          staleTime: 10000,
        });
  }, [context.data, cache, user?.id]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (
        (e.target as HTMLElement)?.closest(
          "input,textarea,[contenteditable=true]",
        )
      )
        return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        void (e.shiftKey ? annotation.redo() : annotation.undo());
      } else if (e.key === "Delete" && annotation.selected.length) {
        e.preventDefault();
        void annotation.remove();
      } else if (e.key === "q" && context.data?.previous)
        navigateSlide(context.data.previous);
      else if (e.key === "e" && context.data?.next)
        navigateSlide(context.data.next);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [annotation, context.data]);
  const replaceChosen = async (regions: api.Geometry[]) => {
    const values = regions.map((r, index) => ({
      ...r,
      id: index === 0 && selection ? selection.id : crypto.randomUUID(),
      revision: index === 0 && selection ? selection.revision : 0,
      label: selection?.label || label,
      color: selection?.color || color,
    }));
    const ids = [
      ...new Set([...annotation.selected, ...values.map((r) => r.id)]),
    ];
    await annotation.apply(
      [
        ...annotation.regions.filter(
          (r) => !annotation.selected.includes(r.id),
        ),
        ...values,
      ],
      ids,
    );
  };
  const changeShape = (
    operation: string,
    stroke?: number[][],
    radius?: number,
  ) =>
    void act(async () => {
      const result = await api.changeGeometry(id, {
        operation,
        regions: chosen.map(geometry),
        points: stroke,
        radius,
      });
      if (chosen.length) await replaceChosen(result.regions);
      else
        await annotation.create(
          result.regions.map((r) => ({ ...r, label, color })),
        );
    });
  const copyTo = async (target: api.AnnotationLayer) => {
    if (!chosen.length) return;
    const changes = chosen.map((region) => ({
      id: crypto.randomUUID(),
      revision: 0,
      value: api.regionValue(region),
    }));
    await api.saveViewerRegions(id, target, changes, crypto.randomUUID());
    setLayer(target);
    annotation.setSelected([]);
  };
  const assist = () =>
    void act(async () => {
      const region = selection ? geometry(selection) : bounds;
      if (!region) {
        setError(t("assistViewMissing"));
        return;
      }
      controller.current = new AbortController();
      const result = await api.assistRegion(
        id,
        {
          region,
          method,
          points,
          model_id: promptModel || undefined,
        },
        controller.current.signal,
      );
      showPreview(result.regions, t("preview"));
      if (!result.regions.length) setError(t("noPreview"));
    });
  const similar = () =>
    void act(async () => {
      if (!selection || chosen.length !== 1) {
        setError(t("similarOneHint"));
        return;
      }
      if (!featureId) {
        setPlanReason(t("features_missing"));
        return;
      }
      const result = await api.searchViewerFeatures(id, {
        feature_id: featureId,
        region: geometry(selection),
      });
      if (result.status === "handoff") {
        setPlanReason(
          t((result.reason || "features_missing") as ViewerTextKey),
        );
        return;
      }
      showPreview(result.regions, t("similarity"));
      if (!result.regions.length) setError(t("noPreview"));
    });
  const receive = (reply: api.ViewerReply) => {
    if (reply.action === "highlight") showPreview(reply.regions, t("semantic"));
    else if (reply.action === "filter" && reply.threshold !== undefined) {
      setThreshold(reply.threshold);
      setResultAction({ type: "filter", serial: Date.now() });
      setTab("results");
    } else if (reply.action === "attention") {
      attentionPending.current = true;
      setResultAction({ type: "attention", serial: Date.now() });
      setShowHeatmap(true);
      setTab("results");
      if (heatmap?.top_patches?.length) {
        attentionPending.current = false;
        showPreview(
          heatmap.top_patches.slice(0, 5).map((p) => ({
            type: "rect",
            x: p.x,
            y: p.y,
            width: heatmap.patch_size,
            height: heatmap.patch_size,
          })),
          t("heatmap"),
        );
      }
    } else if (reply.action === "label") setProposal(reply);
    else if (reply.measurement)
      setMeasurement(
        `${reply.measurement.count} ${t("objects")}, ${t("area")}: ${(reply.measurement.area_um2 ?? reply.measurement.area_px).toFixed(1)} ${reply.measurement.area_um2 !== null ? "μm²" : "px²"}`,
      );
  };
  const measure = () => {
    if (!chosen.length) return;
    const area = chosen.reduce((sum, r) => sum + geometryArea(r), 0);
    setMeasurement(
      `${chosen.length} ${t("objects")}, ${t("area")}: ${(context.data?.mpp ? area * context.data.mpp ** 2 : area).toFixed(1)} ${context.data?.mpp ? "μm²" : "px²"}`,
    );
  };
  const gt = showGT ? truth.data?.annotations[id] || [] : [];
  return (
    <section className="viewer-workspace research-surface">
      <header className="viewer-topbar">
        <button
          aria-label={t("backToDataset")}
          title={t("backToDataset")}
          className="viewer-icon viewer-back"
          onClick={() =>
            navigate("/datasets", {
              state: { dataset_id: context.data?.dataset_id },
            })
          }
        >
          <ArrowLeft size={18} />
        </button>
        <div className="viewer-identity">
          <span>{context.data?.dataset_name || t("title")}</span>
          <h1 title={context.data?.name}>{context.data?.name || t("title")}</h1>
        </div>
        <div className="viewer-slide-navigation" role="group" aria-label={t("title")}>
        <button
          className="viewer-icon"
          aria-label={t("previous")}
          title={t("previous")}
          disabled={!context.data?.previous || annotation.saving || busy}
          onClick={() =>
            context.data?.previous && navigateSlide(context.data.previous)
          }
        >
          <ChevronLeft size={18} />
        </button>
        <button
          className="viewer-icon"
          aria-label={t("next")}
          title={t("next")}
          disabled={!context.data?.next || annotation.saving || busy}
          onClick={() => context.data?.next && navigateSlide(context.data.next)}
        >
          <ChevronRight size={18} />
        </button>
        </div>
        <div className="viewer-topbar-actions">
        <button
          className="viewer-icon"
          aria-label={t("assistant")}
          title={t("assistant")}
          aria-pressed={tab === "assistant" && side}
          onClick={() => {
            setTab("assistant");
            setSide(true);
          }}
        >
          <MessageSquare size={17} />
        </button>
        <button
          className="viewer-icon"
          ref={inspectorToggle}
          aria-label={t("results")}
          title={t("inspector")}
          aria-pressed={side}
          aria-expanded={side}
          aria-controls="slide-inspector"
          onClick={() => setSide((v) => !v)}
        >
          <PanelRight size={18} />
        </button>
        </div>
      </header>
      <div className="viewer-body">
        <div className="viewer-slide">
          <WSIViewer
            controls={false}
            wsi_id={id}
            showHeatmap={showHeatmap && entry?.data_type !== "patch"}
            heatmapOpacity={opacity}
            taskId={entry?.task_id || undefined}
            foldKey={entry?.fold_key || undefined}
            dataLevel={context.data?.data_type || "wsi"}
            onViewerReady={setViewer}
            onHeatmapLoaded={setHeatmap}
          />
          <ViewerCanvas
            viewer={viewer}
            regions={[
              ...annotation.regions,
              ...gt.map((r) => ({
                ...r,
                revision: 0,
                id: "gt-" + r.id,
                color: "#16a34a",
              })),
            ]}
            preview={preview}
            selected={annotation.selected}
            onSelect={annotation.setSelected}
            tool={tool}
            label={label}
            color={color}
            enabled={tab === "annotations"}
            busy={busy || annotation.saving || annotation.pendingEdit}
            onCreate={(value) => void annotation.create([value])}
            onUpdate={(value) => void annotation.update(value)}
            onStroke={(points, radius, subtract) =>
              changeShape(subtract ? "erase" : "brush", points, radius)
            }
            onPrompt={(point) =>
              setPoints((previous) => [...previous.slice(-255), point])
            }
            promptPoints={points}
            onRemovePrompt={(index) => setPoints((previous) => previous.filter((_, i) => i !== index))}
            onViewport={setBounds}
          />
          <ViewerToolbar
            viewer={viewer}
            annotating={tab === "annotations"}
            tool={tool}
            onTool={setTool}
            busy={busy || annotation.saving || annotation.pendingEdit}
            canUndo={annotation.canUndo}
            canRedo={annotation.canRedo}
            onUndo={() => void annotation.undo()}
            onRedo={() => void annotation.redo()}
          />
          <div className="viewer-canvas-label" aria-hidden="true">
            <ScanLine size={15} strokeWidth={1.5} />
            <span>{t("originalImage")}</span>
          </div>
          {annotation.saving && (
            <div className="viewer-status" role="status">
              {t("saving")}
            </div>
          )}
          {!!preview.length && (
            <div className="viewer-preview">
              <span>
                {previewLabel} <span className="viewer-preview-count">{preview.length} {t("objects")}</span>
              </span>
              <button
                className="viewer-link"
                disabled={annotation.saving}
                onClick={() =>
                  void act(async () => {
                    if (layer !== "personal") {
                      await api.saveViewerRegions(
                        id,
                        "personal",
                        preview.map((r) => ({
                          id: crypto.randomUUID(),
                          revision: 0,
                          value: { ...r, label, color },
                        })),
                        crypto.randomUUID(),
                      );
                      setLayer("personal");
                    } else
                      await annotation.create(
                        preview.map((r) => ({ ...r, label, color })),
                      );
                    setPreview([]);
                    setTab("annotations");
                  })
                }
              >
                {t("accept")}
              </button>
              <button className="viewer-link" onClick={() => setPreview([])}>
                {t("clear")}
              </button>
            </div>
          )}
        </div>
        <aside
          id="slide-inspector"
          className="viewer-side"
          aria-label={t("inspector")}
          style={{ display: side ? undefined : "none" }}
        >
          <div className="viewer-side-heading">
            <span>{t("inspector")}</span>
            <button
              type="button"
              className="viewer-icon"
              aria-label={t("closeInspector")}
              onClick={() => { setSide(false); inspectorToggle.current?.focus(); }}
            ><X size={16} /></button>
          </div>
          <Tabs.Root
            value={tab}
            onValueChange={(value) => setTab(value as Tab)}
          >
            <Tabs.List className="viewer-tabs" aria-label={t("inspector")}>
              {(["results", "annotations", "assistant"] as Tab[]).map(
                (value) => {
                  const Icon = value === "results" ? ChartNoAxesCombined : value === "annotations" ? Layers2 : MessageSquare;
                  return <Tabs.Trigger key={value} value={value} id={`viewer-tab-${value}`} aria-controls={`viewer-panel-${value}`}>
                    <Icon size={15} strokeWidth={1.7} aria-hidden="true" />
                    {t(value)}
                  </Tabs.Trigger>;
                },
              )}
            </Tabs.List>
          </Tabs.Root>
          {(error || annotation.error || context.error) && (
            <div className="viewer-error" role="alert">
              {error || annotation.error || t("failed")}
              <button
                className="ml-2 underline"
                onClick={() => {
                  setError("");
                  void annotation.retry();
                  void context.refetch();
                }}
              >
                {t("retry")}
              </button>
              {annotation.pendingEdit && (
                <div className="viewer-actions">
                  <button onClick={() => void annotation.preserve()}>
                    {t("saveCopy")}
                  </button>
                  <button onClick={annotation.discard}>{t("discard")}</button>
                </div>
              )}
            </div>
          )}
          <div id="viewer-panel-results" role="tabpanel" aria-labelledby="viewer-tab-results" className="viewer-tab-panel" hidden={tab !== "results"}>
            {catalog.isLoading ? (
              <div className="viewer-empty">
                <Loader2 className="animate-spin" size={18} />
              </div>
            ) : catalog.error ? (
              <div className="viewer-empty" role="alert">
                {t("failed")}
                <button onClick={() => void catalog.refetch()}>
                  {t("retry")}
                </button>
              </div>
            ) : (
              <ViewerResults
                viewer={viewer}
                id={id}
                entries={entries}
                selected={selectedResult}
                onSelected={(value) => {
                  setSelectedResult(value);
                  setShowHeatmap(false);
                }}
                heatmap={heatmap}
                opacity={opacity}
                setOpacity={setOpacity}
                showHeatmap={showHeatmap}
                setShowHeatmap={setShowHeatmap}
                threshold={threshold}
                setThreshold={setThreshold}
                onFocus={focus}
                onPlan={() => plan()}
                action={resultAction}
              />
            )}
          </div>
          {tab === "annotations" && (
            <div id="viewer-panel-annotations" role="tabpanel" aria-labelledby="viewer-tab-annotations" className="viewer-tab-panel">
            <ViewerAnnotationPanel
              annotation={annotation}
              context={context.data}
              layer={layer}
              onLayer={(value) => {
                setLayer(value);
                setPoints([]);
              }}
              label={label}
              onLabel={setLabel}
              color={color}
              onColor={setColor}
              tool={tool}
              onTool={setTool}
              onFocus={focus}
              onDerive={() => setShowCreate(true)}
              onPublish={() =>
                void act(() =>
                  copyTo(layer === "personal" ? "shared" : "personal"),
                )
              }
              onReference={() =>
                void act(async () => {
                  await api.publishViewerReference(
                    id,
                    layer,
                    chosen.map((r) => ({ id: r.id, revision: r.revision })),
                  );
                  setShowGT(true);
                  void truth.refetch();
                })
              }
              onMeasure={measure}
              onGeometry={(operation) => {
                if (operation === "union") changeShape(operation);
                else if (selection) {
                  const x = selection.x + selection.width / 2;
                  changeShape("split", [
                    [x, selection.y - 1],
                    [x, selection.y + selection.height + 1],
                  ]);
                }
              }}
              showReference={showGT}
              onShowReference={setShowGT}
              measurement={measurement}
              busy={busy}
              capabilities={capabilities.data}
              method={method}
              onMethod={setMethod}
              promptModel={promptModel}
              onPromptModel={setPromptModel}
              points={points}
              onClearPoints={() => setPoints([])}
              onUndoPoint={() => setPoints((previous) => previous.slice(0, -1))}
              onAssist={assist}
              featureId={featureId}
              onFeature={setFeatureId}
              onSimilar={similar}
              planReason={planReason}
              onPlan={() => plan(t("similar"))}
            />
            </div>
          )}
          {tab === "assistant" && context.data && (
            <div id="viewer-panel-assistant" role="tabpanel" aria-labelledby="viewer-tab-assistant" className="viewer-tab-panel">
            <ViewerAssistant
              context={context.data}
              capabilities={capabilities.data}
              layer={layer}
              taskId={entry?.task_id || undefined}
              selected={annotation.selected}
              selection={selection ? geometry(selection) : undefined}
              featureId={featureId}
              onFeature={setFeatureId}
              onReply={receive}
              onPlan={plan}
            />
            </div>
          )}
        </aside>
      </div>
      <footer className="viewer-infobar">
        <span>{t("title")}</span>
        {context.data?.width && context.data.height ? <span aria-label={t("slideDimensions")}>{context.data.width.toLocaleString()} × {context.data.height.toLocaleString()} px</span> : null}
        {context.data?.mpp ? <span>{context.data.mpp} μm/px</span> : null}
        <span className="viewer-infobar-hint">{t("canvasHint")}</span>
      </footer>
      {proposal && (
        <ModalShell
          isOpen
          onClose={() => setProposal(null)}
          title={t("applyLabel")}
          maxWidth="sm"
        >
          <div className="viewer-panel-content">
            <p>{proposal.label}</p>
            <button
              className="viewer-button viewer-button-primary"
              onClick={() =>
                void act(async () => {
                  await annotation.relabel(proposal.label || label);
                  setProposal(null);
                })
              }
            >
              {t("applyLabel")}
            </button>
          </div>
        </ModalShell>
      )}
      {showCreate && (
        <ModalShell
          isOpen
          onClose={() => setShowCreate(false)}
          title={t("derive")}
          maxWidth="md"
        >
          <div className="viewer-panel-content">
            <h2 className="text-base font-semibold">{t("derive")}</h2>
            <label className="viewer-field">
              {t("datasetName")}
              <input
                value={datasetName}
                onChange={(e) => setDatasetName(e.target.value)}
                maxLength={255}
              />
            </label>
            <Select
              ariaLabel={t("analysisType")}
              value={taskType}
              onChange={setTaskType}
              options={[
                { value: "patch_classification", label: t("classification") },
                ...(context.data?.data_type === "patch"
                  ? [
                      { value: "patch_segmentation", label: t("segmentation") },
                      { value: "patch_detection", label: t("detection") },
                    ]
                  : []),
              ]}
            />
            <p className="text-xs leading-6 text-slate-500">
              {t("accessHint")}
            </p>
            <button
              disabled={!datasetName.trim() || busy}
              className="viewer-button viewer-button-primary"
              onClick={() =>
                void act(async () => {
                  const result = await extractRegions({
                    dataset_name: datasetName,
                    task_type: taskType,
                    source_dataset_id: context.data?.dataset_id || undefined,
                    dataset_scope: !!context.data?.dataset_id,
                    annotation_mode: layer,
                    annotations: context.data?.dataset_id
                      ? undefined
                      : { [id]: annotation.regions },
                  });
                  addExtractionTask(result.task_id, datasetName);
                  setShowCreate(false);
                })
              }
            >
              {t("create")}
            </button>
          </div>
        </ModalShell>
      )}
    </section>
  );
}
