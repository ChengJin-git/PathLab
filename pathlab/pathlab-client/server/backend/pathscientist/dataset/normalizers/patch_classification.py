"""Normalize a class-subdirectory patch dataset into prepared/images/<class>/*.

Raw layout expected:

    raw_root/
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

logger = logging.getLogger(__name__)

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")


class PatchClassificationNormalizer:
    name = "patch_classification"
    supported_task_types = {"patch_classification"}

    def supports(self, task_type: str) -> bool:
        return task_type in self.supported_task_types

    def prepare(self, raw_root: Path, prepared_root: Path) -> dict[str, Any]:
        raw_root = Path(raw_root)
        prepared_root = Path(prepared_root)
        images_dir = prepared_root / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        all_files: list[tuple[str, Path]] = []   # (class_name, dest_path)
        for class_dir in sorted(p for p in raw_root.iterdir() if p.is_dir()):
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

        # Deterministic 80/20 split based on sorted file paths so the
        # same raw layout always yields the same splits.
        all_files.sort(key=lambda t: str(t[1]))
        split = int(0.8 * len(all_files))
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
