import re
from typing import Any

from .chat_pdf_shared import split_md_into_pages, tokenize_for_search

TOP_K_MODELS_IN_CHAT_CONTEXT = 5


def extract_text_from_content(content: object) -> str:
    """Extract text content from message content (handles both string and multimodal format)"""
    if isinstance(content, str):
        return content
    elif isinstance(content, list):
        # Multimodal format: [{"type": "text", "text": "..."}, {"type": "image_url", ...}]
        text_parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text_parts.append(part.get("text", ""))
        return " ".join(text_parts)
    return ""


def _infer_model_request_filters(user_text: str) -> dict[str, Any]:
    normalized_text = (user_text or "").strip().lower()
    if not normalized_text:
        return {}

    generic_model_listing_patterns = [
        "我有什么模型",
        "我有哪些模型",
        "有多少模型",
        "多少模型",
        "列出模型",
        "看下模型",
        "看看模型",
        "show models",
        "list models",
        "how many models",
        "latest model",
        "newest model",
        "最新模型",
        "最新训练的模型",
    ]
    if any(p in normalized_text for p in generic_model_listing_patterns):
        return {}

    task_type_keywords: dict[str, list[str]] = {
        "classification": ["classification", "classify", "classifier", "分类"],
        "survival": ["survival", "prognosis", "prognostic", "生存", "预后"],
        "segmentation": [
            "segmentation",
            "segment",
            "mask",
            "分割",
            "掩膜",
            "勾边",
            "圈区域",
        ],
    }
    data_type_keywords: dict[str, list[str]] = {
        "wsi": [
            "wsi",
            "whole slide",
            "whole-slide",
            "全切片",
            "全视野",
            "病理大图",
            "大图",
        ],
        "patch": ["patch", "tile", "patches", "小图", "切块", "瓦片"],
    }

    _SURVIVAL_SIGNAL_WORDS = {
        "event",
        "censored",
        "risk",
        "high risk",
        "low risk",
        "intermediate",
        "event_status",
        "risk_group",
        "生存期",
        "事件",
        "删失",
    }

    _STOP_WORDS = {
        "the",
        "a",
        "an",
        "in",
        "on",
        "of",
        "with",
        "for",
        "and",
        "or",
        "my",
        "me",
        "i",
        "is",
        "are",
        "was",
        "were",
        "have",
        "has",
        "that",
        "this",
        "to",
        "from",
        "by",
        "be",
        "can",
        "at",
        "model",
        "models",
        "data",
        "dataset",
        "image",
        "images",
        "图像",
        "模型",
        "数据集",
        "数据",
        "heatmap",
        "热力图",
        "热图",
        "attention",
        "注意力",
        "给",
        "我",
        "看",
        "show",
        "display",
        "view",
        "find",
        "get",
        "list",
        "all",
        "some",
    }

    def _detect_single_match(keyword_map: dict[str, list[str]]) -> str | None:
        matches = [
            value
            for value, keywords in keyword_map.items()
            if any(keyword in normalized_text for keyword in keywords)
        ]
        return matches[0] if len(matches) == 1 else None

    filters: dict[str, Any] = {}
    task_type = _detect_single_match(task_type_keywords)
    data_type = _detect_single_match(data_type_keywords)
    if task_type:
        filters["task_type"] = task_type
    if data_type:
        filters["data_type"] = data_type

    all_indicator_tokens: set[str] = set()
    for tokens in task_type_keywords.values():
        all_indicator_tokens.update(tokens)
    for tokens in data_type_keywords.values():
        all_indicator_tokens.update(tokens)

    raw_tokens = re.split(r"[\s,;/|，；、。\-]+", normalized_text)

    text_keywords: list[str] = []
    seen: set[str] = set()
    for tok in raw_tokens:
        tok = tok.strip()
        if not tok or len(tok) < 2:
            continue
        if tok in seen:
            continue
        seen.add(tok)
        if any(tok == ind or tok in ind for ind in all_indicator_tokens):
            continue
        if tok in _SURVIVAL_SIGNAL_WORDS:
            continue
        if tok in _STOP_WORDS:
            continue
        text_keywords.append(tok)

    if text_keywords:
        filters["text_keywords"] = text_keywords

    return filters


