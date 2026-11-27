import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { TooltipProvider } from "@renderer/components/ui/tooltip";
import { ViewerResults } from "@renderer/components/wsiViewer/ViewerResults";
import type {
  AvailableHeatmap,
  HeatmapData,
  HeatmapPoint,
} from "@renderer/api/heatmap";

vi.mock("@renderer/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { id: "owner" } }),
}));
vi.mock("@renderer/components/wsiViewer/viewerText", () => ({
  useViewerText: () => ({ t: (key: string) => key }),
}));
beforeEach(() =>
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  ),
);
afterEach(() => {
  vi.unstubAllGlobals();
  vi.stubGlobal("fetch", vi.fn());
});

const patches = (low: boolean): HeatmapPoint[] =>
  Array.from({ length: 10 }, (_, index) => ({
    index: (low ? 100 : 0) + index,
    x: index * 512,
    y: low ? 1024 : 0,
    weight: low ? 0 : 1,
    raw_weight: low ? -4 + index / 1000 : 0.000001234 - index / 100000000,
  }));
const entry: AvailableHeatmap = {
  task_id: "task",
  fold_key: "fold_0",
  task_name: "Result A",
  task_type: "wsi_classification",
  data_type: "wsi",
  has_heatmap: true,
  prediction: null,
  probs: null,
  classes: [],
  feature_extractor: "custom",
  created_at: 0,
  attention_file: "",
};
const data: HeatmapData = {
  wsi_id: "slide",
  task_id: "task",
  fold_key: "fold_0",
  task_name: "Result A",
  patch_size: 512,
  slide_width: 10000,
  slide_height: 5000,
  num_patches: 400,
  attention_min: -4,
  attention_max: 1,
  prediction: null,
  probs: null,
  heatmap: [],
  top_patches: patches(false),
  bottom_patches: patches(true),
};

it("shows ten thumbnails per end, focuses the actual footprint and suppresses stale result/fold data", () => {
  const onFocus = vi.fn();
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const props = {
    viewer: null,
    id: "slide",
    entries: [entry, { ...entry, fold_key: "fold_1", task_name: "Result B" }],
    selected: "task:fold_0",
    onSelected: vi.fn(),
    heatmap: data,
    opacity: 0.5,
    setOpacity: vi.fn(),
    showHeatmap: true,
    setShowHeatmap: vi.fn(),
    threshold: 0.5,
    setThreshold: vi.fn(),
    onFocus,
    onPlan: vi.fn(),
  };
  const ui = (selected = props.selected, heatmap = data) => (
    <QueryClientProvider client={cache}>
      <TooltipProvider>
        <ViewerResults {...props} selected={selected} heatmap={heatmap} />
      </TooltipProvider>
    </QueryClientProvider>
  );
  const view = render(ui());
  const high = screen.getByRole("region", { name: "highAttention" }),
    low = screen.getByRole("region", { name: "lowAttention" });
  expect(within(high).getAllByRole("button")).toHaveLength(10);
  expect(within(low).getAllByRole("button")).toHaveLength(10);
  expect(screen.queryByText("1.000")).not.toBeInTheDocument();
  const target = within(low).getAllByRole("button")[9];
  const image = target.querySelector("img")!;
  expect(image.src).toContain("x=4608");
  expect(image.src).toContain("size=512");
  expect(image.src).toContain("thumbnail_size=160");
  fireEvent.click(target);
  expect(onFocus).toHaveBeenLastCalledWith({
    type: "rect",
    x: 4608,
    y: 1024,
    width: 512,
    height: 512,
  });
  expect(target).toHaveAttribute("aria-pressed", "true");
  fireEvent.error(image);
  expect(target.querySelector("img")).toBeNull();
  fireEvent.click(target);
  expect(onFocus).toHaveBeenCalledTimes(2);
  view.rerender(ui("task:fold_1"));
  expect(
    screen.queryByRole("region", { name: "attentionRegions" }),
  ).not.toBeInTheDocument();
  view.rerender(
    ui("task:fold_1", {
      ...data,
      fold_key: "fold_1",
      top_patches: patches(false).slice(0, 3),
      bottom_patches: patches(true).slice(0, 3),
    }),
  );
  expect(
    within(screen.getByRole("region", { name: "highAttention" })).getAllByRole(
      "button",
    ),
  ).toHaveLength(3);
});
