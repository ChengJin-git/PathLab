import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@renderer/components/ui/tooltip";
import { ViewerResults } from "@renderer/components/wsiViewer/ViewerResults";
import * as api from "@renderer/api/heatmap";

vi.mock("@renderer/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { id: "owner" } }),
}));
vi.mock("@renderer/components/wsiViewer/viewerText", () => ({
  useViewerText: () => ({ t: (key: string) => key }),
}));
vi.mock("@renderer/api/heatmap", async (original) => ({
  ...(await original<typeof api>()),
  fetchImagePrediction: vi.fn(),
}));
beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.stubGlobal("fetch", vi.fn());
});

function mount(task: Partial<api.AvailableHeatmap>) {
  const entry: api.AvailableHeatmap = {
    task_id: "task",
    task_type: "patch_segmentation",
    task_name: "Spatial result",
    data_type: "patch",
    classes: ["SUPERFICIAL"],
    class_colors: ["#e11d48"],
    prediction: null,
    probs: null,
    feature_extractor: "custom",
    created_at: 0,
    attention_file: "",
    ...task,
  };
  const viewer = {
    world: {
      getItemCount: () => 1,
      getItemAt: () => ({
        getBounds: () => ({}),
        imageToViewportRectangle: (...args: number[]) => args,
      }),
    },
    addOverlay: vi.fn(),
    removeOverlay: vi.fn(),
    removeHandler: vi.fn(),
  };
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <TooltipProvider>
        <ViewerResults
          viewer={viewer}
          id="slide"
          entries={[entry]}
          selected="task:"
          onSelected={vi.fn()}
          heatmap={null}
          opacity={0.5}
          setOpacity={vi.fn()}
          showHeatmap={false}
          setShowHeatmap={vi.fn()}
          threshold={0.5}
          setThreshold={vi.fn()}
          onFocus={vi.fn()}
          onPlan={vi.fn()}
        />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return viewer;
}

it("shows the single segmentation class before opening its layer", () => {
  mount({});
  expect(screen.getByRole("radio", { name: "SUPERFICIAL" })).toBeChecked();
  expect(screen.getByText("SUPERFICIAL")).toBeVisible();
  expect(api.fetchImagePrediction).not.toHaveBeenCalled();
});

it("selects the named segmentation channel and uses that channel in the mask URL", async () => {
  vi.mocked(api.fetchImagePrediction).mockResolvedValue({
    task_type: "patch_segmentation",
    classes: ["Cell", "Nucleus"],
    class_colors: ["#e11d48", "#2563eb"],
  });
  const viewer = mount({
    classes: ["Cell", "Nucleus"],
    class_colors: ["#e11d48", "#2563eb"],
  });
  fireEvent.click(screen.getByRole("radio", { name: "Nucleus" }));
  await waitFor(() => expect(viewer.addOverlay).toHaveBeenCalled());
  const image = viewer.addOverlay.mock.calls.at(-1)![0]
    .element as HTMLImageElement;
  expect(image.src).toContain("class_index=1");
  expect(screen.getByRole("radio", { name: "Nucleus" })).toBeChecked();
  expect(screen.getByRole("switch", { name: "mask" })).toBeChecked();
});

it("resolves one-based detection labels, colors the right class and filters its boxes", async () => {
  vi.mocked(api.fetchImagePrediction).mockResolvedValue({
    task_type: "patch_detection",
    class_names: ["Cell", "Nucleus"],
    class_colors: ["#e11d48", "#2563eb"],
    detection: {
      prediction: {
        boxes: [
          [1, 1, 10, 10],
          [20, 20, 30, 30],
        ],
        labels: [1, 2],
        scores: [0.9, 0.8],
      },
      target: null,
    },
  });
  const viewer = mount({
    task_type: "patch_detection",
    classes: ["Cell", "Nucleus"],
    class_colors: ["#e11d48", "#2563eb"],
  });
  fireEvent.click(screen.getByRole("switch", { name: "detectionBoxes" }));
  expect(
    await screen.findByRole("button", { name: /^Cell\s*0\.90$/ }),
  ).toBeVisible();
  expect(screen.getByRole("button", { name: /^Nucleus\s*0\.80$/ })).toBeVisible();
  const boxes = viewer.addOverlay.mock.calls.map(
    (call) => call[0].element as HTMLDivElement,
  );
  expect(
    boxes.some(
      (box) =>
        box.dataset.resultClass === "0" &&
        box.style.borderColor === "rgb(225, 29, 72)",
    ),
  ).toBe(true);
  expect(
    boxes.some(
      (box) =>
        box.dataset.resultClass === "1" &&
        box.style.borderColor === "rgb(37, 99, 235)",
    ),
  ).toBe(true);
  fireEvent.click(screen.getByRole("checkbox", { name: "Cell" }));
  expect(
    screen.queryByRole("button", { name: /^Cell\s*0\.90$/ }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /^Nucleus\s*0\.80$/ })).toBeVisible();
});

it("loads missing class metadata without requiring a layer toggle", async () => {
  vi.mocked(api.fetchImagePrediction).mockResolvedValue({
    task_type: "patch_segmentation",
    class_names: ["SUPERFICIAL"],
    class_colors: ["#e11d48"],
  });
  mount({ classes: null });
  expect(
    await screen.findByRole("radio", { name: "SUPERFICIAL" }),
  ).toBeChecked();
});
