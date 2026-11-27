"""Isolated CPU document parsing with bounded sections and preserved page locations."""

import json
import re
import sys
import zipfile
from pathlib import Path
from .file_preview import TEXT_SUFFIXES, xml_member


def parse(path):
    suffix = path.suffix.lower()
    sections = []
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("Document exceeds 64 MiB")
    if suffix == ".pdf":
        from .pdf_cpu import extract

        result = extract(str(path))
        sections = [
            {"text": page["text"], "page": int(page["metadata"]["page"]), "section": ""}
            for page in result["chunks"]
        ]
    elif suffix in TEXT_SUFFIXES:
        value = path.read_text(encoding="utf-8-sig")
        if suffix in {".html", ".htm"}:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(value, "html.parser")
            for tag in soup(["script", "style"]):
                tag.decompose()
            value = soup.get_text("\n")
        if suffix in {".md", ".markdown"}:
            from llama_index.core.node_parser import MarkdownNodeParser
            from llama_index.core.schema import Document

            sections = [
                {
                    "text": node.get_content(),
                    "page": 0,
                    "section": node.metadata.get("header_path", "").strip("/")
                    or "Document",
                }
                for node in MarkdownNodeParser.from_defaults().get_nodes_from_documents(
                    [Document(text=value)]
                )
            ]
        else:
            sections = [{"text": value, "page": 0, "section": "Document"}]
    elif suffix in {".docx", ".pptx"}:
        import xml.etree.ElementTree as ET

        with zipfile.ZipFile(path) as archive:
            names = (
                ["word/document.xml"]
                if suffix == ".docx"
                else sorted(
                    [
                        n
                        for n in archive.namelist()
                        if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)
                    ],
                    key=lambda n: int(re.search(r"(\d+)\.xml", n)[1]),
                )
            )
            if len(names) > 300:
                raise ValueError("Presentation exceeds 300 slides")
            for index, name in enumerate(names):
                with xml_member(archive, name) as stream:
                    root = ET.parse(stream).getroot()
                value = "\n".join(
                    node.text or "" for node in root.iter() if node.tag.endswith("}t")
                )
                sections.append(
                    {
                        "text": value,
                        "page": index + 1 if suffix == ".pptx" else 0,
                        "section": f"Slide {index + 1}"
                        if suffix == ".pptx"
                        else "Document",
                    }
                )
    elif suffix == ".xlsx":
        import openpyxl

        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            for sheet in workbook.worksheets[:30]:
                rows = []
                for index, row in enumerate(sheet.iter_rows(values_only=True)):
                    if index >= 20000:
                        raise ValueError("Worksheet exceeds 20000 rows")
                    rows.append(
                        f"Row {index + 1}: "
                        + " | ".join(
                            str(cell) if cell is not None else "" for cell in row[:100]
                        )
                    )
                sections.append(
                    {"text": "\n".join(rows), "page": 0, "section": sheet.title}
                )
        finally:
            workbook.close()
    else:
        raise ValueError(
            "Knowledge indexing supports PDF, text/code, DOCX, PPTX and XLSX files"
        )
    if sum(len(item["text"]) for item in sections) > 4_000_000:
        raise ValueError("Extracted text exceeds 4 million characters")
    return sections


if __name__ == "__main__":
    try:
        Path(sys.argv[2]).write_text(
            json.dumps(parse(Path(sys.argv[1])), ensure_ascii=False)
        )
    except Exception as exc:
        print(str(exc)[:600], file=sys.stderr)
        raise SystemExit(1)
