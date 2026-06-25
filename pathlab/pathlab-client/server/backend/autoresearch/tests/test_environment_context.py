"""Tests for context.detect_hf_model_cache + build_environment_context.

Truth source is ``common/extractors/checkpoints/<Name>/`` — the directory
``checkpoint_manager.get_ckpt_path`` actually returns from. Not HF_HOME.

Motivated by:

- session_e95aaf19aba4 (2026-04-21) whose agent reasoned "No network
  access (can't download UNI2/CONCH)" — root cause: env context never
  mentioned local pre-installed pathology FMs.
- session_9df3fa411bbf (2026-04-22) whose agent tried
  ``AutoModel.from_pretrained("MahmoodLab/UNI2-h")`` and got
  ``Unrecognized model ...``, then fell back to ImageNet CLIP. Root
  cause: previous env context advertised three load paths (get_extractor /
  timm.create_model / AutoModel) instead of steering hard to the
  registry.
- 2026-04-22 self-review where detect_hf_model_cache advertised HF_HOME
  presence for Virchow2 / H-Optimus-1 even though their ckpt symlinks
  were missing from common/extractors/checkpoints/, so
  ``get_extractor("virchow2")`` would have failed at runtime.

This file locks in:

1. detect_hf_model_cache scans the checkpoints/ directory (the registry's
   truth source), NOT HF_HOME.
2. Entries with a working ckpt (file or symlink, >= 1MB) are listed with
   exact get_extractor(key) strings.
3. Entries whose ckpt dir exists but has no real file (e.g. Virchow2 /
   H-Optimus-1 in the current repo state) are explicitly called out as
   "Not currently installed" so the agent skips them.
4. Entries with < 1MB stub files (e.g. Git LFS pointer) are treated as
   missing, not usable.
5. The block steers the agent OFF AutoModel.from_pretrained /
   timm.create_model(..., pretrained=True).
6. Drop-in code snippet is embedded.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from autoresearch.context import (
    build_environment_context,
    detect_hf_model_cache,
)


def _make_fake_checkpoints(
    ckpts_root: Path,
    entries: list[tuple[str, str, int]],
) -> None:
    """Populate a fake checkpoints/ tree.

    entries = [(dir_name, ckpt_filename, size_bytes), ...]. size_bytes
    of 0 creates an empty dir (no ckpt). size_bytes of -1 creates a
    dangling symlink. Otherwise a real file of the requested size is
    written.
    """
    ckpts_root.mkdir(parents=True, exist_ok=True)
    for dir_name, fname, size in entries:
        d = ckpts_root / dir_name
        d.mkdir(parents=True, exist_ok=True)
        if size == 0:
            continue
        target = d / fname
        if size == -1:
            # Dangling symlink
            target.symlink_to(ckpts_root / "does-not-exist.bin")
        else:
            target.write_bytes(b"\0" * size)


def test_detect_hf_model_cache_lists_pathology_fms(tmp_path):
    """When checkpoints/<Name>/ has a real ckpt, the environment block
    must list each by display name with the EXACT get_extractor(key)
    call so the agent can copy-paste."""
    _make_fake_checkpoints(
        tmp_path,
        [
            ("UNI2",     "pytorch_model.bin", 2_600_000_000),
            ("UNI",      "pytorch_model.bin", 1_100_000_000),
            ("CONCH",    "pytorch_model.bin",   800_000_000),
            ("Virchow",  "pytorch_model.bin", 2_400_000_000),
            ("H-Optimus-1", "pytorch_model.bin", 1_500_000_000),
        ],
    )

    out = detect_hf_model_cache(ckpts_root=tmp_path)

    # Usable extractors must appear with get_extractor calls.
    assert 'get_extractor("uni2")' in out
    assert 'get_extractor("uni")' in out
    assert 'get_extractor("conch")' in out
    assert 'get_extractor("virchow")' in out
    # H-Optimus-1 keeps mixed case per registry entry.
    assert 'get_extractor("H-Optimus-1")' in out
    # "Pre-installed" wording — no network implied.
    assert "OFFLINE" in out or "offline" in out.lower()


def test_detect_hf_model_cache_defaults_to_pathlab_upload_checkpoints(tmp_path, monkeypatch):
    """AutoResearch context should inherit PathLab's extractor checkpoint root."""
    uploads = tmp_path / "uploads"
    ckpts_root = uploads / "extractor_checkpoints"
    _make_fake_checkpoints(
        ckpts_root,
        [("UNI", "pytorch_model.bin", 1_100_000_000)],
    )

    class FakeConfig:
        @staticmethod
        def get_uploads_dir():
            return uploads

    fake_config_module = types.SimpleNamespace(Config=FakeConfig)
    monkeypatch.setitem(sys.modules, "backend.common.config", fake_config_module)
    monkeypatch.delenv("PATHLAB_CKPT_DIR", raising=False)

    out = detect_hf_model_cache()

    assert str(ckpts_root) in out
    assert 'get_extractor("uni")' in out


