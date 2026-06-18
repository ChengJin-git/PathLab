import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_histopathology_rag_sources_include_core_benchmarks_and_methods():
    from gateway.knowledge.chat import BUNDLED_TRAINING_PDF_SOURCES
    from gateway.routes.chat_training_recommendation import (
        get_training_recommendation_source_urls,
    )

    urls = get_training_recommendation_source_urls("histopathology")
    source_ids = {
        source_id
        for source_id, source in BUNDLED_TRAINING_PDF_SOURCES.items()
        if source["url"] in urls
    }

    assert {
        "pathbench",
        "pfm_feature_extractor_benchmark",
        "clinical_public_pfm_benchmark",
        "uni",
        "conch",
        "clam",
        "transmil",
        "abmil",
    }.issubset(source_ids)


def test_vector_search_filters_source_before_limit(monkeypatch):
    import numpy as np

    from gateway.routes import chat_pdf_vectorstore as store

    calls = []

    class FakeSearch:
        def where(self, expression):
            calls.append(("where", expression))
            return self

        def limit(self, value):
            calls.append(("limit", value))
            return self

        def to_list(self):
            return []

    class FakeTable:
        def search(self, _vector):
            calls.append(("search", None))
            return FakeSearch()

    class FakeDb:
        def table_names(self):
            return [store.TABLE_NAME]

        def open_table(self, _name):
            return FakeTable()

    monkeypatch.setattr(store, "_get_db", lambda *_args, **_kwargs: FakeDb())
    monkeypatch.setattr(store, "_embed_texts", lambda _texts: np.array([[0.1] * store.EMBEDDING_DIM]))

    store.search_pdf_chunks("UNI benchmark", url_hashes=["source-a"], top_k=3)

    assert calls[:3] == [
        ("search", None),
        ("where", "url_hash = 'source-a'"),
        ("limit", 3),
    ]


@pytest.mark.asyncio
async def test_bundled_source_ready_falls_back_when_marker_parse_fails(monkeypatch, tmp_path):
    from gateway.routes import chat_training_recommendation as rec

    pdf_path = tmp_path / "fallback.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake enough for mocked fallback")
    url = "https://pathlab.local/training-recommendation/Fallback.pdf"
    source = {
        "id": "fallback",
        "title": "Fallback PDF",
        "url": url,
        "path": str(pdf_path),
    }
    monkeypatch.setattr(rec, "get_bundled_training_pdf_source_by_url", lambda value: source if value == url else None)
    monkeypatch.setattr(rec, "_get_bundled_markdown", lambda _url: None)
    monkeypatch.setattr(rec, "_get_bundled_structured_content", lambda _url: None)
    monkeypatch.setattr(rec, "is_pdf_indexed", lambda *_args, **_kwargs: False)

    async def fake_marker_parse(*_args, **_kwargs):
        return None

    fallback_result = SimpleNamespace(
        markdown="--- Page 1 ---\nUNI and CONCH are pathology foundation models.",
        structured_content={"blocks": [{"type": "paragraph", "text": "UNI and CONCH benchmark evidence", "page": 1}]},
        page_count=1,
    )
    saved = []
    indexed = []

    monkeypatch.setattr(rec, "_parse_pdf_with_marker_best_effort", fake_marker_parse)
    monkeypatch.setattr(rec, "_parse_bundled_pdf_with_text_fallback", lambda _path: fallback_result)
    monkeypatch.setattr(rec, "_save_bundled_marker_cache", lambda *args: saved.append(args))

    async def fake_ensure_vector_index(*args, **kwargs):
        indexed.append((args, kwargs))

    monkeypatch.setattr(rec, "_ensure_vector_index", fake_ensure_vector_index)

    assert await rec._ensure_local_source_ready(url, force_upgrade=True) is True
    assert saved
    assert indexed
    assert indexed[0][0][1].startswith("--- Page 1 ---")


@pytest.mark.asyncio
async def test_prewarm_tolerates_optional_sources_without_local_pdf(monkeypatch):
    from gateway.routes import chat_training_recommendation as rec

    sources = {
        "ready": {
            "id": "ready",
            "title": "Ready",
            "url": "local://ready.pdf",
            "path": "/tmp/ready.pdf",
        },
        "missing": {
            "id": "missing",
            "title": "Missing",
            "url": "local://missing.pdf",
            "path": "/tmp/missing.pdf",
        },
    }
    monkeypatch.setattr(rec, "BUNDLED_TRAINING_PDF_SOURCES", sources)

    async def fake_ready(url, **_kwargs):
        return url == "local://ready.pdf"

    monkeypatch.setattr(rec, "_ensure_local_source_ready", fake_ready)

    results = await rec.prewarm_training_recommendation_sources(prewarm_embedding=False)

    assert results == {"ready": True, "missing": False}
