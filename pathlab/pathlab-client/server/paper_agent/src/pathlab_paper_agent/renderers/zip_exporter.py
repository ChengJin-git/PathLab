"""Dependency-closed LaTeX bundle exporter."""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from gateway.paper_generation.schemas import PaperConfig

from ..templates import get_template

_READY_FIGURE_STATUSES = {"ready", "generated_by_paperbanana"}
_PUBLIC_FIGURE_SUFFIXES = {".pdf", ".png"}
_PRIVATE_NAME_FRAGMENTS = (
    "evidence_lock.private",
    "identifier_mapping",
    "phi_mapping",
    "raw_collected",
    "source_mapping",
    "source_mappings",
    "source_tasks.json",
    "source_analyses.json",
    "raw_prompt",
    "raw_response",
    "intro_rw_draft",
)
_PUBLIC_ROOT_FILES = {
    "main.tex",
    "main.pdf",
    "main.compile_summary.txt",
    "refs.bib",
}
_PUBLIC_SUBDIR_PREFIXES = (
    "figures/",
    "locked_blocks/",
    "sections/",
    "tables/",
)
_TEX_INPUT_RE = re.compile(r"\\(?:input|include)\s*\{([^}]+)\}")
_GRAPHICS_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\s*\{([^}]+)\}")
_BIBLIOGRAPHY_RE = re.compile(r"\\bibliography\s*\{([^}]+)\}")
_BIBLIOGRAPHY_STYLE_RE = re.compile(r"\\bibliographystyle\s*\{([^}]+)\}")


@dataclass(frozen=True)
class BundleExportResult:
    """Metadata from building a paper-facing ZIP bundle."""

    bundle_path: Path
    included_files: tuple[str, ...]
    missing_dependencies: tuple[str, ...]
    private_exclusions: tuple[str, ...]

    @property
    def dependency_closed(self) -> bool:
        return not self.missing_dependencies


def _is_private_arcname(arcname: str) -> bool:
    normalized = arcname.lower()
    return any(fragment in normalized for fragment in _PRIVATE_NAME_FRAGMENTS)


def _is_public_arcname(arcname: str, template_asset_names: set[str]) -> bool:
    if _is_private_arcname(arcname):
        return False
    if "/" not in arcname:
        return arcname in _PUBLIC_ROOT_FILES or arcname in template_asset_names
    if not any(arcname.startswith(prefix) for prefix in _PUBLIC_SUBDIR_PREFIXES):
        return False
    if arcname.startswith("figures/"):
        return Path(arcname).suffix.lower() in _PUBLIC_FIGURE_SUFFIXES
    return Path(arcname).suffix.lower() == ".tex"


def _arcname(final_dir: Path, file_path: Path) -> str:
    return file_path.relative_to(final_dir).as_posix()


def _is_hidden_path(arcname: str) -> bool:
    return any(part.startswith(".") for part in Path(arcname).parts)


def _is_safe_file(final_dir: Path, file_path: Path) -> bool:
    if file_path.is_symlink() or not file_path.is_file():
        return False
    try:
        file_path.resolve().relative_to(final_dir.resolve())
    except ValueError:
        return False
    return True


def _load_ready_figure_arcnames(final_dir: Path) -> set[str] | None:
    manifest_path = final_dir / "figures" / "manifest.json"
    if not manifest_path.is_file():
        return set()
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()

    ready: set[str] = set()
    figures = payload.get("figures") if isinstance(payload, dict) else None
    if not isinstance(figures, list):
        return ready

    for entry in figures:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("status", "")).lower() not in _READY_FIGURE_STATUSES:
            continue
        rel_path = entry.get("path")
        if not isinstance(rel_path, str) or not rel_path.startswith("figures/"):
            continue
        candidate = final_dir / rel_path
        if (
            Path(rel_path).suffix.lower() in _PUBLIC_FIGURE_SUFFIXES
            and _is_safe_file(final_dir, candidate)
            and not _is_private_arcname(rel_path)
        ):
            ready.add(Path(rel_path).as_posix())
    return ready


def _collect_public_files(final_dir: Path, template_asset_names: set[str]) -> tuple[set[str], list[str]]:
    ready_figures = _load_ready_figure_arcnames(final_dir)
    included: set[str] = set()
    private_exclusions: list[str] = []
    for file_path in sorted(final_dir.rglob("*")):
        if not _is_safe_file(final_dir, file_path):
            continue
        arcname = _arcname(final_dir, file_path)
        if _is_private_arcname(arcname):
            private_exclusions.append(arcname)
            continue
        if _is_hidden_path(arcname) or not _is_public_arcname(arcname, template_asset_names):
            continue
        if arcname.startswith("figures/") and ready_figures is not None and arcname not in ready_figures:
            continue
        included.add(arcname)
    return included, private_exclusions


def _copy_missing_template_assets(
    final_dir: Path,
    archive: zipfile.ZipFile,
    included: set[str],
    template_id: str,
) -> None:
    for asset_path in get_template(template_id).asset_paths:
        if asset_path.suffix.lower() not in {".cls", ".bst"}:
            continue
        if asset_path.name in included:
            continue
        target = final_dir / asset_path.name
        source = target if _is_safe_file(final_dir, target) else asset_path
        archive.write(source, arcname=asset_path.name)
        included.add(asset_path.name)


