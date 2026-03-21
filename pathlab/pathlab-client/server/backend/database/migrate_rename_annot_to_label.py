"""
One-time idempotent migration: rename annotation_id prefix 'annot_' -> 'label_'.

Safe to run multiple times: WHERE clause only matches 'annot_%' rows.
Must run BEFORE application code that uses the 'label_' prefix.
'shared_' prefixed rows are NOT affected.
"""

import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_SQL = text("""
    UPDATE segmentation_annotations
    SET annotation_id = 'label_' || substring(annotation_id FROM 7)
    WHERE annotation_id LIKE 'annot_%'
""")


async def run(db: AsyncSession) -> int:
    """Rename 'annot_' rows to 'label_'. Returns number of rows updated."""
    result = await db.execute(_SQL)
    await db.commit()
    count = int(result.rowcount or 0)
    if count > 0:
        logger.info("migrate_rename_annot_to_label: renamed %d rows", count)
    else:
        logger.debug("migrate_rename_annot_to_label: no rows to migrate (already done)")
    return count
