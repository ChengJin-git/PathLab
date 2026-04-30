"""Citation tracker — records which papers are cited in each conversation."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from uuid import UUID

from .types import CitationRecord

logger = logging.getLogger(__name__)


class CitationTracker:
    """Track paper citations per durable conversation.

    Storage scope: CONVERSATION-SCOPED — each conversation gets its own
    ``literature_citations.json`` under ``{persistence_root}/{conv_id_hex}/``.
    The ``persistence_root`` is the same directory tree used by OpenHands for
    conversation state (``base_state.json``, event logs, etc.).

    This tracker never writes to the global corpus index managed by
    ``LiteratureStore``.  The two storage trees are fully independent.
    """

    def __init__(self, persistence_dir: Path):
        self._dir = Path(persistence_dir)

    def cite(
        self,
        paper_id: str,
        cited_in: str,
        context: str,
        conversation_id: str,
        run_id: str | None = None,
        chunk_id: str | None = None,
        page: int | None = None,
        section: str = "",
        quote_snippet: str = "",
    ) -> None:
        """Record a citation usage with optional passage provenance."""
        normalized_id = self._normalize_conversation_id(conversation_id)
        record = CitationRecord(
            paper_id=paper_id,
            cited_in=cited_in,
            context=context,
            conversation_id=normalized_id,
            run_id=run_id,
            chunk_id=chunk_id,
            page=page,
            section=section,
            quote_snippet=quote_snippet,
        )
        citations = self._load(normalized_id)
        citations.append(record.to_dict())
        self._save(normalized_id, citations)

    def get_conversation_citations(self, conversation_id: str) -> list[CitationRecord]:
        """Get all citations for a conversation."""
        data = self._load(self._normalize_conversation_id(conversation_id))
        return [CitationRecord.from_dict(d) for d in data]

    def _normalize_conversation_id(self, conversation_id: str) -> str:
        """Use the OpenHands conversation directory name when the id is a UUID."""
        try:
            return UUID(str(conversation_id)).hex
        except Exception:
            return str(conversation_id)

    def _path(self, conversation_id: str) -> Path:
        conv_dir = self._dir / conversation_id
        conv_dir.mkdir(parents=True, exist_ok=True)
        return conv_dir / "literature_citations.json"

    def _load(self, conversation_id: str) -> list[dict]:
        path = self._path(conversation_id)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []

    def _save(self, conversation_id: str, citations: list[dict]) -> None:
        path = self._path(conversation_id)
        path.write_text(
            json.dumps(citations, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
