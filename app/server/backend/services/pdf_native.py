"""Bounded native-text extraction for interactive Chat (no layout inference)."""

from collections import Counter
from pathlib import Path


def _reading_order(blocks):
    """Split at whitespace gutters before sorting overlapping text blocks.

    A y/x sort alone interleaves two-column papers. Full-width headings and
    footnotes are separated horizontally before the columns can be split.
    """
    if len(blocks) < 2:
        return blocks
    for axis, minimum in ((0, 12), (1, 6)):
        intervals = sorted((b["bbox"][axis], b["bbox"][axis + 2]) for b in blocks)
        end, gaps = intervals[0][1], []
        for start, stop in intervals[1:]:
            if start - end >= minimum:
                gaps.append((start - end, (start + end) / 2))
            end = max(end, stop)
        if gaps:
            _, cut = max(gaps)
            before = [b for b in blocks if b["bbox"][axis + 2] <= cut]
            after = [b for b in blocks if b["bbox"][axis] > cut]
            return _reading_order(before) + _reading_order(after)
    return sorted(blocks, key=lambda b: (b["bbox"][1], b["bbox"][0]))


def extract_native_page(page, *, images: str = "") -> tuple[dict, bool]:
    import pymupdf

    # Never decode embedded raster images just to extract native text.
    data = page.get_text(
        "dict", flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES
    )
    paths = page.get_cdrawings()
    dense_graphics = len(paths) > 150
    tables = []
    # Table/vector clustering on plots with thousands of paths is pathological.
    # Keep all their native labels and a page preview instead. Simple ruled
    # tables retain their real cells and bounding boxes.
    if 3 <= len(paths) <= 150:
        found = page.find_tables(strategy="lines_strict", paths=page.get_drawings())
        for table in found.tables if found else []:
            if table.row_count >= 2 and table.col_count >= 2:
                tables.append(
                    {
                        "bbox": list(table.bbox),
                        "text": table.to_markdown(),
                        "class": "table",
                    }
                )

    sizes = Counter()
    for block in data["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                sizes[round(span["size"])] += len(span["text"].strip())
    body_size = sizes.most_common(1)[0][0] if sizes else 12
    blocks = []
    for block in data["blocks"]:
        lines, bounds = [], pymupdf.EMPTY_RECT()
        for line in block.get("lines", []):
            rect = pymupdf.Rect(line["bbox"])
            cx, cy = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
            if any(
                t["bbox"][0] <= cx <= t["bbox"][2]
                and t["bbox"][1] <= cy <= t["bbox"][3]
                for t in tables
            ):
                continue
            parts, previous = [], None
            for span in line["spans"]:
                if (
                    previous is not None
                    and span["bbox"][0] - previous > span["size"] * 0.8
                ):
                    parts.append("  ")
                parts.append(span["text"])
                previous = span["bbox"][2]
            text = "".join(parts).strip()
            if text:
                if (
                    max(s["size"] for s in line["spans"]) > body_size * 1.2
                    and len(text) < 180
                ):
                    text = "## " + text
                lines.append(text)
                bounds |= rect
        if lines:
            blocks.append(
                {"bbox": list(bounds), "text": "\n".join(lines), "class": "text"}
            )
    blocks = _reading_order(blocks + tables)
    if images and (dense_graphics or page.get_images() or (paths and not tables)):
        directory = Path(images)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"page-{page.number + 1:04d}.png"
        page.get_pixmap(dpi=100, alpha=False).save(path)
        blocks.append(
            {
                "bbox": list(page.rect),
                "text": f"![Original page {page.number + 1} — figures and layout]({path})",
                "class": "picture",
            }
        )
    text, boxes = "", []
    for block in blocks:
        start = len(text)
        text += block["text"] + "\n\n"
        boxes.append(
            {"bbox": block["bbox"], "class": block["class"], "pos": [start, len(text)]}
        )
    return {
        "metadata": {"page": page.number + 1},
        "text": text,
        "page_boxes": boxes,
    }, dense_graphics
