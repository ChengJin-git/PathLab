from __future__ import annotations

import json

import httpx
import pytest

from pathlab_paper_agent.agents import OutlineAgent, OutlineInputs, PhiLeakError
from pathlab_paper_agent.agents.outline_agent import OutlineAgentError, parse_outline_json
from pathlab_paper_agent.llm import LLMConfig, LLMConfigurationError, LLMMessage, LLMResponse
from pathlab_paper_agent.llm.client import OpenAICompatibleLLMClient
from pathlab_paper_agent.pipeline import create_dev_run
from pathlab_paper_agent.stages.outlining import run as run_outlining


def _outline_payload(marker: str = "llm-generated") -> dict:
    return {
        "plotting_plan": [
            {
                "figure_id": "fig:main_results",
                "kind": "empirical",
                "source": "experimental_log",
                "design_objective": marker,
                "backend": "deterministic_plotting",
                "plot_spec": {"generator": "per_fold_roc"},
            }
        ],
        "macro_lit_search": ["whole slide image computational pathology validation"],
        "micro_lit_clusters": [
            {
                "cluster": "multiple instance learning for WSI",
                "queries": ["attention MIL whole slide images"],
            }
        ],
        "section_plan": [
            {
                "section": "Introduction",
                "goal": "motivate the clinical and computational gap",
                "evidence_inputs": ["idea", "experimental_log", "evidence_public"],
                "citation_hints": ["computational pathology", "clinical validation"],
                "locked_block_inputs": ["locked_blocks/method_block.tex"],
            }
        ],
        "pathlab_extensions": {
            "templates": ["miccai"],
            "claim_plan": [
                {
                    "claim": "The model is evaluated on locked PathLab evidence.",
                    "evidence_source": "experimental_log",
                    "strength": "moderate",
                }
            ],
            "table_plan": [],
            "guard_requirements": ["metric", "identifier"],
        },
    }


class MockLLM:
    def __init__(self, response: str | dict) -> None:
        self.response = json.dumps(response) if isinstance(response, dict) else response
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
        return LLMResponse(content=self.response, model="mock", provider="mock")


def _inputs() -> OutlineInputs:
    return OutlineInputs(
        idea="# Core idea\nUse MIL for WSI outcome prediction.",
        experimental_log="# Experimental Log\n- main.auroc: 0.91",
        evidence_public={"metrics": [{"name": "main.auroc", "value": 0.91}]},
        tables_manifest={"tables": [{"path": "tables/table_1_dataset.tex"}]},
        template_styles=[
            {
                "template_id": "miccai",
                "venue": "MICCAI",
                "section_order": ["abstract", "introduction", "methods", "results"],
                "required_sections": ["abstract", "introduction", "methods", "results"],
                "style_constraints": {"max_references": 30},
            }
        ],
        figures_manifest={"figures": [{"figure_id": "fig:existing", "status": "ready"}]},
        conference_guidelines="# Guidelines\nUse a concise MICCAI style.",
        title="Mock PathLab Paper",
    )


