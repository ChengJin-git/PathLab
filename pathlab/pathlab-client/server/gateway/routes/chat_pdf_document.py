from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

PDF_PARSE_METHOD_MARKER = "marker"
PDF_PARSE_METHOD_PYMUPDF = "pymupdf"
PDF_PARSE_METHOD_FAILED = "parse_failed"
PDF_PARSE_METHOD_WEB = "web"
STRUCTURED_SCHEMA_VERSION = 2
PdfParseMethod = Literal["marker", "pymupdf", "parse_failed", "web"]


@dataclass(frozen=True, slots=True)
class ParsedPdfResult:
    markdown: str
    parse_method: PdfParseMethod
    page_count: int
    structured_content: dict[str, Any]


def _extract_page_count(markdown: str) -> int:
    """Return the total page count from markdown with '--- Page X ---' markers.

    Scans all '--- Page X ---' markers and returns the maximum X found, which
    equals the total number of pages parsed.  Returns 0 if no markers are found.
    """
    page_nums = [int(m) for m in re.findall(r"--- Page (\d+) ---", markdown)]
    return max(page_nums) if page_nums else 0


def tokenize_for_search(text: str) -> list[str]:
    """Simple tokenizer for BM25 search. Handles English, numbers, CJK, Japanese, and Korean.

    - Lowercases all text
    - Keeps alphanumeric runs (e.g. ``bm25``, ``page3``) as single tokens
    - Splits each CJK / Hiragana / Katakana / Hangul character as an individual token
    """
    # CJK Unified + Extension A + Hiragana + Katakana + Hangul Syllables
    return re.findall(
        r"[a-z0-9]+|[\u4e00-\u9fff\u3400-\u4dbf\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]",
        text.lower(),
    )


def split_md_into_pages(markdown: str) -> list[tuple[int, str]]:
    """Split markdown by ``--- Page X ---`` markers into ``(page_num, content)`` pairs.

    Content before the first marker (if any) is assigned page number 0.
    """
    parts = re.split(r"--- Page (\d+) ---", markdown)
    pages: list[tuple[int, str]] = []
    if parts[0].strip():
        pages.append((0, parts[0].strip()))
    for i in range(1, len(parts), 2):
        page_num = int(parts[i])
        content = parts[i + 1] if i + 1 < len(parts) else ""
        if content.strip():
            pages.append((page_num, content.strip()))
    return pages


def _parse_markdown_table_rows(table_lines: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in table_lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if cells and any(cell and set(cell) != {"-", ":"} for cell in cells):
            rows.append(cells)
    return rows


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_bbox(raw_bbox: Any) -> dict[str, Any] | None:
    if raw_bbox is None:
        return None

    coord_origin = None
    values: tuple[Any, Any, Any, Any] | None = None

    if isinstance(raw_bbox, dict):
        if all(key in raw_bbox for key in ("l", "t", "r", "b")):
            values = (
                raw_bbox.get("l"),
                raw_bbox.get("t"),
                raw_bbox.get("r"),
                raw_bbox.get("b"),
            )
        elif all(key in raw_bbox for key in ("x0", "y0", "x1", "y1")):
            values = (
                raw_bbox.get("x0"),
                raw_bbox.get("y0"),
                raw_bbox.get("x1"),
                raw_bbox.get("y1"),
            )
        coord_origin = raw_bbox.get("coord_origin")
    elif isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) >= 4:
        values = (raw_bbox[0], raw_bbox[1], raw_bbox[2], raw_bbox[3])
    else:
        as_tuple_fn = getattr(raw_bbox, "as_tuple", None)
        if callable(as_tuple_fn):
            try:
                as_tuple_value = as_tuple_fn()
                if (
                    isinstance(as_tuple_value, (list, tuple))
                    and len(as_tuple_value) >= 4
                ):
                    values = (
                        as_tuple_value[0],
                        as_tuple_value[1],
                        as_tuple_value[2],
                        as_tuple_value[3],
                    )
            except Exception:
                values = None
        if values is None:
            l = getattr(raw_bbox, "l", getattr(raw_bbox, "x0", None))
            t = getattr(raw_bbox, "t", getattr(raw_bbox, "y0", None))
            r = getattr(raw_bbox, "r", getattr(raw_bbox, "x1", None))
            b = getattr(raw_bbox, "b", getattr(raw_bbox, "y1", None))
            if None not in (l, t, r, b):
                values = (l, t, r, b)
        coord_origin = getattr(raw_bbox, "coord_origin", coord_origin)

    if values is None:
        return None

    try:
        left, top, right, bottom = (float(v) for v in values)
    except (TypeError, ValueError):
        return None

    coord_value = getattr(coord_origin, "value", coord_origin)
    return {
        "l": left,
        "t": top,
        "r": right,
        "b": bottom,
        "coord_origin": _coerce_text(coord_value) or "TOPLEFT",
    }


