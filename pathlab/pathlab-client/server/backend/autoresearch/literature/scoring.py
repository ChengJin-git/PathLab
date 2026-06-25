"""BM25-lite relevance scoring for the local paper index.

The legacy `LiteratureStore.search` scored a paper by counting how many
query terms appeared anywhere in its concatenated text. That ignored
document length, term frequency, and field importance — a passing
mention in a 5000-word review beat an on-topic title. This module is the
deterministic, offline replacement: a tiny BM25 variant with field
weights for title/abstract/methods/datasets/organ/task_type.

Design notes:
- No external dependencies; pure Python.
- IDF is computed once per corpus via `CorpusStats.build` and cached on
  the store so per-search overhead is just tokenization + lookup.
- AliasResolver-produced synonyms enter as `expanded_terms` and score at
  half weight — they help recall without dominating exact matches.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

from .types import PaperRecord


_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Field weights chosen so a title hit beats a mid-abstract hit but
# datasets/organ/task carry signal too. Survived a quick sanity pass on
# the seed corpus where a "MSI" title was previously losing to "MSI"
# buried in abstract noise.
_FIELD_WEIGHTS: dict[str, float] = {
    "title": 3.0,
    "datasets": 2.0,
    "methods": 1.5,
    "tags": 1.5,
    "organ": 1.2,
    "task_type": 1.2,
    "abstract": 1.0,
}

_K1 = 1.4
_B = 0.6


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


@dataclass
class CorpusStats:
    """Document-frequency / length stats over a paper corpus."""

    n_docs: int = 0
    avg_doc_len: float = 0.0
    df: dict[str, int] = field(default_factory=dict)

    @classmethod
    def build(cls, papers: Iterable[PaperRecord]) -> "CorpusStats":
        n_docs = 0
        total_len = 0
        df: dict[str, int] = {}
        for paper in papers:
            n_docs += 1
            seen: set[str] = set()
            doc_len = 0
            for field_name in _FIELD_WEIGHTS:
                for token in _tokenize(_field_text(paper, field_name)):
                    doc_len += 1
                    if token not in seen:
                        df[token] = df.get(token, 0) + 1
                        seen.add(token)
            total_len += doc_len
        avg_doc_len = (total_len / n_docs) if n_docs else 0.0
        return cls(n_docs=n_docs, avg_doc_len=avg_doc_len, df=df)

    def idf(self, term: str) -> float:
        if self.n_docs == 0:
            return 0.0
        n = self.df.get(term, 0)
        # BM25 idf with +1 smoothing to keep unknown terms non-negative.
        return math.log((self.n_docs - n + 0.5) / (n + 0.5) + 1.0)


class PaperScorer:
    """Compute BM25-lite scores against pre-built corpus stats."""

    def __init__(self, stats: CorpusStats):
        self._stats = stats

    def score(
        self,
        paper: PaperRecord,
        query_terms: Iterable[str],
        expanded_terms: Iterable[str] = (),
    ) -> float:
        query = [t for t in (q.lower() for q in query_terms) if t]
        synonyms = [t for t in (q.lower() for q in expanded_terms) if t]
        if not query and not synonyms:
            return 0.0

        # Pre-tokenize each field once.
        field_tokens: dict[str, list[str]] = {
            name: _tokenize(_field_text(paper, name)) for name in _FIELD_WEIGHTS
        }
        doc_len = sum(len(tokens) for tokens in field_tokens.values()) or 1
        field_counters: dict[str, Counter] = {
            name: Counter(tokens) for name, tokens in field_tokens.items()
        }

        avg = self._stats.avg_doc_len or float(doc_len)
        norm = 1.0 - _B + _B * (doc_len / avg)

        score = 0.0
        for term in query:
            score += self._term_score(term, field_counters, norm, weight=1.0)
        for term in synonyms:
            if term in query:
                continue
            score += self._term_score(term, field_counters, norm, weight=0.5)

        # Mild recency bonus — keep the historical 0.1 / year slope so
        # behavior overlaps with the legacy scorer on uninteresting ties.
        if paper.year and paper.year > 2020:
            score += 0.1 * (paper.year - 2020)
        return score

    def _term_score(
        self,
        term: str,
        field_counters: dict[str, Counter],
        norm: float,
        *,
        weight: float,
    ) -> float:
        idf = self._stats.idf(term)
        if idf <= 0.0:
            return 0.0
        weighted_tf = 0.0
        for field_name, fw in _FIELD_WEIGHTS.items():
            tf = field_counters[field_name].get(term, 0)
            if tf:
                weighted_tf += fw * tf
        if weighted_tf == 0.0:
            return 0.0
        # Standard BM25 term-frequency saturation.
        tf_component = (weighted_tf * (_K1 + 1.0)) / (weighted_tf + _K1 * norm)
        return weight * idf * tf_component


def _field_text(paper: PaperRecord, field_name: str) -> str:
    if field_name == "title":
        return paper.title
    if field_name == "abstract":
        return paper.abstract
    if field_name == "methods":
        return " ".join(paper.methods)
    if field_name == "datasets":
        return " ".join(paper.datasets)
    if field_name == "tags":
        return " ".join(paper.tags)
    if field_name == "organ":
        return paper.organ
    if field_name == "task_type":
        return paper.task_type
    return ""
