from __future__ import annotations

import json

import pytest

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