def _matches_model_request_filters(
    model_meta: dict[str, Any], filters: dict[str, Any]
) -> bool:
    for key, expected in filters.items():
        if key in ("task_type", "data_type"):
            if expected and model_meta.get(key) != expected:
                return False
        elif key == "text_keywords":
            searchable_lists: list[list[str]] = [
                model_meta.get("classes", []),
                model_meta.get("dataset_names", []),
                model_meta.get("dataset_sources", []),
            ]
            task_name_str = str(model_meta.get("task_name", ""))
            for kw in expected:
                kw_lower = kw.lower()
                in_list = any(
                    kw_lower in item
                    for field_list in searchable_lists
                    for item in field_list
                )
                if not in_list and kw_lower not in task_name_str:
                    return False
    return True


def _matches_quick_model_request_filters(model: Any, filters: dict[str, Any]) -> bool:
    """Fast keyword-only model match used for chunked scan early-stop.

    This intentionally performs a conservative subset of full matching logic
    without DB joins. Full filtering still happens later via
    _matches_model_request_filters on enriched model summaries.
    """
    text_keywords = filters.get("text_keywords") or []
    if not text_keywords:
        return False

    classes = model.classes or []
    if not isinstance(classes, list):
        classes = []

    search_space: list[str] = [
        (model.model_name or "").lower(),
        (model.feature_extractor or "").lower(),
        (model.aggregator or "").lower(),
        (model.task_id or "").lower(),
    ] + [str(cls).lower() for cls in classes]

    return all(
        any(keyword.lower() in field for field in search_space)
        for keyword in text_keywords
    )


def _format_model_filter_summary(filters: dict[str, Any]) -> str:
    parts = []
    if filters.get("task_type"):
        parts.append(f"task_type={filters['task_type']}")
    if filters.get("data_type"):
        parts.append(f"data_type={filters['data_type']}")
    if filters.get("text_keywords"):
        parts.append(f"keywords={','.join(filters['text_keywords'])}")
    return ", ".join(parts)


def _semantic_top_k_models(
    query_text: str,
    model_summaries: list[dict[str, Any]],
    k: int = TOP_K_MODELS_IN_CHAT_CONTEXT,
) -> list[dict[str, Any]]:
    if not model_summaries or len(model_summaries) <= k:
        return model_summaries

    has_embeddings = any(
        isinstance(s.get("embedding"), list) and len(s["embedding"]) > 0
        for s in model_summaries
    )
    if not has_embeddings or not query_text.strip():
        return model_summaries[:k]

    try:
        import numpy as np

        _embed_texts = import_module("gateway.routes.chat_pdf_vectorstore")._embed_texts

        q_vec = _embed_texts([query_text])[0]
        q_norm = np.linalg.norm(q_vec)
        if q_norm == 0:
            return model_summaries[:k]
        q_vec = q_vec / q_norm

        scores: list[tuple[float, int]] = []
        for idx, s in enumerate(model_summaries):
            emb = s.get("embedding")
            if not isinstance(emb, list):
                scores.append((0.0, idx))
                continue
            v = np.array(emb, dtype=np.float32)
            v_norm = np.linalg.norm(v)
            if v_norm == 0:
                scores.append((0.0, idx))
                continue
            sim = float(np.dot(q_vec, v / v_norm))
            scores.append((sim, idx))

        scores.sort(key=lambda x: x[0], reverse=True)
        top_indices = [idx for _, idx in scores[:k]]
        return [model_summaries[i] for i in top_indices]

    except Exception:
        return model_summaries[:k]


def _should_use_semantic_model_ranking(
    latest_user_text: str,
    inferred_model_filters: dict[str, Any],
    recent_user_texts: list[str],
) -> bool:
    normalized = (latest_user_text or "").strip().lower()
    if not normalized:
        return False

    generic_patterns = [
        "有多少模型",
        "多少模型",
        "看下模型",
        "看看模型",
        "列出模型",
        "有哪些模型",
        "show models",
        "list models",
        "how many models",
        "latest model",
        "newest model",
        "最新模型",
        "最新训练的模型",
    ]
    if any(p in normalized for p in generic_patterns):
        return False

    if inferred_model_filters:
        return True

    return len(recent_user_texts) > 1


def _extract_images_from_content(content: object) -> list[str]:
    """Extract image base64 URLs from multimodal message content.

    Returns a list of data URLs (e.g. 'data:image/jpeg;base64,...') for persistence.
    Returns empty list for text-only messages.
    """
    if not isinstance(content, list):
        return []
    images = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "image_url":
            url = part.get("image_url", {}).get("url", "")
            if url:
                images.append(url)
    return images


