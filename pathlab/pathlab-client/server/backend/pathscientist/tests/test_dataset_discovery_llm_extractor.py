"""Tests for the optional LLM dataset extractor.

Phase D T10 of docs/plans/2026-04-30-pathscientist-literature-grounded-dataset-discovery-plan.md.

Pattern follows ``literature/benchmark_extractor.py``: caller injects
a ``llm_parser: Callable[[str], str]`` (typically built by
``runtime/metric_parser.build_llm_text_caller``); malformed output is
swallowed and returns ``[]``.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _profile():
    from pathscientist.dataset.types import TaskProfile
    return TaskProfile(
        task_type="patch_classification",
        asset_level="patch",
        input_modality="patch_images",
        label_granularity="patch",
        organ="prostate",
        prediction_target="gleason_grading",
    )


# ---------------------------------------------------------------- T10 standalone


def test_llm_extractor_parses_json_array():
    from pathscientist.dataset.discovery_llm_extractor import (
        DatasetDiscoveryLLMExtractor,
    )

    def fake_llm(prompt):
        return """
        [
          {
            "name": "PANDA",
            "aliases": ["TCGA-PANDA"],
            "provider_hints": [{"provider": "kaggle", "url": "https://kaggle.com/c/panda"}],
            "access": "manual",
            "confidence": "high",
            "evidence_quote": "PANDA is a Gleason grading challenge dataset."
          }
        ]
        """

    extractor = DatasetDiscoveryLLMExtractor(llm_parser=fake_llm)
    records = extractor.extract(
        texts=[{"paper_id": "openalex:W1", "text": "PANDA is a Gleason grading challenge."}],
        profile=_profile(),
    )
    assert len(records) == 1
    rec = records[0]
    assert rec.name == "PANDA"
    assert rec.confidence == "high"
    assert "TCGA-PANDA" in rec.aliases
    assert rec.provider_hints[0].provider == "kaggle"


def test_llm_extractor_returns_empty_when_parser_is_none():
    from pathscientist.dataset.discovery_llm_extractor import (
        DatasetDiscoveryLLMExtractor,
    )

    extractor = DatasetDiscoveryLLMExtractor(llm_parser=None)
    assert extractor.extract(texts=[{"text": "x"}], profile=_profile()) == []


def test_llm_extractor_returns_empty_on_malformed_json():
    from pathscientist.dataset.discovery_llm_extractor import (
        DatasetDiscoveryLLMExtractor,
    )

    extractor = DatasetDiscoveryLLMExtractor(llm_parser=lambda p: "not json")
    assert extractor.extract(texts=[{"text": "x"}], profile=_profile()) == []


def test_llm_extractor_returns_empty_when_llm_raises():
    from pathscientist.dataset.discovery_llm_extractor import (
        DatasetDiscoveryLLMExtractor,
    )

    def boom(prompt):
        raise RuntimeError("llm down")

    extractor = DatasetDiscoveryLLMExtractor(llm_parser=boom)
    assert extractor.extract(texts=[{"text": "x"}], profile=_profile()) == []


def test_llm_extractor_drops_records_with_blank_name():
    from pathscientist.dataset.discovery_llm_extractor import (
        DatasetDiscoveryLLMExtractor,
    )

    def fake(prompt):
        return '[{"name": "", "confidence": "high"}, {"name": "  ", "confidence": "high"}]'

    extractor = DatasetDiscoveryLLMExtractor(llm_parser=fake)
    assert extractor.extract(texts=[{"text": "x"}], profile=_profile()) == []


def test_llm_extractor_no_texts_skips_call():
    """If no input texts, don't waste an LLM call."""
    from pathscientist.dataset.discovery_llm_extractor import (
        DatasetDiscoveryLLMExtractor,
    )

    called = []

    def parser(prompt):
        called.append(prompt)
        return "[]"

    extractor = DatasetDiscoveryLLMExtractor(llm_parser=parser)
    out = extractor.extract(texts=[], profile=_profile())
    assert out == []
    assert called == []   # parser not invoked


def test_llm_extractor_caps_text_length_to_keep_prompt_bounded():
    """Per plan T10 step 3: 'Clip text count/length to bound prompt size.'"""
    from pathscientist.dataset.discovery_llm_extractor import (
        DatasetDiscoveryLLMExtractor,
    )

    long_text = "X" * 10000
    captured: list[str] = []

    def parser(prompt):
        captured.append(prompt)
        return "[]"

    extractor = DatasetDiscoveryLLMExtractor(llm_parser=parser)
    extractor.extract(
        texts=[{"text": long_text}, {"text": long_text}],
        profile=_profile(),
    )
    assert captured
    # The whole prompt must be smaller than 2x the original strings combined.
    assert len(captured[0]) < 2 * len(long_text)


# ---------------------------------------------------------------- T10 integration


def test_extractor_merges_llm_hints_when_extractor_provided():
    """Plan T10 step 4: extract_dataset_candidates accepts an llm_extractor and merges results."""
    from pathscientist.dataset.discovery_extractor import extract_dataset_candidates
    from pathscientist.dataset.discovery_llm_extractor import (
        DatasetDiscoveryLLMExtractor,
    )

    grounding = {
        "baselines": [
            {"dataset": "CRC-MSI", "paper_id": "openalex:W1", "context": "AUC"},
        ],
        "passages": [
            {"paper_id": "openalex:W2", "text": "PANDA is for Gleason grading."},
        ],
    }
    profile = _profile()

    def fake_llm(prompt):
        return '[{"name": "PANDA-extra", "confidence": "high", "evidence_quote": "x"}]'

    llm_extractor = DatasetDiscoveryLLMExtractor(llm_parser=fake_llm)
    records = extract_dataset_candidates(grounding, profile, llm_extractor=llm_extractor)
    names = {r.name for r in records}
    # Heuristic baseline + LLM extraction both present.
    assert "CRC-MSI" in names
    assert "PANDA-extra" in names


def test_extractor_heuristic_wins_when_name_collides_with_llm_lower_confidence():
    """Plan T10 step 4: 'Heuristic records win on name conflict unless LLM
    confidence is higher and has provider hints.'"""
    from pathscientist.dataset.discovery_extractor import extract_dataset_candidates
    from pathscientist.dataset.discovery_llm_extractor import (
        DatasetDiscoveryLLMExtractor,
    )

    grounding = {
        "baselines": [
            {"dataset": "CRC-MSI", "paper_id": "openalex:W1", "context": "AUC"},
        ],
    }
    # LLM returns CRC-MSI but at LOW confidence with no provider hints.
    def fake(prompt):
        return '[{"name": "CRC-MSI", "confidence": "low", "evidence_quote": "x"}]'

    extractor = DatasetDiscoveryLLMExtractor(llm_parser=fake)
    records = extract_dataset_candidates(
        grounding, _profile(), llm_extractor=extractor,
    )
    crc = [r for r in records if r.name == "CRC-MSI"]
    assert len(crc) == 1
    # Heuristic baseline = "medium". LLM contribution shouldn't downgrade.
    assert crc[0].confidence == "medium"
