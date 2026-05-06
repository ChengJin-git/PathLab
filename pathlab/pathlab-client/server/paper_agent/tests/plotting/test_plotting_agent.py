from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from PIL import Image

from pathlab_paper_agent.agents.plotting_agent import PlottingAgent
from pathlab_paper_agent.llm import LLMResponse
from pathlab_paper_agent.pipeline import create_dev_run
from pathlab_paper_agent.schemas import PaperManifest
from pathlab_paper_agent.stages.plotting import run as run_plotting


class MockCaptionLLM:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def complete(
        self,
        messages,
        *,
        temperature: float = 0.2,
        response_format=None,
        stream=None,
    ) -> LLMResponse:
        payload = _payload_from_prompt(messages[-1].content)
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "response_format": response_format,
                "stream": stream,
                "payload": payload,
            }
        )
        return LLMResponse(
            content=f"Figure 9: concise caption for {payload['figure_id']} via {payload['generator']}.",
            model="mock-caption",
            provider="mock",
        )


def _write_plot_data(paths, name: str = "calibration_agent.json") -> str:
    rel_path = f"evidence/plot_data/{name}"
    path = paths.root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "confidence": [0.2, 0.5, 0.8],
                "accuracy": [0.24, 0.52, 0.78],
            }
        ),
        encoding="utf-8",
    )
    return rel_path


