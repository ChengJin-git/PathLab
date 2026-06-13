"""One-off script to backfill cached recommendation heatmap previews."""
from __future__ import annotations

import asyncio
import argparse

from backend.common.config import Config
from backend.database import async_session
from backend.database.repositories import WSIRepository

try:
    from .heatmap_preview_cache import ensure_recommendation_preview_cache
except ImportError:  # pragma: no cover - supports direct script execution
    from backend.preprocessing.heatmap_preview_cache import ensure_recommendation_preview_cache


async def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill cached recommendation heatmap previews")
    parser.add_argument("--overwrite", action="store_true", help="Regenerate previews even if they already exist")
    parser.add_argument("--wsi-id", help="Only process a specific WSI ID")
    args = parser.parse_args()

    uploads_dir = Config.get_uploads_dir()
    ai_results_dir = uploads_dir / "ai_results"
    if args.wsi_id:
        attention_files = sorted((ai_results_dir / args.wsi_id).glob("*_attention.npy"))
    else:
        attention_files = sorted(ai_results_dir.glob("*/*_attention.npy"))

    wsi_ids = sorted({attention_file.parent.name for attention_file in attention_files})
    async with async_session() as db:
        wsi_map = await WSIRepository.get_by_ids(db, wsi_ids)

    generated = 0
    skipped = 0
    failed = 0

    for attention_file in attention_files:
        wsi_id = attention_file.parent.name
        wsi = wsi_map.get(wsi_id)
        if wsi is None:
            failed += 1
            print(f"[fail] {wsi_id}: missing WSI record in database")
            continue

        preview_path = attention_file.with_name(
            attention_file.stem.replace("_attention", "") + "_recommendation_preview.png"
        )
        existed_before = preview_path.exists()
        was_fresh_before = existed_before and preview_path.stat().st_mtime >= attention_file.stat().st_mtime
        preview_path = ensure_recommendation_preview_cache(
            wsi_id,
            attention_file,
            uploads_dir,
            overwrite=args.overwrite,
            wsi_path=wsi.wsi_path,
            file_size=wsi.file_size,
        )
        if preview_path is None:
            failed += 1
        elif was_fresh_before and not args.overwrite:
            skipped += 1
            print(f"[skip] {wsi_id}: {preview_path.name}")
        else:
            generated += 1
            print(f"[ok] {wsi_id}: {preview_path.name}")

    total = len(attention_files)
    print(f"done: total={total} generated={generated} skipped={skipped} failed={failed}")


if __name__ == "__main__":
    asyncio.run(main())