from __future__ import annotations

import json

import pytest
from PIL import Image

from pathlab_paper_agent.pipeline import create_dev_run, run_stage
from pathlab_paper_agent.plotting import generate_figure, supported_generators
from pathlab_paper_agent.plotting.types import FigureGenerationError

TINY_IMAGE = [[0.1, 0.3], [0.6, 0.9]]
TINY_MASK = [[0, 1], [1, 0]]


PNG_GENERATOR_SPECS = [
    {
        "figure_id": "fig:calibration",
        "kind": "empirical",
        "generator": "calibration_plot",
        "data": {
            "bins": [
                {"confidence": 0.1, "accuracy": 0.12, "count": 8},
                {"confidence": 0.3, "accuracy": 0.28, "count": 14},
                {"confidence": 0.5, "accuracy": 0.55, "count": 20},
                {"confidence": 0.7, "accuracy": 0.68, "count": 11},
                {"confidence": 0.9, "accuracy": 0.86, "count": 6},
            ]
        },
    },
    {
        "figure_id": "fig:roc",
        "kind": "empirical",
        "generator": "per_fold_roc",
        "data": {
            "folds": [
                {"label": "fold_1", "fpr": [0, 0.1, 0.4, 1], "tpr": [0, 0.7, 0.9, 1], "auc": 0.91},
                {"label": "fold_2", "fpr": [0, 0.2, 0.5, 1], "tpr": [0, 0.65, 0.88, 1], "auc": 0.87},
            ]
        },
    },
    {
        "figure_id": "fig:km",
        "kind": "empirical",
        "generator": "km_stratified",
        "data": {
            "groups": [
                {"label": "low", "times": [1, 3, 5], "survival": [0.96, 0.9, 0.84]},
                {"label": "high", "times": [1, 3, 5], "survival": [0.8, 0.62, 0.48]},
            ]
        },
    },
    {
        "figure_id": "fig:failure",
        "kind": "empirical",
        "generator": "failure_cases_panel",
        "data": {
            "cases": [
                {
                    "case_id": "case_001",
                    "image": TINY_IMAGE,
                    "true_label": "A",
                    "predicted_label": "B",
                    "confidence": 0.93,
                }
            ]
        },
    },
    {
        "figure_id": "fig:heatmap",
        "kind": "empirical",
        "generator": "heatmap_examples",
        "data": {
            "examples": [
                {
                    "case_id": "case_001",
                    "image": TINY_IMAGE,
                    "heatmap": [[0.1, 0.8], [0.3, 0.5]],
                }
            ]
        },
    },
    {
        "figure_id": "fig:seg",
        "kind": "empirical",
        "generator": "seg_qualitative_4panel",
        "data": {
            "examples": [
                {
                    "image": TINY_IMAGE,
                    "mask": TINY_MASK,
                    "prediction": [[1, 1], [0, 0]],
                    "overlay": TINY_IMAGE,
                }
            ]
        },
    },
    {
        "figure_id": "fig:gradcam",
        "kind": "empirical",
        "generator": "grad_cam_examples",
        "data": {
            "examples": [
                {
                    "patch_id": "patch_001",
                    "image": TINY_IMAGE,
                    "heatmap": [[0.2, 0.7], [0.1, 0.9]],
                }
            ]
        },
    },
]


@pytest.mark.parametrize("spec", PNG_GENERATOR_SPECS)
def test_empirical_generators_write_valid_png(tmp_path, spec):
    result = generate_figure(tmp_path, spec)

    assert result.status == "ready"
    assert result.path.startswith("figures/")
    output_path = tmp_path / result.path.removeprefix("figures/")
    assert output_path.is_file()
    with Image.open(output_path) as image:
        assert image.format == "PNG"
        assert image.size[0] >= 200
        assert image.size[1] >= 200


def test_chart_passthrough_copies_existing_png(tmp_path):
    figures_dir = tmp_path / "paper_run" / "figures"
    source_dir = figures_dir / "source_charts"
    source_dir.mkdir(parents=True)
    source = source_dir / "source.png"
    Image.new("RGB", (64, 64), "red").save(source)

    result = generate_figure(
        figures_dir,
        {
            "figure_id": "fig:copied_chart",
            "kind": "empirical",
            "generator": "chart_passthrough",
            "data": {"source_path": str(source)},
        },
    )

    assert result.content_type == "image/png"
    assert result.source == "figures/source_charts/source.png"
    assert (figures_dir / "fig_copied_chart.png").is_file()


