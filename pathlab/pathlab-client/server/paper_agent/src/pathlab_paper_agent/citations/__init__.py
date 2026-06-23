"""Deterministic citation-chain utilities for M8a."""

from __future__ import annotations

from .bib_generator import generate_bibtex
from .coverage_gate import CitationCoverageReport, check_citation_coverage, extract_cite_keys
from .models import CitationCandidate, CitationReference, VerificationReport
from .orphan_cite_gate import OrphanCitationReport, check_orphan_cites
from .ref_selector import ReferenceSelection, make_unique_key, select_references
from .verifier import verify_candidates

__all__ = [
    "CitationCandidate",
    "CitationCoverageReport",
    "CitationReference",
    "OrphanCitationReport",
    "ReferenceSelection",
    "VerificationReport",
    "check_citation_coverage",
    "check_orphan_cites",
    "extract_cite_keys",
    "generate_bibtex",
    "make_unique_key",
    "select_references",
    "verify_candidates",
]