def test_detect_hf_model_cache_skips_missing_ckpt_dirs(tmp_path):
    """When checkpoints/<Name>/ exists but has no ckpt file (e.g.
    Virchow2 / H-Optimus-1 in the current repo state), the entry must
    NOT appear in the usable list — otherwise the agent calls
    get_extractor and gets a FileNotFoundError.

    It must be CALLED OUT in the 'Not currently installed' line so the
    agent knows to pick something else.
    """
    _make_fake_checkpoints(
        tmp_path,
        [
            ("UNI2",     "pytorch_model.bin", 2_600_000_000),
            ("Virchow2", "pytorch_model.bin",             0),  # empty dir
            ("H-Optimus-1", "pytorch_model.bin",          0),  # empty dir
        ],
    )

    out = detect_hf_model_cache(ckpts_root=tmp_path)

    # UNI2 is installed.
    assert 'get_extractor("uni2")' in out

    # Virchow2 / H-Optimus-1 must NOT appear in the installed call-list
    # (the line that says get_extractor(...) with the key).
    installed_section = out.split("Not currently installed", 1)[0]
    assert 'get_extractor("virchow2")' not in installed_section
    assert 'get_extractor("H-Optimus-1")' not in installed_section

    # But they MUST appear in the 'Not currently installed' callout so
    # the agent sees the exclusion explicitly.
    assert "Not currently installed" in out
    assert "Virchow2" in out.split("Not currently installed", 1)[1]
    assert "H-Optimus-1" in out.split("Not currently installed", 1)[1]


def test_detect_hf_model_cache_treats_stub_files_as_missing(tmp_path):
    """A <1MB 'ckpt' file is almost certainly a Git LFS pointer or
    placeholder. Treat it as missing — the agent must not be told the
    extractor is installed when the file won't actually torch.load.
    """
    _make_fake_checkpoints(
        tmp_path,
        [
            ("UNI2", "pytorch_model.bin", 500),  # 500-byte stub
            ("CONCH", "pytorch_model.bin", 800_000_000),  # real
        ],
    )

    out = detect_hf_model_cache(ckpts_root=tmp_path)

    # CONCH is real and must appear.
    assert 'get_extractor("conch")' in out
    # UNI2 is a stub and must NOT appear as installed.
    installed_section = out.split("Not currently installed", 1)[0]
    assert 'get_extractor("uni2")' not in installed_section


def test_detect_hf_model_cache_empty_is_explicit(tmp_path):
    """No pathology FM checkpoints at all → block must say so explicitly
    and tell the agent ImageNet backbones are the remaining option."""
    # No dirs under tmp_path at all.

    out = detect_hf_model_cache(ckpts_root=tmp_path / "nonexistent")

    # Must not falsely claim any pathology FM is available.
    assert 'get_extractor("uni2")' not in out
    assert 'get_extractor("conch")' not in out
    # Must explicitly tell the agent why it's falling back.
    assert "no pathology" in out.lower() or "none usable" in out.lower()


def test_detect_hf_model_cache_warns_against_automodel(tmp_path):
    """Regression for session_9df3fa411bbf. Block must explicitly name
    the AutoModel anti-pattern and point at the registry as the only
    path — otherwise the agent reaches for the familiar AutoModel call
    and gets 'Unrecognized model ...'."""
    _make_fake_checkpoints(
        tmp_path,
        [("UNI2", "pytorch_model.bin", 2_600_000_000)],
    )

    out = detect_hf_model_cache(ckpts_root=tmp_path)

    assert "AutoModel" in out, "block must NAME the anti-pattern so agent recognizes it"
    # Must negate it.
    assert "Do NOT" in out or "do not" in out.lower() or "not use" in out.lower()
    # Canonical usage code must be present.
    assert "from common.extractors.registry import get_extractor" in out


