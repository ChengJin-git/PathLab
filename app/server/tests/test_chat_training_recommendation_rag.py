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
    monkeypatch.setattr(
        store, "_embed_texts", lambda _texts: np.array([[0.1] * store.EMBEDDING_DIM])
    )

    store.search_pdf_chunks("UNI benchmark", url_hashes=["source-a"], top_k=3)

    assert calls[:3] == [
        ("search", None),
        ("where", "url_hash = 'source-a'"),
        ("limit", 3),
    ]


@pytest.mark.asyncio
async def test_bundled_source_uses_single_cpu_parser(monkeypatch, tmp_path):
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
    monkeypatch.setattr(
        rec,
        "get_bundled_training_pdf_source_by_url",
        lambda value: source if value == url else None,
    )
    monkeypatch.setattr(rec, "_get_bundled_markdown", lambda _url: None)
    monkeypatch.setattr(rec, "_get_bundled_structured_content", lambda _url: None)
    monkeypatch.setattr(rec, "is_pdf_indexed", lambda *_args, **_kwargs: False)

    async def fake_parse(*_args, **_kwargs):
        assert _kwargs == {"profile": "chat"}
        return fallback_result

    fallback_result = SimpleNamespace(
        markdown="--- Page 1 ---\nUNI and CONCH are pathology foundation models.",
        structured_content={
            "blocks": [
                {
                    "type": "paragraph",
                    "text": "UNI and CONCH benchmark evidence",
                    "page": 1,
                }
            ]
        },
        page_count=1,
    )
    saved = []
    indexed = []

    monkeypatch.setattr(rec, "parse_pdf", fake_parse)
    monkeypatch.setattr(rec, "_save_bundled_cache", lambda *args: saved.append(args))

    async def fake_ensure_vector_index(*args, **kwargs):
        indexed.append((args, kwargs))

    monkeypatch.setattr(rec, "_ensure_vector_index", fake_ensure_vector_index)

    assert await rec._ensure_local_source_ready(url, force_upgrade=True) is True
    assert saved
    assert indexed
    assert indexed[0][0][1].startswith("--- Page 1 ---")


async def test_bundled_ready_source_reuses_cache_without_reparsing(
    monkeypatch, tmp_path
):
    from unittest.mock import AsyncMock
    from gateway.routes import chat_training_recommendation as rec

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF-1.4 fixture")
    monkeypatch.setattr(
        rec, "get_bundled_training_pdf_source_by_url", lambda _: {"path": str(source)}
    )
    monkeypatch.setattr(rec, "_get_bundled_markdown", lambda _: "Complete paper")
    monkeypatch.setattr(
        rec,
        "_get_bundled_structured_content",
        lambda _: {"blocks": [{"page": 1, "text": "Complete paper"}]},
    )
    monkeypatch.setattr(rec, "is_pdf_indexed", lambda *a, **k: True)
    parse = AsyncMock(
        side_effect=AssertionError("Ready source must not be parsed again")
    )
    monkeypatch.setattr(rec, "parse_pdf", parse)
    assert await rec._ensure_local_source_ready("https://example.org/ready-paper.pdf")
    parse.assert_not_called()


async def test_empty_vector_index_is_not_marked_ready(monkeypatch):
    from gateway.routes import chat_training_recommendation as rec

    url = "https://example.org/empty-index.pdf"
    identity = rec.get_url_hash(url)
    monkeypatch.setattr(rec, "_LOCAL_INDEX_READY", set())
    monkeypatch.setattr(rec, "index_pdf_to_vectorstore", lambda *args, **kwargs: 0)
    with pytest.raises(RuntimeError, match="index is empty"):
        await rec._ensure_vector_index(url, "text", "Paper", {}, force=True)
    assert identity not in rec._LOCAL_INDEX_READY


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


@pytest.mark.asyncio
async def test_chat_evidence_never_builds_indexes_and_searches_all_sources_once(
    monkeypatch,
):
    import threading
    from gateway.routes import chat_training_recommendation as rec

    def forbidden(*args, **kwargs):
        raise AssertionError("Chat must not parse or index PDFs")

    monkeypatch.setattr(
        rec, "ensure_training_recommendation_sources_for_query", forbidden
    )
    monkeypatch.setattr(
        rec,
        "get_training_recommendation_source_urls",
        lambda profile: ["https://example.test/a", "https://example.test/b"],
    )
    calls = []
    main_thread = threading.get_ident()

    def search(query, **kwargs):
        calls.append(kwargs)
        assert threading.get_ident() != main_thread
        return [{"chunk_text": "A relevant pathology benchmark finding."}]

    monkeypatch.setattr(rec, "search_pdf_chunks", search)
    result = await rec.build_training_recommendation_evidence_context(
        "recommend a pathology model", "en"
    )
    assert len(calls) == 1 and len(calls[0]["url_hashes"]) == 2
    assert "benchmark finding" in result
    assert calls[0]["ready_only"] is True


def test_foreground_training_search_does_not_lazy_load_the_embedder(monkeypatch):
    from gateway.routes import chat_pdf_vectorstore as store

    monkeypatch.setattr(store, "_embedding_model", None)

    def forbidden(*args, **kwargs):
        raise AssertionError("Foreground search must not initialize the model/index")

    monkeypatch.setattr(store, "_get_db", forbidden)
    monkeypatch.setattr(store, "_embed_texts", forbidden)
    assert store.search_pdf_chunks("baseline", ready_only=True) == []


@pytest.mark.parametrize("existing_threads,expected_threads", [(96, 4), (2, 2)])
def test_bundled_embedder_bounds_cpu_parallelism(
    monkeypatch, existing_threads, expected_threads
):
    from unittest.mock import Mock
    import torch
    from gateway.routes import chat_pdf_vectorstore as store

    model = SimpleNamespace(device="cpu")
    load = Mock(return_value=model)
    threads = Mock()
    monkeypatch.setattr(store, "_embedding_model", None)
    monkeypatch.setattr(store, "ensure_transformers_runtime_ready", lambda *_: None)
    monkeypatch.setattr(store, "_resolve_embedding_device", lambda: "cpu")
    monkeypatch.setattr(torch, "get_num_threads", lambda: existing_threads)
    monkeypatch.setattr(torch, "set_num_threads", threads)
    monkeypatch.setitem(
        sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=load)
    )

    assert store._get_embedding_model() is model
    assert store._get_embedding_model() is model
    threads.assert_called_once_with(expected_threads)
    load.assert_called_once_with(
        store.EMBEDDING_MODEL_NAME,
        revision=store.EMBEDDING_MODEL_REVISION,
        local_files_only=True,
        device="cpu",
    )
