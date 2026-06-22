from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pathscientist.literature.benchmark_extractor import BenchmarkExtractor
from pathscientist.literature.types import PaperRecord


def _paper(pid: str, abstract: str) -> PaperRecord:
    return PaperRecord(
        paper_id=pid, title=f"p{pid}", authors=["x"], year=2024,
        abstract=abstract, venue="", source="openalex", url="",
        methods=[], datasets=[], baselines=[], organ="", task_type="", tags=[],
    )


def test_extract_parses_llm_json_output():
    """The LLM returns structured JSON; we parse it into ExtractedBenchmark."""
    fake_response = json.dumps([
        {"method": "KatherNet", "dataset": "CRC-MSI", "metric_name": "auc",
         "metric_value": 0.87, "evidence": "achieved 0.87 AUC on CRC-MSI",
         "confidence": "high"},
    ])
    extractor = BenchmarkExtractor(llm_parser=lambda prompt: fake_response)
    out = extractor.extract(
        papers=[_paper("p1", "We report 0.87 AUC on CRC-MSI...")],
        dataset="CRC-MSI", task_type="classification", metric="auc",
    )
    assert len(out) == 1
    assert out[0].method == "KatherNet"
    assert out[0].metric_value == 0.87
    assert out[0].paper_id == "p1"


def test_extract_empty_when_llm_returns_empty_list():
    extractor = BenchmarkExtractor(llm_parser=lambda prompt: "[]")
    out = extractor.extract(
        papers=[_paper("p1", "Irrelevant abstract about cars.")],
        dataset="CRC-MSI", task_type="classification", metric="auc",
    )
    assert out == []


def test_extract_tolerates_malformed_llm_output():
    """LLM returns non-JSON garbage — must not raise."""
    extractor = BenchmarkExtractor(llm_parser=lambda prompt: "not json at all")
    out = extractor.extract(
        papers=[_paper("p1", "x")],
        dataset="CRC-MSI", task_type="classification", metric="auc",
    )
    assert out == []


def test_extract_returns_empty_when_llm_parser_is_none():
    extractor = BenchmarkExtractor(llm_parser=None)
    out = extractor.extract(
        papers=[_paper("p1", "x")],
        dataset="CRC-MSI", task_type="classification", metric="auc",
    )
    assert out == []


def test_extract_clamps_to_max_abstracts():
    captured = {}
    def parser(prompt: str) -> str:
        captured["prompt"] = prompt
        return "[]"
    extractor = BenchmarkExtractor(llm_parser=parser, max_abstracts=2)
    papers = [_paper(f"p{i}", f"abstract {i}") for i in range(5)]
    extractor.extract(papers=papers, dataset="X",
                      task_type="classification", metric="auc")
    # Prompt must reference only 2 abstracts, not 5.
    assert captured["prompt"].count("abstract ") <= 3  # <=2 in abstracts + 1 for "Abstract(s):"
