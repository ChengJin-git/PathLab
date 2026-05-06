"""Jinja2-based LaTeX template renderer."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from pathlab_paper_agent.schemas import PaperConfig
from pathlab_paper_agent.storage import PaperRunPaths

from ..templates import TemplateDefinition, get_template
from ..stages.common import copy_tree_contents, write_json, write_text

_LATEX_REPLACEMENTS = {
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "\\": r"\textbackslash{}",
}
_LATEX_SECTION_COMMAND_RE = re.compile(r"\\(section|subsection|subsubsection)(?!\*)\{")
_ABSTRACT_HEADING_RE = re.compile(r"^\s*\\section\*?\{Abstract\}\s*", re.IGNORECASE)


def latex_escape(value: Any) -> str:
    """Escape a short string for safe insertion into LaTeX."""
    text = "" if value is None else str(value)
    return "".join(_LATEX_REPLACEMENTS.get(ch, ch) for ch in text)


def _short_title(title: str, limit: int = 64) -> str:
    return title if len(title) <= limit else title[: limit - 1].rstrip() + "..."


def _template_env(template: TemplateDefinition) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(template.directory)),
        autoescape=False,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _copy_template_assets(template: TemplateDefinition, final_dir: Path) -> None:
    for asset_path in template.asset_paths:
        if not asset_path.exists():
            raise FileNotFoundError(f"Template asset missing: {asset_path}")
        shutil.copy2(asset_path, final_dir / asset_path.name)


def _ensure_frontmatter_abstract(text: str) -> str:
    stripped = text.strip()
    if re.search(r"\\begin\{abstract\}", stripped):
        return stripped + "\n"
    body = _ABSTRACT_HEADING_RE.sub("", stripped).strip()
    return f"\\begin{{abstract}}\n{body}\n\\end{{abstract}}\n"


def _star_latex_sections(text: str) -> str:
    return _LATEX_SECTION_COMMAND_RE.sub(lambda match: f"\\{match.group(1)}*{{", text)


def _apply_template_section_rules(template: TemplateDefinition, final_dir: Path) -> None:
    constraints = template.style.get("style_constraints")
    if not isinstance(constraints, dict):
        return

    sections_dir = final_dir / "sections"
    if constraints.get("abstract_before_document"):
        abstract_path = sections_dir / "abstract.tex"
        if abstract_path.is_file():
            abstract_path.write_text(
                _ensure_frontmatter_abstract(abstract_path.read_text(encoding="utf-8")),
                encoding="utf-8",
            )

    if not constraints.get("unnumbered_sections"):
        return
    for section_path in sections_dir.glob("*.tex"):
        if section_path.name == "abstract.tex":
            continue
        section_path.write_text(
            _star_latex_sections(section_path.read_text(encoding="utf-8")),
            encoding="utf-8",
        )


def _copy_locked_blocks(paths: PaperRunPaths, template_id: str, final_dir: Path) -> None:
    template_blocks = paths.locked_blocks_dir / template_id
    destination = final_dir / "locked_blocks"
    if template_blocks.is_dir():
        copy_tree_contents(template_blocks, destination)
        return

    destination.mkdir(parents=True, exist_ok=True)
    if not paths.locked_blocks_dir.exists():
        return
    for child in paths.locked_blocks_dir.iterdir():
        if child.is_file():
            shutil.copy2(child, destination / child.name)


def _prepare_final_dir(final_dir: Path) -> None:
    if final_dir.exists():
        if not final_dir.is_dir():
            raise NotADirectoryError(f"Template final path is not a directory: {final_dir}")
        shutil.rmtree(final_dir)
    final_dir.mkdir(parents=True, exist_ok=True)


def _include_bibliography(paths: PaperRunPaths) -> bool:
    if not paths.refs_bib.exists():
        return False
    text = paths.refs_bib.read_text(encoding="utf-8").strip()
    return bool(text and not text.startswith("% Scaffold bibliography"))


def render_template(
    paths: PaperRunPaths,
    config: PaperConfig,
    template_id: str,
) -> Path:
    """Render one venue template into `final/{template_id}`.

    The renderer copies only paper-facing assets into the final directory. It
    never copies `evidence/` or any private source mappings, so export bundles
    remain dependency-closed without leaking private evidence.
    """
    template = get_template(template_id)
    final_dir = paths.final_for_template(template_id)
    _prepare_final_dir(final_dir)

    section_order = template.style.get("section_order") or []
    if not section_order:
        raise ValueError(f"Template {template_id} does not define section_order")

    copy_tree_contents(paths.sections_dir, final_dir / "sections")
    _apply_template_section_rules(template, final_dir)
    _copy_locked_blocks(paths, template_id, final_dir)
    copy_tree_contents(paths.tables_dir, final_dir / "tables")
    copy_tree_contents(paths.figures_dir, final_dir / "figures")
    if paths.refs_bib.exists():
        shutil.copy2(paths.refs_bib, final_dir / "refs.bib")
    else:
        write_text(final_dir / "refs.bib", "")
    _copy_template_assets(template, final_dir)
    write_json(final_dir / "style.json", template.style)

    raw_title = config.title or "PathLab Paper Draft"
    abstract_section = "abstract" if "abstract" in section_order else None
    context = {
        "paper_id": config.paper_id,
        "title": latex_escape(raw_title),
        "short_title": latex_escape(_short_title(raw_title)),
        "template": template,
        "style": template.style,
        "sections": section_order,
        "abstract_section": abstract_section,
        "body_sections": [section for section in section_order if section != abstract_section],
        "include_bibliography": _include_bibliography(paths),
    }
    rendered = _template_env(template).get_template(template.main_template.name).render(**context)
    write_text(final_dir / "main.tex", rendered)
    return final_dir
