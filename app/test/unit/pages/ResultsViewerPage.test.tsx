import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ResultsViewerPage from "../../../src/renderer/src/pages/ResultsViewerPage";
import {
  resultGet,
  resultSend,
} from "../../../src/renderer/src/api/resultWorkbench";

vi.mock("react-i18next", async (original) => ({
  ...(await original<typeof import("react-i18next")>()),
  useTranslation: () => ({
    i18n: { language: "en-US" },
    t: (key: string, options?: { defaultValue?: string }) =>
      options?.defaultValue || key,
  }),
}));
vi.mock("../../../src/renderer/src/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { id: "owner" } }),
}));
vi.mock("../../../src/renderer/src/api/resultWorkbench", async (original) => ({
  ...(await original<
    typeof import("../../../src/renderer/src/api/resultWorkbench")
  >()),
  resultGet: vi.fn(),
  resultSend: vi.fn(),
}));
const source = {
  source_id: "task:t",
  title: "Measured classifier",
  task_id: "t",
  session_id: null,
  task_type: "patch_classification",
  task_families: ["classification"],
  revision: "1",
  kind: "training",
  classes: ["no", "yes"],
  prediction_count: 4,
  gt_count: 4,
  probability_count: 4,
  splits: ["test"],
  unit: "file",
  metrics: {},
  dataset_ids: ["d"],
};
const renderPage = () =>
  render(
    <MemoryRouter initialEntries={["/results"]}>
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <ResultsViewerPage />
      </QueryClientProvider>
    </MemoryRouter>,
  );

describe("Results analysis workbench", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(resultGet).mockImplementation(async (path) =>
      path === "/catalog"
        ? { version: "1", metrics: [], charts: [] }
        : path.startsWith("/runs/")
          ? {
              analysis_id: "a",
              status: "queued",
              progress: 0,
              phase: "queued",
              created_at: "2026-01-01T00:00:00Z",
              source_ids: ["task:t"],
            }
          : { items: path === "/sources" ? [source] : [], has_more: false },
    );
  });
  it("keeps the shell and assistant controls responsive while sources load", () => {
    vi.mocked(resultGet).mockImplementation(() => new Promise(() => {}));
    renderPage();
    expect(
      screen.getByRole("heading", { name: "Results analysis" }),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Analysis assistant" }),
    ).toBeEnabled();
    expect(
      screen.queryByRole("button", { name: "New evaluation" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add analysis" })).toBeDisabled();
    expect(
      vi
        .mocked(resultGet)
        .mock.calls.every(([path]) =>
          ["/sources", "/catalog", "/runs"].includes(path),
        ),
    ).toBe(true);
  });
  it("executes only when requested and submits the explicit source/split configuration", async () => {
    vi.mocked(resultSend).mockResolvedValue({
      analysis_id: "a",
      status: "queued",
      progress: 0,
      phase: "queued",
      created_at: "2026-01-01T00:00:00Z",
      source_ids: ["task:t"],
    });
    renderPage();
    await userEvent.click(
      await screen.findByRole("button", { name: /Measured classifier/ }),
    );
    expect(resultSend).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Add analysis" }));
    expect(
      await screen.findByRole("button", { name: "Advanced settings" }),
    ).toHaveAttribute("aria-expanded", "true");
    expect(resultSend).not.toHaveBeenCalled();
    await userEvent.click(
      await screen.findByRole("button", { name: "Start analysis" }),
    );
    await waitFor(() =>
      expect(resultSend).toHaveBeenCalledWith("/runs", {
        config: expect.objectContaining({
          source_ids: ["task:t"],
          split: "test",
          unit: "file",
        }),
      }),
    );
  });
  it("loads historical metadata only when the history tab is selected", async () => {
    renderPage();
    await screen.findByRole("button", { name: /Measured classifier/ });
    expect(
      vi
        .mocked(resultGet)
        .mock.calls.some(
          ([path, args]) => path === "/runs" && args?.status !== "active",
        ),
    ).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "History" }));
    await waitFor(() =>
      expect(
        vi
          .mocked(resultGet)
          .mock.calls.some(
            ([path, args]) => path === "/runs" && args?.status !== "active",
          ),
      ).toBe(true),
    );
  });
});
