"""Functional, offline image acceptance. Run with the production sandbox flags."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from importlib.metadata import version
from pathlib import Path


def run(*command: str) -> None:
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=120, check=False
    )
    if result.returncode:
        raise RuntimeError(
            f"{command[0]} failed: {(result.stdout + result.stderr)[-3000:]}"
        )


def main() -> None:
    import matplotlib
    import torch
    from docx import Document
    from playwright.sync_api import sync_playwright
    from pptx import Presentation
    from pypdf import PdfReader
    import numpy as np
    from pycocotools import mask

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # The original ML package versions must survive the environment extension.
    for line in Path("/opt/pathlab/ml-constraints.txt").read_text().splitlines():
        name, expected = line.split("==", 1)
        assert version(name) == expected, name
    assert torch.isfinite(torch.tensor([1.0, 2.0]) @ torch.tensor([2.0, 3.0]))
    pixels = np.asfortranarray(np.array([[0,1],[1,1]],dtype=np.uint8))
    assert np.array_equal(mask.decode(mask.encode(pixels)),pixels)

    with tempfile.TemporaryDirectory(prefix="pathlab-skills-") as temporary:
        root = Path(temporary)
        # apptainer test may inherit a read-only host home. Keep browser/Office
        # profiles in this disposable acceptance directory, as real sessions do.
        for key, folder in {
            "HOME": "home",
            "XDG_CONFIG_HOME": "config",
            "XDG_CACHE_HOME": "cache",
            "XDG_RUNTIME_DIR": "runtime",
        }.items():
            directory = root / folder
            directory.mkdir(mode=0o700)
            os.environ[key] = str(directory)
        document = Document()
        document.add_heading("Scientific runtime check", 0)
        document.add_paragraph("真实科研文档。Validation AUROC 0.81; n = 28.")
        document.save(root / "document.docx")
        assert "AUROC" in Document(root / "document.docx").paragraphs[1].text
        deck = Presentation()
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = "Measured results"
        slide.placeholders[1].text = "AUROC 0.81; n = 28"
        deck.save(root / "slides.pptx")
        assert len(Presentation(root / "slides.pptx").slides) == 1
        run(
            "soffice",
            f"-env:UserInstallation=file://{root}/lo",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(root),
            str(root / "document.docx"),
        )
        assert "AUROC" in PdfReader(root / "document.pdf").pages[0].extract_text()
        run(
            "soffice",
            f"-env:UserInstallation=file://{root}/lo",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(root),
            str(root / "slides.pptx"),
        )
        assert len(PdfReader(root / "slides.pdf").pages) == 1
        run(
            "pdftoppm",
            "-scale-to",
            "600",
            "-singlefile",
            "-png",
            str(root / "slides.pdf"),
            str(root / "preview"),
        )
        assert (root / "preview.png").stat().st_size > 1000

        plt.rcParams["font.family"] = "Liberation Sans"
        plt.plot([1, 2, 3], [0.61, 0.75, 0.81])
        plt.savefig(root / "python-figure.svg")
        plt.close()
        rscript = root / "figure.R"
        rscript.write_text(
            "\n".join(
                [
                    "library(ggplot2); library(patchwork); library(ComplexHeatmap)",
                    'p <- ggplot(data.frame(x=1:3,y=c(.61,.75,.81)),aes(x,y))+geom_point()+theme_classic(base_family="Liberation Sans")',
                    f'ggsave("{root}/r-figure.svg",p,device=svglite::svglite)',
                    f'pdf("{root}/heatmap.pdf"); draw(Heatmap(matrix(1:9,3))); dev.off()',
                ]
            )
        )
        run("Rscript", str(rscript))
        assert (root / "r-figure.svg").stat().st_size > 1000

        tex = root / "paper.tex"
        tex.write_text(
            r"\documentclass{article}\usepackage{fontspec}\setmainfont{Liberation Sans}\begin{document}AUROC 0.81; n = 28.\end{document}"
        )
        run(
            "xelatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            f"-output-directory={root}",
            str(tex),
        )
        assert "0.81" in PdfReader(root / "paper.pdf").pages[0].extract_text()

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            page = browser.new_page()
            page.set_content("<h1>Research ready</h1><p>浏览器验证</p>")
            assert page.locator("h1").inner_text() == "Research ready"
            page.screenshot(path=str(root / "browser.png"))
            browser.close()
        flow = root / "flow.mmd"
        flow.write_text("flowchart LR\n A[Data] --> B[Analysis] --> C[Evidence]\n")
        run("pathlab-mermaid", "-i", str(flow), "-o", str(root / "flow.svg"))
        assert "Evidence" in (root / "flow.svg").read_text()
        run("node", "-e", "require('pptxgenjs'); console.log('pptxgenjs ready')")
        run("md-to-word", "--help")
        run("image2ppt", "--help")
        run("image2ppt", "doctor", "--json")
        run("tesseract", "--list-langs")
    print(
        json.dumps(
            {
                "passed": [
                    "ML version preservation",
                    "COCO RLE roundtrip",
                    "Word/PPT create and PDF render",
                    "PDF preview",
                    "Python/R vector figures",
                    "ComplexHeatmap",
                    "XeLaTeX",
                    "Chromium browser",
                    "Mermaid",
                    "PptxGenJS",
                    "md-to-word",
                    "image2ppt",
                    "Tesseract",
                ],
                "temporary_files_removed": True,
            }
        )
    )


if __name__ == "__main__":
    main()
