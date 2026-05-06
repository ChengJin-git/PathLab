"""Backend-authoritative locator for PDF/source text selections."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from .schemas import SelectionLocatorResult
from .storage import PaperRunPaths

_TEXT_COMMANDS = ("textbf", "emph", "underline", "textit", "texttt", "textsc")
_COMMAND_RE = re.compile(r"\\[A-Za-z]+\*?")
_MIN_SELECTION_CHARS = 20
_FOUND_THRESHOLD = 0.72
_AMBIGUOUS_DELTA = 0.08


class SelectionLocatorError(ValueError):
    """Raised when a frontend selection cannot be safely mapped to source."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 422,
        **extra: Any,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.extra = extra

    def detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.extra}


@dataclass(frozen=True)
class _Normalized:
    text: str
    # map normalized character offsets back to original source offsets.
    source_offsets: tuple[int, ...]


@dataclass(frozen=True)
class _Paragraph:
    index: int
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class _Candidate:
    paragraph: _Paragraph
    score: float
    char_start: int
    char_end: int
    normalized_source_text: str


def section_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def locate_selection(
    paths: PaperRunPaths,
    section_name: str,
    *,
    selected_text: str | None = None,
    source_hash: str | None = None,
    target_paragraph: int | None = None,
    target_sentence: int | None = None,
    char_start: int | None = None,
    char_end: int | None = None,
) -> SelectionLocatorResult:
    """Locate a selected PDF/source span inside one section's LaTeX source."""
    source_path = paths.sections_dir / f"{section_name}.tex"
    if not source_path.is_file():
        raise SelectionLocatorError(
            "section_not_found",
            f"Section source not found: {section_name}",
            status_code=404,
            section_name=section_name,
        )
    source = source_path.read_text(encoding="utf-8")
    _assert_source_hash(source, source_hash, section_name)

    normalized_selected = normalize_text(selected_text or "").text
    if char_start is not None or char_end is not None:
        return _locate_by_char_range(
            source,
            section_name,
            normalized_selected_text=normalized_selected,
            target_paragraph=target_paragraph,
            target_sentence=target_sentence,
            char_start=char_start,
            char_end=char_end,
        )

    if target_sentence is not None:
        return _locate_by_sentence_index(
            source,
            section_name,
            selected_text=selected_text,
            normalized_selected_text=normalized_selected,
            target_paragraph=target_paragraph,
            target_sentence=target_sentence,
        )

    if len(normalized_selected) < _MIN_SELECTION_CHARS:
        raise SelectionLocatorError(
            "selection_too_short",
            "Selected text is too short to locate reliably.",
            normalized_selected_text=normalized_selected,
        )

    paragraphs = _paragraphs(source)
    search_space = [
        paragraph
        for paragraph in paragraphs
        if target_paragraph is None or paragraph.index == target_paragraph
    ]
    if not search_space:
        raise SelectionLocatorError(
            "selection_not_found",
            "Target paragraph was not found in the current section source.",
            section_name=section_name,
            target_paragraph=target_paragraph,
        )

    candidates = sorted(
        (
            candidate
            for paragraph in search_space
            for candidate in _matches_in_paragraph(paragraph, normalized_selected)
        ),
        key=lambda item: item.score,
        reverse=True,
    )
    if not candidates or candidates[0].score < _FOUND_THRESHOLD:
        raise SelectionLocatorError(
            "selection_not_found",
            "Selected text was not found in the current section source.",
            section_name=section_name,
        )
    if len(candidates) > 1 and candidates[0].score - candidates[1].score < _AMBIGUOUS_DELTA:
        raise SelectionLocatorError(
            "ambiguous_selection",
            "Selected text matched multiple source spans; please reselect or confirm the paragraph.",
            candidates=[_candidate_payload(candidate) for candidate in candidates[:5]],
        )
    return _result_from_candidate(
        source,
        section_name,
        candidates[0],
        normalized_selected_text=normalized_selected,
        ambiguous=False,
    )


