import zipfile
import shutil
import pytest

from backend.services.file_preview import preview, TEXT_LIMIT


def test_csv_preview_has_row_and_column_bounds(tmp_path):
    path = tmp_path / "metrics.csv"
    path.write_text("model,auc\n" + "\n".join(f"run-{i},0.8" for i in range(1000)))
    result = preview(path, path.name)
    assert result["kind"] == "table"
    assert result["rows"][0] == ["model", "auc"]
    assert len(result["rows"]) == 200 and result["truncated"]


def test_text_preview_reads_more_than_the_llm_excerpt_but_stays_bounded(tmp_path):
    path = tmp_path / "findings.md"
    path.write_text("A" * (TEXT_LIMIT + 100))
    result = preview(path, path.name)
    assert result["kind"] == "markdown"
    assert len(result["content"]) == TEXT_LIMIT and result["truncated"]


def test_xlsx_preview_uses_sheets_and_cell_positions(tmp_path):
    path = tmp_path / "metrics.xlsx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Summary" sheetId="1" r:id="r1"/><sheet name="Validation" sheetId="2" r:id="r2"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/><Relationship Id="r2" Target="worksheets/sheet2.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/sharedStrings.xml",
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>AUC</t></si></sst>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1"><v>0.81</v></c></row></sheetData></worksheet>',
        )
        archive.writestr(
            "xl/worksheets/sheet2.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Held out</t></is></c></row></sheetData></worksheet>',
        )
    result = preview(path, path.name)
    assert result["rows"] == [["AUC", "", "0.81"]]
    assert result["sheets"] == ["Summary", "Validation"]
    assert preview(path, path.name, "Validation")["rows"] == [["Held out"]]


def test_document_preview_and_malformed_archives(tmp_path):
    if not shutil.which('soffice'):
        pytest.skip('LibreOffice is required for rendered document previews')
    from docx import Document
    path = tmp_path / "article.docx"
    document = Document()
    document.add_heading('Research findings', 0)
    document.add_paragraph('Measured results')
    document.save(path)
    result = preview(path, path.name)
    assert result['kind'] == 'document' and result['page_count'] == 1
    assert 'blocks' not in result
    path.write_bytes(b"broken")
    assert preview(path, path.name)["reason"] == "previewUnavailable"


def test_binary_files_are_not_decoded_as_text(tmp_path):
    path = tmp_path / "weights.pt"
    path.write_bytes(b"\x00\xffbinary")
    assert preview(path, path.name)["kind"] == "unsupported"


@pytest.mark.parametrize('suffix,kind', [('.svg','image'), ('.mp4','video'), ('.mp3','audio'), ('.html','html'), ('.py','code')])
def test_supported_types_choose_dedicated_viewers(tmp_path, suffix, kind):
    path = tmp_path / ('file' + suffix)
    path.write_text('Content')
    assert preview(path, path.name)['kind'] == kind
