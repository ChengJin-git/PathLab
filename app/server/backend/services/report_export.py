"""Editable Word and self-contained LaTeX source exports; no shell compilation."""

from __future__ import annotations

import io
import json
import re
import zipfile
from copy import deepcopy
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from markdown_it import MarkdownIt

ASSETS = Path(__file__).with_name("report_templates")
PARSER = MarkdownIt("commonmark").enable("table")


def blocks(content):
    """Tokenize block content; raw HTML/TeX and remote images stay inert."""
    tokens = PARSER.parse(content)
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.type == "table_open":
            rows, row = [], []
            i += 1
            while tokens[i].type != "table_close":
                t = tokens[i]
                if t.type == "tr_open":
                    row = []
                elif t.type == "inline":
                    row.append(t.content)
                elif t.type == "tr_close":
                    rows.append(row)
                i += 1
            yield "table", rows
        elif token.type == "heading_open":
            yield "heading", (int(token.tag[1:]), tokens[i + 1].content)
            i += 2
        elif token.type == "inline":
            children = token.children or []
            if len(children) == 1 and children[0].type == "image":
                yield "image", children[0].attrGet("src")
            else:
                yield "paragraph", token.content
        elif token.type in {"fence", "code_block"}:
            yield "code", token.content
        i += 1


def word_inline(paragraph, text):
    bold = italic = False
    for token in PARSER.parseInline(text)[0].children or []:
        if token.type in {"strong_open", "strong_close"}:
            bold = token.type == "strong_open"
        elif token.type in {"em_open", "em_close"}:
            italic = token.type == "em_open"
        elif token.type in {"softbreak", "hardbreak"}:
            paragraph.add_run().add_break()
        elif token.type in {"text", "code_inline", "image", "html_inline"}:
            run = paragraph.add_run(token.content)
            run.bold, run.italic = bold, italic
            if token.type == "code_inline":
                run.font.name = "Courier New"


