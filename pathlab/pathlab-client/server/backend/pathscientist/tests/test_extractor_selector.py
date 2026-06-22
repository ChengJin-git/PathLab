from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pathscientist.domain.extractor_selector import (
    FeatureExtractorSelector,
    detect_explicit_feature_extractor,
)


_CATALOG = {
    "pathology_foundation": [
        {"name": "UNI"},
        {"name": "Virchow2"},
        {"name": "CONCH"},
    ],
}


def _write_cached_pick(tmp_path: Path, *, name: str = "UNI") -> Path:
    cache_path = tmp_path / "extractor_choice_cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "lung|nsclc_subtype|mil_classification": {
                        "name": name.lower(),
                        "canonical": name,
                        "reason": "cached literature pick",
                        "confidence": "high",
                        "ts": 1,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return cache_path


def test_explicit_virchow2_in_user_question_overrides_cached_extractor_pick(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("PATHSCIENTIST_FEATURE_EXTRACTOR", raising=False)
    selector = FeatureExtractorSelector(
        llm_parser=lambda _prompt: json.dumps(
            {"name": "UNI", "reason": "LLM literature pick", "confidence": "high"}
        ),
        catalog=_CATALOG,
        cache_path=_write_cached_pick(tmp_path, name="UNI"),
    )

    selection = selector.select(
        task_profile={
            "organ": "lung",
            "prediction_target": "nsclc_subtype",
            "task_type": "mil_classification",
            "question": "帮我训练一个NSCLC的分类模型 用ABMIL 和virchow2 feature",
        }
    )

    assert selection.name == "virchow2"
    assert selection.canonical == "Virchow2"
    assert selection.source == "user"


def test_explicit_extractor_detection_handles_chinese_text_adjacent_to_name():
    assert (
        detect_explicit_feature_extractor(
            {"question": "帮我训练一个NSCLC的分类模型 用ABMIL 和virchow2 feature"}
        )
        == "Virchow2"
    )


def test_multiple_explicit_extractors_do_not_freeze_single_extractor(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("PATHSCIENTIST_FEATURE_EXTRACTOR", raising=False)
    selector = FeatureExtractorSelector(
        llm_parser=None,
        catalog=_CATALOG,
        cache_path=_write_cached_pick(tmp_path, name="UNI"),
    )

    selection = selector.select(
        task_profile={
            "organ": "lung",
            "prediction_target": "nsclc_subtype",
            "task_type": "mil_classification",
            "question": "比较 Virchow2 和 UNI 在NSCLC上的效果",
        }
    )

    assert selection.name == "uni"
    assert selection.source == "cache"
