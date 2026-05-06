from __future__ import annotations

import json
import pytest

from pathlab_paper_agent.agents.section_writing_agent import (
    SectionCitationContractError,
    SectionFigureTableContractError,
    SectionMetricContractError,
    SectionPhiLeakError,
    SectionWritingAgent,
    SectionWritingInputs,
    parse_sections_json,
)
from pathlab_paper_agent.llm import LLMResponse
from pathlab_paper_agent.pipeline import create_dev_run
from pathlab_paper_agent.renderers.citation_renderer import CitationRenderError, render_citation_placeholders
from pathlab_paper_agent.schemas import CreatePaperRequest, PaperManifest, SourceTaskRef, TemplateId
from pathlab_paper_agent.stages.sections import run as run_sections
from pathlab_paper_agent.validators.citation_guard import run as run_citation_guard
from pathlab_paper_agent.validators.identifier_guard import run as run_identifier_guard
from pathlab_paper_agent.validators.latex_guard import run as run_latex_guard
from pathlab_paper_agent.validators.metric_guard import run as run_metric_guard


class MockLLM:
    def __init__(self, response: dict | str) -> None:
        self.response = response
        self.calls: list[dict] = []

    def complete(
        self,
        messages,
        *,
        temperature: float = 0.2,
        response_format=None,
        stream=None,
    ) -> LLMResponse:
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "response_format": response_format,
                "stream": stream,
            }
        )
        response = self.response(messages[-1].content) if callable(self.response) else self.response
        content = json.dumps(response) if isinstance(response, dict) else str(response)
        return LLMResponse(content=content, model="mock-section", provider="mock")


def _payload_from_prompt(prompt: str) -> dict:
    marker = "Input payload:"
    assert marker in prompt
    payload = json.loads(prompt.split(marker, 1)[1].strip())
    assert isinstance(payload, dict)
    return payload


def _outline() -> dict:
    return {
        "plotting_plan": [],
        "section_plan": [
            {"section": "Abstract", "goal": "summarize the locked study"},
            {"section": "Introduction", "goal": "motivate the problem"},
            {"section": "Related Work", "goal": "position the work"},
            {
                "section": "Methods",
                "goal": "describe method using locked blocks",
                "locked_block_inputs": ["locked_blocks/method_block.tex"],
            },
            {
                "section": "Experimental Setup",
                "goal": "describe evidence-backed cohorts",
                "locked_block_inputs": ["locked_blocks/dataset_block.tex"],
            },
            {
                "section": "Results",
                "goal": "report locked metrics",
                "locked_block_inputs": ["locked_blocks/results_block.tex"],
            },
            {"section": "Discussion", "goal": "state bounded interpretation"},
            {"section": "Conclusion", "goal": "close the paper"},
        ],
    }


def _refs() -> tuple[list[dict], list[dict]]:
    selected = [
        {
            "key": "ABMIL2021",
            "title": "Attention multiple instance learning for pathology",
            "authors": ["Mock Author"],
            "year": 2021,
        },
        {
            "key": "CLINVAL2022",
            "title": "Clinical validation of computational pathology models",
            "authors": ["Validation Author"],
            "year": 2022,
        },
    ]
    required = [selected[1]]
    return selected, required


