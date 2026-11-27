import { useEffect, useState } from "react";
import {
  MousePointer2,
  Square,
  PenLine,
  Pentagon,
  Paintbrush,
  Eraser,
  Undo2,
  Redo2,
  ZoomIn,
  ZoomOut,
  Scan,
  Maximize,
  Minimize,
  ChevronDown,
} from "lucide-react";
import * as Menu from "@radix-ui/react-dropdown-menu";
import { Tooltip } from "../ui/tooltip";
import type { ViewerTool } from "./ViewerCanvas";
import { useViewerText, type ViewerTextKey } from "./viewerText";

export function ViewerToolbar({
  viewer,
  annotating,
  tool,
  onTool,
  busy,
  canUndo,
  canRedo,
  onUndo,
  onRedo,
}: {
  viewer: any;
  annotating: boolean;
  tool: ViewerTool;
  onTool: (tool: ViewerTool) => void;
  busy: boolean;
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
}) {
  const { t } = useViewerText();
  const [zoom, setZoom] = useState(100),
    [full, setFull] = useState(false);
  useEffect(() => {
    if (!viewer) return;
    const update = () => {
      if (viewer.world.getItemAt(0))
        setZoom(
          Math.round(
            (viewer.viewport.getZoom() / viewer.viewport.getHomeZoom()) * 100,
          ),
        );
    };
    viewer.addHandler("animation", update);
    viewer.addHandler("open", update);
    update();
    return () => {
      viewer.removeHandler("animation", update);
      viewer.removeHandler("open", update);
    };
  }, [viewer]);
  useEffect(() => {
    const update = () => setFull(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", update);
    return () => document.removeEventListener("fullscreenchange", update);
  }, []);
  const tools: [ViewerTool, typeof Square, ViewerTextKey][] = [
    ["select", MousePointer2, "select"],
    ["rect", Square, "rect"],
    ["polygon", Pentagon, "polygon"],
    ["freehand", PenLine, "freehand"],
  ];
  const zoomBy = (factor: number) => {
    viewer?.viewport.zoomBy(factor);
    viewer?.viewport.applyConstraints();
  };
  return (
    <div
      className="viewer-toolbar"
      role="toolbar"
      aria-label={t("canvasTools")}
      data-annotating={annotating}
    >
      {annotating && (
        <>
          <div className="viewer-tool-group viewer-drawing-group">
            {tools.map(([value, Icon, key]) => (
              <Tooltip content={t(key)} key={value}>
                <button
                  type="button"
                  className="viewer-tool-button"
                  aria-label={t(key)}
                  aria-pressed={tool === value}
                  disabled={busy}
                  onClick={() => onTool(value)}
                >
                  <Icon size={18} />
                  <span className="viewer-tool-name">{t(key)}</span>
                </button>
              </Tooltip>
            ))}
            <Menu.Root>
              <Menu.Trigger
                className="viewer-tool-button viewer-tool-menu"
                aria-label={t("refineTools")}
                aria-pressed={tool === "brush" || tool === "erase"}
                disabled={busy}
              >
                {tool === "erase" ? <Eraser size={18} /> : <Paintbrush size={18} />}
                <ChevronDown size={10} />
              </Menu.Trigger>
              <Menu.Portal>
                <Menu.Content className="viewer-menu" sideOffset={8}>
                  <Menu.Item
                    className="viewer-menu-item"
                    onSelect={() => onTool("brush")}
                  >
                    <Paintbrush size={16} />
                    {t("brush")}
                  </Menu.Item>
                  <Menu.Item
                    className="viewer-menu-item"
                    onSelect={() => onTool("erase")}
                  >
                    <Eraser size={16} />
                    {t("erase")}
                  </Menu.Item>
                </Menu.Content>
              </Menu.Portal>
            </Menu.Root>
          </div>
          <div className="viewer-tool-group viewer-history-group">
            <Tooltip content={t("undo")}>
              <button
                className="viewer-tool-button"
                aria-label={t("undo")}
                disabled={!canUndo || busy}
                onClick={onUndo}
              >
                <Undo2 size={17} />
              </button>
            </Tooltip>
            <Tooltip content={t("redo")}>
              <button
                className="viewer-tool-button"
                aria-label={t("redo")}
                disabled={!canRedo || busy}
                onClick={onRedo}
              >
                <Redo2 size={17} />
              </button>
            </Tooltip>
          </div>
        </>
      )}
      <div className="viewer-tool-group viewer-zoom-group">
        <Tooltip content={t("zoomOut")}>
          <button
            className="viewer-tool-button"
            aria-label={t("zoomOut")}
            disabled={!viewer}
            onClick={() => zoomBy(0.8)}
          >
            <ZoomOut size={17} />
          </button>
        </Tooltip>
        <span className="viewer-zoom-value" aria-label={t("zoomLevel")}>
          {zoom}%
        </span>
        <Tooltip content={t("zoomIn")}>
          <button
            className="viewer-tool-button"
            aria-label={t("zoomIn")}
            disabled={!viewer}
            onClick={() => zoomBy(1.25)}
          >
            <ZoomIn size={17} />
          </button>
        </Tooltip>
        <Tooltip content={t("fitView")}>
          <button
            className="viewer-tool-button viewer-fit"
            aria-label={t("fitView")}
            disabled={!viewer}
            onClick={() => viewer?.viewport.goHome()}
          >
            <Scan size={17} />
          </button>
        </Tooltip>
      </div>
      <Tooltip content={t(full ? "exitFullscreen" : "fullscreen")}>
        <button
          className="viewer-tool-button"
          aria-label={t(full ? "exitFullscreen" : "fullscreen")}
          onClick={() => {
            if (document.fullscreenElement) void document.exitFullscreen();
            else
              void document
                .querySelector(".viewer-workspace")
                ?.requestFullscreen();
          }}
        >
          {full ? <Minimize size={17} /> : <Maximize size={17} />}
        </button>
      </Tooltip>
    </div>
  );
}
