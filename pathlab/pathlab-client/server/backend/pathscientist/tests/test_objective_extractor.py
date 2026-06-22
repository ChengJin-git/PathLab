# tests/test_objective_extractor.py
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pathscientist.orchestrator.objective_extractor import extract_dataset_and_task


def test_extract_dataset_from_path():
    """Path fragments like /Data/CRC-MSI should surface as dataset_hint."""
    d, t = extract_dataset_and_task(
        "看下这里的数据 /project/compath/.../Data/CRC-MSI 用patch分类",
        llm_parser=None,
    )
    assert d == "CRC-MSI"
    assert t == "classification"


def test_extract_known_dataset_by_name():
    for name in ["BRACS", "Camelyon16", "PANDA", "TCGA-LUNG"]:
        d, _ = extract_dataset_and_task(f"improve AUC on {name}", llm_parser=None)
        assert d == name


def test_extract_task_type_classification():
    _, t = extract_dataset_and_task("patch classification task", llm_parser=None)
    assert t == "classification"


def test_extract_task_type_segmentation():
    _, t = extract_dataset_and_task("segment nuclei with dice loss", llm_parser=None)
    assert t == "segmentation"


def test_extract_task_type_survival():
    _, t = extract_dataset_and_task("predict survival c-index", llm_parser=None)
    assert t == "survival"


def test_llm_override_when_regex_fails():
    """When the question has no recognizable dataset name but the LLM can
    surface one, prefer the LLM output."""
    import json
    def parser(prompt: str) -> str:
        return json.dumps({"dataset": "CRC-MSI", "task_type": "classification"})
    d, t = extract_dataset_and_task(
        "train a model on that colorectal MSI dataset I mentioned",
        llm_parser=parser,
    )
    assert d == "CRC-MSI"
    assert t == "classification"


def test_returns_empty_when_nothing_identifiable():
    d, t = extract_dataset_and_task("improve results", llm_parser=None)
    assert d == ""
    # Task type may still fall through to a default — empty is fine too.
    assert t in ("", "classification")


def test_preferred_skill_hints_task_type():
    _, t = extract_dataset_and_task(
        "train", preferred_skill="patch_classification", llm_parser=None,
    )
    assert t == "classification"
