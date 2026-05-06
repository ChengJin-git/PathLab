"""LaTeX static guard for obvious syntax and dependency issues."""

from __future__ import annotations

import re
from pathlib import Path

from pathlab_paper_agent.storage import PaperRunPaths

from .common import GuardReport, rel_to_run, tex_files_under

_BEGIN_RE = re.compile(r"\\begin\{([^}]+)\}")
_END_RE = re.compile(r"\\end\{([^}]+)\}")
_INPUT_RE = re.compile(r"\\(?:input|include)\{([^}]+)\}")
_GRAPHICS_RE = re.compile(r"\\includegraphics(?:\[[^]]*\])?\{([^}]+)\}")


def _strip_comments(line: str) -> str:
    escaped = False
    for idx, char in enumerate(line):
        if char == "\\" and not escaped:
            escaped = True
            continue
        if char == "%" and not escaped:
            return line[:idx]
        escaped = False
    return line


def _balanced_braces(text: str) -> tuple[bool, int]:
    depth = 0
    escaped = False
    for idx, char in enumerate(text):
        if char == "\\" and not escaped:
            escaped = True
            continue
        if char == "{" and not escaped:
            depth += 1
        elif char == "}" and not escaped:
            depth -= 1
            if depth < 0:
                return False, idx
        escaped = False
    return depth == 0, len(text)


def _unsafe_include_path(raw_path: str) -> bool:
    path = Path(raw_path)
    return path.is_absolute() or ".." in path.parts


def _inside_run_root(paths: PaperRunPaths, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(paths.root.resolve())
        return True
    except ValueError:
        return False


def _resolve_input(paths: PaperRunPaths, tex_file: Path, include_path: str) -> Path | None:
    if _unsafe_include_path(include_path):
        return None
    candidates: list[Path] = []
    raw = include_path if Path(include_path).suffix else f"{include_path}.tex"
    candidates.append(tex_file.parent / raw)
    candidates.append(paths.root / raw)
    candidates.append(paths.final_dir / raw)
    for candidate in candidates:
        if candidate.exists() and _inside_run_root(paths, candidate):
            return candidate
    return None


def _resolve_graphic(paths: PaperRunPaths, tex_file: Path, graphic_path: str) -> Path | None:
    if _unsafe_include_path(graphic_path):
        return None
    raw = Path(graphic_path)
    candidates = [tex_file.parent / raw, paths.root / raw]
    if raw.suffix:
        candidates.append(paths.figures_dir / raw.name)
    else:
        for suffix in (".pdf", ".png", ".jpg", ".jpeg"):
            candidates.extend([tex_file.parent / f"{graphic_path}{suffix}", paths.root / f"{graphic_path}{suffix}"])
    for candidate in candidates:
        if candidate.exists() and _inside_run_root(paths, candidate):
            return candidate
    return None


def _check_file(paths: PaperRunPaths, path: Path, report: GuardReport) -> None:
    rel = rel_to_run(paths, path)
    text = "\n".join(_strip_comments(line) for line in path.read_text(encoding="utf-8").splitlines())
    ok, pos = _balanced_braces(text)
    if not ok:
        report.error("unbalanced_braces", "LaTeX braces are not balanced.", path=rel, context=f"offset={pos}")

    stack: list[str] = []
    events: list[tuple[int, str, str]] = []
    for match in _BEGIN_RE.finditer(text):
        events.append((match.start(), "begin", match.group(1)))
    for match in _END_RE.finditer(text):
        events.append((match.start(), "end", match.group(1)))
    for _pos, kind, env in sorted(events, key=lambda item: item[0]):
        if kind == "begin":
            stack.append(env)
        elif not stack or stack[-1] != env:
            report.error("environment_mismatch", "LaTeX environment begin/end mismatch.", path=rel, context=env)
            return
        else:
            stack.pop()
    if stack:
        report.error("unclosed_environment", "LaTeX environment is not closed.", path=rel, context=stack[-1])

    for match in _INPUT_RE.finditer(text):
        include_path = match.group(1)
        if _unsafe_include_path(include_path):
            report.error("unsafe_input_path", "LaTeX input/include path escapes the paper run.", path=rel, context=match.group(0))
        elif _resolve_input(paths, path, include_path) is None:
            report.error("missing_input", "LaTeX input/include target is missing.", path=rel, context=match.group(0))
    for match in _GRAPHICS_RE.finditer(text):
        graphic_path = match.group(1)
        if _unsafe_include_path(graphic_path):
            report.error("unsafe_graphic_path", "LaTeX includegraphics path escapes the paper run.", path=rel, context=match.group(0))
        elif _resolve_graphic(paths, path, graphic_path) is None:
            report.error("missing_graphic", "LaTeX includegraphics target is missing.", path=rel, context=match.group(0))


def run(paths: PaperRunPaths) -> GuardReport:
    report = GuardReport("latex_guard", metadata={"checked_files": []})
    checked = tex_files_under(paths.sections_dir)
    checked.extend(tex_files_under(paths.tables_dir))
    checked.extend(tex_files_under(paths.locked_blocks_dir))
    for final_dir in sorted(paths.final_dir.glob("*")) if paths.final_dir.exists() else []:
        checked.extend(tex_files_under(final_dir))
    # Deduplicate after final copies.
    unique = sorted(set(checked))
    report.metadata["checked_files"] = [rel_to_run(paths, path) for path in unique]
    for path in unique:
        _check_file(paths, path, report)
    return report
