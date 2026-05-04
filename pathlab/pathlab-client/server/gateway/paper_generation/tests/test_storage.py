"""Filesystem layout + §3.7 download safety tests."""

from __future__ import annotations

import pytest

from gateway.paper_generation.storage import (
    PaperRunPaths,
    is_path_allowed_for_download,
    papers_root,
    safe_resolve,
    validate_paper_id,
)


# ---------------------------------------------------------------------------
# validate_paper_id
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "paper_id,is_valid",
    [
        ("paper_abc123", True),
        ("paper_aabbccdd11223344", True),
        ("a", True),
        ("a" * 128, True),
        ("Z9-_test", True),
        # invalid
        ("a" * 129, False),
        ("paper_!@#", False),
        ("../paper", False),
        ("", False),
        ("paper id with spaces", False),
        ("paper/slash", False),
        ("paper.with.dots", False),  # dots aren't in the regex
        ("_starts_with_underscore", False),  # must start alnum
    ],
)
def test_validate_paper_id(paper_id: str, is_valid: bool) -> None:
    if is_valid:
        assert validate_paper_id(paper_id) == paper_id
    else:
        with pytest.raises((ValueError, TypeError)):
            validate_paper_id(paper_id)


def test_validate_paper_id_rejects_non_string() -> None:
    with pytest.raises((ValueError, TypeError)):
        validate_paper_id(None)
    with pytest.raises((ValueError, TypeError)):
        validate_paper_id(12345)


# ---------------------------------------------------------------------------
# is_path_allowed_for_download (the §3.7 allowlist — security critical)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "rel_path,expected",
    [
        # ALLOW: top-level files
        ("manifest.json", True),
        ("config.json", True),
        # ALLOW: prefixes
        ("tables/table_1.tex", True),
        ("tables/nested/deep.tex", True),  # any depth under tables/
        ("figures/manifest.json", True),
        ("figures/fig1.pdf", True),
        ("drafts/sections/abstract.tex", True),
        ("drafts/sections/introduction.tex", True),
        ("final/miccai/main.pdf", True),
        ("final/nature_scientific_reports/main.pdf", True),
        ("exports/miccai_bundle.zip", True),
        # ALLOW: explicit allowlist
        ("evidence/experimental_log.md", True),
        ("evidence/evidence_public.json", True),
        ("drafts/outline.json", True),
        ("citations/refs.bib", True),
        ("citations/coverage_report.json", True),
        ("validation/warnings.md", True),

        # DENY: PHI / private
        ("evidence/evidence_lock.private.json", False),
        # DENY: source task references (could leak case_id mappings)
        ("inputs/source_tasks.json", False),
        ("inputs/source_analyses.json", False),
        ("inputs/idea.md", False),  # user idea — keep server-side
        # DENY: intro_rw_draft (Section Writing Agent's input only)
        ("drafts/intro_rw_draft/introduction.tex", False),
        ("drafts/intro_rw_draft/related_work.tex", False),
        # DENY: refinement loop snapshots (internal)
        ("drafts/snapshots/iter_0/sections/abstract.tex", False),
        # DENY: validation guard JSONs (potential PHI leakage)
        ("validation/metric_guard.json", False),
        ("validation/identifier_guard.json", False),
        # DENY: nonsense / unknown
        ("hidden/secret.txt", False),
        ("random/path.txt", False),
    ],
)
def test_allowlist_decisions(rel_path: str, expected: bool) -> None:
    assert is_path_allowed_for_download(rel_path) is expected, (
        f"§3.7 allowlist violation: {rel_path!r} should be "
        f"{'ALLOWED' if expected else 'DENIED'}"
    )


# ---------------------------------------------------------------------------
# safe_resolve — path traversal / symlink rejection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "user_path",
    [
        "../../../etc/passwd",
        "/etc/passwd",
        "/absolute/path",
        "final/../../../etc/passwd",
        "..",
        "tables/..",
        ".hidden/x.txt",
        "final/.hidden/x.txt",
        "  manifest.json",          # leading whitespace
        "manifest.json  ",          # trailing whitespace
        "",                         # empty
    ],
)
def test_safe_resolve_rejects_attacks(user_path: str) -> None:
    paths = PaperRunPaths.for_paper("paper_attack")
    with pytest.raises(ValueError):
        safe_resolve(paths, user_path)


def test_safe_resolve_rejects_non_string() -> None:
    paths = PaperRunPaths.for_paper("paper_attack")
    with pytest.raises((ValueError, TypeError)):
        safe_resolve(paths, None)  # type: ignore[arg-type]


def test_safe_resolve_accepts_valid_relative() -> None:
    paths = PaperRunPaths.for_paper("paper_abc")
    paths.ensure_dirs()
    paths.manifest.write_text("{}", encoding="utf-8")

    target = safe_resolve(paths, "manifest.json")
    assert target == (paths.root / "manifest.json").resolve()


def test_safe_resolve_rejects_symlink_escape(tmp_path) -> None:
    paths = PaperRunPaths.for_paper("paper_link")
    paths.ensure_dirs()

    # Create a symlink inside paper run that points outside.
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = paths.root / "tables" / "linked.tex"
    link.symlink_to(outside)

    with pytest.raises(ValueError, match="escapes"):
        safe_resolve(paths, "tables/linked.tex")


# ---------------------------------------------------------------------------
# PaperRunPaths construction + ensure_dirs
# ---------------------------------------------------------------------------

def test_paper_run_paths_for_paper_validates_id() -> None:
    """Constructor should reject malformed paper_id even if user manages
    to bypass route-level validation."""
    with pytest.raises(ValueError):
        PaperRunPaths.for_paper("../escape")
    with pytest.raises(ValueError):
        PaperRunPaths.for_paper("with space")


def test_paper_run_paths_root_lives_under_uploads() -> None:
    paths = PaperRunPaths.for_paper("paper_xyz")
    assert paths.root == papers_root() / "paper_xyz"
    assert paths.root.parent == papers_root()


def test_ensure_dirs_creates_full_layout() -> None:
    paths = PaperRunPaths.for_paper("paper_layout")
    paths.ensure_dirs()

    expected_subs = [
        paths.inputs_dir,
        paths.evidence_dir,
        paths.tables_dir,
        paths.locked_blocks_dir,
        paths.figures_dir,
        paths.citations_dir,
        paths.drafts_dir,
        paths.intro_rw_draft_dir,
        paths.sections_dir,
        paths.snapshots_dir,
        paths.validation_dir,
        paths.final_dir,
        paths.exports_dir,
    ]
    for sub in expected_subs:
        assert sub.is_dir(), f"ensure_dirs did not create {sub}"


def test_ensure_dirs_is_idempotent() -> None:
    """Re-running ensure_dirs on an existing run must not raise."""
    paths = PaperRunPaths.for_paper("paper_idempotent")
    paths.ensure_dirs()
    paths.ensure_dirs()  # should not raise


def test_final_for_template_returns_subpath() -> None:
    paths = PaperRunPaths.for_paper("paper_tmpl")
    miccai = paths.final_for_template("miccai")
    nature = paths.final_for_template("nature_scientific_reports")

    assert miccai == paths.final_dir / "miccai"
    assert nature == paths.final_dir / "nature_scientific_reports"
    assert miccai != nature