def _write_pathlab_analysis_chart(paths, tmp_path, chart_kind: str = "roc_curve") -> str:
    analysis_dir = tmp_path / "logs" / "analysis" / "task-main" / "20260101_010101"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    chart_path = analysis_dir / f"{chart_kind}.png"
    Image.new("RGB", (64, 64), "blue").save(chart_path)
    raw_dir = paths.evidence_dir / "raw_collected"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "analysis_summary.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "task_id": "task-main",
                        "role": "main",
                        "selected_analysis_id": "20260101_010101",
                        "analyses": [
                            {
                                "analysis_id": "20260101_010101",
                                "analysis_dir": str(analysis_dir),
                                "chart_paths": {chart_kind: str(chart_path)},
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return str(chart_path)


def _payload_from_prompt(prompt: str) -> dict:
    marker = "Input payload:"
    assert marker in prompt
    payload = json.loads(prompt.split(marker, 1)[1].strip())
    assert isinstance(payload, dict)
    return payload


def _plotting_plan(data_ref: str) -> list[dict]:
    return [
        {
            "figure_id": "fig:calibration_agent",
            "kind": "empirical",
            "source": "analysis_summary",
            "design_objective": "show calibration from locked evidence",
            "backend": "deterministic_plotting",
            "plot_spec": {
                "generator": "calibration_plot",
                "data_ref": data_ref,
            },
        },
        {
            "figure_id": "fig:overview",
            "kind": "conceptual",
            "source": "idea + method_block",
            "design_objective": "show the PathLab WSI workflow",
            "backend": "paperbanana",
        },
        {
            "figure_id": "fig:user_overview",
            "kind": "conceptual",
            "source": "user uploaded concept art",
            "design_objective": "use user-provided artwork",
            "backend": "user_revision",
        },
    ]


@pytest.mark.asyncio
async def test_plotting_agent_dispatches_plan_and_captions_every_item(tmp_path) -> None:
    _paper_id, paths = await create_dev_run(paper_id="paper_plotting_agent", uploads_dir=tmp_path)
    paths.outline_json.write_text(
        json.dumps({"plotting_plan": _plotting_plan(_write_plot_data(paths))}),
        encoding="utf-8",
    )
    llm = MockCaptionLLM()

    result = PlottingAgent(llm).generate(paths)
    entries = {entry["figure_id"]: entry for entry in result.figures_manifest["figures"]}

    assert result.errors == ()
    assert entries["fig:calibration_agent"]["status"] == "ready"
    assert entries["fig:calibration_agent"]["kind"] == "empirical"
    assert entries["fig:calibration_agent"]["generator"] == "calibration_plot"
    assert entries["fig:calibration_agent"]["caption"] == "concise caption for fig:calibration_agent via calibration_plot."
    assert (paths.figures_dir / "fig_calibration_agent.png").is_file()
    assert entries["fig:overview"]["status"] == "requires_user_revision"
    assert entries["fig:overview"]["generator"] == "paperbanana"
    assert entries["fig:user_overview"]["status"] == "user_provided"
    assert entries["fig:user_overview"]["generator"] == "user_revision"
    assert [call["payload"]["figure_id"] for call in llm.calls] == [
        "fig:calibration_agent",
        "fig:overview",
        "fig:user_overview",
    ]
    assert all(call["temperature"] == 0.1 for call in llm.calls)
    assert all(call["response_format"] is None for call in llm.calls)


@pytest.mark.asyncio
async def test_plotting_stage_reuses_pathlab_chart_paths_without_redrawing(tmp_path) -> None:
    _paper_id, paths = await create_dev_run(paper_id="paper_plotting_reuse_chart", uploads_dir=tmp_path)
    source_chart = _write_pathlab_analysis_chart(paths, tmp_path, "roc_curve")
    paths.outline_json.write_text(json.dumps({"plotting_plan": []}), encoding="utf-8")
    manifest = PaperManifest.model_validate(json.loads(paths.manifest.read_text(encoding="utf-8")))

    run_plotting(paths, manifest, agent=PlottingAgent(MockCaptionLLM()))

    payload = json.loads(paths.figures_manifest.read_text(encoding="utf-8"))
    entries = {entry["figure_id"]: entry for entry in payload["figures"]}
    entry = entries["fig:pathlab_roc_curve"]
    final_path = paths.root / entry["path"]
    staged_source = paths.root / "figures/source_charts/chart_01_roc_curve.png"
    data_ref = paths.root / "evidence/plot_data/pathlab_chart_01_roc_curve.json"
    assert entry["status"] == "ready"
    assert entry["generator"] == "chart_passthrough"
    assert entry["path"] == "figures/fig_pathlab_roc_curve.png"
    assert final_path.read_bytes() == staged_source.read_bytes() == Path(source_chart).read_bytes()
    assert json.loads(data_ref.read_text(encoding="utf-8"))["source_path"] == (
        "figures/source_charts/chart_01_roc_curve.png"
    )
    assert source_chart not in paths.figures_manifest.read_text(encoding="utf-8")
    bridge_artifact = manifest.artifact_index["evidence/plot_data/pathlab_charts_manifest.json"]
    assert bridge_artifact["visibility"] == "private_backend_only"
    assert bridge_artifact["downloadable"] is False


@pytest.mark.asyncio
async def test_pathlab_chart_replaces_matching_outline_generator(tmp_path) -> None:
    _paper_id, paths = await create_dev_run(paper_id="paper_plotting_replace_chart", uploads_dir=tmp_path)
    _write_pathlab_analysis_chart(paths, tmp_path, "roc_curve")
    paths.outline_json.write_text(
        json.dumps(
            {
                "plotting_plan": [
                    {
                        "figure_id": "fig:main_roc",
                        "kind": "empirical",
                        "backend": "deterministic_plotting",
                        "plot_spec": {
                            "generator": "per_fold_roc",
                            "data_ref": "evidence/plot_data/missing_roc.json",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    manifest = PaperManifest.model_validate(json.loads(paths.manifest.read_text(encoding="utf-8")))

    run_plotting(paths, manifest, agent=PlottingAgent(MockCaptionLLM()))

    payload = json.loads(paths.figures_manifest.read_text(encoding="utf-8"))
    assert payload["figures"][0]["figure_id"] == "fig:main_roc"
    assert payload["figures"][0]["status"] == "ready"
    assert payload["figures"][0]["generator"] == "chart_passthrough"
    assert payload["figures"][0]["path"] == "figures/fig_main_roc.png"
    assert (paths.figures_dir / "fig_main_roc.png").is_file()


@pytest.mark.asyncio
async def test_crc_msi_fixture_charts_are_reused_from_raw_collected(tmp_path) -> None:
    fixture_dir = Path(__file__).parents[1] / "fixtures" / "crc_msi_classification"
    _paper_id, paths = await create_dev_run(paper_id="paper_plotting_crc_msi_fixture", uploads_dir=tmp_path)
    shutil.copytree(
        fixture_dir / "raw_collected",
        paths.evidence_dir / "raw_collected",
        dirs_exist_ok=True,
    )
    paths.outline_json.write_text(json.dumps({"plotting_plan": []}), encoding="utf-8")
    manifest = PaperManifest.model_validate(json.loads(paths.manifest.read_text(encoding="utf-8")))

    run_plotting(paths, manifest, agent=PlottingAgent(MockCaptionLLM()))

    payload = json.loads(paths.figures_manifest.read_text(encoding="utf-8"))
    entries = {entry["figure_id"]: entry for entry in payload["figures"]}
    for figure_id in (
        "fig:pathlab_roc_curve",
        "fig:pathlab_pr_curve",
        "fig:pathlab_confusion_matrix",
        "fig:pathlab_calibration",
    ):
        assert entries[figure_id]["status"] == "ready"
        assert entries[figure_id]["generator"] == "chart_passthrough"
        assert (paths.root / entries[figure_id]["path"]).is_file()


@pytest.mark.asyncio
async def test_plotting_stage_writes_manifest_and_registers_generated_artifact(tmp_path) -> None:
    _paper_id, paths = await create_dev_run(paper_id="paper_plotting_stage", uploads_dir=tmp_path)
    paths.outline_json.write_text(
        json.dumps({"plotting_plan": _plotting_plan(_write_plot_data(paths))}),
        encoding="utf-8",
    )
    manifest = PaperManifest.model_validate(json.loads(paths.manifest.read_text(encoding="utf-8")))

    run_plotting(paths, manifest, agent=PlottingAgent(MockCaptionLLM()))

    payload = json.loads(paths.figures_manifest.read_text(encoding="utf-8"))
    entries = {entry["figure_id"]: entry for entry in payload["figures"]}
    assert set(entries) == {"fig:calibration_agent", "fig:overview", "fig:user_overview"}
    assert manifest.artifact_index["figures/manifest.json"]["visibility"] == "public"
    assert manifest.artifact_index["figures/fig_calibration_agent.png"]["content_type"] == "image/png"
    assert "figures/fig_overview.png" not in manifest.artifact_index


@pytest.mark.asyncio
async def test_inline_empirical_data_is_rejected(tmp_path) -> None:
    _paper_id, paths = await create_dev_run(paper_id="paper_plotting_inline", uploads_dir=tmp_path)
    paths.outline_json.write_text(
        json.dumps(
            {
                "plotting_plan": [
                    {
                        "figure_id": "fig:inline",
                        "kind": "empirical",
                        "backend": "deterministic_plotting",
                        "plot_spec": {
                            "generator": "calibration_plot",
                            "data": {"confidence": [0.1], "accuracy": [0.2]},
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    manifest = PaperManifest.model_validate(json.loads(paths.manifest.read_text(encoding="utf-8")))

    with pytest.raises(RuntimeError, match="inline empirical plot data"):
        run_plotting(paths, manifest, agent=PlottingAgent(MockCaptionLLM()))

    payload = json.loads(paths.figures_manifest.read_text(encoding="utf-8"))
    assert payload["figures"][0]["status"] == "pending_generation"
    assert "inline empirical plot data" in payload["figures"][0]["error"]


@pytest.mark.asyncio
async def test_manifest_scrubs_private_paths_and_cases(tmp_path) -> None:
    _paper_id, paths = await create_dev_run(paper_id="paper_plotting_phi", uploads_dir=tmp_path)
    paths.outline_json.write_text(
        json.dumps(
            {
                "plotting_plan": [
                    {
                        "figure_id": "fig:raw_path",
                        "kind": "conceptual",
                        "source": "/private/pathlab/CASE-1234/source.png",
                        "path": "/private/pathlab/CASE-1234/source.png",
                        "backend": "user_revision",
                    },
                    {
                        "figure_id": "fig:error_path",
                        "kind": "empirical",
                        "backend": "deterministic_plotting",
                        "plot_spec": {
                            "generator": "chart_passthrough",
                            "data": {"source_path": "/private/pathlab/CASE-5678/missing.png"},
                        },
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    manifest = PaperManifest.model_validate(json.loads(paths.manifest.read_text(encoding="utf-8")))

    with pytest.raises(RuntimeError, match="Empirical figure generation failed"):
        run_plotting(paths, manifest, agent=PlottingAgent(MockCaptionLLM()))

    text = paths.figures_manifest.read_text(encoding="utf-8")
    assert "/private/pathlab" not in text
    assert "CASE-1234" not in text
    assert "CASE-5678" not in text
    payload = json.loads(text)
    entries = {entry["figure_id"]: entry for entry in payload["figures"]}
    assert entries["fig:raw_path"]["path"] is None
    assert entries["fig:raw_path"]["source"] == "evidence_artifact"


@pytest.mark.asyncio
async def test_duplicate_figure_ids_are_deduplicated_before_render(tmp_path) -> None:
    _paper_id, paths = await create_dev_run(paper_id="paper_plotting_duplicate_ids", uploads_dir=tmp_path)
    first_ref = _write_plot_data(paths, "first.json")
    second_ref = _write_plot_data(paths, "second.json")
    paths.outline_json.write_text(
        json.dumps(
            {
                "plotting_plan": [
                    {
                        "figure_id": "fig:duplicate",
                        "kind": "empirical",
                        "backend": "deterministic_plotting",
                        "plot_spec": {"generator": "calibration_plot", "data_ref": first_ref},
                    },
                    {
                        "figure_id": "fig_duplicate",
                        "kind": "empirical",
                        "backend": "deterministic_plotting",
                        "plot_spec": {"generator": "calibration_plot", "data_ref": second_ref},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    result = PlottingAgent(MockCaptionLLM()).generate(paths)
    entries = result.figures_manifest["figures"]

    assert [entry["figure_id"] for entry in entries] == ["fig:duplicate", "fig_duplicate_2"]
    assert (paths.figures_dir / "fig_duplicate.png").is_file()
    assert (paths.figures_dir / "fig_duplicate_2.png").is_file()


@pytest.mark.asyncio
async def test_deterministic_failure_keeps_manifest_entry_then_raises(tmp_path) -> None:
    _paper_id, paths = await create_dev_run(paper_id="paper_plotting_missing_data", uploads_dir=tmp_path)
    paths.outline_json.write_text(
        json.dumps(
            {
                "plotting_plan": [
                    {
                        "figure_id": "fig:missing_data",
                        "kind": "empirical",
                        "source": "analysis_summary",
                        "backend": "deterministic_plotting",
                        "plot_spec": {
                            "generator": "calibration_plot",
                            "data_ref": "evidence/plot_data/missing.json",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    manifest = PaperManifest.model_validate(json.loads(paths.manifest.read_text(encoding="utf-8")))

    with pytest.raises(RuntimeError, match="Empirical figure generation failed"):
        run_plotting(paths, manifest, agent=PlottingAgent(MockCaptionLLM()))

    payload = json.loads(paths.figures_manifest.read_text(encoding="utf-8"))
    entry = payload["figures"][0]
    assert entry["figure_id"] == "fig:missing_data"
    assert entry["status"] == "pending_generation"
    assert entry["kind"] == "empirical"
    assert entry["caption"] == "concise caption for fig:missing_data via calibration_plot."
    assert "does not exist" in entry["error"]