def _build_markdown_table_from_rows(rows: list[list[str]]) -> str:
    normalized_rows = [
        [str(cell).strip() for cell in row]
        for row in rows
        if isinstance(row, list) and any(str(cell).strip() for cell in row)
    ]
    if not normalized_rows:
        return ""

    header = normalized_rows[0]
    separator = ["---"] * len(header)
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for row in normalized_rows[1:]:
        padded = row + [""] * max(0, len(header) - len(row))
        lines.append("| " + " | ".join(padded[: len(header)]) + " |")
    return "\n".join(lines)


def _extract_markdown_image(markdown_text: str) -> tuple[str, str]:
    match = re.search(r"!\[([^\]]*)\]\(([^)]+)\)", markdown_text)
    if not match:
        return "", ""
    return match.group(1).strip(), match.group(2).strip()


def _make_page_node(page_num: int) -> dict[str, Any]:
    return {
        "id": f"page-{page_num}",
        "type": "section",
        "title": f"Page {page_num}",
        "page_start": page_num,
        "page_end": page_num,
        "children": [],
    }


def _append_blocks_from_markdown_text(
    *,
    page_num: int,
    page_text: str,
    page_node: dict[str, Any],
    blocks: list[dict[str, Any]],
    next_block_id: Callable[[str, int], str],
    current_path: list[str] | None = None,
    base_payload: dict[str, Any] | None = None,
) -> list[str]:
    if not page_text.strip():
        return list(current_path or [])

    working_path = list(current_path or [])
    common_payload = dict(base_payload or {})
    paragraph_buffer: list[str] = []
    table_buffer: list[str] = []
    equation_buffer: list[str] = []
    in_equation = False

    def _append_block(block_type: str, **payload: Any) -> None:
        block_id = next_block_id(block_type, page_num)
        merged_payload = {
            **common_payload,
            **payload,
        }
        merged_payload.setdefault("section_path", working_path.copy())
        block = {
            "id": block_id,
            "type": block_type,
            "page": page_num,
            "parent_id": page_node["id"],
            **merged_payload,
        }
        blocks.append(block)
        page_node["children"].append(block_id)

    def _flush_paragraph() -> None:
        if not paragraph_buffer:
            return
        text = "\n".join(paragraph_buffer).strip()
        paragraph_buffer.clear()
        if text:
            _append_block("paragraph", text=text, section_path=working_path.copy())

    def _flush_table() -> None:
        if not table_buffer:
            return
        table_markdown = "\n".join(table_buffer).strip()
        rows = _parse_markdown_table_rows(table_buffer)
        table_buffer.clear()
        if table_markdown:
            _append_block(
                "table",
                markdown=table_markdown,
                cells=rows,
                caption="",
                section_path=working_path.copy(),
            )

    def _flush_equation() -> None:
        if not equation_buffer:
            return
        latex = "\n".join(equation_buffer).strip()
        equation_buffer.clear()
        if latex:
            _append_block(
                "equation",
                latex=latex,
                surrounding_text="",
                section_path=working_path.copy(),
            )

    for raw_line in page_text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped.startswith("$$"):
            _flush_paragraph()
            _flush_table()
            if in_equation and stripped != "$$":
                equation_buffer.append(stripped)
            in_equation = not in_equation
            if not in_equation:
                _flush_equation()
            continue

        if in_equation:
            equation_buffer.append(line)
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        image_match = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", stripped)

        if not stripped:
            _flush_paragraph()
            _flush_table()
            continue

        if heading_match:
            _flush_paragraph()
            _flush_table()
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            working_path = working_path[: max(level - 1, 0)]
            working_path.append(title)
            _append_block(
                "section",
                text=title,
                level=level,
                section_path=working_path.copy(),
            )
            continue

        if image_match:
            _flush_paragraph()
            _flush_table()
            _append_block(
                "figure",
                image=image_match.group(2).strip(),
                caption=image_match.group(1).strip(),
                vision_summary="",
                section_path=working_path.copy(),
            )
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            _flush_paragraph()
            table_buffer.append(stripped)
            continue

        if table_buffer:
            _flush_table()

        paragraph_buffer.append(stripped)

    _flush_paragraph()
    _flush_table()
    _flush_equation()
    return working_path


