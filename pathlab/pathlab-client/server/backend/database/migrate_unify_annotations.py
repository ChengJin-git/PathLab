"""
Migration script: Unify annotation storage
===========================================

This script performs a one-shot migration from the old `annotation_drafts` table
to the new `segmentation_annotations` table, renaming columns and adding new fields.

Run once:
    cd pathlab/pathlab-client/server
    python -m backend.database.migrate_unify_annotations

What it does:
  1. Renames table `annotation_drafts` → `segmentation_annotations`
  2. Renames column `draft_id` → `annotation_id`
  3. Adds columns `status` (default "draft") and `source` (default "viewer")
  4. Backfills `annotation_id` values: replaces "draft_" prefix with "annot_"
  5. Backfills `status` and `source` based on annotation content heuristics

Safe to run multiple times (idempotent) — each step checks before acting.
"""

import asyncio
import json
import logging
import sys
import os

# Ensure the server directory is on the path so imports work when run as a module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from sqlalchemy import text
from backend.database.database import engine

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("migrate_unify_annotations")


async def table_exists(conn, table_name: str) -> bool:
    result = await conn.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = :t)"
        ),
        {"t": table_name},
    )
    return result.scalar()


async def column_exists(conn, table_name: str, column_name: str) -> bool:
    result = await conn.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c)"
        ),
        {"t": table_name, "c": column_name},
    )
    return result.scalar()


async def migrate():
    async with engine.begin() as conn:
        # ──────────────────────────────────────────────────────────────────────
        # Step 1: Rename table annotation_drafts → segmentation_annotations
        # ──────────────────────────────────────────────────────────────────────
        old_exists = await table_exists(conn, "annotation_drafts")
        new_exists = await table_exists(conn, "segmentation_annotations")

        if old_exists and not new_exists:
            logger.info("Renaming table annotation_drafts → segmentation_annotations")
            await conn.execute(
                text("ALTER TABLE annotation_drafts RENAME TO segmentation_annotations")
            )
        elif old_exists and new_exists:
            logger.error(
                "Both annotation_drafts and segmentation_annotations exist! "
                "Please resolve manually before running this migration."
            )
            return
        elif not old_exists and new_exists:
            logger.info(
                "Table already renamed to segmentation_annotations — skipping step 1"
            )
        else:
            logger.warning(
                "Neither annotation_drafts nor segmentation_annotations exists. "
                "Nothing to migrate — the table will be created on next app startup."
            )
            return

        # ──────────────────────────────────────────────────────────────────────
        # Step 2: Rename column draft_id → annotation_id
        # ──────────────────────────────────────────────────────────────────────
        has_draft_id = await column_exists(conn, "segmentation_annotations", "draft_id")
        has_annotation_id = await column_exists(
            conn, "segmentation_annotations", "annotation_id"
        )

        if has_draft_id and not has_annotation_id:
            logger.info("Renaming column draft_id → annotation_id")
            await conn.execute(
                text(
                    "ALTER TABLE segmentation_annotations RENAME COLUMN draft_id TO annotation_id"
                )
            )
        elif has_draft_id and has_annotation_id:
            logger.error(
                "Both draft_id and annotation_id columns exist! "
                "Please resolve manually before running this migration."
            )
            return
        elif not has_draft_id and has_annotation_id:
            logger.info("Column already renamed to annotation_id — skipping step 2")
        else:
            logger.error(
                "Neither draft_id nor annotation_id column found — unexpected schema state"
            )
            return

        # ──────────────────────────────────────────────────────────────────────
        # Step 3: Add status column (if missing)
        # ──────────────────────────────────────────────────────────────────────
        if not await column_exists(conn, "segmentation_annotations", "status"):
            logger.info("Adding column: status (VARCHAR(20), default 'draft')")
            await conn.execute(
                text(
                    "ALTER TABLE segmentation_annotations "
                    "ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'draft'"
                )
            )
        else:
            logger.info("Column status already exists — skipping")

        # ──────────────────────────────────────────────────────────────────────
        # Step 4: Add source column (if missing)
        # ──────────────────────────────────────────────────────────────────────
        if not await column_exists(conn, "segmentation_annotations", "source"):
            logger.info("Adding column: source (VARCHAR(50), default 'viewer')")
            await conn.execute(
                text(
                    "ALTER TABLE segmentation_annotations "
                    "ADD COLUMN source VARCHAR(50) NOT NULL DEFAULT 'viewer'"
                )
            )
        else:
            logger.info("Column source already exists — skipping")

        # ──────────────────────────────────────────────────────────────────────
        # Step 5: Backfill annotation_id prefix (draft_ → annot_)
        # ──────────────────────────────────────────────────────────────────────
        result = await conn.execute(
            text(
                "UPDATE segmentation_annotations "
                "SET annotation_id = 'annot_' || SUBSTRING(annotation_id FROM 7) "
                "WHERE annotation_id LIKE 'draft\\_%'"
            )
        )
        if result.rowcount > 0:
            logger.info(
                f"Updated {result.rowcount} annotation_id values: draft_ → annot_"
            )
        else:
            logger.info("No annotation_id values with draft_ prefix — skipping")

        # ──────────────────────────────────────────────────────────────────────
        # Step 6: Backfill status and source based on content heuristics
        # ──────────────────────────────────────────────────────────────────────
        # Fetch all rows that still have the default values to inspect their content
        rows = await conn.execute(
            text(
                "SELECT id, annotation_id, annotations "
                "FROM segmentation_annotations "
                "WHERE status = 'draft' AND source = 'viewer'"
            )
        )
        rows = rows.fetchall()

        updated_count = 0
        for row in rows:
            row_id, annot_id, annotations = row[0], row[1], row[2]

            # Parse annotations to determine format
            annot_data = annotations if isinstance(annotations, dict) else {}
            if isinstance(annotations, str):
                try:
                    annot_data = json.loads(annotations)
                except (json.JSONDecodeError, TypeError):
                    annot_data = {}

            # Heuristic: COCO format has "images" key at top level
            is_coco = isinstance(annot_data, dict) and "images" in annot_data

            if is_coco:
                # COCO-format annotation — came from import or extraction
                new_status = "finalized"
                # Distinguish import vs extraction by annotation_id pattern
                if annot_id and annot_id.startswith("annot_"):
                    new_source = "import"
                else:
                    new_source = "import"  # safe default for COCO data
            else:
                # ROI map format (wsi_id → regions[]) — came from viewer
                new_status = "draft"
                new_source = "viewer"

            # Only update if values differ from defaults
            if new_status != "draft" or new_source != "viewer":
                await conn.execute(
                    text(
                        "UPDATE segmentation_annotations SET status = :s, source = :src WHERE id = :id"
                    ),
                    {"s": new_status, "src": new_source, "id": row_id},
                )
                updated_count += 1

        if updated_count > 0:
            logger.info(f"Backfilled status/source for {updated_count} rows")
        else:
            logger.info("No rows needed status/source backfill")

    logger.info("✅ Migration complete!")


def main():
    asyncio.run(migrate())


if __name__ == "__main__":
    main()
