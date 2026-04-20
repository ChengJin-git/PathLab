"""Paper title normalization.

Converts a raw research objective (often pasted by a human, sometimes
mixing Chinese filler phrases with absolute filesystem paths) into a
paper-suitable H1.

Motivated by session_142a4acaed08 whose paper_draft.md H1 was:

    # 看下这里的数据 /project/compath/storage/ywangrm/.../CRC-MSI 用这个这个路径训里那一个patch-level 的分类模型

No title should contain a filesystem path, and the opening filler
("看下这里的数据") is not useful title text. When stripping leaves
nothing useful, we fall back to a stable boring template built from the
success metric and dataset hint.
"""
from __future__ import annotations

import re

# Matches absolute Unix-style paths (e.g. /a/b/c, /project/foo/bar.ext).
# Requires at least one "/segment" after the leading slash to avoid eating
# bare slashes in prose. Segments allow any non-whitespace, non-slash char
# except '/' itself, which includes dots, dashes, underscores, letters,
# digits. The path extends as long as /segment keeps matching.
_ABSOLUTE_PATH_RE = re.compile(r"/[^\s/]+(?:/[^\s]*)+")

# Chinese filler patterns observed in real session objectives. These are
# stripped (replaced with a space) before whitespace collapsing. Kept
# intentionally conservative — e.g. "数据" ("data") is NOT stripped because
# it is legitimate title text on its own.
_CHINESE_FILLER_PATTERNS: list[re.Pattern] = [
    re.compile(r"看下"),
    re.compile(r"这里的"),
    re.compile(r"用这个(?:这个)?路径?"),
    re.compile(r"训[里练]?(?:那一个|那个)?"),
    re.compile(r"这个这个"),
]

# Runs of ASCII letters, used to detect whether the stripped text contains
# meaningful English content. A hyphen breaks a run ("patch-level" yields
# two 5-char runs, not one 10-char run), so the hyphen test is deliberate.
_ASCII_LETTER_RUN_RE = re.compile(r"[A-Za-z]+")

# Minimum required length of the longest ASCII letter run before we consider
# the stripped text to contain enough English content to be a real title.
# Chosen so that "patch" and "level" (both 5) are NOT sufficient — a pure
# Chinese fragment with a single hyphenated compound falls back — while
# single real English words like "Linear" (6), "Improve" (7), "attention"
# (9), or "classifier" (10) are all sufficient.
_MIN_ASCII_RUN = 6


def _longest_ascii_letter_run(text: str) -> int:
    """Return the length (in ASCII letters) of the longest [A-Za-z]+ run.

    Hyphens, digits, and whitespace all break a run, so "patch-level"
    yields a max run of 5 ("patch" or "level"), not 10.
    """
    return max((len(m) for m in _ASCII_LETTER_RUN_RE.findall(text)), default=0)


def normalize_title(
    objective: str,
    *,
    success_metric: str = "",
    dataset_hint: str = "",
    max_chars: int = 120,
) -> str:
    """Best-effort convert a raw research objective into a paper title.

    Rules (in order):
      1. Strip any absolute-path-looking tokens (/xxx/yyy/...).
      2. Strip known Chinese filler phrases ("看下", "这里的", "这个这个路径" ...).
      3. Collapse whitespace.
      4. Fall back to f"Research Report: {success_metric.upper() or 'Results'}" +
         (f" on {dataset_hint}" if dataset_hint else "") when the stripped
         remainder looks meaningless. "Meaningless" is any of:
           - empty,
           - shorter than 8 codepoints, or
           - no ASCII letter run of length >= 6 (catches pure-Chinese
             fragments like "数据 patch-level 的分类模型" whose only
             English tokens are short and hyphen-split, leaving no
             substantive English word).
      5. Truncate to max_chars on a word boundary; never cut a multi-byte char.

    Python ``str`` is codepoint-indexed, so slicing ``s[:max_chars]`` already
    cuts at a codepoint boundary — there is no mid-byte hazard. The truncation
    concern is purely about staying under ``max_chars`` codepoints.
    """
    if not isinstance(objective, str):
        objective = str(objective or "")

    # 1. Strip absolute paths.
    text = _ABSOLUTE_PATH_RE.sub(" ", objective)

    # 2. Strip known Chinese filler phrases.
    for pat in _CHINESE_FILLER_PATTERNS:
        text = pat.sub(" ", text)

    # 3. Collapse whitespace.
    text = re.sub(r"\s+", " ", text).strip()

    # 4. Fallback when stripping leaves nothing useful. Empty and very short
    #    remainders were always insufficient; we additionally reject strings
    #    with no ASCII letter run of length >= _MIN_ASCII_RUN, which catches
    #    pure-Chinese fragments that happen to exceed the length threshold
    #    (e.g. "数据 patch-level 的分类模型", 20 codepoints, longest ASCII
    #    run = 5).
    if (
        not text
        or len(text) < 8
        or _longest_ascii_letter_run(text) < _MIN_ASCII_RUN
    ):
        metric = success_metric.upper() if success_metric else "Results"
        fallback = f"Research Report: {metric}"
        if dataset_hint:
            fallback = f"{fallback} on {dataset_hint}"
        text = fallback

    # 5. Truncate. Python str slicing is codepoint-safe; no mid-byte hazard.
    if len(text) > max_chars:
        truncated = text[:max_chars]
        # Prefer a word boundary: if the slice ends mid-ASCII-word, back up to
        # the last whitespace. For pure-CJK text there are no spaces so this
        # no-op and we accept the codepoint cut.
        if " " in truncated:
            last_space = truncated.rfind(" ")
            # Only back up if we would keep a meaningful amount of text.
            if last_space >= max_chars // 2:
                truncated = truncated[:last_space]
        text = truncated.rstrip()

    return text