def normalize_text(text: str) -> _Normalized:
    """Normalize rendered/PDF and LaTeX text while retaining source offsets."""
    text = unicodedata.normalize("NFKC", text).replace("\u00a0", " ")
    out: list[str] = []
    offsets: list[int] = []
    i = 0
    pending_space = False
    while i < len(text):
        if text[i] == "%" and not _is_escaped(text, i):
            newline = text.find("\n", i)
            i = len(text) if newline == -1 else newline
            pending_space = True
            continue
        if text.startswith("\\cite", i) or text.startswith("\\parencite", i):
            i = _skip_latex_command_with_optional_args(text, i)
            pending_space = True
            continue
        if text.startswith("\\ref", i) or text.startswith("\\autoref", i):
            token = "[ref]"
            if pending_space:
                _emit(out, offsets, " ", i)
                pending_space = False
            for ch in token:
                _emit(out, offsets, ch, i)
            i = _skip_latex_command_with_optional_args(text, i)
            continue
        command = _command_at(text, i)
        if command in _TEXT_COMMANDS:
            i += len(command) + 1
            if i < len(text) and text[i] == "{":
                i += 1
            continue
        if text[i] in "{}":
            i += 1
            continue
        if text[i] == "\\":
            command_match = _COMMAND_RE.match(text, i)
            if command_match:
                i = command_match.end()
                continue
        if text[i] == "$":
            end = text.find("$", i + 1)
            if end != -1:
                if pending_space:
                    _emit(out, offsets, " ", i)
                    pending_space = False
                for ch in "[math]":
                    _emit(out, offsets, ch, i)
                i = end + 1
                continue
        ch = _normalize_char(text[i])
        if ch.isspace():
            pending_space = bool(out)
            i += 1
            continue
        if pending_space:
            _emit(out, offsets, " ", i)
            pending_space = False
        _emit(out, offsets, ch.lower(), i)
        i += 1
    normalized = "".join(out).strip()
    if normalized and offsets and normalized[0] == " ":
        offsets = offsets[1:]
    if normalized and offsets and normalized[-1] == " ":
        offsets = offsets[:-1]
    return _Normalized(normalized, tuple(offsets))


def _locate_by_char_range(
    source: str,
    section_name: str,
    *,
    normalized_selected_text: str,
    target_paragraph: int | None,
    target_sentence: int | None,
    char_start: int | None,
    char_end: int | None,
) -> SelectionLocatorResult:
    if (
        char_start is None
        or char_end is None
        or char_start < 0
        or char_start >= char_end
        or char_end > len(source)
    ):
        raise SelectionLocatorError("selection_mismatch", "Invalid selection character range.")
    span = source[char_start:char_end]
    normalized_span = normalize_text(span).text
    if normalized_selected_text:
        score = SequenceMatcher(None, normalized_selected_text, normalized_span).ratio()
        if score < _FOUND_THRESHOLD:
            raise SelectionLocatorError(
                "selection_mismatch",
                "Selected text does not match the source character range.",
                confidence=score,
            )
    else:
        score = 1.0
        normalized_selected_text = normalized_span
    paragraph_index = _paragraph_index_for_span(source, char_start, target_paragraph)
    sentence_index = _sentence_index_for_span(source, paragraph_index, char_start)
    if target_sentence is not None:
        sentence_index = target_sentence
    return SelectionLocatorResult(
        section_name=section_name,
        paragraph_index=paragraph_index,
        sentence_index=sentence_index,
        char_start=char_start,
        char_end=char_end,
        matched_source_text=span,
        normalized_selected_text=normalized_selected_text,
        normalized_source_text=normalized_span,
        confidence=score,
        ambiguous=False,
    )


def _locate_by_sentence_index(
    source: str,
    section_name: str,
    *,
    selected_text: str | None,
    normalized_selected_text: str,
    target_paragraph: int | None,
    target_sentence: int,
) -> SelectionLocatorResult:
    paragraphs = _paragraphs(source)
    candidates = [p for p in paragraphs if target_paragraph is None or p.index == target_paragraph]
    for paragraph in candidates:
        sentences = _sentence_spans(paragraph.text, base=paragraph.start)
        if target_sentence >= len(sentences):
            continue
        start, end = sentences[target_sentence]
        return _locate_by_char_range(
            source,
            section_name,
            normalized_selected_text=normalized_selected_text or normalize_text(selected_text or source[start:end]).text,
            target_paragraph=paragraph.index,
            target_sentence=target_sentence,
            char_start=start,
            char_end=end,
        )
    raise SelectionLocatorError(
        "selection_not_found",
        "Target sentence was not found in the current section source.",
        section_name=section_name,
        target_paragraph=target_paragraph,
        target_sentence=target_sentence,
    )


def _matches_in_paragraph(paragraph: _Paragraph, normalized_selected: str) -> list[_Candidate]:
    normalized = normalize_text(paragraph.text)
    haystack = normalized.text
    if not haystack:
        return []
    candidates: list[_Candidate] = []
    start = haystack.find(normalized_selected)
    if start >= 0:
        while start >= 0:
            candidate = _candidate_from_normalized_span(
                paragraph,
                normalized,
                start=start,
                end=start + len(normalized_selected),
                score=1.0,
            )
            if candidate is not None:
                candidates.append(candidate)
            start = haystack.find(normalized_selected, start + 1)
        return candidates

    match = SequenceMatcher(None, normalized_selected, haystack).find_longest_match(
        0, len(normalized_selected), 0, len(haystack)
    )
    if match.size == 0:
        return []
    candidate = _candidate_from_normalized_span(
        paragraph,
        normalized,
        start=match.b,
        end=min(len(haystack), match.b + match.size),
        score=match.size / max(1, len(normalized_selected)),
    )
    return [candidate] if candidate is not None else []


