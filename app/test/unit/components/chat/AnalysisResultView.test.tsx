import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import AnalysisResultView from "@renderer/components/autoresearch/AnalysisResultView";
import { apiFetch } from "@renderer/api/client";
import i18n from "@renderer/i18n";

const viewer = vi.hoisted(() => ({ openFile: vi.fn() }));
vi.mock("@renderer/components/chat/ConversationFiles", () => ({
  useConversationFiles: () => viewer,
}));
vi.mock("@renderer/api/client", () => ({ apiFetch: vi.fn() }));
vi.mock("@renderer/api/autoresearch", () => ({ readResearchImage: vi.fn() }));
vi.mock("@renderer/components/charts/AnalysisCharts", () => ({
  RocCurveChart: ({ data }: { data: { classes: string[] } }) => (
    <div>ROC: {data.classes.join(",")}</div>
  ),
  ConfusionMatrixChart: () => null,
  KMCurveChart: () => null,
  LossCurveChart: () => null,
}));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("renders custom units, confidence intervals, tables and shared charts and opens executed source", async () => {
  await i18n.changeLanguage("en-US");
  vi.mocked(apiFetch).mockResolvedValue({
    title: "Paired calibration",
    summary: "Computed on held-out patients",
    code_path: "analyze.py",
    source_files: ["predictions.csv"],
    metrics: {
      custom_bias: {
        value: -0.125,
        label: "Paired bias",
        unit: "mm",
        ci_lower: -0.2,
        ci_upper: 0.1,
      },
    },
    chart_data: { roc_curve: { classes: ["Positive"], data: {} } },
    figures: [],
    tables: [
      {
        title: "Groups",
        columns: ["Group", "N"],
        rows: [
          ["A", 12],
          ["B", null],
        ],
      },
    ],
  });
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <AnalysisResultView sessionId="s" analysisId="a" userId="u" />
    </QueryClientProvider>,
  );
  expect(await screen.findByText("-0.125 mm")).toBeInTheDocument();
  expect(screen.getByText("[-0.2, 0.1]")).toBeInTheDocument();
  expect(screen.getByText("ROC: Positive")).toBeInTheDocument();
  expect(screen.getByRole("table")).toHaveTextContent("12");
  fireEvent.click(
    screen.getByRole("button", { name: "View executed analysis code" }),
  );
  expect(viewer.openFile).toHaveBeenCalledWith({
    sessionId: "s",
    path: "analyze.py",
  });
});
