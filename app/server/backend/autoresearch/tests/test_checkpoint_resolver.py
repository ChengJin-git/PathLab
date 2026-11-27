from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def test_default_checkpoint_root_uses_pathlab_ai_checkpoint_dir(monkeypatch):
    monkeypatch.delenv("PATHLAB_CKPT_DIR", raising=False)

    resolver = importlib.import_module(
        "autoresearch.domain.templates.common.extractors.checkpoint_resolver"
    )

    expected = Path(__file__).resolve().parents[2] / "ai" / "extractors" / "checkpoints"
    assert resolver.checkpoint_root() == expected


def test_resolve_model_file_falls_back_to_bundled_checkpoints(monkeypatch, tmp_path):
    monkeypatch.delenv("PATHLAB_CKPT_DIR", raising=False)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")

    resolver = importlib.import_module(
        "autoresearch.domain.templates.common.extractors.checkpoint_resolver"
    )
    main_root = tmp_path / "pathlab-main"
    bundled_root = tmp_path / "autoresearch-bundled"
    (bundled_root / "Virchow2").mkdir(parents=True)
    expected = bundled_root / "Virchow2" / "pytorch_model.bin"
    expected.write_bytes(b"weights")

    monkeypatch.setattr(resolver, "_pathlab_checkpoint_root", lambda: main_root)
    monkeypatch.setattr(resolver, "_bundled_checkpoint_root", lambda: bundled_root)

    resolved = resolver.resolve_model_file(
        resolver.ModelFileSpec(
            "Virchow2",
            "Virchow2",
            "paige-ai/Virchow2",
            ("pytorch_model.bin", "model.safetensors"),
        ),
        allow_download=False,
    )

    assert resolved == expected
