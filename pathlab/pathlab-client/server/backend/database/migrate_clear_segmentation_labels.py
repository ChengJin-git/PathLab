"""
One-shot migration script to clear image-level labels from segmentation datasets.

Dry run:
    cd pathlab/pathlab-client/server
    python -m backend.database.migrate_clear_segmentation_labels

Apply changes:
    cd pathlab/pathlab-client/server
    python -m backend.database.migrate_clear_segmentation_labels --apply
"""

import asyncio
import logging
import os
import sys

from sqlalchemy import text

# Ensure the server directory is on the path so imports work when run as a module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.database.database import engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migrate_clear_segmentation_labels")


async def fetch_affected_rows(conn):
    result = await conn.execute(
        text(
            """
            SELECT d.dataset_id, d.name, COUNT(*) AS affected_count
            FROM wsi_slides AS w
            JOIN datasets AS d ON d.dataset_id = w.dataset_id
            JOIN data_groups AS g ON g.group_id = d.group_id
            WHERE g.task_type = :task_type
              AND w.label IS NOT NULL
            GROUP BY d.dataset_id, d.name
            ORDER BY affected_count DESC, d.name ASC
            """
        ),
        {"task_type": "segmentation"},
    )
    return result.mappings().all()


async def clear_labels(conn) -> int:
    result = await conn.execute(
        text(
            """
            UPDATE wsi_slides AS w
            SET label = NULL,
                updated_at = CURRENT_TIMESTAMP
            FROM datasets AS d, data_groups AS g
            WHERE w.dataset_id = d.dataset_id
              AND d.group_id = g.group_id
              AND g.task_type = :task_type
              AND w.label IS NOT NULL
            """
        ),
        {"task_type": "segmentation"},
    )
    return result.rowcount or 0


async def main(apply_changes: bool) -> None:
    async with engine.begin() as conn:
        affected = await fetch_affected_rows(conn)

        if not affected:
            logger.info("No segmentation WSI labels found. Nothing to clean.")
            return

        total = sum(int(row["affected_count"] or 0) for row in affected)
        logger.info("Found %s segmentation WSI records with non-null labels.", total)
        for row in affected[:20]:
            logger.info(
                "  - %s (%s): %s rows",
                row["name"],
                row["dataset_id"],
                row["affected_count"],
            )

        if not apply_changes:
            logger.info("Dry run only. Re-run with --apply to clear these labels.")
            return

        cleared = await clear_labels(conn)
        logger.info("Cleared labels for %s segmentation WSI records.", cleared)


if __name__ == "__main__":
    asyncio.run(main("--apply" in sys.argv[1:]))