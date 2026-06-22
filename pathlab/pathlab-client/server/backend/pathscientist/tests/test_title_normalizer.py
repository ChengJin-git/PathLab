"""Tests for synthesis.title_normalizer.normalize_title.

Motivated by session_142a4acaed08 whose paper_draft.md H1 was the user's
raw Chinese + filesystem path objective verbatim:

    # 看下这里的数据 /project/compath/storage/ywangrm/PathLab_data_collection/Data/CRC-MSI 用这个这个路径训里那一个patch-level 的分类模型

The normalizer converts such raw objectives into paper-suitable H1s by
stripping absolute-path tokens, known Chinese filler phrases, and
collapsing whitespace; with a stable fallback when the result is empty.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pathscientist.synthesis.title_normalizer import normalize_title


def test_strips_absolute_path():
    """Absolute-path tokens like /a/b/c must never appear in the title."""
    raw = "看下这里的数据 /a/b/c 用这个模型"
    out = normalize_title(raw)
    assert "/a/b/c" not in out, f"title still contains path: {out!r}"


def test_strips_chinese_filler():
    """Leading Chinese filler like '看下这里的数据' must not start the title."""
    raw = "看下这里的数据 /tmp/dataset 训一个模型"
    out = normalize_title(raw)
    assert not out.startswith("看下"), f"title still starts with filler: {out!r}"
    assert not out.startswith("看下这里的"), f"title still starts with filler: {out!r}"


def test_fallback_when_empty():
    """When stripping removes everything, fall back to a stable template."""
    raw = "/a/b/c /d/e/f"
    out = normalize_title(raw, success_metric="auc", dataset_hint="CRC-MSI")
    assert out == "Research Report: AUC on CRC-MSI", f"unexpected fallback: {out!r}"


def test_truncation_respects_multibyte():
    """Truncation must stay <= max_chars codepoints and never split mid-byte.

    Python str slicing is codepoint-indexed, so s[:max_chars] is safe for
    multi-byte UTF-8 chars. We verify length and that the output re-encodes
    cleanly as UTF-8 (i.e. no partial multibyte char).
    """
    # 200+ chars: alternating Chinese + English so the string is clearly
    # mixed-width and exceeds max_chars. "测试ABC" is 5 codepoints, *40 = 200.
    raw = ("测试ABC" * 40)
    assert len(raw) == 200
    out = normalize_title(raw, max_chars=120)
    assert len(out) <= 120, f"output exceeds max_chars: len={len(out)}"
    # Must re-encode as UTF-8 without error (no partial multibyte char).
    encoded = out.encode("utf-8")
    assert encoded.decode("utf-8") == out


def test_ascii_objective_unchanged():
    """A clean ASCII objective should pass through untouched."""
    raw = "Improve AUC on BRACS via attention pooling"
    out = normalize_title(raw)
    assert out == raw, f"ascii objective was modified: {out!r}"


def test_chinese_fragment_falls_back():
    """A Chinese fragment with only short ASCII runs must fall back.

    Motivated by session_b14b074d2268 (2026-04-20) whose paper H1 was
    ``# 数据 patch-level 的分类模型`` (20 codepoints). That is better than
    the pre-Task-7 raw path-containing title, but still not a real paper
    title — it is Chinese filler with one hyphenated English term whose
    longest ASCII run is only 5 chars ("patch"/"level").

    The normalizer should recognize this as "no meaningful ASCII content"
    and fall back to the ``Research Report: {metric} on {dataset}``
    template instead.
    """
    raw = (
        "看下这里的数据 "
        "/project/compath/storage/ywangrm/PathLab_data_collection/Data/CRC-MSI "
        "用这个这个路径训里那一个patch-level 的分类模型"
    )
    title = normalize_title(raw, success_metric="auc", dataset_hint="CRC-MSI")
    assert title == "Research Report: AUC on CRC-MSI", (
        f"expected fallback title for Chinese fragment, got: {title!r}"
    )
