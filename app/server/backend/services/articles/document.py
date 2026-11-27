"""Normalized page/block evidence and deterministic query selection."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import re
from typing import Any, Literal


def clean_extracted_text(text: str) -> str:
    """Mark undecodable control glyphs without shifting page-box text offsets.

    NUL cannot be stored in PostgreSQL text/JSON. Other non-whitespace C0
    controls are also extraction artifacts, not evidence of a particular glyph.
    Keep tabs/newlines and printable Unicode; never guess missing equation text.
    """
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "\ufffd", text)


def clean_extracted_content(value):
    """Normalize textual fields in parsed/cache JSON without altering geometry."""
    if isinstance(value, str):
        return clean_extracted_text(value)
    if isinstance(value, list):
        return [clean_extracted_content(item) for item in value]
    if isinstance(value, dict):
        return {key: clean_extracted_content(item) for key, item in value.items()}
    return value


@dataclass(frozen=True, slots=True)
class ParsedPdfResult:
    markdown: str
    parse_method: Literal["pymupdf", "web"]
    page_count: int
    structured_content: dict[str, Any]

    def __post_init__(self):
        object.__setattr__(self, 'markdown', clean_extracted_text(self.markdown))
        object.__setattr__(self, 'structured_content', clean_extracted_content(self.structured_content))


def tokenize_for_search(text: str) -> list[str]:
    return re.findall(
        r"[a-z0-9]+|[\u4e00-\u9fff\u3400-\u4dbf\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]",
        text.lower(),
    )


def split_md_into_pages(markdown: str) -> list[tuple[int, str]]:
    parts = re.split(r"---\s*Page\s+(\d+)\s*---", markdown)
    pages = [(0, parts[0].strip())] if parts[0].strip() else []
    pages.extend(
        (int(parts[index]), parts[index + 1].strip())
        for index in range(1, len(parts) - 1, 2)
        if parts[index + 1].strip()
    )
    return pages


def _table_rows(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if any(cell and not set(cell) <= {"-", ":"} for cell in cells):
            rows.append(cells)
    return rows


def _build_document_graph_from_pymupdf_chunks(
    page_chunks: list[dict], parse_method: str
) -> dict:
    blocks, pages, section_path = [], [], []
    for chunk in page_chunks:
        page_number = int(chunk.get("metadata", {}).get("page", 0))
        if page_number < 1:
            continue
        page = {
            "id": f"page-{page_number}",
            "type": "section",
            "title": f"Page {page_number}",
            "page_start": page_number,
            "page_end": page_number,
            "children": [],
        }
        pages.append(page)
        text = str(chunk.get("text") or "")
        boxes = chunk.get("page_boxes") or [{"pos": [0, len(text)], "class": "text"}]
        for box in boxes:
            start, stop = (box.get("pos") or [0, len(text)])[:2]
            body = text[int(start) : int(stop)].strip()
            if not body:
                continue
            label = str(box.get("class") or "text")
            bbox = box.get("bbox")
            if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                bbox = dict(zip(["l", "t", "r", "b"], bbox), coord_origin="TOPLEFT")
            # Layout boxes already preserve table/caption geometry. Markdown-only
            # blocks are split by paragraphs for grounded retrieval.
            pieces = (
                [body]
                if label in {"table", "picture", "formula", "caption"}
                else re.split(r"\n\s*\n", body)
            )
            for piece in pieces:
                kind, payload = "paragraph", {"text": piece}
                heading = re.match(r"^(#{1,6})\s+(.+)", piece)
                image = re.search(r"!\[([^]]*)\]\(([^)]+)\)", piece)
                if label == "table" or piece.startswith("|"):
                    kind, payload = (
                        "table",
                        {"markdown": piece, "cells": _table_rows(piece), "caption": ""},
                    )
                elif image:
                    kind, payload = (
                        "figure",
                        {"image": image[2], "caption": image[1], "vision_summary": ""},
                    )
                elif label == "formula":
                    kind, payload = "equation", {"latex": piece, "surrounding_text": ""}
                elif heading:
                    level = len(heading[1])
                    section_path = section_path[: level - 1] + [heading[2]]
                    kind, payload = "section", {"text": heading[2], "level": level}
                identity = f"{kind}-p{page_number}-{len(blocks) + 1}"
                blocks.append(
                    {
                        "id": identity,
                        "type": kind,
                        "page": page_number,
                        "parent_id": page["id"],
                        "section_path": section_path.copy(),
                        "bbox": bbox,
                        "source_backend": parse_method,
                        "native_label": label,
                        "native_ref": f"page-box-{page_number}-{box.get('index', len(blocks))}",
                        **payload,
                    }
                )
                page["children"].append(identity)
    return {
        "schema_version": 3,
        "type": "document",
        "parse_method": parse_method,
        "page_count": max((page["page_start"] for page in pages), default=0),
        "children": pages,
        "blocks": blocks,
    }


def search_pdf_pages(
    markdown: str, query: str, top_k: int = 10
) -> list[tuple[int, str, float]]:
    return _rank_passages(split_md_into_pages(markdown), query, top_k)


def _rank_passages(pages: list[tuple[int, str]], query: str, top_k: int):
    tokens = tokenize_for_search(query)
    if not pages or not tokens:
        return []
    terms = [tokenize_for_search(body) for _, body in pages]
    average = sum(map(len, terms)) / len(terms) or 1
    frequency = {token: sum(token in page for page in terms) for token in set(tokens)}
    scored = []
    for (number, body), words in zip(pages, terms):
        counts = Counter(words)
        score = 0
        for token in tokens:
            if token not in counts:
                continue
            idf = math.log(
                (len(pages) - frequency[token] + 0.5) / (frequency[token] + 0.5) + 1
            )
            score += (
                idf
                * counts[token]
                * 2.5
                / (counts[token] + 1.5 * (0.25 + 0.75 * len(words) / average))
            )
        if score:
            scored.append((number, body, score))
    return sorted(scored, key=lambda row: row[2], reverse=True)[:top_k]


def select_article_context(markdown: str, query: str, budget: int = 40000) -> str:
    if len(markdown) <= budget:
        return markdown
    if not re.search(r"---\s*Page\s+\d+\s*---", markdown):
        # HTML has sections, not PDF pages. Rank sections instead of silently
        # returning only the first 12k characters of a publisher's long article.
        passages = []
        for section in re.split(r"(?=^#{1,6}\s)", markdown, flags=re.M):
            heading = section.split("\n", 1)[0] if section.startswith("#") else ""
            for start in range(0, len(section), 8000):
                body = section[start : start + 8000]
                passages.append(
                    (len(passages), (heading + "\n" if start else "") + body)
                )
        ranked = _rank_passages(passages, query, 12)
        order = list(
            dict.fromkeys([*[number for number, _, _ in ranked], 0, len(passages) - 1])
        )
        selected, remaining = {}, budget - 150
        for number in order:
            if remaining <= 100:
                break
            body = passages[number][1][: remaining - 2]
            selected[number] = body
            remaining -= len(body) + 2
        return (
            "[Query-relevant HTML excerpts; other sections omitted.]\n\n"
            + "\n\n".join(selected[number] for number in sorted(selected))
        )
    pages = split_md_into_pages(markdown)
    if not pages:
        return markdown[:budget]
    requested = [
        int(value) for value in re.findall(r"(?:page|p\.?|第)\s*(\d+)", query, re.I)
    ]
    ranked = search_pdf_pages(markdown, query, top_k=12)
    order = list(
        dict.fromkeys(
            [
                *requested,
                *[number for number, _, _ in ranked],
                pages[0][0],
                pages[-1][0],
            ]
        )
    )
    lookup = dict(pages)
    selected = {}
    remaining = budget - 150
    for number in order:
        if number not in lookup or remaining <= 100:
            continue
        text = lookup[number][: min(12000, remaining - 30)]
        selected[number] = f"--- Page {number} ---\n{text}\n"
        remaining -= len(selected[number])
    return (
        "[Query-relevant excerpts; other pages omitted from this context.]\n"
        + "\n".join(selected[number] for number in sorted(selected))
    )
