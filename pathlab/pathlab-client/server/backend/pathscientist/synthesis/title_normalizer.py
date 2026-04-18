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
      4. If the remaining title is empty or shorter than 8 chars, fall back to
         f"Research Report: {success_metric.upper() or 'Results'}" +
         (f" on {dataset_hint}" if dataset_hint else "").
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

    # 4. Fallback when stripping leaves nothing useful.
    if len(text) < 8:
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