def _read_exported_text(final_dir: Path, included: set[str], arcname: str) -> str:
    if arcname not in included:
        return ""
    path = final_dir / arcname
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def _strip_latex_comments(text: str) -> str:
    stripped_lines = []
    for line in text.splitlines():
        chars: list[str] = []
        escaped = False
        for char in line:
            if char == "%" and not escaped:
                break
            chars.append(char)
            escaped = char == "\\" and not escaped
        stripped_lines.append("".join(chars))
    return "\n".join(stripped_lines)


def _normalize_tex_dependency(raw: str) -> str | None:
    candidate = raw.strip()
    if not candidate or candidate.startswith(("/", "\\")) or ".." in Path(candidate).parts:
        return None
    path = Path(candidate)
    if path.suffix == "":
        path = path.with_suffix(".tex")
    if path.suffix.lower() != ".tex":
        return None
    return path.as_posix()


def _normalize_bib_dependency(raw: str) -> Iterable[str]:
    for item in raw.split(","):
        candidate = item.strip()
        if not candidate or candidate.startswith(("/", "\\")) or ".." in Path(candidate).parts:
            continue
        path = Path(candidate)
        if path.suffix == "":
            path = path.with_suffix(".bib")
        if path.suffix.lower() == ".bib":
            yield path.as_posix()


def _normalize_bst_dependency(raw: str) -> str | None:
    candidate = raw.strip()
    if not candidate or candidate.startswith(("/", "\\")) or ".." in Path(candidate).parts:
        return None
    path = Path(candidate)
    if path.suffix == "":
        path = path.with_suffix(".bst")
    if path.suffix.lower() != ".bst":
        return None
    return path.name


def _graphics_dependency_missing(raw: str, included: set[str]) -> str | None:
    candidate = raw.strip()
    if not candidate or candidate.startswith(("/", "\\")) or ".." in Path(candidate).parts:
        return None
    path = Path(candidate)
    if path.suffix:
        arcname = path.as_posix()
        return None if arcname in included else arcname
    for suffix in _PUBLIC_FIGURE_SUFFIXES:
        arcname = path.with_suffix(suffix).as_posix()
        if arcname in included:
            return None
    return path.as_posix()


def _dependency_closure(final_dir: Path, included: set[str], template_assets: set[str]) -> tuple[str, ...]:
    missing: set[str] = set()
    required = {"main.tex", "refs.bib", *template_assets}
    missing.update(name for name in required if name not in included)

    visited: set[str] = set()
    pending = ["main.tex"]
    while pending:
        arcname = pending.pop()
        if arcname in visited:
            continue
        visited.add(arcname)
        text = _strip_latex_comments(_read_exported_text(final_dir, included, arcname))
        for match in _TEX_INPUT_RE.finditer(text):
            dependency = _normalize_tex_dependency(match.group(1))
            if dependency is None:
                continue
            if dependency not in included:
                missing.add(dependency)
                continue
            pending.append(dependency)
        for match in _GRAPHICS_RE.finditer(text):
            dependency = _graphics_dependency_missing(match.group(1), included)
            if dependency is not None:
                missing.add(dependency)
        for match in _BIBLIOGRAPHY_RE.finditer(text):
            missing.update(path for path in _normalize_bib_dependency(match.group(1)) if path not in included)
        for match in _BIBLIOGRAPHY_STYLE_RE.finditer(text):
            dependency = _normalize_bst_dependency(match.group(1))
            if dependency is not None and dependency not in included:
                missing.add(dependency)
    return tuple(sorted(missing))


def _readme(config: PaperConfig, template_id: str, included: set[str]) -> str:
    generated_at = datetime.now(UTC).isoformat()
    source_tasks = ", ".join(
        f"{task.task_id}:{task.role.value}" for task in config.source_tasks
    ) or "none"
    return (
        "# PathLab Paper Agent Bundle\n\n"
        f"Paper ID: `{config.paper_id}`\n\n"
        f"Template: `{template_id}`\n\n"
        f"Generated at: `{generated_at}`\n\n"
        f"Source tasks: `{source_tasks}`\n\n"
        "Agent versions: `pathlab-paper-agent@0.1.0`\n\n"
        f"Included files: `{len(included) + 1}`\n\n"
        "This dependency-closed bundle contains only paper-facing LaTeX sources, "
        "template assets, ready figures, tables, and compile summaries when "
        "available. Private evidence locks, raw collected evidence, source "
        "mappings, intro/related-work drafts, raw prompts, and raw responses "
        "are excluded.\n"
    )


def export_bundle(
    final_dir: Path,
    bundle_path: Path,
    config: PaperConfig,
    template_id: str,
) -> BundleExportResult:
    """Zip a rendered template without private evidence or raw LLM payloads."""
    if not final_dir.exists():
        raise FileNotFoundError(f"final directory missing for template {template_id}")
    template_asset_names = {
        asset.name
        for asset in get_template(template_id).asset_paths
        if asset.suffix.lower() in {".cls", ".bst"}
    }
    included, private_exclusions = _collect_public_files(final_dir, template_asset_names)
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for arcname in sorted(included):
            archive.write(final_dir / arcname, arcname=arcname)
        _copy_missing_template_assets(final_dir, archive, included, template_id)
        missing_dependencies = _dependency_closure(final_dir, included, template_asset_names)
        archive.writestr("README.md", _readme(config, template_id, included))
        included.add("README.md")
    return BundleExportResult(
        bundle_path=bundle_path,
        included_files=tuple(sorted(included)),
        missing_dependencies=missing_dependencies,
        private_exclusions=tuple(sorted(private_exclusions)),
    )
