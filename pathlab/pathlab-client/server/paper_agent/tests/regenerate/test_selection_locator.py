from __future__ import annotations

import pytest

from pathlab_paper_agent.selection_locator import (
    SelectionLocatorError,
    locate_selection,
    section_content_hash,
)
from pathlab_paper_agent.storage import PaperRunPaths


def _paths(tmp_path) -> PaperRunPaths:
    paths = PaperRunPaths(paper_id="paper_locator", root=tmp_path / "paper_locator")
    paths.sections_dir.mkdir(parents=True)
    return paths


def test_exact_pdf_selection_locates_source_span(tmp_path) -> None:
    paths = _paths(tmp_path)
    source = (
        "\\section{Results}\n"
        "First paragraph is background.\n\n"
        "Our method improves Dice by 4.2 points over the strongest baseline. "
        "The estimate is reported cautiously.\n"
    )
    (paths.sections_dir / "results.tex").write_text(source, encoding="utf-8")

    result = locate_selection(
        paths,
        "results",
        selected_text="Our method improves Dice by 4.2 points over the strongest baseline.",
        source_hash=section_content_hash(source),
    )

    assert result.paragraph_index == 1
    assert result.sentence_index == 0
    assert source[result.char_start:result.char_end] == result.matched_source_text
    assert result.confidence == 1.0


def test_pdf_selection_normalizes_latex_commands_and_citations(tmp_path) -> None:
    paths = _paths(tmp_path)
    source = (
        "\\section{Results}\n"
        "The \\textbf{attention model} remains robust across folds \\cite{Smith2024}. "
        "No private identifiers are reported.\n"
    )
    (paths.sections_dir / "results.tex").write_text(source, encoding="utf-8")

    result = locate_selection(
        paths,
        "results",
        selected_text="The attention model remains robust across folds.",
    )

    assert result.paragraph_index == 0
    assert "textbf" in result.matched_source_text
    assert result.confidence >= 0.72


def test_source_hash_stale_returns_409_code(tmp_path) -> None:
    paths = _paths(tmp_path)
    (paths.sections_dir / "results.tex").write_text("A current section sentence with enough text.\n", encoding="utf-8")

    with pytest.raises(SelectionLocatorError) as exc_info:
        locate_selection(
            paths,
            "results",
            selected_text="A current section sentence with enough text.",
            source_hash="sha256:not-current",
        )

    assert exc_info.value.code == "stale_selection"
    assert exc_info.value.status_code == 409
    assert "current_source_hash" in exc_info.value.detail()


def test_selection_too_short_is_rejected(tmp_path) -> None:
    paths = _paths(tmp_path)
    (paths.sections_dir / "results.tex").write_text("A long enough paragraph for matching.\n", encoding="utf-8")

    with pytest.raises(SelectionLocatorError) as exc_info:
        locate_selection(paths, "results", selected_text="too short")

    assert exc_info.value.code == "selection_too_short"


def test_ambiguous_selection_is_rejected(tmp_path) -> None:
    paths = _paths(tmp_path)
    repeated = "The same repeated sentence is intentionally duplicated for matching."
    (paths.sections_dir / "results.tex").write_text(f"{repeated}\n\n{repeated}\n", encoding="utf-8")

    with pytest.raises(SelectionLocatorError) as exc_info:
        locate_selection(paths, "results", selected_text=repeated)

    assert exc_info.value.code == "ambiguous_selection"
    assert len(exc_info.value.detail()["candidates"]) == 2


def test_ambiguous_selection_in_same_paragraph_is_rejected(tmp_path) -> None:
    paths = _paths(tmp_path)
    repeated = "The same repeated sentence is intentionally duplicated for matching."
    (paths.sections_dir / "results.tex").write_text(f"{repeated} {repeated}\n", encoding="utf-8")

    with pytest.raises(SelectionLocatorError) as exc_info:
        locate_selection(paths, "results", selected_text=repeated)

    assert exc_info.value.code == "ambiguous_selection"
    assert len(exc_info.value.detail()["candidates"]) == 2


def test_char_range_hint_uses_exact_source_offsets(tmp_path) -> None:
    paths = _paths(tmp_path)
    source = "\\section{Results}\nThe source-tab selected sentence should be patched exactly.\n"
    selected = "source-tab selected sentence"
    start = source.index(selected)
    end = start + len(selected)
    (paths.sections_dir / "results.tex").write_text(source, encoding="utf-8")

    result = locate_selection(
        paths,
        "results",
        selected_text=selected,
        source_hash=f"sha256:{section_content_hash(source)}",
        char_start=start,
        char_end=end,
    )

    assert result.char_start == start
    assert result.char_end == end
    assert result.matched_source_text == selected