def _extract_citation_contexts(
    ai_response: str,
    article_pdf_content: str,
    per_paper_content: dict[int, str] | None = None,
    per_paper_source_ids: dict[int, str] | None = None,
) -> dict[str, dict[str, Any]] | None:
    """Extract citation contexts from AI response using BM25 paragraph search.

    For each ``[N, p.Y]`` citation found in *ai_response*, locate the
    most relevant ~200-char snippet from the corresponding page in the
    article PDF content (which contains ``--- Page X ---`` markers).

    Also handles bare ``[N]`` citations (without page numbers) by using
    BM25 on the full paper content.  These are keyed ``"N-bare"`` in the
    returned dict so the frontend can distinguish them.

    When *per_paper_content* is provided (multi-paper follow-up), each
    paper's pages are stored separately so page numbers from different
    papers don't collide.

    Returns a dict keyed by ``"N-pY"`` or ``"N-bare"`` with
    ``{page, context, source_id?}`` values, or ``None`` if no citations are found.
    """
    import math
    from collections import Counter

    # General pattern: [N, p.ANY_PAGE_DESCRIPTION] — matches p.2, p.2-3, p.2, p.4, etc.
    citation_pattern = re.compile(r"\[(\d{1,2}),\s*(p\.[^\]]+)\]")
    citations = citation_pattern.findall(ai_response)

    # Also detect bare [N] citations (no page number).
    # Negative lookbehind avoids matching inside [N, p.Y] or markdown links.
    bare_pattern = re.compile(r"(?<![,\w])\[(\d{1,2})\](?!\()")
    bare_matches = set(bare_pattern.findall(ai_response))
    # Remove indices already covered by [N, p.Y] patterns
    covered_indices = {idx_str for idx_str, _ in citations}
    bare_only = bare_matches - covered_indices

    if not citations and not bare_only:
        return None

    # Build per-paper page maps to avoid page-number collisions
    _single_page_map: dict[int, str] = {}
    if per_paper_content:
        paper_page_maps: dict[int, dict[int, str]] = {}
        for paper_idx, content in per_paper_content.items():
            pgs = split_md_into_pages(content)
            paper_page_maps[paper_idx] = {pn: ct for pn, ct in pgs}
    else:
        # Single-paper mode: all citations share the same page map
        pages = split_md_into_pages(article_pdf_content)
        _single_page_map = {pn: ct for pn, ct in pages}
        paper_page_maps = {}  # unused in single mode

    def _best_paragraph(page_text: str, query: str, max_len: int = 200) -> str:
        """BM25-rank paragraphs of *page_text* against *query*,
        return the best-matching snippet truncated to *max_len* chars."""

        def _clean_snippet_text(text: str) -> str:
            text = re.sub(r"^\s*--- Page \d+ ---\s*$", "", text, flags=re.MULTILINE)
            text = re.sub(
                r"^\s*!\[[^\]]*\]\([^\)]+\)\s*$", "", text, flags=re.MULTILINE
            )
            text = re.sub(r"https?://[^\s)\]]+", "", text).strip()
            text = re.sub(r"\s+", " ", text)
            return text.strip()

        def _is_low_value_paragraph(text: str) -> bool:
            compact = _clean_snippet_text(text)
            if not compact:
                return True
            lower = compact.lower()
            if compact.count("@") >= 2:
                return True
            if any(
                marker in lower
                for marker in (
                    "correspondence:",
                    "corresponding author",
                    "orcid",
                    "all rights reserved",
                )
            ):
                return True
            if len(compact) <= 140 and re.match(
                r"^(figure|fig\.?|table)\s*[0-9ivx]+", lower
            ):
                return True
            affiliation_hits = sum(
                lower.count(token)
                for token in (
                    "department of",
                    "university",
                    "hospital",
                    "institute",
                )
            )
            if affiliation_hits >= 2 and len(re.findall(r"[\.!?]", compact)) <= 1:
                return True
            return False

        paragraphs = [p.strip() for p in re.split(r"\n{2,}", page_text) if p.strip()]
        if not paragraphs:
            return _clean_snippet_text(page_text)[:max_len].strip()

        q_tokens = tokenize_for_search(query)
        if not q_tokens:
            for paragraph in paragraphs:
                cleaned = _clean_snippet_text(paragraph)
                if cleaned and not _is_low_value_paragraph(paragraph):
                    return cleaned[:max_len]
            cleaned_page = _clean_snippet_text(page_text)
            return cleaned_page[:max_len] if cleaned_page else paragraphs[0][:max_len]

        para_tokens = [tokenize_for_search(p) for p in paragraphs]
        N = len(paragraphs)
        avgdl = sum(len(t) for t in para_tokens) / N if N else 1
        k1, b = 1.5, 0.75

        unique_qt = set(q_tokens)
        df: dict[str, int] = {qt: 0 for qt in unique_qt}
        for tl in para_tokens:
            for qt in unique_qt & set(tl):
                df[qt] += 1

        best_score, best_idx = -1.0, 0
        best_non_noise_score, best_non_noise_idx = -1.0, None
        for idx, tl in enumerate(para_tokens):
            tf = Counter(tl)
            dl = len(tl)
            score = 0.0
            for qt in q_tokens:
                if qt not in tf:
                    continue
                n_qt = df[qt]
                idf = math.log((N - n_qt + 0.5) / (n_qt + 0.5) + 1)
                score += (
                    idf * (tf[qt] * (k1 + 1)) / (tf[qt] + k1 * (1 - b + b * dl / avgdl))
                )
            if score > best_score:
                best_score = score
                best_idx = idx
            if (
                not _is_low_value_paragraph(paragraphs[idx])
                and score > best_non_noise_score
            ):
                best_non_noise_score = score
                best_non_noise_idx = idx

        chosen_idx = best_idx
        if best_non_noise_idx is not None and (
            _is_low_value_paragraph(paragraphs[best_idx]) or best_non_noise_score > 0
        ):
            chosen_idx = best_non_noise_idx

        best_text = _clean_snippet_text(paragraphs[chosen_idx])
        if not best_text:
            best_text = _clean_snippet_text(page_text)
        snippet = best_text[:max_len].strip()
        if len(best_text) > max_len:
            snippet += "…"
        return snippet

    contexts: dict[str, dict[str, Any]] = {}
    for idx_str, page_part in citations:
        # Normalize key: remove whitespace from page part for consistent lookup
        key = f"{idx_str}-{page_part.replace(' ', '')}"
        if key in contexts:
            continue

        # Select the correct page map for this paper
        paper_idx = int(idx_str)
        if per_paper_content:
            page_map = paper_page_maps.get(paper_idx, {})
        else:
            page_map = _single_page_map

        # Extract ALL page numbers mentioned in page_part (handles p.2, p.2-3, p.2, p.4, etc.)
        page_numbers = [int(x) for x in re.findall(r"\d+", page_part)]
        if not page_numbers:
            continue
        # For ranges like p.2-3, expand to [2, 3]
        expanded_pages: list[int] = []
        for rng in re.findall(r"(\d+)(?:-(\d+))?", page_part):
            start_p = int(rng[0])
            end_p = int(rng[1]) if rng[1] else start_p
            expanded_pages.extend(range(start_p, end_p + 1))
        # Deduplicate while preserving order
        seen: set[int] = set()
        unique_pages: list[int] = []
        for p in expanded_pages:
            if p not in seen:
                seen.add(p)
                unique_pages.append(p)
        # Concatenate content from all referenced pages
        page_content = "\n\n".join(
            page_map.get(p, "") for p in unique_pages if page_map.get(p)
        ).strip()
        if not page_content:
            continue

        # Extract ~100 chars around the citation in the AI response for BM25 query
        citation_text = f"[{idx_str}, {page_part}]"
        pos = ai_response.find(citation_text)
        if pos >= 0:
            start = max(0, pos - 80)
            end = min(len(ai_response), pos + 80)
            query = ai_response[start:end]
        else:
            query = ai_response[:160]

        source_id = (
            per_paper_source_ids.get(paper_idx) if per_paper_source_ids else None
        )
        contexts[key] = {
            "page": unique_pages[0],
            "context": _best_paragraph(page_content, query),
            **({"source_id": source_id} if source_id else {}),
        }

    # ── Bare [N] citations — BM25 on full paper content ──────────────────
    for idx_str in bare_only:
        key = f"{idx_str}-bare"
        if key in contexts:
            continue
        paper_idx = int(idx_str)

        # Select full content for this paper
        if per_paper_content and paper_idx in per_paper_content:
            full_content = per_paper_content[paper_idx]
        elif not per_paper_content:
            full_content = article_pdf_content
        else:
            continue

        # Extract ~160 chars around the bare citation for BM25 query
        citation_text = f"[{idx_str}]"
        pos = ai_response.find(citation_text)
        if pos >= 0:
            start = max(0, pos - 80)
            end = min(len(ai_response), pos + 80)
            query = ai_response[start:end]
        else:
            query = ai_response[:160]

        source_id = (
            per_paper_source_ids.get(paper_idx) if per_paper_source_ids else None
        )
        contexts[key] = {
            "page": 0,  # no specific page
            "context": _best_paragraph(full_content, query),
            **({"source_id": source_id} if source_id else {}),
        }

    return contexts if contexts else None
