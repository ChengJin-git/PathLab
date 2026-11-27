# Viewer, annotation and assistance

`/wsi/:wsi_id` displays a slide with OpenSeadragon. The canvas has one toolbar and an inspector
panel that switches between analysis results, annotations and the slide assistant. Results, objects
and assistance are each loaded on demand from their own endpoints.

## Results

Writing or deleting a result updates `ai_results_bundles/catalog.sqlite3` (SQLite WAL). Lists only
query this catalog and PostgreSQL permissions; ZIP files, coordinates and arrays are read once a
layer is opened. Query failure, no results and loading have distinct states.

- **Classification**: the predicted class and probability first, other classes by descending
  probability, minor classes collapsible.
- **Attention**: the 10 highest and 10 lowest patches per result (fewer if not available). Ranking
  and scores come from the saved raw weights; percentile clipping only affects heatmap colours.
  Thumbnails are cut from the real image extent, resized to 160 px, and clicking navigates there.
- **Detection**: saved labels are one-based class indices; classes, colours and counts correspond,
  with confidence and class filters.
- **Segmentation**: a legend is shown even for one class; channels and colours come from the
  backend's class palette.

Changing task, fold or slide clears the previous selection and cancels old requests. Attention
weights, class probabilities, detection scores and similarity are each shown with their own meaning.

## Object annotation

`ViewerRegion` stores rectangles or polygons with holes in level-0 coordinates, with label, layer,
task type, creator, last editor and revision. Personal objects belong to the current user; team
objects are edited by the dataset owner or an administrator. Switching layers does not copy objects;
publishing or copying a selection is an explicit action.

| Endpoint | Purpose |
| --- | --- |
| `GET /viewer/slides/{id}/context` | Slide information, permissions, neighbouring slides |
| `GET /viewer/slides/{id}/regions` | Query by layer, cursor and optional viewport |
| `POST /viewer/slides/{id}/regions` | Create, update or delete objects |
| `POST /viewer/slides/{id}/regions/selection` | Refresh selected objects and deletion tombstones |
| `POST /viewer/slides/{id}/geometry` | Union, subtract, split, brush and erase |
| `GET /viewer/slides/{id}/events` | Object changes and access revocation |
| `POST /viewer/slides/{id}/reference-labels` | Publish selected objects as reference labels |

Writes carry an `operation_id`, a `layer` and up to 100 `{id, revision, value}` changes;
`value: null` deletes. A stale revision returns 409; repeating the same operation returns the saved
receipt. `ViewerOperation` records the request fingerprint and response in the same transaction.

Annotation lists show 50 items per page. The canvas loads 500 objects per batch for the current
viewport and keeps at most 2,000, asking the user to zoom in when an area is dense. Unfinished
operations are kept in `sessionStorage` per user, slide and layer and can be retried, saved as a copy
or discarded. Undo and redo check the current revision so remote edits are not overwritten.

The SSE stream re-validates account, session, slide, team permission and workspace every two seconds
and sends only change stamps or revocation notices; the client then refreshes objects.

## Reference labels and derived data

`SegmentationAnnotation` only stores published COCO reference labels. Publishing requires dataset
management rights and the current object revision, updates the selected objects by
`viewer_region_id` and keeps other labels; geometry with holes is stored both as standard RLE and as
exact editing coordinates. Regions on whole slides are first extracted as patches before spatial
labels are published.

`POST /annotation/extract` reads saved objects from the selected layer (or explicit ROIs) within the
dataset scope, checks access and geometry per image, and creates a derived dataset that records
source image, ROI and lineage. The derived dataset belongs to the user who created it.

Any user who can read a slide can create personal objects; team edits and reference-label publication
require dataset management rights (owner or administrator). See
[permissions](../../permissions/README.md).

## Assistance

All endpoints below are prefixed with `/viewer/slides/{id}`: `/capabilities` lists available features
and installed prompt models, `/assist` provides local assistance, `/search` searches existing features
and `/assistant` interprets natural-language requests.

Similar-colour selection, GrabCut, a random forest on positive/negative examples and dark-nucleus
candidates run on local CPU crops (longest side 768 px, at most 8 cached, CPU concurrency 2). Results
are previews until the user saves them as annotations.

The slide assistant only handles simple localisation, measurement, filtering and annotation on the
current slide. The model returns `scope: local | main_workspace` and typed actions; complex or
multi-step requests return a `handoff` that carries dataset, slide and the original question to the
main chat. A simple request that only lacks a selection stays in the side panel and asks for one.

Rules for feature versions, coordinates and image–text alignment are in
[FEATURE-ARTIFACTS.md](FEATURE-ARTIFACTS.md). Missing capabilities are reported with a reason; the
viewer never downloads weights, extracts features or recomputes a whole slide on its own.

An optional EfficientSAM ONNX model can be placed in `viewer_models/<id>/model.json` with `id`,
`name`, `family: efficient_sam` and local relative paths `encoder` and `decoder`. The encoder takes a
`[1,3,H,W]` RGB input in `[0,1]`; the decoder uses `image_embeddings`, `batched_point_coords`,
`batched_point_labels` and optionally `orig_im_size`. The exported model handles its own
preprocessing. This adapter has not yet been validated with real EfficientSAM weights.

## Code

Client: `components/wsiViewer/`, `pages/WSIViewerPage.tsx`. Gateway: `routes/viewer.py`,
`heatmap.py`, `annotation.py`. Services: `viewer_*.py`; result catalog: `backend/ai/result_catalog.py`.

Tests: `test_viewer_workspace.py`, `test_viewer_postgres.py`, `test_viewer_attention_patches.py`,
`test_viewer_result_classes.py`, `test_viewer_assistant_scope.py`, `test_annotation_workflow.py`.
Browser tests are described in [test/README.md](../../../test/README.md).
