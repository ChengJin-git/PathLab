"""Real document bytes retain searchable text and locations without executing content."""

import zipfile
import pytest
from backend.services.knowledge_parser import parse


def test_docx_pptx_xlsx_and_markup(tmp_path):
    from docx import Document
    from openpyxl import Workbook

    doc = Document()
    doc.add_heading("Protocol", 0)
    doc.add_paragraph("Cold ischemia limit is 38 minutes.")
    path = tmp_path / "protocol.docx"
    doc.save(path)
    assert "38 minutes" in parse(path)[0]["text"]
    slides = tmp_path / "slides.pptx"
    with zipfile.ZipFile(slides, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", '<a xmlns="a"><t>Overview</t></a>')
        archive.writestr(
            "ppt/slides/slide2.xml",
            '<a xmlns="a"><t>Validation cohort: 147 patients.</t></a>',
        )
    result = parse(slides)
    assert result[1]["page"] == 2 and "147" in result[1]["text"]
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Validation"
    sheet.append(["site", "patients"])
    sheet.append(["青竹", 147])
    path = tmp_path / "cohort.xlsx"
    workbook.save(path)
    result = parse(path)
    assert (
        result[0]["section"] == "Validation"
        and "Row 2: 青竹 | 147" in result[0]["text"]
    )
    path = tmp_path / "report.html"
    path.write_text(
        '<h1>Result</h1><p>Measured 0.873</p><script>throw new Error("never execute")</script>'
    )
    assert (
        "0.873" in parse(path)[0]["text"]
        and "never execute" not in parse(path)[0]["text"]
    )


def test_invalid_binary_and_oversized_text_are_explicit(tmp_path):
    path = tmp_path / "binary.pt"
    path.write_bytes(b"\x00\xff")
    with pytest.raises(ValueError):
        parse(path)
    path = tmp_path / "large.txt"
    path.write_text("a" * 4_000_001)
    with pytest.raises(ValueError, match="4 million"):
        parse(path)
