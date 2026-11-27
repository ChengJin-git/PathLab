"""Real CPU extraction: born-digital columns/tables and selective scanned OCR."""

import re
import asyncio
import pymupdf
import pytest
from reportlab.pdfgen import canvas
from backend.services.articles.reader import parse_pdf


@pytest.fixture
def documents(tmp_path):
    source = tmp_path / "native.pdf"
    pdf = canvas.Canvas(str(source), pagesize=(600, 800))
    pdf.setFont("Helvetica", 12)
    for col, x in [("LEFT", 40), ("RIGHT", 320)]:
        for index in range(8):
            pdf.drawString(x, 740 - index * 18, f"{col} evidence sequence {index:02}.")
    for x in [40, 200, 360, 520]:
        pdf.line(x, 340, x, 460)
    for y in [340, 370, 400, 430, 460]:
        pdf.line(40, y, 520, y)
    for row, values in enumerate(
        [
            ["Model", "AUC", "Brier"],
            ["Linear", "0.812", "0.134"],
            ["MLP", "0.934", "0.072"],
            ["Base", "0.500", "0.250"],
        ]
    ):
        for col, value in enumerate(values):
            pdf.drawString(50 + col * 160, 440 - row * 30, value)
    pdf.save()
    with pymupdf.open(source) as native:
        scan = pymupdf.open()
        page = scan.new_page(width=600, height=800)
        page.insert_image(
            page.rect, stream=native[0].get_pixmap(dpi=220).tobytes("png")
        )
        mixed = pymupdf.open()
        mixed.insert_pdf(native)
        mixed.insert_pdf(scan)
        values = (source.read_bytes(), scan.tobytes(), mixed.tobytes())
        scan.close()
        mixed.close()
    return values


@pytest.mark.parametrize(
    "position,ocr_pages,table_count", [(0, [], 1), (1, [1], 1), (2, [2], 2)]
)
@pytest.mark.parametrize("profile", ["layout", "chat"])
async def test_actual_cpu_parser_preserves_values_columns_and_pages(
    documents, position, ocr_pages, table_count, profile
):
    progress = []
    result = await parse_pdf(
        documents[position], profile=profile, on_progress=progress.append
    )
    quality = result.structured_content["quality"]
    assert quality["cuda_visible_devices"] == ""
    assert quality["ocr_pages"] == ocr_pages
    assert quality["ocr_providers"] == (["CPUExecutionProvider"] if ocr_pages else [])
    assert not quality["empty_pages"]
    assert result.markdown.index("LEFT evidence") < result.markdown.index(
        "RIGHT evidence"
    )
    assert result.markdown.index("LEFT evidence sequence 07") < result.markdown.index(
        "RIGHT evidence sequence 00"
    )
    tables = [b for b in result.structured_content["blocks"] if b["type"] == "table"]
    assert len(tables) == table_count
    for table in tables:
        text = str(table["cells"])
        for value in ["0.812", "0.134", "0.934", "0.072", "0.500", "0.250"]:
            assert value in text
    assert [int(n) for n in re.findall(r"--- Page (\d+) ---", result.markdown)] == list(
        range(1, result.page_count + 1)
    )
    if profile == "chat":
        assert (
            progress[-1]["pages_done"]
            == progress[-1]["total_pages"]
            == result.page_count
        )
        assert quality["engine"] == "pymupdf-native-chat"


async def test_cancelling_read_terminates_real_parser_process(documents, monkeypatch):
    from backend.services.articles import reader as chat_pdf

    original = asyncio.create_subprocess_exec
    created = asyncio.Event()
    processes = []

    async def launch(*args, **kwargs):
        process = await original(*args, **kwargs)
        processes.append(process)
        created.set()
        return process

    monkeypatch.setattr(chat_pdf.asyncio, "create_subprocess_exec", launch)
    operation = asyncio.create_task(parse_pdf(documents[2]))
    await asyncio.wait_for(created.wait(), 10)
    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert processes[0].returncode is not None


def test_cpu_detector_preprocessing_is_numerically_equivalent():
    import numpy as np
    from backend.services.ocr_models import detector_tensor

    image = np.random.default_rng(42).integers(0, 256, (128, 160, 3), dtype=np.uint8)
    expected = ((image.astype(np.float32) / 255 - 0.5) / 0.5).transpose(2, 0, 1)[None]
    np.testing.assert_allclose(detector_tensor(image), expected, atol=2e-7, rtol=2e-7)


@pytest.mark.parametrize(
    "text,font",
    [
        ("病理图像分析报告。患者数量128，模型准确率0.934。", "china-s"),
        ("病理影像分析報告。病人數量128，模型準確率0.934。", "china-t"),
    ],
)
async def test_actual_chinese_scanned_pdf(text, font):
    native = pymupdf.open()
    page = native.new_page(width=680, height=200)
    page.insert_text((35, 80), text, fontname=font, fontsize=18)
    scan = pymupdf.open()
    target = scan.new_page(width=680, height=200)
    target.insert_image(target.rect, stream=page.get_pixmap(dpi=220).tobytes("png"))
    data = scan.tobytes()
    native.close()
    scan.close()
    result = await parse_pdf(data)

    def normalize(value):
        return re.sub(r"[^\w.]+", "", value)

    assert normalize(text) in normalize(result.markdown)
    assert result.structured_content["quality"]["ocr_providers"] == [
        "CPUExecutionProvider"
    ]


async def test_blank_pdf_is_not_reported_as_readable():
    document = pymupdf.open()
    document.new_page()
    data = document.tobytes()
    document.close()
    with pytest.raises(ValueError, match="no readable text"):
        await parse_pdf(data)


async def test_chat_dense_vector_page_keeps_text_and_original_preview(tmp_path):
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text(
        (50, 50), "Figure 1: observed accuracy 0.934. Original plot below."
    )
    for index in range(200):
        page.draw_line((50, 100 + index), (400, 110 + index))
    result = await parse_pdf(
        document.tobytes(),
        profile="chat",
        images_output_dir=tmp_path,
        images_url_prefix="https://example.org/images",
    )
    document.close()
    assert "0.934" in result.markdown
    assert result.structured_content["quality"]["dense_graphics_pages"] == [1]
    assert "https://example.org/images/page-0001.png" in result.markdown
    assert (tmp_path / "page-0001.png").is_file()
