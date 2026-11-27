"""CPU-only PDF layout extraction with selective OCR, isolated from GPU services.

Run as a script so timeout/cancellation can terminate the actual parser process.
The caller bounds concurrency and supplies a temporary output directory.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
import re
from typing import Callable


def scanned_tables(
    image, words: list[dict], page_size: tuple[float, float]
) -> list[dict]:
    """Recover ruled raster tables from the same OCR pass, never infer values."""
    import cv2
    import numpy as np

    image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = image.shape
    binary = cv2.adaptiveThreshold(
        image, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 15
    )
    horizontal = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(30, width // 25), 1)),
    )
    vertical = cv2.morphologyEx(
        binary,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(30, height // 35))),
    )
    contours, _ = cv2.findContours(
        cv2.bitwise_or(horizontal, vertical), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    def positions(values):
        groups = []
        for value in values:
            if not groups or value - groups[-1][-1] > 3:
                groups.append([])
            groups[-1].append(value)
        return [int(np.mean(group)) for group in groups]

    tables = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w < width * 0.15 or h < 50:
            continue
        xs = [
            x + v
            for v in positions(
                np.where(np.sum(vertical[y : y + h, x : x + w] > 0, axis=0) > h * 0.6)[
                    0
                ]
            )
        ]
        ys = [
            y + v
            for v in positions(
                np.where(
                    np.sum(horizontal[y : y + h, x : x + w] > 0, axis=1) > w * 0.6
                )[0]
            )
        ]
        if not 3 <= len(xs) <= 41 or not 3 <= len(ys) <= 201:
            continue
        cells = []
        for top, bottom in zip(ys, ys[1:]):
            row = []
            for left, right in zip(xs, xs[1:]):
                inside = [
                    word
                    for word in words
                    if left < float(word["left"]) + float(word["width"]) / 2 < right
                    and top < float(word["top"]) + float(word["height"]) / 2 < bottom
                ]
                inside.sort(
                    key=lambda word: (
                        round(word["top"] / 8),
                        word["left"],
                    )
                )
                row.append(
                    " ".join(word["text"] for word in inside).replace("|", "\\|")
                )
            cells.append(row)
        if sum(bool(cell) for row in cells for cell in row) < len(cells):
            continue
        markdown = "\n".join(
            [
                "|" + "|".join(cells[0]) + "|",
                "|" + "|".join(["---"] * len(cells[0])) + "|",
                *["|" + "|".join(row) + "|" for row in cells[1:]],
            ]
        )
        tables.append(
            {
                "bbox": [
                    x / width * page_size[0],
                    y / height * page_size[1],
                    (x + w) / width * page_size[0],
                    (y + h) / height * page_size[1],
                ],
                "text": markdown,
                "class": "table",
            }
        )
    return tables


def merge_scanned_tables(chunk: dict, tables: list[dict]) -> None:
    if not tables:
        return
    text = chunk["text"]
    entries = []
    for box in chunk["page_boxes"]:
        left, top, right, bottom = box["bbox"]
        cx, cy = (left + right) / 2, (top + bottom) / 2
        if any(
            table["bbox"][0] <= cx <= table["bbox"][2]
            and table["bbox"][1] <= cy <= table["bbox"][3]
            for table in tables
        ):
            continue
        start, stop = box["pos"]
        entries.append({**box, "text": text[start:stop]})
    from functools import cmp_to_key

    def reading_order(a, b):
        left, top, right, bottom = a["bbox"]
        other_left, other_top, other_right, other_bottom = b["bbox"]
        overlap = min(bottom, other_bottom) - max(top, other_top)
        if overlap > min(bottom - top, other_bottom - other_top) * 0.5 and (
            right <= other_left or other_right <= left
        ):
            return -1 if left < other_left else 1
        return -1 if (top, left) < (other_top, other_left) else 1

    entries.extend(tables)
    entries.sort(key=cmp_to_key(reading_order))
    output = ""
    boxes = []
    for index, box in enumerate(entries):
        start = len(output)
        output += box["text"].strip() + "\n\n"
        boxes.append(
            {
                "index": index,
                "class": box["class"],
                "bbox": box["bbox"],
                "pos": [start, len(output)],
            }
        )
    chunk.update(text=output, page_boxes=boxes)


def extract(
    source: str,
    *,
    images: str = "",
    max_pages: int = 0,
    profile: str = "layout",
    on_progress: Callable[[dict], None] | None = None,
) -> dict:
    import pymupdf
    import pymupdf4llm
    import numpy as np
    import cv2
    from backend.services.ocr_models import create_engine

    if profile == "chat":
        # pymupdf4llm activates layout inference globally even for page.get_text.
        # Chat runs in its own process, so disable it before the native scan.
        pymupdf4llm.use_layout(False)
    started = time.monotonic()
    with pymupdf.open(source) as document:
        total = len(document)
        count = min(total, max_pages) if max_pages else total
        if count > 300:
            raise ValueError("PDF exceeds the 300-page interactive reading limit")
        native, scanned = [], []
        progress = on_progress or (lambda _: None)
        progress({"status": "parsing", "pages_done": 0, "total_pages": count})
        for number in range(count):
            page = document[number]
            text = page.get_text().strip()
            # Full-page raster content with no usable text requires OCR. Sparse
            # born-digital title/figure pages are not automatically scans.
            image_area = (
                sum(
                    (pymupdf.Rect(item["bbox"]) & page.rect).get_area()
                    for item in page.get_image_info()
                )
                if len(text) < 80
                else 0
            )
            bad_text = text.count("\ufffd") > max(3, len(text) * 0.05)
            needs_ocr = bad_text or (
                len(text) < 80 and image_area > page.rect.get_area() * 0.5
            )
            (scanned if needs_ocr else native).append(number)
        engine = create_engine() if scanned else None
        tables_by_page, confidences, timings = {}, [], []
        font = pymupdf.Font("cjk") if scanned else None

        def ocr_page(page, **kwargs):
            stage = time.monotonic()
            pixmap = page.get_pixmap(dpi=180, alpha=False, colorspace=pymupdf.csRGB)
            image = cv2.cvtColor(
                np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                    pixmap.height, pixmap.width, 3
                ),
                cv2.COLOR_RGB2BGR,
            )
            result = engine(image, use_cls=False)
            inference_seconds = time.monotonic() - stage
            if not result.txts:
                raise ValueError(f"No OCR text recognized on page {page.number + 1}")
            words = []
            for box, text, score in zip(result.boxes, result.txts, result.scores):
                text = re.sub(r"(?<=\d)．(?=\d)", ".", text)
                left, top = np.min(box, axis=0)
                right, bottom = np.max(box, axis=0)
                words.append(
                    {
                        "left": float(left),
                        "top": float(top),
                        "width": float(right - left),
                        "height": float(bottom - top),
                        "text": text,
                    }
                )
                confidences.append(float(score))
            tables_by_page[page.number + 1] = scanned_tables(
                image, words, (page.rect.width, page.rect.height)
            )
            # Remove only the unusable old text, preserving all original pixels.
            for block in page.get_text("blocks"):
                if block[6] == 0:
                    page.add_redact_annot(block[:4])
            page.apply_redactions(images=0, graphics=0, text=0)
            page.insert_font(fontname="ocrfont", fontbuffer=font.buffer)
            scale = pymupdf.Rect(pixmap.irect).torect(page.rect)
            for word in words:
                rect = (
                    pymupdf.Rect(
                        word["left"],
                        word["top"],
                        word["left"] + word["width"],
                        word["top"] + word["height"],
                    )
                    * scale
                )
                size = rect.height
                length = font.text_length(word["text"], fontsize=size)
                if not length:
                    continue
                page.insert_text(
                    rect.bl + (0, -0.2 * size),
                    word["text"],
                    fontsize=size,
                    fontname="ocrfont",
                    render_mode=0,
                    morph=(rect.bl, pymupdf.Matrix(rect.width / length, 1)),
                )
            timings.append(
                {
                    "page": page.number + 1,
                    "ocr_seconds": round(inference_seconds, 3),
                    "total_ocr_stage_seconds": round(time.monotonic() - stage, 3),
                    "lines": len(words),
                }
            )

        options = dict(
            write_images=bool(images),
            image_path=images,
            image_format="png",
            dpi=120,
            page_chunks=True,
            show_progress=False,
            header=True,
            footer=True,
        )
        chunks = []
        dense_pages = []
        if native and profile == "chat":
            from backend.services.pdf_native import extract_native_page

            for number in native:
                chunk, dense = extract_native_page(document[number], images=images)
                chunks.append(chunk)
                if dense:
                    dense_pages.append(number + 1)
                progress(
                    {
                        "status": "parsing",
                        "pages_done": len(chunks),
                        "total_pages": count,
                    }
                )
        elif native:
            chunks.extend(
                pymupdf4llm.to_markdown(
                    document, pages=native, use_ocr=False, **options
                )
            )
        if scanned and profile == "chat":
            pymupdf4llm.use_layout(True)
        for number in scanned:
            progress(
                {
                    "status": "parsing",
                    "phase": "ocr",
                    "pages_done": len(chunks),
                    "total_pages": count,
                }
            )
            chunks.extend(
                pymupdf4llm.to_markdown(
                    document,
                    pages=[number],
                    use_ocr=True,
                    force_ocr=True,
                    ocr_function=ocr_page,
                    **options,
                )
            )
            progress(
                {
                    "status": "parsing",
                    "phase": "ocr",
                    "pages_done": len(chunks),
                    "total_pages": count,
                }
            )
        for chunk in chunks:
            chunk["metadata"]["page"] = chunk["metadata"].get(
                "page_number", chunk["metadata"].get("page")
            )
            merge_scanned_tables(
                chunk, tables_by_page.get(chunk["metadata"]["page"], [])
            )
        chunks.sort(key=lambda chunk: int(chunk.get("metadata", {}).get("page", 0)))
        missing = [
            int(chunk.get("metadata", {}).get("page", 0))
            for chunk in chunks
            if not str(chunk.get("text") or "").strip()
        ]
        return {
            "chunks": chunks,
            "quality": {
                "engine": (
                    "pymupdf-native-chat" if profile == "chat" else "pymupdf-layout-cpu"
                ),
                "dense_graphics_pages": dense_pages,
                "extraction_notes": (
                    "Native text and ruled tables; figures preserved as original page previews. "
                    "Complex plot geometry and unruled table structure are not inferred."
                    if profile == "chat"
                    else "Layout extraction with selective OCR."
                ),
                "version": pymupdf4llm.__version__,
                "total_pages": total,
                "parsed_pages": count,
                "ocr_pages": [p + 1 for p in scanned],
                "ocr_engine": "PP-OCRv6-small/ONNX CPU" if scanned else None,
                "ocr_mean_confidence": (
                    sum(confidences) / len(confidences) if confidences else None
                ),
                "ocr_timings": timings,
                "ocr_providers": (
                    sorted(
                        set(
                            engine.text_det.session.session.get_providers()
                            + engine.text_rec.session.session.get_providers()
                        )
                    )
                    if engine
                    else []
                ),
                "empty_pages": missing,
                "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
                "elapsed_ms": round((time.monotonic() - started) * 1000),
            },
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("output")
    parser.add_argument("--images", default="")
    parser.add_argument("--max-pages", type=int, default=0)
    parser.add_argument("--profile", choices=["layout", "chat"], default="layout")
    args = parser.parse_args()
    # Set before any library import: parsing never receives a GPU assignment.
    os.environ["CUDA_VISIBLE_DEVICES"] = ""

    def progress(event):
        print("PDF_PROGRESS " + json.dumps(event), flush=True)

    result = extract(
        args.source,
        images=args.images,
        max_pages=args.max_pages,
        profile=args.profile,
        on_progress=progress,
    )
    Path(args.output).write_text(
        json.dumps(result, ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