def _build_document_graph_from_markdown(
    markdown: str, parse_method: PdfParseMethod
) -> dict[str, Any]:
    """Normalize markdown into a lightweight Document Graph / Block Graph sidecar."""
    page_entries = split_md_into_pages(markdown)
    blocks: list[dict[str, Any]] = []
    section_nodes: list[dict[str, Any]] = []
    block_counter = 0
    current_path: list[str] = []

    def _next_block_id(prefix: str, page_num: int) -> str:
        nonlocal block_counter
        block_counter += 1
        return f"{prefix}-p{page_num}-{block_counter}"

    for page_num, page_text in page_entries:
        page_node = _make_page_node(page_num)
        section_nodes.append(page_node)
        current_path = _append_blocks_from_markdown_text(
            page_num=page_num,
            page_text=page_text,
            page_node=page_node,
            blocks=blocks,
            next_block_id=_next_block_id,
            current_path=current_path,
            base_payload={
                "source_backend": parse_method,
                "native_label": "markdown",
                "native_ref": f"markdown-page-{page_num}",
            },
        )

    return {
        "schema_version": STRUCTURED_SCHEMA_VERSION,
        "type": "document",
        "parse_method": parse_method,
        "page_count": _extract_page_count(markdown),
        "children": section_nodes,
        "blocks": blocks,
    }


def _marker_image_block_id_from_name(image_name: str) -> str:
    stem = Path(image_name).stem
    if not stem:
        return ""
    return stem.replace("_", "/")


def _normalize_marker_markdown(markdown: str, first_page_id: int | None) -> str:
    page_offset = 1 if first_page_id == 0 else 0

    def _replace_page_marker(match: re.Match[str]) -> str:
        page_num = int(match.group(1)) + page_offset
        return f"--- Page {page_num} ---"

    return re.sub(
        r"\{(\d+)\}<<<PATHLAB_MARKER_PAGE_BREAK>>>", _replace_page_marker, markdown
    ).strip()


def _extract_marker_text_from_html(html_content: str) -> str:
    if not html_content:
        return ""
    try:
        from bs4 import BeautifulSoup

        text = BeautifulSoup(html_content, "html.parser").get_text("\n", strip=True)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", html_content)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _extract_marker_table_rows(html_content: str) -> list[list[str]]:
    if not html_content:
        return []
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html_content, "html.parser")
        table = soup.find("table")
        if table is None:
            return []
        rows: list[list[str]] = []
        for tr in table.find_all("tr"):
            cells = [
                cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])
            ]
            if cells:
                rows.append(cells)
        return rows
    except Exception:
        return []


def _collect_marker_section_titles(
    node: dict[str, Any], title_map: dict[str, str]
) -> None:
    block_type = _coerce_text(node.get("block_type")).lower()
    node_id = _coerce_text(node.get("id"))
    if block_type == "sectionheader" and node_id:
        title_text = _extract_marker_text_from_html(_coerce_text(node.get("html")))
        if title_text:
            title_map[node_id] = title_text
    for child in node.get("children") or []:
        if isinstance(child, dict):
            _collect_marker_section_titles(child, title_map)


def _resolve_marker_section_path(
    section_hierarchy: Any, title_map: dict[str, str]
) -> list[str]:
    if not isinstance(section_hierarchy, dict):
        return []
    resolved: list[str] = []

    def _sort_key(item: tuple[Any, Any]) -> tuple[int, str]:
        key_text = _coerce_text(item[0])
        try:
            return (0, f"{int(key_text):06d}")
        except Exception:
            return (1, key_text)

    for value in (item[1] for item in sorted(section_hierarchy.items(), key=_sort_key)):
        title = title_map.get(_coerce_text(value), _coerce_text(value))
        if title and title not in resolved:
            resolved.append(title)
    return resolved


def _find_marker_image_url(node: dict[str, Any], image_url_map: dict[str, str]) -> str:
    node_id = _coerce_text(node.get("id"))
    if node_id and image_url_map.get(node_id):
        return image_url_map[node_id]
    for child in node.get("children") or []:
        if isinstance(child, dict):
            image_url = _find_marker_image_url(child, image_url_map)
            if image_url:
                return image_url
    return ""


