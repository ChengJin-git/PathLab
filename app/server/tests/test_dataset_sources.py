"""Dataset acquisition accepts how agents name sources, fetches only what a study needs, and keeps
feature-only downloads usable."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from backend.autoresearch.dataset.download_progress import DownloadProgressReporter
from backend.autoresearch.dataset.providers import huggingface
from backend.autoresearch.dataset.providers.huggingface import HuggingFaceProvider
from backend.autoresearch.dataset.types import DatasetRecord
from backend.autoresearch.engine.acquisition_contract import (
    AcquisitionRecord,
    normalize_provider,
)


def record(**changes):
    data = {"dataset_id": "hub:camelyon17", "name": "CAMELYON17 features", "provider": "huggingface",
            "access": "public", "task_types": ["wsi_classification"], "asset_types": ["features"],
            "organs": ["Lymph node"], "license": "Apache-2.0",
            "source_url": "https://huggingface.co/datasets/hub/features",
            "download": {"kind": "hf_dataset", "remote_id": "hub/features"}}
    data.update(changes)
    return data


@pytest.mark.parametrize(("name", "download", "expected"), [
    ("Hugging Face", {}, "huggingface"),
    ("Owkin / Hugging Face", {}, "huggingface"),
    ("Dearcat/Hugging Face 与 CAMELYON17", {}, "huggingface"),
    ("HTTP", {"urls": ["https://huggingface.co/x/resolve/main/a.tar.gz"]}, "direct_http"),
    ("Owkin", {"remote_id": "owkin/x", "urls": ["https://huggingface.co/datasets/owkin/x"]}, "huggingface"),
    ("TCGA", {}, "gdc"),
])
def test_source_names_are_normalized(name, download, expected):
    assert normalize_provider(name, download) == expected


def test_unknown_source_lists_valid_providers_and_include_needs_huggingface():
    with pytest.raises(ValidationError, match="Use one of: huggingface"):
        AcquisitionRecord.model_validate(record(provider="Mystery source", download={"kind": "x"}))
    assert AcquisitionRecord.model_validate(record(provider="Hugging Face")).provider == "huggingface"
    with pytest.raises(ValidationError, match="download.include selects files"):
        AcquisitionRecord.model_validate(record(provider="zenodo", download={"kind": "z", "include": ["a/*"]}))


def hub(tmp_path, files, include=(), free=10 << 40):
    calls = {}

    def snapshot(**kwargs):
        calls.update(kwargs)
        for path in kwargs["allow_patterns"]:
            target = tmp_path / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"x" * dict(files)[path])
        return str(tmp_path)

    provider = HuggingFaceProvider(snapshot_fn=snapshot, list_fn=lambda repo: files,
                                   disk_free_fn=lambda path: free, poll_seconds=0.01)
    data = AcquisitionRecord.model_validate(record(download={"kind": "hf", "remote_id": "hub/features",
                                                             "include": list(include)})).model_dump()
    return provider, DatasetRecord.from_dict(data), calls


def test_huggingface_fetches_only_included_files_and_reports_progress(tmp_path):
    files = [("camelyon17/gigapath/a.pt", 10), ("camelyon17/gigapath/b.pt", 20),
             ("camelyon17/uni/a.pt", 30), ("brca/gigapath/c.pt", 40)]
    provider, data, calls = hub(tmp_path / "raw", files, include=["camelyon17/gigapath/*"])
    progress = DownloadProgressReporter(tmp_path / "progress.json", dataset_id="d", provider="huggingface",
                                        raw_root=tmp_path)
    result = provider.download(data, tmp_path / "raw", progress)
    assert result.status == "downloaded"
    assert calls["allow_patterns"] == ["camelyon17/gigapath/a.pt", "camelyon17/gigapath/b.pt"]
    assert sorted(p.name for p in result.files) == ["a.pt", "b.pt"]
    state = progress._payload
    assert (state["files_done"], state["files_total"], state["downloaded_bytes"], state["bytes_total"]) == (2, 2, 30, 30)


def test_huggingface_refuses_unbounded_or_unfitting_downloads(tmp_path, monkeypatch):
    files = [(f"{cohort}/{encoder}/{i}.pt", 1 << 20) for cohort in ("brca", "blca")
             for encoder in ("uni", "gigapath") for i in range(3)]
    monkeypatch.setattr(huggingface, "MAX_UNSELECTED_FILES", 5)
    provider, data, calls = hub(tmp_path, files)
    result = provider.download(data, tmp_path)
    assert result.status == "failed" and "set download.include" in result.reason
    assert "brca/uni/ (3 files" in result.reason and not calls
    provider, data, calls = hub(tmp_path, files, include=["luad/*"])
    assert "matched no files" in provider.download(data, tmp_path).reason and not calls
    provider, data, calls = hub(tmp_path, files, include=["brca/*"], free=50 << 30)
    assert "only 50.0 GB is free" in provider.download(data, tmp_path).reason and not calls


async def test_feature_only_download_is_mounted_instead_of_failing(tmp_path, monkeypatch):
    from backend.autoresearch.dataset.providers.base import DownloadResult
    from backend.autoresearch.engine import datasets

    workspace = tmp_path / "workspace"
    (workspace / "downloads").mkdir(parents=True)
    session = SimpleNamespace(user_id="owner", workspace_path=str(workspace),
                              recovery_metadata={"allow_downloads": True, "data_mounts": {"/old": "/research-data/x"}})
    monkeypatch.setattr(datasets.Config, "get_autoresearch_dir", lambda: tmp_path / "research")
    monkeypatch.setattr(datasets.store, "get", AsyncMock(return_value=session))
    update = AsyncMock()
    monkeypatch.setattr(datasets.store, "update", update)

    @asynccontextmanager
    async def database():
        yield SimpleNamespace(commit=AsyncMock())

    monkeypatch.setattr(datasets, "safe_session", database)
    monkeypatch.setattr(datasets, "register_manifest_with_pathlab",
                        AsyncMock(return_value={"status": "skipped", "reason": "no_wsi_files"}))

    class Provider:
        def download(self, record, root, progress):
            (root / "a.pt").write_bytes(b"features")
            return DownloadResult("downloaded", root, files=[root / "a.pt"])

    monkeypatch.setattr(datasets, "build_default_providers", lambda: {"huggingface": Provider()})
    result = await datasets.acquire("session", record(download={"kind": "hf", "remote_id": "hub/features",
                                                                "include": ["camelyon17/*"]}), "job")
    assert result["mounted_at"] == "/research-data/downloads/hub_camelyon17"
    meta = update.await_args.kwargs["meta"]
    assert meta["data_mounts"]["/old"] == "/research-data/x"
    assert meta["data_mounts"][result["root"]] == result["mounted_at"]
    assert meta["downloaded_sources"][0]["dataset_id"] == "hub:camelyon17"