def _sections_payload(*, metric_key: str = "main.metrics.test_accuracy") -> dict:
    return {
        "sections": {
            "abstract": (
                "\\begin{abstract}\n"
                f"PathLab writes around locked evidence and reports {{{{m:{metric_key}}}}}.\n"
                "\\end{abstract}\n"
            ),
            "introduction": (
                "\\section{Introduction}\n"
                "Pathology model reporting needs citation-grounded context [CITE:ABMIL2021].\n"
            ),
            "related_work": (
                "\\section{Related Work}\n"
                "Clinical validation frames deployment claims [CITE:CLINVAL2022].\n"
            ),
            "methods": "\\section{Methods}\n\\input{locked_blocks/method_block.tex}\n",
            "experiments": "\\section{Experimental Setup}\n\\input{locked_blocks/dataset_block.tex}\n",
            "results": (
                "\\section{Results}\n"
                "\\input{locked_blocks/results_block.tex}\n"
                "\\input{tables/table_2_main_results.tex}\n"
                "\\begin{figure}[t]\n"
                "\\centering\n"
                "\\includegraphics[width=0.95\\linewidth]{figures/fig_main.png}\n"
                "\\caption{Ready PathLab figure.}\n"
                "\\label{fig:main}\n"
                "\\end{figure}\n"
                f"The locked primary metric is {{{{m:{metric_key}}}}}.\n"
            ),
            "discussion": "\\section{Discussion}\nClaims remain bounded by locked evidence.\n",
            "conclusion": "\\section{Conclusion}\nThe evidence-locked draft is ready for guard validation.\n",
        }
    }


