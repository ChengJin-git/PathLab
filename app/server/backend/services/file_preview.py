"""Bounded, on-demand file previews. No parsers run during directory search."""

from __future__ import annotations

import csv
import io
from itertools import islice
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile
from .document_preview import PAGE_SUFFIXES, preview_document

TEXT_LIMIT = 1024 * 1024
MEDIA_LIMIT = 32 * 1024 * 1024
ROW_LIMIT = 200
COLUMN_LIMIT = 40
XML_LIMIT = 16 * 1024 * 1024
TEXT_SUFFIXES = {
    ".txt",
    ".log",
    ".md",
    ".markdown",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".py",
    ".r",
    ".sh",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".css",
    ".html",
    ".htm",
    ".xml",
    ".svg",
    ".tex",
    ".sql",
    ".csv",
    ".tsv",
}
IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
}
AUDIO_TYPES = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg", ".m4a": "audio/mp4"}
VIDEO_TYPES = {".mp4": "video/mp4", ".webm": "video/webm", ".ogv": "video/ogg"}
MEDIA_TYPES = {**IMAGE_TYPES, **AUDIO_TYPES, **VIDEO_TYPES, ".pdf": "application/pdf"}


def xml_member(archive: zipfile.ZipFile, name: str):
    entry = archive.getinfo(name)
    if entry.file_size > XML_LIMIT:
        raise ValueError("previewTooLarge")
    return archive.open(entry)


def xlsx_preview(path: Path, sheet: str):
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        with xml_member(archive, "xl/workbook.xml") as stream:
            workbook = ET.parse(stream)
        sheets = workbook.findall("s:sheets/s:sheet", ns)[:20]
        names = [entry.get("name", "") for entry in sheets]
        selected = names.index(sheet) if sheet in names else 0
        if not sheets:
            return {
                "kind": "table",
                "rows": [],
                "sheets": [],
                "sheet": "",
                "truncated": False,
            }
        with xml_member(archive, "xl/_rels/workbook.xml.rels") as stream:
            relationships = {
                entry.get("Id"): entry.get("Target", "")
                for entry in ET.parse(stream).getroot()
            }
        target = relationships.get(
            sheets[selected].get(
                "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
            ),
            "",
        )
        member = target.lstrip("/") if target.startswith("/") else "xl/" + target
        if ".." in Path(member).parts:
            raise ValueError("previewUnavailable")
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            with xml_member(archive, "xl/sharedStrings.xml") as stream:
                for _, element in ET.iterparse(stream, events=("end",)):
                    if element.tag.endswith("}si"):
                        shared.append("".join(element.itertext())[:2000])
                        element.clear()
                        if len(shared) >= 50000:
                            break
        rows, clipped, budget = [], False, TEXT_LIMIT
        with xml_member(archive, member) as stream:
            for _, element in ET.iterparse(stream, events=("end",)):
                if not element.tag.endswith("}row"):
                    continue
                if len(rows) == ROW_LIMIT:
                    clipped = True
                    break
                cells = [""] * COLUMN_LIMIT
                last = 0
                for cell in element.findall("s:c", ns):
                    column = 0
                    for char in cell.get("r", "A"):
                        if not char.isalpha():
                            break
                        column = column * 26 + ord(char.upper()) - 64
                    if not 1 <= column <= COLUMN_LIMIT:
                        clipped = True
                        continue
                    raw = cell.findtext("s:v", "", ns)
                    if cell.get("t") == "s":
                        value = (
                            shared[int(raw)]
                            if raw.isdigit() and int(raw) < len(shared)
                            else ""
                        )
                    elif cell.get("t") == "inlineStr":
                        value = (
                            "".join(cell.find("s:is", ns).itertext())
                            if cell.find("s:is", ns) is not None
                            else ""
                        )
                    else:
                        value = raw or (
                            "=" + cell.findtext("s:f", "", ns)
                            if cell.find("s:f", ns) is not None
                            else ""
                        )
                    cells[column - 1] = value[: min(2000, max(0, budget))]
                    budget -= len(cells[column - 1])
                    last = max(last, column)
                rows.append(cells[:last])
                element.clear()
                if budget <= 0:
                    clipped = True
                    break
        return {
            "kind": "table",
            "rows": rows,
            "sheets": names,
            "sheet": names[selected],
            "truncated": clipped,
        }


def preview(path: Path, display_name: str, sheet: str = "") -> dict:
    stat = path.stat()
    suffix = Path(display_name).suffix.lower()
    base = {
        "name": display_name,
        "size": stat.st_size,
        "revision": f"{stat.st_mtime_ns}:{stat.st_size}",
        "truncated": False,
    }
    if suffix in PAGE_SUFFIXES:
        try:
            return {**base, **preview_document(path, display_name)}
        except (ValueError, OSError) as exc:
            code = str(exc)
            return {**base, "kind": "unsupported", "reason": code if code in {
                "previewTooLarge", "previewTimeout", "previewRendererUnavailable", "previewBusy",
            } else "previewUnavailable"}
    if suffix in IMAGE_TYPES or suffix in AUDIO_TYPES or suffix in VIDEO_TYPES:
        return {
            **base,
            "kind": ("image" if suffix in IMAGE_TYPES else "audio" if suffix in AUDIO_TYPES else "video")
            if stat.st_size <= MEDIA_LIMIT
            else "unsupported",
            "reason": "previewTooLarge" if stat.st_size > MEDIA_LIMIT else None,
        }
    if suffix in {".xlsx", ".xlsm"}:
        if stat.st_size > MEDIA_LIMIT:
            return {**base, "kind": "unsupported", "reason": "previewTooLarge"}
        try:
            return {
                **base,
                **xlsx_preview(path, sheet),
            }
        except (ValueError, KeyError, zipfile.BadZipFile, ET.ParseError, OSError):
            return {**base, "kind": "unsupported", "reason": "previewUnavailable"}
    if suffix not in TEXT_SUFFIXES:
        return {**base, "kind": "unsupported", "reason": "unsupportedPreview"}
    with path.open("rb") as stream:
        data = stream.read(TEXT_LIMIT + 1)
    content = data[:TEXT_LIMIT].decode("utf-8-sig", errors="replace")
    truncated = len(data) > TEXT_LIMIT
    if suffix in {".csv", ".tsv"}:
        csv.field_size_limit(TEXT_LIMIT)
        try:
            # Do not show a cut-off quoted record as a complete row.
            table_content = content.rsplit("\n", 1)[0] if truncated else content
            rows = list(
                islice(
                    csv.reader(
                        io.StringIO(table_content),
                        delimiter="\t" if suffix == ".tsv" else ",",
                    ),
                    ROW_LIMIT + 1,
                )
            )
            return {
                **base,
                "kind": "table",
                "rows": [
                    [cell[:2000] for cell in row[:COLUMN_LIMIT]]
                    for row in rows[:ROW_LIMIT]
                ],
                "sheets": [],
                "sheet": "",
                "truncated": truncated
                or len(rows) > ROW_LIMIT
                or any(
                    len(row) > COLUMN_LIMIT or any(len(cell) > 2000 for cell in row)
                    for row in rows
                ),
            }
        except csv.Error:
            pass
    kind = (
        "markdown"
        if suffix in {".md", ".markdown"}
        else "html"
        if suffix in {".html", ".htm"}
        else "text"
        if suffix in {".txt", ".log"}
        else "code"
    )
    return {**base, "kind": kind, "content": content, "truncated": truncated}
