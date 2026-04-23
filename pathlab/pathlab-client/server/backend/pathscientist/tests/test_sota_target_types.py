from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pathscientist.literature.types import SotaTarget, ExtractedBenchmark


def test_sota_target_roundtrip():
    t = SotaTarget(
        dataset="CRC-MSI", task_type="classification",
        metric_name="auc", metric_value=0.87,
        paper_id="openalex:W1234", paper_title="MSI prediction",
        paper_url="https://example.org/p/W1234",
        source="openalex+llm", confidence="medium",
        retrieved_at="2026-04-23T10:00:00Z",
        raw_evidence="achieves 0.87 AUC on CRC-MSI",
    )
    d = t.to_dict()
    assert d["metric_value"] == 0.87
    restored = SotaTarget.from_dict(d)
    assert restored == t


def test_sota_target_from_dict_coerces_metric_value():
    restored = SotaTarget.from_dict({
        "dataset": "X", "task_type": "classification", "metric_name": "auc",
        "metric_value": "0.91",   # string on purpose
        "paper_id": "p1", "paper_title": "t", "paper_url": "u",
        "source": "pwc", "confidence": "high",
        "retrieved_at": "2026-04-23T10:00:00Z", "raw_evidence": "",
    })
    assert restored.metric_value == 0.91
    assert isinstance(restored.metric_value, float)


def test_extracted_benchmark_fields_required():
    b = ExtractedBenchmark(
        paper_id="p1", method="foo", dataset="CRC-MSI",
        metric_name="auc", metric_value=0.85,
        evidence="...", confidence="high",
    )
    assert b.method == "foo"
    assert b.metric_value == 0.85
