#!/usr/bin/env python3
"""Database migration: convert legacy task_type values to canonical IDs.

Run this script after deploying the canonical task taxonomy code.
It updates the data_groups table in-place, mapping legacy strings
(e.g. 'classification', 'survival', 'segmentation') to canonical IDs
(e.g. 'wsi_classification', 'wsi_survival', 'patch_segmentation').

Invalid combinations (patch/case classification, patch survival) that
have zero datasets are deleted.  external_validation groups are left
untouched because they represent inference operations, not training
families.
"""

import asyncio
import logging
from typing import Any

from sqlalchemy import text

from backend.database.database import safe_session

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


LEGACY_TO_CANONICAL: dict[tuple[str, str, str], str | None] = {
    ("classification", "wsi", "case"): "wsi_classification",
    ("classification", "wsi", "file"): "wsi_classification",
    ("classification", "patch", "file"): "patch_classification",
    ("classification", "patch", "case"): None,
    ("survival", "wsi", "case"): "wsi_survival",
    ("survival", "wsi", "file"): "wsi_survival",
    ("survival", "patch", "file"): None,
    ("segmentation", "patch", "file"): "patch_segmentation",
}


async def _get_legacy_groups(db) -> list[dict[str, Any]]:
    canonical_ids = (
        "wsi_classification",
        "patch_classification",
        "wsi_survival",
        "patch_segmentation",
    )
    placeholders = ", ".join(f"'{t}'" for t in canonical_ids)
    sql = text(f"""
        SELECT group_id, name, task_type, data_type, aggregation_level,
               (SELECT COUNT(*) FROM datasets d WHERE d.group_id = dg.group_id) AS dataset_count
        FROM data_groups dg
        WHERE task_type NOT IN ({placeholders})
        ORDER BY task_type, data_type, aggregation_level
    """)
    result = await db.execute(sql)
    rows = result.mappings().all()
    return [dict(row) for row in rows]


async def _delete_group(db, group_id: str) -> None:
    await db.execute(
        text("DELETE FROM data_groups WHERE group_id = :gid"),
        {"gid": group_id},
    )


async def migrate() -> None:
    async with safe_session() as db:
        legacy_groups = await _get_legacy_groups(db)
        if not legacy_groups:
            logger.info("No legacy task_type values found in data_groups. Nothing to migrate.")
            return

        logger.info(f"Found {len(legacy_groups)} data_group(s) with legacy task_type:")
        for g in legacy_groups:
            logger.info(
                f"  • {g['group_id']}: {g['task_type']} ({g['data_type']}/{g['aggregation_level']}) – {g['dataset_count']} dataset(s)"
            )

        updated = 0
        deleted = 0
        skipped = 0

        for g in legacy_groups:
            key = (g["task_type"], g["data_type"], g["aggregation_level"])
            
            if g["task_type"] == "external_validation":
                logger.info(f"  Skipping external_validation group {g['group_id']}")
                skipped += 1
                continue
            
            canonical = LEGACY_TO_CANONICAL.get(key)

            if canonical is None:
                if g["dataset_count"] > 0:
                    logger.error(
                        f"  ABORT: cannot delete group {g['group_id']} – it has {g['dataset_count']} dataset(s). "
                        f"Manual intervention required."
                    )
                    skipped += 1
                    continue
                logger.info(f"  Deleting invalid group {g['group_id']} ({'/'.join(key)})")
                await _delete_group(db, g["group_id"])
                deleted += 1
                continue

            # Update task_type (and try to fix the name)
            old_name = g["name"]
            new_name = old_name.replace(g["task_type"].capitalize(), canonical.replace("_", " ").title())
            await db.execute(
                text("""
                    UPDATE data_groups
                    SET task_type = :tt, name = :name
                    WHERE group_id = :gid
                """),
                {"tt": canonical, "name": new_name, "gid": g["group_id"]},
            )
            logger.info(f"  Updated {g['group_id']}: {g['task_type']} → {canonical} (name: '{old_name}' → '{new_name}')")
            updated += 1

        await db.commit()

        logger.info(
            f"Migration complete: {updated} updated, {deleted} deleted, {skipped} skipped."
        )


if __name__ == "__main__":
    asyncio.run(migrate())