def _candidate_from_normalized_span(
    paragraph: _Paragraph,
    normalized: _Normalized,
    *,
    start: int,
    end: int,
    score: float,
) -> _Candidate | None:
    if start >= len(normalized.source_offsets) or end <= 0:
        return None
    source_start = paragraph.start + normalized.source_offsets[max(0, start)]
    source_end = paragraph.start + normalized.source_offsets[min(len(normalized.source_offsets) - 1, end - 1)] + 1
    return _Candidate(
        paragraph=paragraph,
        score=score,
        char_start=source_start,
        char_end=source_end,
        normalized_source_text=normalized.text[start:end],
    )


def _result_from_candidate(
    source: str,
    section_name: str,
    candidate: _Candidate,
    *,
    normalized_selected_text: str,
    ambiguous: bool,
) -> SelectionLocatorResult:
    sentence_index = _sentence_index_for_span(source, candidate.paragraph.index, candidate.char_start)
    return SelectionLocatorResult(
        section_name=section_name,
        paragraph_index=candidate.paragraph.index,
        sentence_index=sentence_index,
        char_start=candidate.char_start,
        char_end=candidate.char_end,
        matched_source_text=source[candidate.char_start:candidate.char_end],
        normalized_selected_text=normalized_selected_text,
        normalized_source_text=candidate.normalized_source_text,
        confidence=candidate.score,
        ambiguous=ambiguous,
    )


def _assert_source_hash(source: str, source_hash: str | None, section_name: str) -> None:
    if not source_hash:
        return
    current = section_content_hash(source)
    expected = source_hash.removeprefix("sha256:")
    if expected != current:
        raise SelectionLocatorError(
            "stale_selection",
            "The section changed after the text was selected. Please reselect the sentence.",
            status_code=409,
            section_name=section_name,
            current_source_hash=current,
        )


def _paragraphs(source: str) -> list[_Paragraph]:
    paragraphs: list[_Paragraph] = []
    start = 0
    index = 0
    for match in re.finditer(r"\n[ \t]*\n+", source):
        end = match.start()
        if source[start:end].strip():
            paragraphs.append(_Paragraph(index, start, end, source[start:end]))
            index += 1
        start = match.end()
    if source[start:].strip():
        paragraphs.append(_Paragraph(index, start, len(source), source[start:]))
    return paragraphs


def _paragraph_index_for_span(source: str, char_start: int, hint: int | None) -> int:
    for paragraph in _paragraphs(source):
        if paragraph.start <= char_start <= paragraph.end:
            return paragraph.index
    return hint if hint is not None else 0


def _sentence_index_for_span(source: str, paragraph_index: int, char_start: int) -> int | None:
    paragraphs = _paragraphs(source)
    if paragraph_index >= len(paragraphs):
        return None
    for index, (start, end) in enumerate(_sentence_spans(paragraphs[paragraph_index].text, base=paragraphs[paragraph_index].start)):
        if start <= char_start <= end:
            return index
    return None


def _sentence_spans(text: str, *, base: int = 0) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for match in re.finditer(r"(?<=[.!?])\s+", text):
        end = match.start()
        if text[start:end].strip():
            spans.append((base + start, base + end))
        start = match.end()
    if text[start:].strip():
        spans.append((base + start, base + len(text)))
    return spans


def _candidate_payload(candidate: _Candidate) -> dict[str, Any]:
    return {
        "paragraph_index": candidate.paragraph.index,
        "char_start": candidate.char_start,
        "char_end": candidate.char_end,
        "confidence": round(candidate.score, 3),
        "preview": candidate.paragraph.text[:160],
    }


def _skip_latex_command_with_optional_args(text: str, start: int) -> int:
    match = _COMMAND_RE.match(text, start)
    if not match:
        return start + 1
    i = match.end()
    while i < len(text) and text[i] == "[":
        i = _skip_balanced(text, i, "[", "]")
    if i < len(text) and text[i] == "{":
        i = _skip_balanced(text, i, "{", "}")
    return i


def _skip_balanced(text: str, start: int, open_ch: str, close_ch: str) -> int:
    depth = 0
    i = start
    while i < len(text):
        if text[i] == open_ch and not _is_escaped(text, i):
            depth += 1
        elif text[i] == close_ch and not _is_escaped(text, i):
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(text)


def _command_at(text: str, index: int) -> str | None:
    if text[index] != "\\":
        return None
    match = _COMMAND_RE.match(text, index)
    return match.group(0).lstrip("\\").rstrip("*") if match else None


def _normalize_char(ch: str) -> str:
    if ch in {"“", "”", "„"}:
        return '"'
    if ch in {"‘", "’"}:
        return "'"
    if ch in {"‐", "‑", "–", "—", "−"}:
        return "-"
    return ch


def _emit(out: list[str], offsets: list[int], ch: str, source_offset: int) -> None:
    out.append(ch)
    offsets.append(source_offset)


def _is_escaped(text: str, index: int) -> bool:
    slash_count = 0
    i = index - 1
    while i >= 0 and text[i] == "\\":
        slash_count += 1
        i -= 1
    return slash_count % 2 == 1
