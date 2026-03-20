-- PathLab migration: normalize shared-annotation semantics
-- Safe to run multiple times on PostgreSQL.

BEGIN;

-- 1) Remove legacy inherit mode from stored annotations.
UPDATE segmentation_annotations
SET visibility_mode = 'personal'
WHERE visibility_mode IS NULL OR visibility_mode = 'inherit';

ALTER TABLE segmentation_annotations
    ALTER COLUMN visibility_mode SET DEFAULT 'personal';

ALTER TABLE segmentation_annotations
    ADD CONSTRAINT ck_segmentation_annotations_visibility_mode
    CHECK (visibility_mode IN ('personal', 'shared'));

-- 2) Ensure dataset collaboration flag never stays enabled on private datasets.
UPDATE datasets
SET is_open_collaboration = FALSE
WHERE COALESCE(is_public, FALSE) = FALSE
  AND COALESCE(is_open_collaboration, FALSE) = TRUE;

ALTER TABLE datasets
    ALTER COLUMN is_public SET DEFAULT FALSE;

ALTER TABLE datasets
    ALTER COLUMN is_open_collaboration SET DEFAULT FALSE;

ALTER TABLE datasets
    ADD CONSTRAINT ck_datasets_open_collab_requires_public
    CHECK (
        COALESCE(is_public, FALSE) = TRUE
        OR COALESCE(is_open_collaboration, FALSE) = FALSE
    );

COMMIT;