def test_detect_hf_model_cache_surfaces_checkpoints_path(tmp_path):
    """The block must print the checkpoints/ path so the agent can
    verify what's actually on disk via the terminal tool before picking
    an extractor."""
    _make_fake_checkpoints(
        tmp_path,
        [("UNI2", "pytorch_model.bin", 2_600_000_000)],
    )

    out = detect_hf_model_cache(ckpts_root=tmp_path)

    assert str(tmp_path) in out


def test_detect_hf_model_cache_does_not_require_hf_token(tmp_path):
    """Regression for the 2026-04-22 overcorrection: previous block
    warned that Mahmood Lab gated repos need HF_TOKEN. That's
    misleading — when the ckpt is a pre-installed symlink under
    checkpoints/, checkpoint_manager's os.path.exists path is hit and
    no HF download (and therefore no token) is needed. The block must
    NOT push HF_TOKEN as a barrier to UNI/UNI2/CONCH usage."""
    _make_fake_checkpoints(
        tmp_path,
        [
            ("UNI2",  "pytorch_model.bin", 2_600_000_000),
            ("CONCH", "pytorch_model.bin",   800_000_000),
        ],
    )

    out = detect_hf_model_cache(ckpts_root=tmp_path)

    # Usage snippet must NOT demand an HF_TOKEN env var as part of the
    # normal path — that was misleading because ckpts are pre-installed.
    assert "HF_TOKEN" not in out, (
        "Block must not push HF_TOKEN as a prerequisite for the installed "
        "extractors; checkpoints are pre-provisioned and token is only "
        "consulted on the unreachable download branch."
    )
    assert 'get_extractor("uni2")' in out


def test_detect_hf_model_cache_handles_working_symlink(tmp_path):
    """The real checkpoints/<Name>/pytorch_model.bin entries are
    symlinks to /project/vcompath/storage/ywangrm/PrePATH_backup/ckpts/.
    Detection must follow the symlink and read the target's size, not
    the symlink inode (which is ~24 bytes and would falsely look like
    an LFS stub).
    """
    # Create real payload, then a symlink pointing at it.
    payload = tmp_path / "real_weights.bin"
    payload.write_bytes(b"\0" * 2_600_000_000)
    ckpts_root = tmp_path / "checkpoints"
    uni2_dir = ckpts_root / "UNI2"
    uni2_dir.mkdir(parents=True)
    (uni2_dir / "pytorch_model.bin").symlink_to(payload)

    out = detect_hf_model_cache(ckpts_root=ckpts_root)

    assert 'get_extractor("uni2")' in out


def test_detect_hf_model_cache_skips_dangling_symlink(tmp_path):
    """A dangling symlink (target missing) must be treated as a missing
    ckpt, not as an installed one. Otherwise the agent picks it and
    torch.load fails."""
    ckpts_root = tmp_path / "checkpoints"
    uni2_dir = ckpts_root / "UNI2"
    uni2_dir.mkdir(parents=True)
    (uni2_dir / "pytorch_model.bin").symlink_to(
        tmp_path / "does-not-exist.bin"
    )
    # Also add a real extractor so the function returns a usable list.
    conch_dir = ckpts_root / "CONCH"
    conch_dir.mkdir(parents=True)
    (conch_dir / "pytorch_model.bin").write_bytes(b"\0" * 800_000_000)

    out = detect_hf_model_cache(ckpts_root=ckpts_root)

    # UNI2 must NOT be in the installed list.
    installed_section = out.split("Not currently installed", 1)[0]
    assert 'get_extractor("uni2")' not in installed_section
    assert 'get_extractor("conch")' in out


def test_build_environment_context_includes_extractor_section():
    """build_environment_context must compose the extractor block into
    the full environment string. Uses the REAL checkpoints/ dir — the
    repo ships with UNI2 / CONCH / Virchow symlinks so we get a
    deterministic non-empty block."""
    out = build_environment_context()

    # The block must appear alongside GPU / packages / common libs.
    assert "Pre-installed pathology foundation models" in out
    # At least one well-known extractor must surface — if this test
    # flakes, it means the repo's checkpoints/ symlinks got mangled and
    # the LIVE agent would also see an empty block.
    assert 'get_extractor("uni2")' in out or 'get_extractor("conch")' in out