def _collect_marker_caption_text(node: dict[str, Any]) -> str:
    parts: list[str] = []
    self_text = _extract_marker_text_from_html(_coerce_text(node.get("html")))
    if self_text:
        parts.append(self_text)
    for child in node.get("children") or []:
        if not isinstance(child, dict):
            continue
        child_type = _coerce_text(child.get("block_type")).lower()
        if child_type == "caption":
            caption_text = _extract_marker_text_from_html(
                _coerce_text(child.get("html"))
            )
            if caption_text:
                parts.append(caption_text)
    deduped: list[str] = []
    for part in parts:
        if part not in deduped:
            deduped.append(part)
    return "\n".join(deduped).strip()


def _build_document_graph_from_marker_document(
    rendered_json: dict[str, Any],
    parse_method: PdfParseMethod,
    *,
    max_pages: int = 0,
    page_count_hint: int = 0,
    image_url_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    section_nodes: list[dict[str, Any]] = []
    page_node_map: dict[int, dict[str, Any]] = {}
    block_counter = 0
    image_url_map = image_url_map or {}
    section_title_map: dict[str, str] = {}

    for child in rendered_json.get("children") or []:
        if isinstance(child, dict):
            _collect_marker_section_titles(child, section_title_map)

    initial_page_count = page_count_hint if page_count_hint > 0 else max_pages
    for page_num in range(1, max(initial_page_count, 0) + 1):
        page_node = _make_page_node(page_num)
        section_nodes.append(page_node)
        page_node_map[page_num] = page_node

    def _next_block_id(prefix: str, page_num: int) -> str:
        nonlocal block_counter
        block_counter += 1
        return f"{prefix}-p{page_num}-{block_counter}"

    def _get_page_node(page_num: int) -> dict[str, Any]:
        if page_num not in page_node_map:
            page_node = _make_page_node(page_num)
            page_node_map[page_num] = page_node
            section_nodes.append(page_node)
        return page_node_map[page_num]

    def _append_block(page_num: int, block_type: str, **payload: Any) -> None:
        page_node = _get_page_node(page_num)
        block_id = _next_block_id(block_type, page_num)
        block = {
            "id": block_id,
            "type": block_type,
            "page": page_num,
            "parent_id": page_node["id"],
            **payload,
        }
        blocks.append(block)
        page_node["children"].append(block_id)

    def _walk(
        node: dict[str, Any],
        page_num: int,
        current_path: list[str],
        parent_type: str = "",
    ) -> None:
        raw_type = _coerce_text(node.get("block_type"))
        normalized_type = raw_type.lower()
        if not normalized_type or normalized_type == "page":
            for child in node.get("children") or []:
                if isinstance(child, dict):
                    _walk(child, page_num, current_path, normalized_type)
            return

        if normalized_type in {"pageheader", "pagefooter", "footnote", "reference"}:
            return

        node_id = _coerce_text(node.get("id"))
        html_content = _coerce_text(node.get("html"))
        text = _extract_marker_text_from_html(html_content)
        bbox = _normalize_bbox(node.get("bbox"))
        resolved_path = (
            _resolve_marker_section_path(
                node.get("section_hierarchy"), section_title_map
            )
            or current_path.copy()
        )
        base_payload = {
            "bbox": bbox,
            "section_path": resolved_path.copy(),
            "source_backend": PDF_PARSE_METHOD_MARKER,
            "native_label": raw_type,
            "native_ref": node_id,
        }

        next_path = resolved_path.copy()
        if normalized_type == "sectionheader":
            title_text = text
            if title_text:
                next_path = resolved_path or [title_text]
                if next_path[-1] != title_text:
                    next_path = [*next_path, title_text]
                _append_block(
                    page_num,
                    "section",
                    text=title_text,
                    level=max(1, len(next_path)),
                    **{**base_payload, "section_path": next_path.copy()},
                )
            for child in node.get("children") or []:
                if isinstance(child, dict):
                    _walk(child, page_num, next_path, normalized_type)
            return

        if normalized_type == "table":
            cells = _extract_marker_table_rows(html_content)
            table_markdown = _build_markdown_table_from_rows(cells)
            _append_block(
                page_num,
                "table",
                caption=_collect_marker_caption_text(node),
                markdown=table_markdown,
                cells=cells,
                image=_find_marker_image_url(node, image_url_map),
                **base_payload,
            )
            for child in node.get("children") or []:
                if isinstance(child, dict) and _coerce_text(
                    child.get("block_type")
                ).lower() not in {"caption", "picture", "table"}:
                    _walk(child, page_num, next_path, normalized_type)
            return

        if normalized_type in {"picture", "figure"}:
            image_url = _find_marker_image_url(node, image_url_map)
            caption = _collect_marker_caption_text(node)
            if image_url or caption:
                _append_block(
                    page_num,
                    "figure",
                    image=image_url,
                    caption=caption,
                    vision_summary="",
                    **base_payload,
                )
            for child in node.get("children") or []:
                if isinstance(child, dict) and _coerce_text(
                    child.get("block_type")
                ).lower() not in {"caption", "picture", "figure"}:
                    _walk(child, page_num, next_path, normalized_type)
            return

        if normalized_type in {"equation", "formula"} and text:
            _append_block(
                page_num,
                "equation",
                latex=text,
                surrounding_text="",
                **base_payload,
            )
        elif normalized_type == "code" and text:
            _append_block(page_num, "code", text=text, **base_payload)
        elif normalized_type.startswith("list") and text:
            _append_block(page_num, "list", text=text, **base_payload)
        elif normalized_type == "caption" and parent_type in {
            "picture",
            "figure",
            "table",
        }:
            return
        elif text:
            _append_block(page_num, "paragraph", text=text, **base_payload)

        for child in node.get("children") or []:
            if isinstance(child, dict):
                _walk(child, page_num, next_path, normalized_type)

    pages = [
        child
        for child in rendered_json.get("children") or []
        if isinstance(child, dict)
    ]
    for page_index, page in enumerate(pages, start=1):
        if max_pages > 0 and page_index > max_pages:
            break
        _get_page_node(page_index)
        for child in page.get("children") or []:
            if isinstance(child, dict):
                _walk(child, page_index, [], "page")

    section_nodes.sort(key=lambda node: int(node.get("page_start") or 0))
    total_pages = page_count_hint or len(pages)
    page_count = min(total_pages, max_pages) if max_pages > 0 else total_pages
    return {
        "schema_version": STRUCTURED_SCHEMA_VERSION,
        "type": "document",
        "parse_method": parse_method,
        "page_count": page_count,
        "children": section_nodes,
        "blocks": blocks,
    }


def _build_document_graph_from_pymupdf_chunks(
    page_chunks: list[dict[str, Any]],
    parse_method: PdfParseMethod,
) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    section_nodes: list[dict[str, Any]] = []
    block_counter = 0
    current_path: list[str] = []

    def _next_block_id(prefix: str, page_num: int) -> str:
        nonlocal block_counter
        block_counter += 1
        return f"{prefix}-p{page_num}-{block_counter}"

    for chunk in page_chunks:
        metadata = chunk.get("metadata", {}) if isinstance(chunk, dict) else {}
        page_num = _safe_int(metadata.get("page", metadata.get("page_number", 0)), 0)
        if page_num <= 0:
            continue
        page_text = str(chunk.get("text") or "")
        page_node = _make_page_node(page_num)
        section_nodes.append(page_node)

        page_boxes = chunk.get("page_boxes")
        if not isinstance(page_boxes, list) or not page_boxes:
            current_path = _append_blocks_from_markdown_text(
                page_num=page_num,
                page_text=page_text,
                page_node=page_node,
                blocks=blocks,
                next_block_id=_next_block_id,
                current_path=current_path,
                base_payload={
                    "source_backend": PDF_PARSE_METHOD_PYMUPDF,
                    "native_label": "text",
                    "native_ref": f"pymupdf-page-{page_num}",
                },
            )
            continue

        block_count_before = len(blocks)
        for page_box in page_boxes:
            if not isinstance(page_box, dict):
                continue
            position = page_box.get("pos")
            box_text = ""
            if isinstance(position, (list, tuple)) and len(position) >= 2:
                start = _safe_int(position[0], 0)
                stop = _safe_int(position[1], 0)
                box_text = page_text[start:stop].strip()

            native_label = (_coerce_text(page_box.get("class")) or "text").lower()
            bbox = _normalize_bbox(page_box.get("bbox"))
            native_ref = (
                f"page-box-{page_num}-{_safe_int(page_box.get('index'), len(blocks))}"
            )
            base_payload = {
                "bbox": bbox,
                "source_backend": PDF_PARSE_METHOD_PYMUPDF,
                "native_label": native_label,
                "native_ref": native_ref,
            }

            if native_label == "table":
                rows = _parse_markdown_table_rows(box_text.splitlines())
                blocks.append(
                    {
                        "id": _next_block_id("table", page_num),
                        "type": "table",
                        "page": page_num,
                        "parent_id": page_node["id"],
                        "caption": "",
                        "markdown": box_text,
                        "cells": rows,
                        "section_path": current_path.copy(),
                        **base_payload,
                    }
                )
                page_node["children"].append(blocks[-1]["id"])
                continue

            if native_label in {"picture", "image"}:
                caption, image = _extract_markdown_image(box_text)
                if image or caption or box_text:
                    blocks.append(
                        {
                            "id": _next_block_id("figure", page_num),
                            "type": "figure",
                            "page": page_num,
                            "parent_id": page_node["id"],
                            "image": image,
                            "caption": caption or box_text,
                            "vision_summary": "",
                            "section_path": current_path.copy(),
                            **base_payload,
                        }
                    )
                    page_node["children"].append(blocks[-1]["id"])
                continue

            current_path = _append_blocks_from_markdown_text(
                page_num=page_num,
                page_text=box_text,
                page_node=page_node,
                blocks=blocks,
                next_block_id=_next_block_id,
                current_path=current_path,
                base_payload=base_payload,
            )

        if len(blocks) == block_count_before and page_text:
            current_path = _append_blocks_from_markdown_text(
                page_num=page_num,
                page_text=page_text,
                page_node=page_node,
                blocks=blocks,
                next_block_id=_next_block_id,
                current_path=current_path,
                base_payload={
                    "source_backend": PDF_PARSE_METHOD_PYMUPDF,
                    "native_label": "text",
                    "native_ref": f"pymupdf-page-{page_num}",
                },
            )

    section_nodes.sort(key=lambda node: int(node.get("page_start") or 0))
    return {
        "schema_version": STRUCTURED_SCHEMA_VERSION,
        "type": "document",
        "parse_method": parse_method,
        "page_count": max(
            (int(node.get("page_start") or 0) for node in section_nodes), default=0
        ),
        "children": section_nodes,
        "blocks": blocks,
    }


def _to_parsed_pdf_result(
    markdown: str,
    parse_method: PdfParseMethod,
    structured_content: dict[str, Any] | None = None,
) -> ParsedPdfResult:
    structured_content = structured_content or _build_document_graph_from_markdown(
        markdown, parse_method
    )
    return ParsedPdfResult(
        markdown=markdown,
        parse_method=parse_method,
        page_count=int(structured_content.get("page_count") or 0),
        structured_content=structured_content,
    )


def search_pdf_pages(
    markdown: str,
    query: str,
    top_k: int = 10,
) -> list[tuple[int, str, float]]:
    """BM25 page-level search over parsed PDF markdown.

    Returns up to *top_k* pages as ``(page_num, content, score)`` tuples
    sorted by descending BM25 score.  Pages with score == 0 are excluded.

    Self-contained implementation — no external dependencies required.
    """
    import math
    from collections import Counter

    pages = split_md_into_pages(markdown)
    if not pages:
        return []

    query_tokens = tokenize_for_search(query)
    if not query_tokens:
        return []

    # Tokenize every page once
    page_token_lists = [tokenize_for_search(content) for _, content in pages]

    # BM25 hyper-parameters
    k1, b = 1.5, 0.75
    N = len(pages)
    avgdl = sum(len(tl) for tl in page_token_lists) / N if N > 0 else 1

    # Document frequency for each unique query term
    unique_qts = set(query_tokens)
    df: dict[str, int] = {qt: 0 for qt in unique_qts}
    for tl in page_token_lists:
        present = unique_qts & set(tl)
        for qt in present:
            df[qt] += 1

    # Score each page
    scored: list[tuple[int, str, float]] = []
    for idx, (page_num, content) in enumerate(pages):
        tf = Counter(page_token_lists[idx])
        dl = len(page_token_lists[idx])
        score = 0.0
        for qt in query_tokens:
            if qt not in tf:
                continue
            n_qt = df[qt]
            idf = math.log((N - n_qt + 0.5) / (n_qt + 0.5) + 1)
            score += (
                idf * (tf[qt] * (k1 + 1)) / (tf[qt] + k1 * (1 - b + b * dl / avgdl))
            )
        if score > 0:
            scored.append((page_num, content, score))

    scored.sort(key=lambda x: x[2], reverse=True)
    return scored[:top_k]