def word(report: dict) -> bytes:
    from .manuscript_language import document_language
    language = document_language(report)
    chinese = language.startswith('zh')
    conference = report["template"] == "conference"
    doc = Document(ASSETS / "miccai.docx") if conference else Document()
    if conference:
        # Keep official page geometry, styles, and anonymized author block.
        author, affiliation = [deepcopy(p._p) for p in doc.paragraphs[1:3]]
        body = doc._element.body
        for child in list(body):
            if child.tag != qn("w:sectPr"):
                body.remove(child)
        # The official sample contains a chart linked to a publisher's local XLSX.
        # Discard example-only drawing relationships when replacing its body.
        referenced = {
            value
            for node in doc._element.iter()
            for key, value in node.attrib.items()
            if key in {qn("r:id"), qn("r:embed"), qn("r:link")}
        }
        for rel_id, rel in list(doc.part.rels.items()):
            if rel_id not in referenced and rel.reltype.rsplit("/", 1)[-1] in {
                "chart",
                "image",
                "oleObject",
                "package",
                "hyperlink",
            }:
                doc.part.drop_rel(rel_id)
        p = doc.add_paragraph(report["title"], style="papertitle")
        p._p.addnext(author)
        author.addnext(affiliation)
    else:
        section = doc.sections[0]
        section.page_width, section.page_height = Inches(8.27), Inches(11.69)
        section.top_margin = section.bottom_margin = Inches(1)
        section.left_margin = section.right_margin = Inches(1)
        normal = doc.styles["Normal"]
        normal.font.name, normal.font.size = "Times New Roman", Pt(12)
        normal.paragraph_format.line_spacing = 2
        for name in ["Title", "Heading 1", "Heading 2", "Heading 3"]:
            style = doc.styles[name]
            style.font.name, style.font.size, style.font.color.rgb = (
                "Times New Roman",
                Pt(12),
                RGBColor(0, 0, 0),
            )
            style.font.bold = True
            fonts = style._element.rPr.rFonts
            for key in ["asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"]:
                fonts.attrib.pop(qn("w:" + key), None)
            if style._element.pPr is not None:
                borders = style._element.pPr.find(qn("w:pBdr"))
                if borders is not None:
                    style._element.pPr.remove(borders)
        numbering = OxmlElement("w:lnNumType")
        numbering.set(qn("w:countBy"), "1")
        numbering.set(qn("w:restart"), "continuous")
        section._sectPr.insert_element_before(
            numbering, "w:pgNumType", "w:cols", "w:formProt", "w:vAlign", "w:docGrid"
        )
        doc.add_heading(report["title"], 0)
        doc.add_paragraph("[Authors and affiliations]")
        footer = section.footer.paragraphs[0]
        field = OxmlElement("w:fldSimple")
        field.set(qn("w:instr"), "PAGE")
        footer._p.append(field)
    doc.core_properties.title = report["title"]
    zoom = doc.settings.element.find(qn("w:zoom"))
    if zoom is not None and zoom.get(qn("w:percent")) is None:
        zoom.set(qn("w:percent"), "100")
    doc.core_properties.author = "" if conference else "PathLab"
    if report.get("status") == "draft":
        doc.add_paragraph('草稿 — 稿件尚未完成' if chinese else 'DRAFT — manuscript incomplete')
    abstract = False
    for kind, value in blocks(report["content"]):
        if kind == "heading":
            level, text = value
            abstract = text.lower() in {"abstract", "摘要"}
            if abstract:
                continue
            doc.add_paragraph(
                text,
                style=("heading1" if level <= 2 else "heading2")
                if conference
                else f"Heading {min(max(level - 1, 1), 3)}",
            )
        elif kind == "image":
            from .report_figures import figure_path

            filename = str(value).removeprefix("figures/")
            if filename in {f["filename"] for f in report.get("figures", [])}:
                figure = next(f for f in report["figures"] if f["filename"] == filename)
                doc.add_picture(
                    str(figure_path(report["report_id"], filename)),
                    width=min(
                        Inches(figure.get("width_mm", 90) / 25.4),
                        doc.sections[0].page_width
                        - doc.sections[0].left_margin
                        - doc.sections[0].right_margin,
                    ),
                )
        elif kind == "table":
            width = int(
                doc.sections[0].page_width
                - doc.sections[0].left_margin
                - doc.sections[0].right_margin
            )
            cols = max(len(row) for row in value)
            table = doc.add_table(rows=0, cols=cols)
            table.autofit = False
            for column in table.columns:
                column.width = int(width / cols)
            for index, row in enumerate(value):
                cells = table.add_row().cells
                for col, text in enumerate(row):
                    cells[col].width = int(width / cols)
                    word_inline(cells[col].paragraphs[0], text)
                if index == 0:
                    table.rows[0]._tr.get_or_add_trPr().append(
                        OxmlElement("w:tblHeader")
                    )
                    for cell in cells:
                        for run in cell.paragraphs[0].runs:
                            run.bold = True
        else:
            p = doc.add_paragraph(
                style=("abstract" if abstract else "p1a") if conference else "Normal"
            )
            if kind == "code":
                p.add_run(value.rstrip()).font.name = "Courier New"
            else:
                word_inline(p, (("摘要。" if chinese else "Abstract. ") if abstract and conference else "") + value)
            if abstract and not conference:
                for run in p.runs:
                    run.bold = True
    if conference:
        # Mandatory keyword block, adjacent to abstract rather than in end matter.
        abstract_p = next(
            (p for p in doc.paragraphs if p.style.style_id == "abstract"), None
        )
        keywords = doc.add_paragraph(
            ('關鍵詞：計算病理學' if language == 'zh-HK' else '关键词：计算病理学') if chinese else 'Keywords: Computational pathology', style="keywords"
        )
        if abstract_p is not None:
            abstract_p._p.addnext(keywords._p)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def tex_escape(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "$": r"\$",
        "&": r"\&",
        "#": r"\#",
        "%": r"\%",
        "_": r"\_",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(c, c) for c in text)


def tex_inline(text: str) -> str:
    output = []
    for token in PARSER.parseInline(text)[0].children or []:
        if token.type in {"strong_open", "em_open"}:
            output.append(r"\textbf{" if token.type == "strong_open" else r"\emph{")
        elif token.type in {"strong_close", "em_close"}:
            output.append("}")
        elif token.type in {"softbreak", "hardbreak"}:
            output.append("\n")
        elif token.type in {"text", "code_inline", "image", "html_inline"}:
            output.append(tex_escape(token.content))
    return "".join(output)