def test_chart_passthrough_rejects_unscoped_source(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (64, 64), "red").save(source)

    with pytest.raises(FigureGenerationError, match="source_path must be inside"):
        generate_figure(
            tmp_path / "paper_run" / "figures",
            {
                "figure_id": "fig:copied_chart",
                "kind": "empirical",
                "generator": "chart_passthrough",
                "data": {"source_path": str(source)},
            },
        )


def test_supported_generators_lists_expected_aliases():
    names = set(supported_generators())
    assert "calibration_plot" in names
    assert "per_fold_roc" in names
    assert "heatmap_examples" in names


def test_empirical_generator_requires_evidence(tmp_path):
    with pytest.raises(FigureGenerationError, match="confidence"):
        generate_figure(
            tmp_path,
            {
                "figure_id": "fig:no_data",
                "kind": "empirical",
                "generator": "calibration_plot",
                "data": {},
            },
        )


def test_nested_plot_spec_generator_takes_precedence_over_kind(tmp_path):
    result = generate_figure(
        tmp_path,
        {
            "figure_id": "fig:nested",
            "kind": "empirical",
            "plot_spec": {
                "generator": "calibration_plot",
                "data": {
                    "confidence": [0.2, 0.8],
                    "accuracy": [0.25, 0.75],
                },
            },
        },
    )

    assert result.path == "figures/fig_nested.png"


@pytest.mark.asyncio
async def test_plotting_stage_generates_empirical_manifest_entries(tmp_path):
    paper_id, paths = await create_dev_run(paper_id="paper_figures", uploads_dir=tmp_path)
    data_ref = "evidence/plot_data/calibration_stage.json"
    (paths.root / data_ref).parent.mkdir(parents=True, exist_ok=True)
    (paths.root / data_ref).write_text(
        json.dumps(
            {
                "confidence": [0.2, 0.4, 0.6, 0.8],
                "accuracy": [0.18, 0.45, 0.61, 0.77],
            }
        ),
        encoding="utf-8",
    )
    paths.outline_json.write_text(
        json.dumps(
            {
                "plotting_plan": [
                    {
                        "figure_id": "fig:overview",
                        "kind": "conceptual",
                        "source": "idea + method_block",
                    },
                    {
                        "figure_id": "fig:calibration_stage",
                        "kind": "empirical",
                        "source": "mock_analysis_summary",
                        "plot_spec": {
                            "generator": "calibration_plot",
                            "data_ref": data_ref,
                        },
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    manifest = run_stage(paper_id, "plotting", uploads_dir=tmp_path)
    figures_manifest = json.loads(paths.figures_manifest.read_text(encoding="utf-8"))
    entries = {entry["figure_id"]: entry for entry in figures_manifest["figures"]}

    assert entries["fig:overview"]["status"] == "requires_user_revision"
    assert entries["fig:calibration_stage"]["status"] == "ready"
    assert entries["fig:calibration_stage"]["path"] == "figures/fig_calibration_stage.png"
    assert (paths.figures_dir / "fig_calibration_stage.png").is_file()
    assert manifest.artifact_index["figures/fig_calibration_stage.png"]["visibility"] == "public"


@pytest.mark.asyncio
async def test_plotting_stage_fails_on_missing_empirical_evidence(tmp_path):
    paper_id, paths = await create_dev_run(paper_id="paper_figures_missing", uploads_dir=tmp_path)
    paths.outline_json.write_text(
        json.dumps(
            {
                "plotting_plan": [
                    {
                        "figure_id": "fig:no_data",
                        "kind": "empirical",
                        "generator": "calibration_plot",
                        "data": {},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="Empirical figure generation failed"):
        run_stage(paper_id, "plotting", uploads_dir=tmp_path)

    figures_manifest = json.loads(paths.figures_manifest.read_text(encoding="utf-8"))
    assert figures_manifest["figures"][0]["status"] == "pending_generation"
