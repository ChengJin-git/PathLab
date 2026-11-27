import { useCallback, useEffect, useRef, useState } from "react";
import type { Geometry, ViewerRegion, RegionValue } from "../../api/viewer";
import { containsPoint, corners } from "./viewerGeometry";
import { useViewerText, type ViewerTextKey } from "./viewerText";

export type ViewerTool =
  | "select"
  | "rect"
  | "polygon"
  | "freehand"
  | "brush"
  | "erase"
  | "positive"
  | "negative";
type Point = [number, number];
export function ViewerCanvas({
  viewer,
  regions,
  preview,
  selected,
  onSelect,
  tool,
  label,
  color,
  enabled,
  busy,
  onCreate,
  onUpdate,
  onStroke,
  onPrompt,
  onRemovePrompt,
  onViewport,
  promptPoints = [],
}: {
  viewer: any;
  regions: ViewerRegion[];
  preview: Geometry[];
  selected: string[];
  onSelect: (ids: string[]) => void;
  tool: ViewerTool;
  label: string;
  color: string;
  enabled: boolean;
  busy: boolean;
  onCreate: (value: RegionValue) => void;
  onUpdate: (value: ViewerRegion) => void;
  onStroke: (points: number[][], radius: number, subtract: boolean) => void;
  onPrompt: (point: [number, number, number]) => void;
  onRemovePrompt: (index: number) => void;
  onViewport: (bounds: Geometry) => void;
  promptPoints?: number[][];
}) {
  const { t } = useViewerText();
  const hints: Record<ViewerTool, ViewerTextKey> = {
    select: "hintSelect", rect: "hintRect", polygon: "hintPolygon",
    freehand: "hintFreehand", brush: "hintBrush", erase: "hintErase",
    positive: "hintPositive", negative: "hintNegative",
  };
  const canvas = useRef<HTMLCanvasElement>(null),
    state = useRef({
      drawing: false,
      points: [] as Point[],
      start: null as Point | null,
      drag: null as ViewerRegion | null,
      vertex: -1,
      space: false,
      pan: null as Point | null,
      pointer: null as number | null,
      moved: false,
    });
  const [frame, setFrame] = useState(0);
  const raf = useRef(0);
  const image = () => viewer?.world?.getItemAt(0);
  const toScreen = (point: Point) => {
    const item = image();
    if (!item) return null;
    const p = viewer.viewport.pixelFromPoint(
      item.imageToViewportCoordinates(point[0], point[1]),
    );
    return [p.x, p.y] as Point;
  };
  const toImage = (x: number, y: number) => {
    const item = image(),
      rect = canvas.current?.getBoundingClientRect();
    if (!item || !rect) return null;
    const p = item.viewportToImageCoordinates(
      viewer.viewport.pointFromPixel(
        new (window as any).OpenSeadragon.Point(x - rect.left, y - rect.top),
      ),
    );
    const size = item.getContentSize();
    return [
      Math.min(size.x, Math.max(0, p.x)),
      Math.min(size.y, Math.max(0, p.y)),
    ] as Point;
  };
  const redraw = () => {
    if (!raf.current)
      raf.current = requestAnimationFrame(() => {
        raf.current = 0;
        setFrame((v) => v + 1);
      });
  };
  const reset = () => {
    state.current.drawing = false;
    state.current.points = [];
    state.current.start = null;
    state.current.drag = null;
    state.current.pan = null;
    state.current.pointer = null;
    redraw();
  };
  useEffect(reset, [enabled, tool]);
  useEffect(() => {
    if (
      state.current.drag &&
      !regions.some((r) => r.id === state.current.drag?.id)
    )
      reset();
  }, [regions]);
  const bounds = useCallback(() => {
    const item = viewer?.world?.getItemAt(0);
    if (!item) return;
    const r = item.viewportToImageRectangle(viewer.viewport.getBounds(true));
    const size = item.getContentSize();
    onViewport({
      type: "rect",
      x: Math.max(0, r.x),
      y: Math.max(0, r.y),
      width: Math.max(1, Math.min(size.x, r.x + r.width) - Math.max(0, r.x)),
      height: Math.max(1, Math.min(size.y, r.y + r.height) - Math.max(0, r.y)),
    });
  }, [viewer, onViewport]);
  useEffect(() => {
    const element = canvas.current;
    if (!element || !viewer) return;
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      event.stopPropagation();
      const rect = element.getBoundingClientRect();
      const pivot = viewer.viewport.pointFromPixel(
        new (window as any).OpenSeadragon.Point(
          event.clientX - rect.left,
          event.clientY - rect.top,
        ),
      );
      viewer.viewport.zoomBy(
        Math.pow(1.0018, -Math.max(-200, Math.min(200, event.deltaY))),
        pivot,
      );
      viewer.viewport.applyConstraints();
    };
    element.addEventListener("wheel", wheel, { passive: false });
    return () => element.removeEventListener("wheel", wheel);
  }, [viewer]);
  useEffect(() => {
    if (!viewer) return;
    viewer.addHandler("animation", redraw);
    viewer.addHandler("animation-finish", bounds);
    viewer.addHandler("open", bounds);
    viewer.addHandler("resize", redraw);
    bounds();
    redraw();
    const observer = new ResizeObserver(() => {
      redraw();
      bounds();
    });
    if (canvas.current) observer.observe(canvas.current);
    return () => {
      observer.disconnect();
      viewer.removeHandler("animation", redraw);
      viewer.removeHandler("animation-finish", bounds);
      viewer.removeHandler("open", bounds);
      viewer.removeHandler("resize", redraw);
      cancelAnimationFrame(raf.current);
      raf.current = 0;
    };
  }, [viewer, bounds]);
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (
        (e.target as HTMLElement)?.closest(
          "input,textarea,[contenteditable=true]",
        )
      )
        return;
      if (
        enabled &&
        e.code === "Space" &&
        !(e.target as HTMLElement)?.closest("button,[role=option]")
      ) {
        e.preventDefault();
        state.current.space = true;
      }
      if (e.code === "Escape") {
        state.current.points = [];
        state.current.drawing = false;
        state.current.drag = null;
        state.current.pan = null;
        redraw();
      }
    };
    const up = (event: KeyboardEvent | Event) => {
      if (event.type === "keyup" && (event as KeyboardEvent).code !== "Space")
        return;
      state.current.space = false;
      if (event.type === "blur") reset();
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", up);
    };
  }, [enabled]);
  useEffect(() => {
    const element = canvas.current;
    if (!element || !viewer) return;
    const rect = element.getBoundingClientRect(),
      dpr = devicePixelRatio || 1;
    if (
      element.width !== Math.round(rect.width * dpr) ||
      element.height !== Math.round(rect.height * dpr)
    ) {
      element.width = rect.width * dpr;
      element.height = rect.height * dpr;
    }
    const ctx = element.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, rect.width, rect.height);
    const draw = (
      r: Geometry,
      stroke: string,
      active = false,
      dashed = false,
    ) => {
      const screenCorners = corners(r).map((p) => toScreen(p as Point));
      const a = screenCorners[0],
        b = screenCorners[2];
      if (
        !a ||
        !b ||
        Math.max(...screenCorners.map((p) => p![0])) < 0 ||
        Math.max(...screenCorners.map((p) => p![1])) < 0 ||
        Math.min(...screenCorners.map((p) => p![0])) > rect.width ||
        Math.min(...screenCorners.map((p) => p![1])) > rect.height
      )
        return;
      ctx.beginPath();
      const ring = (points: number[][]) => {
        points.forEach((p, i) => {
          const q = toScreen(p as Point)!;
          i ? ctx.lineTo(...q) : ctx.moveTo(...q);
        });
        ctx.closePath();
      };
      if (r.type === "polygon" && r.points) {
        ring(r.points);
        r.holes?.forEach(ring);
      } else ring(corners(r));
      ctx.fillStyle = stroke + "18";
      ctx.strokeStyle = stroke;
      ctx.lineWidth = active ? 2.5 : 1.5;
      ctx.setLineDash(dashed ? [5, 4] : []);
      ctx.fill("evenodd");
      ctx.stroke();
      ctx.setLineDash([]);
      if (active) {
        const points =
          r.type === "polygon"
            ? r.points!
            : [
                [r.x, r.y],
                [r.x + r.width, r.y],
                [r.x + r.width, r.y + r.height],
                [r.x, r.y + r.height],
              ];
        points.forEach((p) => {
          const q = toScreen(p as Point)!;
          ctx.fillStyle = "#fff";
          ctx.fillRect(q[0] - 3, q[1] - 3, 6, 6);
          ctx.strokeRect(q[0] - 3, q[1] - 3, 6, 6);
        });
      }
    };
    regions.forEach((region) =>
      draw(
        state.current.drag?.id === region.id ? state.current.drag : region,
        region.color,
        selected.includes(region.id),
      ),
    );
    preview.forEach((r) => draw(r, "#d97706", false, true));
    promptPoints.forEach(([x, y, label]) => {
      const point = toScreen([x, y]);
      if (!point) return;
      ctx.beginPath();
      ctx.arc(point[0], point[1], 5, 0, Math.PI * 2);
      ctx.fillStyle = label ? "#16a34a" : "#dc2626";
      ctx.fill();
      ctx.strokeStyle = "#fff";
      ctx.lineWidth = 2;
      ctx.stroke();
    });
    const points = state.current.points;
    if (points.length) {
      ctx.beginPath();
      points.forEach((p, i) => {
        const q = toScreen(p)!;
        i ? ctx.lineTo(...q) : ctx.moveTo(...q);
      });
      ctx.strokeStyle = color;
      ctx.lineWidth = tool === "brush" || tool === "erase" ? 18 : 2;
      ctx.lineCap = "round";
      ctx.stroke();
    }
    if (tool === "rect" && state.current.start && points.length) {
      const [x, y] = state.current.start,
        [right, bottom] = points.at(-1)!;
      draw(
        {
          type: "rect",
          x: Math.min(x, right),
          y: Math.min(y, bottom),
          width: Math.abs(right - x),
          height: Math.abs(bottom - y),
        },
        color,
        false,
        true,
      );
    }
  }, [viewer, regions, preview, selected, frame, tool, color, promptPoints]);
  const finish = (points: Point[]) => {
    if (points.length < 3) return;
    const xs = points.map((p) => p[0]),
      ys = points.map((p) => p[1]);
    onCreate({
      type: "polygon",
      x: Math.min(...xs),
      y: Math.min(...ys),
      width: Math.max(...xs) - Math.min(...xs),
      height: Math.max(...ys) - Math.min(...ys),
      points,
      label,
      color,
    });
  };
  return (
    <>
    <canvas
      ref={canvas}
      className="absolute inset-0 z-20 h-full w-full touch-none"
      style={{
        pointerEvents: enabled ? "auto" : "none",
        cursor: tool === "select" ? "default" : "crosshair",
      }}
      onPointerDown={(e) => {
        if (e.button !== 0 && e.button !== 1) return;
        const p = toImage(e.clientX, e.clientY);
        if (!p) return;
        e.preventDefault();
        e.stopPropagation();
        e.currentTarget.setPointerCapture(e.pointerId);
        state.current.pointer = e.pointerId;
        state.current.moved = false;
        if (state.current.space || busy || e.button === 1) {
          state.current.pan = [e.clientX, e.clientY];
          return;
        }
        if (tool === "positive" || tool === "negative") {
          const pointer = toScreen(p);
          const hit = promptPoints.findIndex((point) => {
            const screen = toScreen([point[0], point[1]]);
            return pointer && screen && Math.hypot(screen[0] - pointer[0], screen[1] - pointer[1]) <= 10;
          });
          if (hit >= 0) {
            onRemovePrompt(hit);
            return;
          }
          onPrompt([...p, tool === "positive" ? 1 : 0]);
          return;
        }
        if (tool === "polygon") {
          state.current.points.push(p);
          redraw();
          return;
        }
        if (tool === "select") {
          const candidate = [...regions].reverse().find(
            (r) =>
              !r.id.startsWith("gt-") &&
              (containsPoint(r, p) ||
                (selected.includes(r.id) &&
                  (r.points || corners(r)).some((point) => {
                    const q = toScreen(point as Point)!,
                      s = toScreen(p)!;
                    return Math.hypot(q[0] - s[0], q[1] - s[1]) < 10;
                  }))),
          );
          if (!candidate) {
            onSelect([]);
            state.current.pan = [e.clientX, e.clientY];
            return;
          }
          onSelect(
            e.shiftKey
              ? [...new Set([...selected, candidate.id])]
              : [candidate.id],
          );
          state.current.drag = {
            ...candidate,
            points: candidate.points?.map((p) => [...p]),
          };
          state.current.start = p;
          state.current.vertex = -1;
          const vertices =
            candidate.type === "polygon"
              ? candidate.points!
              : [
                  [candidate.x, candidate.y],
                  [candidate.x + candidate.width, candidate.y],
                  [
                    candidate.x + candidate.width,
                    candidate.y + candidate.height,
                  ],
                  [candidate.x, candidate.y + candidate.height],
                ];
          const screen = toScreen(p)!;
          state.current.vertex = vertices.findIndex((v) => {
            const q = toScreen(v as Point)!;
            return Math.hypot(q[0] - screen[0], q[1] - screen[1]) < 10;
          });
          return;
        }
        state.current.drawing = true;
        state.current.start = p;
        state.current.points = [p];
        redraw();
      }}
      onPointerMove={(e) => {
        if (state.current.pan) {
          const [x, y] = state.current.pan;
          const delta = viewer.viewport.deltaPointsFromPixels(
            new (window as any).OpenSeadragon.Point(
              x - e.clientX,
              y - e.clientY,
            ),
          );
          viewer.viewport.panBy(delta);
          viewer.viewport.applyConstraints();
          state.current.pan = [e.clientX, e.clientY];
          return;
        }
        const p = toImage(e.clientX, e.clientY);
        if (!p) return;
        const s = state.current;
        if (s.drag && s.start) {
          let dx = p[0] - s.start[0],
            dy = p[1] - s.start[1];
          if (Math.abs(dx) + Math.abs(dy) < 0.01) return;
          s.moved = true;
          if (s.vertex >= 0) {
            if (s.drag.type === "polygon" && s.drag.points) {
              s.drag.points[s.vertex] = p;
              const xs = s.drag.points.map((v) => v[0]),
                ys = s.drag.points.map((v) => v[1]);
              s.drag = {
                ...s.drag,
                x: Math.min(...xs),
                y: Math.min(...ys),
                width: Math.max(...xs) - Math.min(...xs),
                height: Math.max(...ys) - Math.min(...ys),
              };
            } else {
              const r = s.drag;
              const corners: Point[] = [
                [r.x, r.y],
                [r.x + r.width, r.y],
                [r.x + r.width, r.y + r.height],
                [r.x, r.y + r.height],
              ];
              const opposite = corners[(s.vertex + 2) % 4];
              s.drag = {
                ...r,
                x: Math.min(p[0], opposite[0]),
                y: Math.min(p[1], opposite[1]),
                width: Math.max(1, Math.abs(p[0] - opposite[0])),
                height: Math.max(1, Math.abs(p[1] - opposite[1])),
              };
            }
          } else {
            const size = image().getContentSize();
            dx = Math.max(
              -s.drag.x,
              Math.min(dx, size.x - s.drag.x - s.drag.width),
            );
            dy = Math.max(
              -s.drag.y,
              Math.min(dy, size.y - s.drag.y - s.drag.height),
            );
            s.drag = {
              ...s.drag,
              x: Math.max(0, s.drag.x + dx),
              y: Math.max(0, s.drag.y + dy),
              points: s.drag.points?.map((v) => [v[0] + dx, v[1] + dy]),
              holes: s.drag.holes?.map((ring) =>
                ring.map((v) => [v[0] + dx, v[1] + dy]),
              ),
            };
            s.start = p;
          }
          redraw();
        } else if (s.drawing) {
          if (tool === "rect") s.points = [p];
          else if (
            !s.points.length ||
            Math.hypot(p[0] - s.points.at(-1)![0], p[1] - s.points.at(-1)![1]) >
              1
          )
            s.points.push(p);
          redraw();
        }
      }}
      onPointerUp={(e) => {
        const s = state.current;
        if (e.currentTarget.hasPointerCapture(e.pointerId))
          e.currentTarget.releasePointerCapture(e.pointerId);
        s.pointer = null;
        if (s.pan) {
          s.pan = null;
          bounds();
          return;
        }
        if (s.drag) {
          if (s.moved && !busy) onUpdate(s.drag);
          s.drag = null;
          s.start = null;
          redraw();
          return;
        }
        if (!s.drawing) return;
        s.drawing = false;
        const p = toImage(e.clientX, e.clientY);
        if (!p || !s.start) return;
        if (tool === "rect") {
          const [x, y] = s.start;
          if (Math.abs(p[0] - x) > 1 && Math.abs(p[1] - y) > 1)
            onCreate({
              type: "rect",
              x: Math.min(x, p[0]),
              y: Math.min(y, p[1]),
              width: Math.abs(p[0] - x),
              height: Math.abs(p[1] - y),
              label,
              color,
            });
        } else if (tool === "brush" || tool === "erase") {
          const item = image(),
            a = item.viewportToImageCoordinates(
              viewer.viewport.pointFromPixel(
                new (window as any).OpenSeadragon.Point(18, 0),
              ),
            ),
            b = item.viewportToImageCoordinates(
              viewer.viewport.pointFromPixel(
                new (window as any).OpenSeadragon.Point(0, 0),
              ),
            );
          if (s.points.length > 1)
            onStroke(
              s.points,
              Math.hypot(a.x - b.x, a.y - b.y) / 2,
              tool === "erase",
            );
        } else
          finish(
            s.points.filter(
              (_, i) =>
                i % Math.max(1, Math.ceil(s.points.length / 1000)) === 0,
            ),
          );
        s.points = [];
        s.start = null;
        redraw();
      }}
      onPointerCancel={reset}
      onDoubleClick={(e) => {
        e.stopPropagation();
        if (tool === "polygon" && !busy) {
          finish(state.current.points);
          state.current.points = [];
          redraw();
        }
      }}
    />
    {enabled && tool !== "select" && !busy && preview.length === 0 && (
      <div className="viewer-tool-guidance">
        <span role="status">{t(hints[tool])}</span>
        {tool === "polygon" && state.current.points.length > 0 && (
          <div className="viewer-guidance-actions">
            <button type="button" disabled={state.current.points.length < 3}
              onClick={() => { finish(state.current.points); reset(); }}>
              {t("finishDrawing")}
            </button>
            <button type="button" onClick={reset}>{t("cancelDrawing")}</button>
          </div>
        )}
      </div>
    )}
    </>
  );
}