def latex(report: dict) -> bytes:
    from .manuscript_language import document_language
    language = document_language(report)
    chinese = language.startswith('zh')
    keywords = '計算病理學' if language == 'zh-HK' else '计算病理学' if chinese else 'Computational pathology'
    conference = report["template"] == "conference"
    cjk = bool(re.search(r"[\u3400-\u9fff]", report["title"] + report["content"]))
    preamble = [
        r"\documentclass[runningheads]{llncs}"
        if conference
        else r"\documentclass[12pt,a4paper]{article}",
        r"\usepackage{fontspec}",
        r"\usepackage{longtable,array,graphicx}",
    ]
    if cjk:
        preamble += [r"\usepackage{xeCJK}", r"\setCJKmainfont{FandolSong-Regular.otf}"]
    if chinese:
        preamble += [r'\renewcommand{\abstractname}{摘要}']
        if conference:
            preamble += [r'\renewcommand{\keywordname}{' + ('關鍵詞' if language == 'zh-HK' else '关键词') + '}']
    if not conference:
        preamble += [
            r"\setmainfont{TeX Gyre Termes}",
            r"\usepackage[margin=1in]{geometry}",
            r"\usepackage{setspace,lineno}",
            r"\doublespacing",
            r"\linenumbers",
        ]
    preamble += [r"\begin{document}", r"\title{" + tex_escape(report["title"]) + "}"]
    if conference:
        preamble += [
            r"\author{Anonymized Authors}",
            r"\authorrunning{Anonymized Author et al.}",
            r"\institute{Anonymized Affiliations \\ \email{email@anonymized.com}}",
        ]
    else:
        preamble += [r"\author{[Authors and affiliations]}", r"\date{}"]
    lines = preamble + [r"\maketitle"]
    if report.get("status") == "draft":
        lines.append(r'\noindent\textbf{' + ('草稿 — 稿件尚未完成' if chinese else 'DRAFT --- manuscript incomplete') + r'}\par')
    abstract = False
    for kind, value in blocks(report["content"]):
        if kind == "heading":
            if abstract:
                if conference:
                    lines.append(r'\keywords{' + keywords + '}')
                lines.append(r"\end{abstract}")
            level, text = value
            abstract = text.lower() in {"abstract", "摘要"}
            lines.append(
                r"\begin{abstract}"
                if abstract
                else "\\"
                + ("section" if level <= 2 else "subsection")
                + "{"
                + tex_escape(text)
                + "}"
            )
        elif kind == "image":
            filename = str(value).removeprefix("figures/")
            if filename in {f["filename"] for f in report.get("figures", [])}:
                figure = next(f for f in report["figures"] if f["filename"] == filename)
                lines.append(
                    r"\begin{center}\includegraphics[width="
                    + ("90mm" if figure.get("width_mm") == 90 else r"\linewidth")
                    + r"]{figures/"
                    + filename
                    + r"}\end{center}"
                )
        elif kind == "table":
            cols = max(len(row) for row in value)
            spec = "|".join(
                [
                    f"p{{\\dimexpr\\linewidth/{cols}-2\\tabcolsep-2\\arrayrulewidth\\relax}}"
                ]
                * cols
            )
            lines.append(r"\begin{longtable}{" + spec + "}")
            for row in value:
                lines.append(
                    " & ".join(tex_inline(cell) for cell in row) + r" \\ \hline"
                )
            lines.append(r"\end{longtable}")
        else:
            # Always escape input, including code fences: never allow raw TeX execution.
            lines.append(tex_escape(value) if kind == "code" else tex_inline(value))
            lines.append("")
    if abstract:
        if conference:
            lines.append(r'\keywords{' + keywords + '}')
        lines.append(r"\end{abstract}")
    lines.append(r"\end{document}")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        from .citations import bibtex

        z.writestr("references.bib", bibtex(report.get("references", [])))
        z.writestr(
            "references.json",
            json.dumps(report.get("references", []), ensure_ascii=False, indent=2),
        )
        from .report_figures import figure_path

        for figure in report.get("figures", []):
            for extension in ["png", "svg", "pdf", "json"]:
                name = figure["filename"].removesuffix(".png") + "." + extension
                path = figure_path(report["report_id"], name)
                if path.is_file():
                    z.write(path, "figures/" + name)
        if report.get("figures"):
            for font in (ASSETS / "fonts").iterdir():
                z.write(font, "fonts/" + font.name)
        z.writestr("main.tex", "\n".join(lines))
        z.writestr("report.md", f"# {report['title']}\n\n{report['content']}")
        z.writestr(
            "evidence.json",
            json.dumps(report["evidence"], ensure_ascii=False, indent=2),
        )
        z.writestr(
            "README.txt",
            "Edit main.tex in Overleaf or compile with: xelatex -no-shell-escape main.tex\nRun twice for references. Use TeX Live with fontspec, longtable and xeCJK (for Chinese).\n"
            "Conference template: compact manuscript with anonymized authors. Journal template: extended article structure with methods and declarations.\n"
            "Evidence is an internal provenance snapshot, not submission supplementary material. Fill author-provided fields and verify venue page limits before submission.\n",
        )
        if conference:
            for name in ["llncs.cls", "splncs04.bst", "readme.txt", "history.txt"]:
                z.write(ASSETS / name, name)
    return out.getvalue()
