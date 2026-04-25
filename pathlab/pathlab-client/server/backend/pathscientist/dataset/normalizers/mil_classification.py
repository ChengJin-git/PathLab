"""Normalize a WSI/MIL dataset into prepared/slides/*.

Raw layout expected (any of):

    raw_root/slides/*.{svs,tiff,tif,ndpi,mrxs}
    raw_root/*.{svs,tiff,tif,ndpi,mrxs}

Prepared layout produced:

    prepared_root/slides/*.{svs,...}    (symlinks where possible)
    prepared_root/labels.csv            (slide_id, label) — empty if no
                                         labels.csv was found in raw

Always returns ``requires_feature_extraction = True`` because the v1
skill chain expects a feature-extraction step before MIL training.
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_WSI_EXTS = (".svs", ".tif", ".tiff", ".ndpi", ".mrxs", ".scn", ".vms", ".vmu")


class MILClassificationNormalizer:
    name = "mil_classification"
    supported_task_types = {"mil_classification"}

    def supports(self, task_type: str) -> bool:
        return task_type in self.supported_task_types

    def prepare(self, raw_root: Path, prepared_root: Path) -> dict[str, Any]:
        raw_root = Path(raw_root)
        prepared_root = Path(prepared_root)
        slides_dir = prepared_root / "slides"
        slides_dir.mkdir(parents=True, exist_ok=True)

        # Find slides: prefer raw_root/slides/, fall back to scanning root.
        candidate_dirs = []
        if (raw_root / "slides").is_dir():
            candidate_dirs.append(raw_root / "slides")
        else:
            candidate_dirs.append(raw_root)

        slide_count = 0
        for src_dir in candidate_dirs:
            for src in sorted(src_dir.rglob("*")):
                if not src.is_file():
                    continue
                if src.suffix.lower() not in _WSI_EXTS:
                    continue
                dest = slides_dir / src.name
                if dest.exists():
                    continue
                try:
                    os.symlink(src.resolve(), dest)
                except OSError:
                    shutil.copy2(src, dest)
                slide_count += 1

        # Carry through labels.csv if present; otherwise leave empty.
        labels_src = raw_root / "labels.csv"
        labels_dest = prepared_root / "labels.csv"
        if labels_src.exists():
            shutil.copy2(labels_src, labels_dest)
        else:
            labels_dest.write_text("slide_id,label\n")

        return {
            "task_type": "mil_classification",
            "wsi_dir": str(slides_dir),
            "labels_file": str(labels_dest),
            "requires_feature_extraction": True,
            "data_mounts": {str(prepared_root): "/data"},
            "n_slides": slide_count,
        }
