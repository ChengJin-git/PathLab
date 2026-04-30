"""ProviderCapability — declares what each literature provider supplies.

Plan-2026-04-29 literature-acquisition Phase 5 / Task 1.

Pre-ingest, we need to decide what we can do with a paper from a given
source:

- ``has_metadata``     — title, authors, year, venue, source URL
- ``has_abstract``     — paper abstract text (RAG-ingestable)
- ``has_full_text``    — paper body (rare; OpenAccess only, via separate fetch)
- ``has_pdf``          — direct PDF link (open access)
- ``has_citation_graph`` — cite/cited_by edges
- ``has_benchmarks``   — structured (method, dataset, metric, value) rows

Phase 5 ingestion paths use this to decide whether a hit can be
auto-registered in PaperRegistry (metadata-only is enough), inserted
into ChunkStore (needs abstract minimum), or dense-indexed (needs
ingest of full text).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ProviderCapability:
    """What one provider supplies for a paper."""

    provider: str = ""
    has_metadata: bool = True
    has_abstract: bool = False
    has_full_text: bool = False
    has_pdf: bool = False
    has_citation_graph: bool = False
    has_benchmarks: bool = False

    def supports(self, capability: str) -> bool:
        """Lookup by capability name (``"metadata"`` / ``"abstract"`` / ...)."""
        return bool(getattr(self, f"has_{capability}", False))


# Presets for known providers. Phase 5 wires these into the auto-ingest
# decision: e.g. an OpenAlex hit is metadata + abstract + citation_graph,
# so ``service.ingest`` can register it AND chunk the abstract; a PwC
# hit is metadata + benchmarks only, so it lands in PaperRegistry but
# NOT in ChunkStore.

OPENALEX_CAPABILITY = ProviderCapability(
    provider="openalex",
    has_metadata=True,
    has_abstract=True,
    has_citation_graph=True,
)

PWC_CAPABILITY = ProviderCapability(
    provider="pwc",
    has_metadata=True,
    has_benchmarks=True,
)

LOCAL_SEED_CAPABILITY = ProviderCapability(
    provider="local_seed",
    has_metadata=True,
    has_abstract=True,
    has_benchmarks=True,
)

ARXIV_CAPABILITY = ProviderCapability(
    provider="arxiv",
    has_metadata=True,
    has_abstract=True,
    has_pdf=True,
    has_full_text=True,
)

SEMANTIC_SCHOLAR_CAPABILITY = ProviderCapability(
    provider="s2",
    has_metadata=True,
    has_abstract=True,
    has_citation_graph=True,
)


PROVIDER_PRESETS: dict[str, ProviderCapability] = {
    "openalex": OPENALEX_CAPABILITY,
    "pwc": PWC_CAPABILITY,
    "local_seed": LOCAL_SEED_CAPABILITY,
    "arxiv": ARXIV_CAPABILITY,
    "s2": SEMANTIC_SCHOLAR_CAPABILITY,
}


def get_capability(provider: str) -> ProviderCapability:
    """Return the preset for ``provider`` or a metadata-only default."""
    return PROVIDER_PRESETS.get(
        provider.lower(),
        ProviderCapability(provider=provider, has_metadata=True),
    )
