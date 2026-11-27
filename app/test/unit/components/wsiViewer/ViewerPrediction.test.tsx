import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ViewerPrediction } from "@renderer/components/wsiViewer/ViewerPrediction";
import type { AvailableHeatmap } from "@renderer/api/heatmap";

vi.mock("@renderer/components/wsiViewer/viewerText", () => ({
  useViewerText: () => ({ t: (key: string) => key }),
}));
const entry: AvailableHeatmap = {
  task_id: "cytology",
  task_type: "patch_classification",
  task_name: "Ascites",
  prediction: "Malignant_Determined",
  probs: {
    Benign_eosinophil_granulocyte: 0,
    Benign_lymphocyte: 0.000002,
    Benign_mesothelial: 0.001,
    Benign_neutrophil_granulocyte: 0,
    Malignant_Determined: 0.673,
    Malignant_Suspicious: 0.325998,
  },
  classes: [],
  feature_extractor: "custom",
  created_at: 0,
  attention_file: "",
};

it("prioritizes the predicted class without repeating it and reveals minor classes in probability order", () => {
  render(<ViewerPrediction entry={entry} />);
  expect(screen.getAllByText("Malignant Determined")).toHaveLength(1);
  expect(screen.getByText("67.3%")).toBeVisible();
  const alternatives = screen.getByRole("list", { name: "otherProbabilities" });
  expect(within(alternatives).getAllByRole("listitem")).toHaveLength(1);
  expect(within(alternatives).getByText("Malignant Suspicious")).toBeVisible();
  expect(
    screen.queryByRole("list", { name: "remainingClasses" }),
  ).not.toBeInTheDocument();
  const disclosure = screen.getByRole("button", { name: /moreClasses/ });
  fireEvent.click(disclosure);
  const details = screen.getByRole("list", { name: "remainingClasses" });
  expect(
    within(details)
      .getAllByRole("listitem")
      .map((row) => row.getAttribute("aria-label")),
  ).toEqual([
    "Benign_mesothelial: 0.1%",
    "Benign_lymphocyte: <0.1%",
    "Benign_eosinophil_granulocyte: 0%",
    "Benign_neutrophil_granulocyte: 0%",
  ]);
  expect(disclosure).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByText("Benign eosinophil granulocyte")).toHaveAttribute(
    "title",
    "Benign_eosinophil_granulocyte",
  );
  fireEvent.click(disclosure);
  expect(
    screen.queryByRole("list", { name: "remainingClasses" }),
  ).not.toBeInTheDocument();
});

it("keeps the stored prediction even when probabilities rank another class first", () => {
  render(
    <ViewerPrediction
      entry={{
        ...entry,
        prediction: "Tumor-intrinsic",
        probs: { "TME-associated": 0.602, "Tumor-intrinsic": 0.398 },
      }}
    />,
  );
  expect(
    screen.getByRole("heading", { name: "Tumor-intrinsic" }),
  ).toBeVisible();
  expect(screen.getAllByText("Tumor-intrinsic")).toHaveLength(1);
  expect(screen.getByText("60.2%")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: /moreClasses/ }),
  ).not.toBeInTheDocument();
});
