"""Dependency-closed LaTeX bundle exporter."""

from __future__ import annotations

import zipfile
from pathlib import Path

from gateway.paper_generation.schemas import PaperConfig

from ..templates import get_template

_PRIVATE_NAME_FRAGMENTS = (
    "evidence_lock.private",
    "identifier_mapping",
    "phi_mapping",
    "source_mapping",
    "source_mappings",
    "source_tasks.json",
    "source_analyses.json",
    "raw_prompt",
    "raw_response",
)
_PUBLIC_ROOT_FILES = {
    "main.tex",
    "main.pdf",
    "main.compile_summary.txt",
    "refs.bib",
    "style.json",
}
_PUBLIC_SUBDIR_PREFIXES = (
    "figures/",
    "locked_blocks/",
    "sections/",
    "tables/",
)


def _is_private_arcname(arcname: str) -> bool:
    normalized = arcname.lower()
    return any(fragment in normalized for fragment in _PRIVATE_NAME_FRAGMENTS)


def _is_public_arcname(arcname: str, template_asset_names: set[str]) -> bool:
    if _is_private_arcname(arcname):
        return False
    if "/" not in arcname:
        return arcname in _PUBLIC_ROOT_FILES or arcname in template_asset_names
    return any(arcname.startswith(prefix) for prefix in _PUBLIC_SUBDIR_PREFIXES)


def export_bundle(final_dir: Path, bundle_path: Path, config: PaperConfig, template_id: str) -> None:
    """Zip a rendered template without private evidence or raw LLM payloads."""
    if not final_dir.exists():
        raise FileNotFoundError(f"final directory missing for template {template_id}")
    template_asset_names = {asset.name for asset in get_template(template_id).asset_paths}
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in sorted(final_dir.rglob("*")):
            if not file_path.is_file():
                continue
            arcname = str(file_path.relative_to(final_dir))
            if not _is_public_arcname(arcname, template_asset_names):
                continue
            archive.write(file_path, arcname=arcname)
        archive.writestr(
            "README.md",
            "# PathLab Paper Agent Bundle\n\n"
            f"Paper ID: `{config.paper_id}`\n\n"
            f"Template: `{template_id}`\n\n"
            "This bundle contains paper-facing LaTeX sources, template assets, "
            "figures, tables, and compile summaries when available. Private "
            "evidence locks, source mappings, raw prompts, and raw responses are excluded.\n",
        )
