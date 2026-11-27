import httpx
import pytest

from backend.services import citations


async def test_citations_use_registry_records_deduplicate_and_exclude_retracted(
    monkeypatch,
):
    monkeypatch.delenv("PATHLAB_SERPAPI_KEY", raising=False)

    def handle(request):
        if request.url.host == "www.ebi.ac.uk":
            return httpx.Response(
                200,
                json={
                    "resultList": {
                        "result": [
                            {
                                "source": "MED",
                                "id": "123",
                                "title": "Verified pathology study",
                                "doi": "10.1/a",
                                "pubYear": "2024",
                                "abstractText": "Measured pathology results.",
                                "authorList": {"author": [{"fullName": "Author A"}]},
                            },
                            {
                                "source": "MED",
                                "id": "456",
                                "title": "Retracted paper",
                                "isRetracted": "Y",
                                "abstractText": "Must not be used.",
                            },
                        ]
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "message": {
                    "items": [
                        {
                            "DOI": "10.1/a",
                            "title": ["Verified pathology study"],
                            "abstract": "Duplicate record",
                            "type": "journal-article",
                            "author": [{"family": "A"}],
                            "published": {"date-parts": [[2024]]},
                        },
                        {
                            "DOI": "10.1/b",
                            "title": ["Independent methods paper"],
                            "abstract": "<jats:p>Real abstract</jats:p>",
                            "type": "proceedings-article",
                            "author": [{"given": "B", "family": "Author"}],
                            "published": {"date-parts": [[2023]]},
                        },
                    ]
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(citations.httpx, "AsyncClient", lambda **kwargs: client)
    records = await citations.search_verified("pathology")
    assert len(records) == 2 and records[0]["pmid"] == "123"
    assert records[1]["abstract"] == "Real abstract"
    assert all(
        r["source_url"].startswith("https://") and r["verified_at"] for r in records
    )
    assert "Retracted paper" not in str(records)


async def test_unavailable_sources_never_fall_back_to_invented_references(monkeypatch):
    monkeypatch.delenv("PATHLAB_SERPAPI_KEY", raising=False)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503))
    )
    monkeypatch.setattr(citations.httpx, "AsyncClient", lambda **kwargs: client)
    with pytest.raises(citations.CitationRetrievalError):
        await citations.search_verified("pathology")


def test_citation_parser_validates_groups_and_ranges():
    assert citations.citation_numbers("Evidence [1, 3–5] and [2].") == {1, 2, 3, 4, 5}
    with pytest.raises(ValueError):
        citations.citation_numbers("[1-999]")
    body, refs = citations.finalize_numbers(
        "First [5], then [2, 5].",
        [{"number": 2, "title": "B"}, {"number": 5, "title": "A"}],
    )
    assert body == "First [1], then [2, 1]."
    assert [ref["title"] for ref in refs] == ["A", "B"]


def test_confusion_matrix_is_not_misclassified_as_bibliographic_citations():
    text = "Confusion matrix [[7, 5], [3, 13]]; previous studies [2, 5]."
    assert citations.citation_numbers(text) == {2, 5}
    body, refs = citations.finalize_numbers(
        text, [{"number": 2, "title": "A"}, {"number": 5, "title": "B"}]
    )
    assert "[[7, 5], [3, 13]]" in body
    assert body.endswith("previous studies [1, 2].")
    assert len(refs) == 2
    assert citations.citation_numbers("Prior studies, [99], remain unverified.") == {99}
    assert citations.citation_numbers(
        "Matrix [[1, 2], [3, 4], [5, 6]] and references [2, 7]."
    ) == {2, 7}


async def test_provider_timeout_retries_only_once_and_rechecks_budget(monkeypatch):
    from unittest.mock import AsyncMock

    from backend.services import manuscript_writer

    call = AsyncMock(side_effect=[httpx.ReadTimeout("temporary"), "Complete article"])
    check = AsyncMock()
    monkeypatch.setattr(manuscript_writer, "complete", call)
    monkeypatch.setattr(manuscript_writer.asyncio, "sleep", AsyncMock())
    assert (
        await manuscript_writer.complete_with_retry(
            None, "Review", {}, tokens=14000, check=check
        )
        == "Complete article"
    )
    assert call.await_count == 2 and check.await_count == 2
    call.reset_mock(side_effect=True)
    call.side_effect = httpx.ReadTimeout("persistent")
    with pytest.raises(manuscript_writer.WritingError, match="provider_timeout"):
        await manuscript_writer.complete_with_retry(None, "Review", {})
    assert call.await_count == 2
    call.reset_mock(side_effect=True)
    call.side_effect = httpx.ReadTimeout("temporary")
    check.side_effect = [None, manuscript_writer.WritingPaused("budget")]
    with pytest.raises(manuscript_writer.WritingPaused):
        await manuscript_writer.complete_with_retry(None, "Review", {}, check=check)
    assert call.await_count == 1


async def test_authentication_provider_failure_is_not_retried(monkeypatch):
    from unittest.mock import AsyncMock

    from backend.services import manuscript_writer

    response = httpx.Response(
        401, request=httpx.Request("POST", "https://provider.test")
    )
    call = AsyncMock(
        side_effect=httpx.HTTPStatusError(
            "unauthorized", request=response.request, response=response
        )
    )
    monkeypatch.setattr(manuscript_writer, "complete", call)
    with pytest.raises(httpx.HTTPStatusError):
        await manuscript_writer.complete_with_retry(None, "Review", {})
    assert call.await_count == 1


async def test_writer_repairs_unverified_citation_once_before_accepting(monkeypatch):
    from unittest.mock import AsyncMock

    from backend.services import manuscript_writer

    complete = AsyncMock(
        side_effect=["Measured results [99]. " * 10, "Measured results [1]. " * 10]
    )
    monkeypatch.setattr(manuscript_writer, "complete", complete)
    output = await manuscript_writer.write_validated(
        None, "Write results", {}, [{"number": 1}], minimum=100
    )
    assert "[99]" not in output and "[1]" in output
    assert complete.await_count == 2
    assert "previous_response" in complete.call_args.args[2]
