"""Jinja2-based LaTeX template renderer."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from gateway.paper_generation.schemas import PaperConfig
from gateway.paper_generation.storage import PaperRunPaths

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
    context = {
        "paper_id": config.paper_id,
        "title": latex_escape(raw_title),
        "short_title": latex_escape(_short_title(raw_title)),
        "template": template,
        "style": template.style,
        "sections": section_order,
        "include_bibliography": _include_bibliography(paths),
    }
    rendered = _template_env(template).get_template(template.main_template.name).render(**context)
    write_text(final_dir / "main.tex", rendered)
    return final_dir
