import sys
import types

import pytest

from task_worker.jobs.analysis import run_analysis_pipeline


async def _fake_analysis_runner(**_kwargs):
    return {"ok": True}


def test_run_analysis_pipeline_allows_registered_runner(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "gateway.routes.results",
        types.SimpleNamespace(run_analysis_pipeline=_fake_analysis_runner),
    )

    fn = run_analysis_pipeline("gateway.routes.results", "run_analysis_pipeline")

    assert fn is _fake_analysis_runner


def test_run_analysis_pipeline_rejects_unregistered_runner():
    with pytest.raises(ValueError, match="not in allowlist"):
        run_analysis_pipeline("os", "system")
