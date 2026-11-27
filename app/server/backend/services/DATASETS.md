# Datasets and upload

`/datasets` is the data repository; `/upload` creates a dataset or adds images and labels to an
existing one. The same images can serve several tasks; each task's configuration and labels are
stored separately.

## Data and tasks

`Dataset` stores name, image type, aggregation level, owner, public flag, organ, description,
metadata and revision; `DatasetTask` stores the task list and task descriptions. `DataGroup`
describes the type combination of a training task and does not own datasets.

| Task | Canonical ID | Image type |
| --- | --- | --- |
| Whole-slide classification | `wsi_classification` | `wsi` |
| Patch classification | `patch_classification` | `patch` |
| Survival analysis | `wsi_survival` | `wsi` |
| Detection | `patch_detection` | `patch` |
| Segmentation | `patch_segmentation` | `patch` |

The interface lists tasks as classification, survival, detection and segmentation. "Patch" is an
image tile used as a sample; "tile" refers to the viewer's display tiles.

Classification labels and survival outcomes are separate slide columns. Detection and segmentation
COCO records are separated by `task_type`. Adding a task never overwrites another task's labels, and
a task that has labels cannot simply be removed from a dataset.

## Create, edit and append

- `POST /wsi/datasets` — create a dataset with `task_types`, `data_type`, `aggregation_level` and
  metadata.
- `PATCH /wsi/datasets/{dataset_id}/properties` — atomic property update with a revision check; the
  task combination, existing image type and name conflicts are validated and statistics recomputed
  when needed.
- `POST /wsi/datasets/{dataset_id}/labels` — match existing images by original file name and append
  tasks, classification or survival fields and per-task COCO labels; at most 10,000 table rows per
  request.

Case-level data needs real `case_id`s, and one case cannot be split across train, validation and
test. Follow-up time and event status must be given together; a time of 0 and a censoring value of 0
are valid. COCO files must list negative images: an empty annotation list is different from a missing
annotation.

Upload de-duplication uses `{dataset_id, filenames}` (up to 1,000 names per call) within the target
dataset only; a file name is a key inside one dataset, not a global identity. Retrying a single file
reuses its upload ID and a successful receipt.

The browser accepts files, folders and recursive drag-and-drop; MRXS and TMAP companion files are
paired with their main image. CSV files carry table labels and XLSX files are converted and parsed
the same way. Upload tables render page by page and the background progress publishes at most one
snapshot every 250 ms.

## Visibility and writes

Read access is resolved by `dataset_access.accessible_dataset_ids()`: owners and administrators read
and write; public datasets are readable by every signed-in user. Models and results belong to their
owners; a public image never makes someone else's results visible.

Upload candidates use `purpose=upload`: users can only choose their own datasets, administrators all
datasets, and the current workspace narrows the list further. The restriction is applied in SQL
before paging; target lookups and writes are authorised again.

`parent_dataset_id` only records lineage; a derived dataset belongs to the user who created it.

Downloaded datasets are identified by a stable provider and source ID. Re-downloading keeps manual
corrections, visibility and existing labels; URL, license, organ and import records are kept in the
acquisition metadata.

## Code

- `gateway/routes/dataset_catalog.py` — creation, properties, label import.
- `services/dataset_catalog.py` — task combinations, metadata validation, label summaries.
- `gateway/routes/wsi_upload.py` — image upload, de-duplication, writes.
- `services/dataset_access.py` — dataset access and management rights.
- `src/renderer/src/pages/UploadPage.tsx`, `ListPage.tsx` — upload page and data repository.

Tests: `test_dataset_catalog_and_result_privacy.py`, `test_manual_upload_contract.py`,
`test_upload_dataset_visibility.py`, `test_wsi_split_upload.py`, and the frontend upload and data
repository tests.
