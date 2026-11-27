from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
import json
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from backend.database.models import ChatConversation, ChatMessage, StorageTask
from gateway.chat import article_sources
from gateway.routes.chat_model_selector import _extract_citation_contexts
from backend.services.articles.identity import get_url_hash


async def test_search_after_read_preserves_prior_source_index(monkeypatch):
    from gateway.routes import chat

    monkeypatch.setattr(
        chat.Config,
        "get_global_settings",
        lambda: {"local_vllm_enabled": False, "exa_api_key": "fixture"},
    )
    monkeypatch.setattr(
        chat, "get_cached_markdown", lambda url: "--- Page 1 ---\nPreviously read BERT."
    )
    monkeypatch.setattr(chat, "get_cached_pdf_meta", lambda url: {"title": "BERT"})
    monkeypatch.setattr(
        chat, "find_cached_articles_by_title", lambda *args, **kwargs: []
    )
    monkeypatch.setattr(
        chat,
        "execute_exa_search",
        AsyncMock(
            return_value={
                "query": "new",
                "results": [
                    {
                        "title": "Attention",
                        "url": "https://arxiv.org/abs/1706.03762",
                        "snippet": "BLEU 28.4.",
                    }
                ],
            }
        ),
    )
    calls = 0

    async def generate(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            text = '[WEB_SEARCH]{"query":"new"}[/WEB_SEARCH]'
        else:
            assert "2. Attention" in str(kwargs["messages"])
            text = "New search evidence [2]."
        yield "data: " + json.dumps({"content": text}) + "\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat, "_stream_from_openai_compatible", generate)
    output = "".join(
        [
            line
            async for line in chat.stream_ai_response(
                [{"role": "user", "content": "Search a second article"}],
                api_key="fixture",
                model="fixture",
                article_sources=[
                    {
                        "index": 1,
                        "source_id": get_url_hash("https://arxiv.org/abs/1810.04805"),
                        "url": "https://arxiv.org/abs/1810.04805",
                        "title": "BERT",
                        "last_read_at": 1,
                    }
                ],
            )
        ]
    )
    assert "source_index: 1" in output and "source_index: 2" in output
    assert get_url_hash("https://arxiv.org/abs/1706.03762") in output


async def test_conversation_registry_preserves_numbers_across_rereads_and_unrelated_turns(
    monkeypatch,
):
    engine = create_async_engine("sqlite+aiosqlite://")
    metadata = MetaData()
    for model in [ChatConversation, ChatMessage, StorageTask]:
        model.__table__.to_metadata(metadata)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def db_session():
        async with sessions() as db:
            yield db

    monkeypatch.setattr("backend.database.database.safe_session", db_session)
    async with sessions() as db:
        db.add(ChatConversation(conversation_id="one", user_id="u", title="Test"))
        db.add(ChatConversation(conversation_id="two", user_id="u", title="Other"))
        await db.commit()
    a = "https://arxiv.org/abs/1706.03762"
    b = "https://arxiv.org/abs/1810.04805"
    assert (await article_sources.register_source("one", a, "Attention"))[0][
        "index"
    ] == 1
    assert (await article_sources.register_source("one", b, "BERT"))[1]["index"] == 2
    async with sessions() as db:
        db.add(
            ChatMessage(
                conversation_id="one",
                role="assistant",
                content="Unrelated answer",
                extra_metadata={"anything": True},
            )
        )
        await db.commit()
    reread = await article_sources.register_source(
        "one", "https://arxiv.org/pdf/1706.03762.pdf", "Attention again"
    )
    assert len(reread) == 2 and [s["index"] for s in reread] == [1, 2]
    assert (
        reread[0]["source_id"] == get_url_hash(a)
        and reread[0]["last_read_at"] > reread[1]["last_read_at"]
    )
    async with sessions() as db:
        db.add(
            ChatMessage(
                conversation_id="one",
                role="assistant",
                content="[CITATION_CONTEXTS]"
                + json.dumps(
                    {
                        "2-p.4": {
                            "page": 4,
                            "context": "MLM and NSP",
                            "source_id": get_url_hash(b),
                        }
                    }
                )
                + "[/CITATION_CONTEXTS]",
            )
        )
        await db.commit()
        assert (await article_sources.load_sources(db, "one"))[1]["recent_pages"] == [4]
    assert (await article_sources.register_source("two", b, "BERT"))[0]["index"] == 1
    await engine.dispose()


def test_citations_never_borrow_another_paper_or_invalid_page():
    contents = {
        1: "--- Page 1 ---\nAttention BLEU 28.4.",
        2: "--- Page 1 ---\nBERT GLUE 80.5.",
    }
    source_ids = {1: "attention", 2: "bert"}
    contexts = _extract_citation_contexts(
        "Attention [1, p.1]; BERT [2, p.1] and [2]. Missing [3, p.1] [1, p.99] [2, p.1-99].",
        "",
        contents,
        source_ids,
    )
    assert (
        contexts["1-p.1"]["source_id"] == "attention"
        and "28.4" in contexts["1-p.1"]["context"]
    )
    assert (
        contexts["2-p.1"]["source_id"] == "bert"
        and "80.5" in contexts["2-p.1"]["context"]
    )
    assert contexts["2-bare"]["source_id"] == "bert"
    assert (
        "3-p.1" not in contexts
        and "1-p.99" not in contexts
        and "2-p.1-99" not in contexts
    )


async def test_first_read_uses_server_source_number_not_search_ordinal(monkeypatch):
    from gateway.routes import chat

    monkeypatch.setattr(
        chat.Config, "get_global_settings", lambda: {"local_vllm_enabled": False}
    )
    monkeypatch.setattr(chat, "get_cached_markdown", lambda url: None)
    calls = 0

    async def generate(**kwargs):
        nonlocal calls
        calls += 1
        text = (
            '[READ_ARTICLE]{"url":"https://arxiv.org/abs/1706.03762","title":"Attention","index":7}[/READ_ARTICLE]'
            if calls == 1
            else "Result BLEU 28.4 [1, p.1]."
        )
        yield "data: " + json.dumps({"content": text}) + "\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat, "_stream_from_openai_compatible", generate)
    monkeypatch.setattr(
        chat,
        "process_pdf_url",
        AsyncMock(
            return_value={
                "success": True,
                "pdf_content": "--- Page 1 ---\nResult BLEU 28.4.",
                "page_count": 1,
                "is_academic": True,
                "content_scope": "pdf",
            }
        ),
    )
    output = "".join(
        [
            line
            async for line in chat.stream_ai_response(
                [{"role": "user", "content": "Read Attention"}],
                api_key="fixture",
                model="fixture",
            )
        ]
    )
    assert "source_index: 1" in output and "1-p.1" in output
    assert "source_index: 7" not in output
    events = [
        json.loads(line[6:])
        for line in output.splitlines()
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    evidence_position = next(
        i for i, event in enumerate(events) if event.get("type") == "citation_sources"
    )
    answer_position = next(
        i
        for i, event in enumerate(events)
        if event.get("content", "").startswith("Result BLEU")
    )
    assert evidence_position < answer_position
    source = events[evidence_position]["sources"][0]
    assert source["source_index"] == 1 and source["pages"] == {"1": "Result BLEU 28.4."}


async def test_followup_citation_sources_arrive_before_answer_tokens(monkeypatch):
    from gateway.routes import chat

    monkeypatch.setattr(
        chat.Config, "get_global_settings", lambda: {"local_vllm_enabled": False}
    )
    monkeypatch.setattr(
        chat,
        "get_cached_markdown",
        lambda url: "--- Page 8 ---\nActual ablation results.",
    )
    monkeypatch.setattr(chat, "get_cached_pdf_meta", lambda url: {"title": "GPFM"})

    async def generate(**kwargs):
        yield "data: " + json.dumps({"content": "Ablation [1, p.8]."}) + "\n\n"
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(chat, "_stream_from_openai_compatible", generate)
    events = []
    async for chunk in chat.stream_ai_response(
        [{"role": "user", "content": "Explain ablation"}],
        api_key="fixture",
        model="fixture",
        article_sources=[
            {
                "index": 1,
                "source_id": "gpfm",
                "title": "GPFM",
                "url": "https://example.org/gpfm",
                "last_read_at": 1,
            }
        ],
    ):
        if chunk.startswith("data: ") and chunk.strip() != "data: [DONE]":
            events.append(json.loads(chunk[6:]))
    assert events[0]["type"] == "citation_sources"
    assert events[0]["sources"][0]["pages"] == {"8": "Actual ablation results."}


def test_unicode_page_ranges_validate_every_page():
    from gateway.routes.chat_model_selector import _extract_citation_contexts

    assert (
        _extract_citation_contexts(
            "Result [1, p.2–4]",
            "",
            {1: "--- Page 2 ---\nFirst\n--- Page 4 ---\nLast"},
            {1: "gpfm"},
        )
        is None
    )
