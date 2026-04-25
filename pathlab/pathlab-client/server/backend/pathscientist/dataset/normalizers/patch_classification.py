"""Normalize a class-subdirectory patch dataset into prepared/images/<class>/*.

Raw layout expected:

    raw_root/
      <class_a>/*.png
      <class_b>/*.png

Or (single-top-level archive extraction pattern):

    raw_root/
      <archive_inner>/
        <class_a>/*.png
        <class_b>/*.png

Prepared layout produced:

    prepared_root/
      images/
        <class_a>/*.png    (copied via os.symlink when on the same fs;
                            falls back to shutil.copy2 otherwise)
        <class_b>/*.png
      splits.json          (deterministic: alphabetical paths, 80/20 train/val)

Returns a contract dict consumable by the patch_classification skill.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from .base import NormalizerError

logger = logging.getLogger(__name__)

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")


class PatchClassificationNormalizer:
    name = "patch_classification"
    supported_task_types = {"patch_classification"}

    def __init__(self, min_classes: int = 2):
        self._min_classes = min_classes

    def supports(self, task_type: str) -> bool:
        return task_type in self.supported_task_types

    def _find_class_root(self, raw_root: Path) -> Path | None:
        """Locate the directory whose immediate subdirs are class folders.

        - If ``raw_root`` itself has >=1 subdir whose contents are images,
          ``raw_root`` is the class root.
        - Else if ``raw_root`` has exactly one subdir AND that subdir has
          >=1 subdir of images, use the inner subdir (handles archives
          that extract as ``raw/<dataset_name>/<class>/*``).
        - Otherwise return ``None``.
        """
        def _has_image_subdirs(p: Path) -> bool:
            try:
                subdirs = [d for d in p.iterdir() if d.is_dir()]
            except OSError:
                return False
            if not subdirs:
                return False
            for sd in subdirs:
                try:
                    for f in sd.iterdir():
                        if f.is_file() and f.suffix.lower() in _IMAGE_EXTS:
                            return True
                except OSError:
                    continue
            return False

        if not raw_root.is_dir():
            return None
        if _has_image_subdirs(raw_root):
            return raw_root
        children = [c for c in raw_root.iterdir() if c.is_dir()]
        if len(children) == 1 and _has_image_subdirs(children[0]):
            return children[0]
        return None

    def prepare(self, raw_root: Path, prepared_root: Path) -> dict[str, Any]:
        raw_root = Path(raw_root)
        prepared_root = Path(prepared_root)
        class_root = self._find_class_root(raw_root)
        if class_root is None:
            raise NormalizerError(
                f"unsupported_layout: no class subdirectories found under {raw_root}"
            )
        images_dir = prepared_root / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        all_files: list[tuple[str, Path]] = []   # (class_name, dest_path)
        class_dirs_seen: set[str] = set()
        for class_dir in sorted(p for p in class_root.iterdir() if p.is_dir()):
            class_name = class_dir.name
            dest_class_dir = images_dir / class_name
            dest_class_dir.mkdir(parents=True, exist_ok=True)
            for src in sorted(class_dir.iterdir()):
                if not src.is_file():
                    continue
                if src.suffix.lower() not in _IMAGE_EXTS:
                    continue
                dest = dest_class_dir / src.name
                if not dest.exists():
                    try:
                        os.symlink(src.resolve(), dest)
                    except OSError:
                        # Fallback: copy when symlink isn't available
                        # (e.g. cross-device).
                        shutil.copy2(src, dest)
                all_files.append((class_name, dest))
                class_dirs_seen.add(class_name)

        if not all_files:
            raise NormalizerError("no_images")
        if len(class_dirs_seen) < self._min_classes:
            raise NormalizerError(
                f"insufficient_classes:{len(class_dirs_seen)} (need >= {self._min_classes})"
            )

        # Deterministic 80/20 split based on sorted file paths so the
        # same raw layout always yields the same splits.  Clamp so each
        # side has at least 1 sample when len >= 2.
        all_files.sort(key=lambda t: str(t[1]))
        n = len(all_files)
        split = int(0.8 * n)
        if n >= 2:
            split = max(1, min(split, n - 1))
        train = [{"path": str(p), "label": cls} for cls, p in all_files[:split]]
        val = [{"path": str(p), "label": cls} for cls, p in all_files[split:]]
        splits_file = prepared_root / "splits.json"
        splits_file.write_text(json.dumps({"train": train, "val": val}, indent=2))

        return {
            "task_type": "patch_classification",
            "images_dir": str(images_dir),
            "splits_file": str(splits_file),
            "data_mounts": {str(prepared_root): "/data"},
            "n_train": len(train),
            "n_val": len(val),
        }