def _write_minimal_inputs(paths) -> None:
    selected, required = _refs()
    paths.outline_json.write_text(json.dumps(_outline()), encoding="utf-8")
    (paths.intro_rw_draft_dir / "introduction.tex").write_text(
        "\\section{Introduction}\nDraft intro cites prior work \\cite{ABMIL2021}.\n",
        encoding="utf-8",
    )
    (paths.intro_rw_draft_dir / "related_work.tex").write_text(
        "\\section{Related Work}\nDraft RW cites validation \\cite{CLINVAL2022}.\n",
        encoding="utf-8",
    )
    paths.figures_manifest.write_text(
        json.dumps(
            {
                "figures": [
                    {
                        "figure_id": "fig:main",
                        "status": "ready",
                        "path": "figures/fig_main.png",
                        "caption": "Locked main-result visualization.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (paths.figures_dir / "fig_main.png").write_bytes(b"not a real png but guard only checks existence")
    paths.refs_bib.write_text(
        "@article{ABMIL2021, title={Attention MIL}, year={2021}}\n"
        "@article{CLINVAL2022, title={Clinical Validation}, year={2022}}\n",
        encoding="utf-8",
    )
    (paths.citations_dir / "selected_refs.json").write_text(json.dumps({"items": selected}), encoding="utf-8")
    (paths.citations_dir / "required_cites.json").write_text(json.dumps({"items": required}), encoding="utf-8")
    paths.evidence_lock_private.write_text(
        json.dumps(
            {
                "source_tasks": [{"task_id": "task_secret_123"}],
                "metrics": {
                    "main.metrics.test_accuracy": {
                        "value": 0.9123,
                        "formatted": "0.9123",
                        "task_id": "task_secret_123",
                        "analysis_id": "analysis_secret_456",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    paths.experimental_log.write_text("# Experimental Log\n\nMetrics are available through locked placeholders.\n", encoding="utf-8")
    paths.idea.write_text("# Idea\nEvidence-locked WSI model reporting.\n", encoding="utf-8")
    for name, text in {
        "method_block.tex": "The locked method block describes the model without raw private paths.\n",
        "dataset_block.tex": "The locked dataset block describes the scrubbed cohort.\n",
        "results_block.tex": "The locked results block delegates metric text to evidence placeholders.\n",
        "evidence_gaps.tex": "No blocking evidence gap is reported for this fixture.\n",
        "metrics_macros.tex": "% Metric macros are deterministic in production.\n",
    }.items():
        (paths.locked_blocks_dir / name).write_text(text, encoding="utf-8")
    (paths.tables_dir / "table_2_main_results.tex").write_text(
        "\\begin{tabular}{ll}\n\\toprule\nMetric & Value \\\\\n\\midrule\nPrimary & locked \\\\\n\\bottomrule\n\\end{tabular}\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_section_agent_prompt_contains_all_m9_inputs_and_normalizes_intro_rw_cites(tmp_path) -> None:
    _paper_id, paths = await create_dev_run(paper_id="paper_sections_prompt", uploads_dir=tmp_path)
    _write_minimal_inputs(paths)
    llm = MockLLM(_sections_payload())
    agent = SectionWritingAgent(llm)

    result = agent.generate(SectionWritingInputs.from_paths(paths, json.loads(paths.config.read_text(encoding="utf-8"))))

    assert "0.9123" in result.sections["results"]
    assert len(llm.calls) == 1
    assert llm.calls[0]["response_format"] == {"type": "json_object"}
    prompt = llm.calls[0]["messages"][1].content
    payload = _payload_from_prompt(prompt)
    assert payload["outline"]["section_plan"][1]["section"] == "Introduction"
    assert payload["drafts_intro_rw_draft"]["introduction"].count("[CITE:ABMIL2021]") == 1
    assert "\\cite{ABMIL2021}" not in payload["drafts_intro_rw_draft"]["introduction"]
    assert payload["figures_manifest"]["figures"][0]["figure_id"] == "fig:main"
    assert "@article{ABMIL2021" in payload["citations"]["refs_bib"]
    assert payload["section_contract"]["required_cite_keys"] == ["CLINVAL2022"]
    assert payload["generation_template_id"] == "miccai"
    assert payload["section_contract"]["generation_template_id"] == "miccai"
    assert payload["section_contract"]["single_template_run"] is True
    assert "abstract" in payload["section_guidelines"]
    assert "must_include" in payload["section_guidelines"]["abstract"]
    assert "main.metrics.test_accuracy" in payload["section_contract"]["allowed_metric_keys"]
    prompt_text = llm.calls[0]["messages"][1].content
    assert "task_secret_123" not in prompt_text
    assert "analysis_secret_456" not in prompt_text
    assert {item["path"] for item in payload["locked_blocks"]} >= {
        "locked_blocks/method_block.tex",
        "locked_blocks/dataset_block.tex",
        "locked_blocks/results_block.tex",
    }


@pytest.mark.asyncio
async def test_section_agent_prompt_uses_user_selected_nature_guidelines(tmp_path) -> None:
    request = CreatePaperRequest(
        source_tasks=[SourceTaskRef(task_id="paper_dev_source")],
        selected_templates=[TemplateId.nature_scientific_reports],
    )
    _paper_id, paths = await create_dev_run(request, paper_id="paper_sections_nature_prompt", uploads_dir=tmp_path)
    _write_minimal_inputs(paths)

    inputs = SectionWritingInputs.from_paths(paths, json.loads(paths.config.read_text(encoding="utf-8")))
    prompt = SectionWritingAgent(MockLLM(_sections_payload())).build_prompt(inputs)
    payload = _payload_from_prompt(prompt)

    assert payload["generation_template_id"] == "nature_scientific_reports"
    assert payload["primary_template_style"]["venue"] == "Nature Scientific Reports"
    assert payload["section_guidelines"]["results"]["purpose"].startswith("Present findings before Methods")


@pytest.mark.asyncio
async def test_section_agent_renders_metric_and_citation_placeholders(tmp_path) -> None:
    _paper_id, paths = await create_dev_run(paper_id="paper_sections_render", uploads_dir=tmp_path)
    _write_minimal_inputs(paths)

    result = SectionWritingAgent(MockLLM(_sections_payload())).generate(
        SectionWritingInputs.from_paths(paths, json.loads(paths.config.read_text(encoding="utf-8")))
    )

    assert "\\cite{ABMIL2021}" in result.sections["introduction"]
    assert "\\cite{CLINVAL2022}" in result.sections["related_work"]
    assert "0.9123" in result.sections["abstract"]
    assert "{{m:" not in "\n".join(result.sections.values())
    assert "[CITE:" not in "\n".join(result.sections.values())


@pytest.mark.asyncio
async def test_section_agent_repairs_missing_required_locked_block_inputs(tmp_path) -> None:
    _paper_id, paths = await create_dev_run(paper_id="paper_sections_repair_locked_block", uploads_dir=tmp_path)
    _write_minimal_inputs(paths)
    payload = _sections_payload()
    payload["sections"]["experiments"] = "\\section{Experimental Setup}\nThe cohort is described from locked evidence.\n"

    result = SectionWritingAgent(MockLLM(payload)).generate(
        SectionWritingInputs.from_paths(paths, json.loads(paths.config.read_text(encoding="utf-8")))
    )

    assert "\\input{locked_blocks/dataset_block.tex}" in result.sections["experiments"]


@pytest.mark.asyncio
async def test_section_agent_rejects_missing_required_cite(tmp_path) -> None:
    _paper_id, paths = await create_dev_run(paper_id="paper_sections_missing_required", uploads_dir=tmp_path)
    _write_minimal_inputs(paths)
    payload = _sections_payload()
    payload["sections"]["related_work"] = "\\section{Related Work}\nNo required citation remains.\n"

    with pytest.raises(SectionCitationContractError, match="Required citation"):
        SectionWritingAgent(MockLLM(payload)).generate(
            SectionWritingInputs.from_paths(paths, json.loads(paths.config.read_text(encoding="utf-8")))
        )


@pytest.mark.asyncio
async def test_section_agent_rejects_unknown_cite_outside_selected_refs(tmp_path) -> None:
    _paper_id, paths = await create_dev_run(paper_id="paper_sections_unknown_cite", uploads_dir=tmp_path)
    _write_minimal_inputs(paths)
    payload = _sections_payload()
    payload["sections"]["discussion"] = "\\section{Discussion}\nUnsupported citation [CITE:Ghost2026].\n"

    with pytest.raises(SectionCitationContractError, match="outside selected_refs"):
        SectionWritingAgent(MockLLM(payload)).generate(
            SectionWritingInputs.from_paths(paths, json.loads(paths.config.read_text(encoding="utf-8")))
        )


@pytest.mark.asyncio
async def test_section_agent_rejects_raw_cite_and_raw_metric_numbers(tmp_path) -> None:
    _paper_id, paths = await create_dev_run(paper_id="paper_sections_raw_contract", uploads_dir=tmp_path)
    _write_minimal_inputs(paths)
    raw_cite_payload = _sections_payload()
    raw_cite_payload["sections"]["introduction"] = "\\section{Introduction}\nRaw cite \\cite{ABMIL2021}.\n"

    with pytest.raises(SectionCitationContractError, match="raw"):
        SectionWritingAgent(MockLLM(raw_cite_payload)).generate(
            SectionWritingInputs.from_paths(paths, json.loads(paths.config.read_text(encoding="utf-8")))
        )

    raw_metric_payload = _sections_payload()
    raw_metric_payload["sections"]["results"] = (
        "\\section{Results}\n\\input{locked_blocks/results_block.tex}\nThe model reached 0.9123.\n"
    )
    with pytest.raises(SectionMetricContractError, match="raw metric-like"):
        SectionWritingAgent(MockLLM(raw_metric_payload)).generate(
            SectionWritingInputs.from_paths(paths, json.loads(paths.config.read_text(encoding="utf-8")))
        )


@pytest.mark.asyncio
async def test_sections_stage_writes_final_sections_and_registers_artifacts(tmp_path) -> None:
    _paper_id, paths = await create_dev_run(paper_id="paper_sections_stage", uploads_dir=tmp_path)
    _write_minimal_inputs(paths)
    manifest = PaperManifest.model_validate(json.loads(paths.manifest.read_text(encoding="utf-8")))

    run_sections(paths, manifest, agent=SectionWritingAgent(MockLLM(_sections_payload())))

    assert (paths.sections_dir / "introduction.tex").read_text(encoding="utf-8").startswith("\\section{Introduction}")
    assert "\\cite{ABMIL2021}" in (paths.sections_dir / "introduction.tex").read_text(encoding="utf-8")
    assert "0.9123" in (paths.sections_dir / "results.tex").read_text(encoding="utf-8")
    assert (paths.intro_rw_draft_dir / "introduction.tex").read_text(encoding="utf-8").startswith("\\section{Introduction}")
    assert manifest.artifact_index["drafts/sections/results.tex"]["content_type"] == "text/x-tex"


@pytest.mark.asyncio
async def test_m9_outputs_pass_m10a_deterministic_guards(tmp_path) -> None:
    _paper_id, paths = await create_dev_run(paper_id="paper_sections_guards", uploads_dir=tmp_path)
    _write_minimal_inputs(paths)
    manifest = PaperManifest.model_validate(json.loads(paths.manifest.read_text(encoding="utf-8")))

    run_sections(paths, manifest, agent=SectionWritingAgent(MockLLM(_sections_payload())))

    reports = [
        run_metric_guard(paths),
        run_identifier_guard(paths),
        run_latex_guard(paths),
        run_citation_guard(paths),
    ]
    assert {report.guard: report.status for report in reports} == {
        "metric_guard": "pass",
        "identifier_guard": "pass",
        "latex_guard": "pass",
        "citation_guard": "pass",
    }


def test_parse_sections_json_accepts_fenced_response() -> None:
    parsed = parse_sections_json(f"```json\n{json.dumps(_sections_payload())}\n```")

    assert parsed["introduction"].startswith("\\section{Introduction}")


def test_citation_renderer_is_strict_about_allowed_and_malformed_keys() -> None:
    assert render_citation_placeholders("See [CITE:ABMIL2021].", {"ABMIL2021"}) == "See \\cite{ABMIL2021}."
    with pytest.raises(CitationRenderError, match="not present"):
        render_citation_placeholders("See [CITE:Ghost2026].", {"ABMIL2021"})
    with pytest.raises(CitationRenderError, match="Malformed"):
        render_citation_placeholders("See [CITE:Bad Key].", {"Bad Key"})


@pytest.mark.asyncio
async def test_section_agent_rejects_private_source_ids_in_output(tmp_path) -> None:
    _paper_id, paths = await create_dev_run(paper_id="paper_sections_private_source", uploads_dir=tmp_path)
    _write_minimal_inputs(paths)
    payload = _sections_payload()
    payload["sections"]["discussion"] = "\\section{Discussion}\nThis text copied task_secret_123 from private evidence.\n"

    with pytest.raises(SectionPhiLeakError, match="Private source identifier"):
        SectionWritingAgent(MockLLM(payload)).generate(
            SectionWritingInputs.from_paths(paths, json.loads(paths.config.read_text(encoding="utf-8")))
        )


@pytest.mark.asyncio
async def test_section_agent_requires_ready_figures_and_rejects_invented_tables(tmp_path) -> None:
    _paper_id, paths = await create_dev_run(paper_id="paper_sections_figure_contract", uploads_dir=tmp_path)
    _write_minimal_inputs(paths)
    missing_figure = _sections_payload()
    missing_figure["sections"]["results"] = (
        "\\section{Results}\n"
        "\\input{locked_blocks/results_block.tex}\n"
        "\\input{tables/table_2_main_results.tex}\n"
        "The locked primary metric is {{m:main.metrics.test_accuracy}}.\n"
    )

    with pytest.raises(SectionFigureTableContractError, match="Ready figure"):
        SectionWritingAgent(MockLLM(missing_figure)).generate(
            SectionWritingInputs.from_paths(paths, json.loads(paths.config.read_text(encoding="utf-8")))
        )

    invented_table = _sections_payload()
    invented_table["sections"]["results"] = invented_table["sections"]["results"].replace(
        "\\input{tables/table_2_main_results.tex}",
        "\\input{tables/table_999_invented.tex}",
    )
    with pytest.raises(SectionFigureTableContractError, match="Table input"):
        SectionWritingAgent(MockLLM(invented_table)).generate(
            SectionWritingInputs.from_paths(paths, json.loads(paths.config.read_text(encoding="utf-8")))
        )