def test_outline_agent_calls_mock_llm_with_all_inputs() -> None:
    llm = MockLLM(_outline_payload(marker="from mocked LLM"))
    agent = OutlineAgent(llm)

    outline = agent.generate(_inputs())

    assert outline["plotting_plan"][0]["design_objective"] == "from mocked LLM"
    assert outline["pathlab_extensions"]["templates"] == ["miccai"]
    assert outline["template_style"]["max_refs"] == 30
    assert len(llm.calls) == 1
    prompt = llm.calls[0]["messages"][1].content
    assert "Use MIL for WSI outcome prediction" in prompt
    assert "main.auroc" in prompt
    assert '"evidence_public"' in prompt
    assert '"tables_manifest"' in prompt
    assert "concise MICCAI style" in prompt
    assert '"template_id": "miccai"' in prompt
    assert '"figure_id": "fig:existing"' in prompt
    assert llm.calls[0]["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_outlining_stage_writes_llm_output_and_manifest(tmp_path) -> None:
    _paper_id, paths = await create_dev_run(paper_id="paper_outline", uploads_dir=tmp_path)
    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    from pathlab_paper_agent.schemas import PaperManifest

    paper_manifest = PaperManifest.model_validate(manifest)
    paths.idea.write_text("# Idea\nLLM should drive this outline.\n", encoding="utf-8")
    paths.experimental_log.write_text("# Experimental Log\n- main.f1: 0.88\n", encoding="utf-8")
    paths.evidence_public.write_text(json.dumps({"metrics": [{"name": "main.f1", "value": 0.88}]}), encoding="utf-8")
    (paths.tables_dir / "manifest.json").write_text(
        json.dumps({"tables": [{"path": "tables/table_1_dataset.tex"}]}),
        encoding="utf-8",
    )
    (paths.inputs_dir / "conference_guidelines.md").write_text(
        "# Venue\nFollow MICCAI limits.\n",
        encoding="utf-8",
    )
    paths.figures_manifest.write_text(
        json.dumps({"figures": [{"figure_id": "fig:roc", "status": "ready"}]}),
        encoding="utf-8",
    )
    agent = OutlineAgent(MockLLM(_outline_payload(marker="stage mock marker")))

    run_outlining(paths, paper_manifest, agent=agent)

    outline = json.loads(paths.outline_json.read_text(encoding="utf-8"))
    assert outline["plotting_plan"][0]["design_objective"] == "stage mock marker"
    assert outline["section_plan"][0]["goal"] != "scaffold"
    assert paper_manifest.artifact_index["drafts/outline.json"]["visibility"] == "public"


@pytest.mark.parametrize(
    ("field", "value", "expected_count_key"),
    [
        ("idea", "Results live at /private/pathlab/raw/run.csv", "raw_paths"),
        ("experimental_log", "Slide CASE-0001 must not leak.", "case_ids"),
        ("idea", "Data came from Example Hospital.", "institution_names"),
        ("experimental_log", r"Data lives at C:\\PathLab\\raw\\slide.svs", "raw_paths"),
        ("idea", "Results live at /mnt/pathlab/raw/run.csv", "raw_paths"),
        ("experimental_log", r"Raw share \\nas01\pathlab\slide.svs", "raw_paths"),
        ("experimental_log", "Surgery on 2024-01-15 at the cohort site.", "dates"),
    ],
)
def test_phi_hard_fails_before_llm_call(field: str, value: str, expected_count_key: str) -> None:
    llm = MockLLM(_outline_payload())
    inputs = _inputs()
    data = inputs.__dict__.copy()
    data[field] = value
    agent = OutlineAgent(llm)

    with pytest.raises(PhiLeakError, match=expected_count_key):
        agent.generate(OutlineInputs(**data))

    assert llm.calls == []


def test_parse_outline_json_accepts_fenced_response() -> None:
    payload = _outline_payload()

    parsed = parse_outline_json(f"Here is the JSON:\n```json\n{json.dumps(payload)}\n```")

    assert parsed["plotting_plan"][0]["figure_id"] == "fig:main_results"


def test_parse_outline_json_rejects_missing_required_fields() -> None:
    agent = OutlineAgent(MockLLM({"plotting_plan": []}))

    with pytest.raises(OutlineAgentError, match="missing required"):
        agent.generate(_inputs())


def test_outline_schema_rejects_malformed_items() -> None:
    payload = _outline_payload()
    payload["plotting_plan"] = [123]
    agent = OutlineAgent(MockLLM(payload))

    with pytest.raises(OutlineAgentError, match="schema validation failed"):
        agent.generate(_inputs())


def test_reasoning_model_streams_and_aggregates_sse() -> None:
    seen_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_payloads.append(json.loads(request.content.decode("utf-8")))
        body = "\n\n".join(
            [
                'data: {"model":"gpt-5.5","choices":[{"delta":{"content":"{\\"ok\\":"}}]}',
                'data: {"choices":[{"delta":{"content":"true}"}}]}',
                "data: [DONE]",
            ]
        )
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    client = OpenAICompatibleLLMClient(
        LLMConfig(
            base_url="https://mock-llm.invalid/v1",
            api_key="test",
            model="gpt-5.5",
            provider="mock",
        ),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    response = client.complete([LLMMessage(role="user", content="hi")])

    assert response.content == '{"ok":true}'
    assert seen_payloads[0]["stream"] is True
    assert seen_payloads[0]["reasoning_effort"] == "xhigh"


def test_default_llm_config_uses_gpt55_xhigh(monkeypatch) -> None:
    monkeypatch.delenv("PAPER_GEN_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("PAPER_GEN_LLM_API_KEY", raising=False)
    monkeypatch.delenv("PAPER_GEN_LLM_MODEL", raising=False)
    monkeypatch.delenv("PAPER_GEN_LLM_REASONING_EFFORT", raising=False)
    monkeypatch.delenv("PAPER_GEN_VLLM_MODEL", raising=False)
    monkeypatch.delenv("PAPER_GEN_VLLM_REASONING_EFFORT", raising=False)

    config = LLMConfig.from_env()

    assert config.model == "gpt-5.5"
    assert config.reasoning_effort == "xhigh"
    assert config.timeout_s == 300.0


def test_transient_timeout_is_retried_once_before_failing() -> None:
    seen_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_payloads.append(json.loads(request.content.decode("utf-8")))
        if len(seen_payloads) == 1:
            raise httpx.TimeoutException("simulated transient timeout")
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "retried ok"}}]},
        )

    client = OpenAICompatibleLLMClient(
        LLMConfig(
            base_url="https://primary.invalid/v1",
            api_key="test",
            model="gpt-4o-mini",
            provider="primary",
        ),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    response = client.complete([LLMMessage(role="user", content="hi")])

    assert response.content == "retried ok"
    assert len(seen_payloads) == 2
    assert "reasoning_effort" not in seen_payloads[0]


def test_two_transient_timeouts_trigger_fallback_when_available() -> None:
    seen_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_payloads.append(json.loads(request.content.decode("utf-8")))
        # Primary times out twice (one initial + one retry), then fallback succeeds.
        if len(seen_payloads) <= 2:
            raise httpx.TimeoutException("simulated primary timeout")
        return httpx.Response(
            200,
            json={
                "model": "fallback-model",
                "choices": [{"message": {"content": "fallback ok"}}],
            },
        )

    client = OpenAICompatibleLLMClient(
        LLMConfig(
            base_url="https://primary.invalid/v1",
            api_key="test",
            model="gpt-4o-mini",
            provider="primary",
        ),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        fallback_config=LLMConfig(
            base_url="https://fallback.invalid/v1",
            api_key="fallback",
            model="fallback-model",
            provider="openrouter",
        ),
    )

    response = client.complete([LLMMessage(role="user", content="hi")])

    assert response.content == "fallback ok"
    assert len(seen_payloads) == 3


def test_invalid_primary_payload_falls_back_to_openrouter_config() -> None:
    seen_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_payloads.append(json.loads(request.content.decode("utf-8")))
        if len(seen_payloads) == 1:
            return httpx.Response(200, json={"choices": []})
        return httpx.Response(
            200,
            json={
                "model": "fallback-model",
                "choices": [{"message": {"content": "fallback ok"}}],
            },
        )

    client = OpenAICompatibleLLMClient(
        LLMConfig(
            base_url="https://primary.invalid/v1",
            api_key="test",
            model="gpt-4o-mini",
            provider="primary",
        ),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        fallback_config=LLMConfig(
            base_url="https://fallback.invalid/v1",
            api_key="fallback",
            model="fallback-model",
            provider="openrouter",
        ),
    )

    response = client.complete([LLMMessage(role="user", content="hi")])

    assert response.content == "fallback ok"
    assert len(seen_payloads) == 2


def test_invalid_primary_json_falls_back_to_openrouter_config() -> None:
    seen_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_payloads.append(json.loads(request.content.decode("utf-8")))
        if len(seen_payloads) == 1:
            return httpx.Response(200, text="not-json")
        return httpx.Response(
            200,
            json={
                "model": "fallback-model",
                "choices": [{"message": {"content": "fallback ok"}}],
            },
        )

    client = OpenAICompatibleLLMClient(
        LLMConfig(
            base_url="https://primary.invalid/v1",
            api_key="test",
            model="gpt-4o-mini",
            provider="primary",
        ),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        fallback_config=LLMConfig(
            base_url="https://fallback.invalid/v1",
            api_key="fallback",
            model="fallback-model",
            provider="openrouter",
        ),
    )

    response = client.complete([LLMMessage(role="user", content="hi")])

    assert response.content == "fallback ok"
    assert len(seen_payloads) == 2


def test_llm_env_override_requires_all_fields(monkeypatch) -> None:
    monkeypatch.setenv("PAPER_GEN_LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.delenv("PAPER_GEN_LLM_API_KEY", raising=False)
    monkeypatch.delenv("PAPER_GEN_LLM_MODEL", raising=False)

    with pytest.raises(LLMConfigurationError):
        LLMConfig.from_env()


def test_default_llm_client_uses_no_network_fixture_in_pytest_even_when_provider_env_set(
    monkeypatch,
) -> None:
    # Regression: a developer exporting PAPER_GEN_LLM_BASE_URL for smoke testing
    # must not turn pytest into a live-network run by accident.
    from pathlab_paper_agent.agents.outline_agent import (
        _NoNetworkOutlineLLMClient,
        _default_llm_client,
    )

    monkeypatch.setenv("PAPER_GEN_LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("PAPER_GEN_LLM_API_KEY", "test-key")
    monkeypatch.setenv("PAPER_GEN_LLM_MODEL", "gpt-5.5")
    monkeypatch.delenv("PAPER_GEN_LLM_ALLOW_NETWORK_IN_TESTS", raising=False)

    client = _default_llm_client()
    assert isinstance(client, _NoNetworkOutlineLLMClient)


def test_default_llm_client_honours_explicit_network_opt_in(monkeypatch) -> None:
    from pathlab_paper_agent.agents.outline_agent import (
        _NoNetworkOutlineLLMClient,
        _default_llm_client,
    )

    monkeypatch.setenv("PAPER_GEN_LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("PAPER_GEN_LLM_API_KEY", "test-key")
    monkeypatch.setenv("PAPER_GEN_LLM_MODEL", "gpt-5.5")
    monkeypatch.setenv("PAPER_GEN_LLM_ALLOW_NETWORK_IN_TESTS", "1")

    client = _default_llm_client()
    assert not isinstance(client, _NoNetworkOutlineLLMClient)
