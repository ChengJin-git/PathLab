# Storage management

PathLab v1.0.8 · 2026-11-08

Settings → Storage uses a persistent, reference-aware inventory. Opening the page,
changing filters and paging read SQLite; none of these requests traverses storage.
The former `/storage/stats`, `/storage/orphaned*` and `/storage/reset-derived-data`
interfaces have been removed.

## Modules

- `inventory.py`: generation-based SQLite index, physical/logical sizes, reference
  graph, manifest cache and keyset pagination.
- `references.py`: streamed PostgreSQL references, result-bundle SQLite catalog,
  pending jobs and active TaskWorker state.
- `deletion.py`: transactional file-cleanup outbox, restart recovery, per-item
  receipts, change detection and reference revalidation.
- `manager.py`, `stats_mixin.py`: object-level storage information and metadata.
- `inspection_jobs.py`, `external_availability.py`: external file health checks.
- `migration.py`: whole-storage migration.

## Inventory and performance

`Config.get_uploads_dir()` resolves `PATHLAB_UPLOADS_DIR`, then `storage.json`, then
the application data directory. Its `.storage-inventory/inventory.sqlite3` uses WAL.
It contains one row per loose artifact or owned directory, not one row per input
symlink. Scans use `os.scandir` and never stat or traverse symlink targets; external
NAS data is outside the managed deletion scope.

The summary contains category totals, physical allocation, regular-file/link counts
and reclaimable sizes. Detail requests return at most 100 rows (UI: 50), sorted by
allocation and ID with a keyset cursor. Expensive work runs in ResearchWorker; a
scan publishes a new generation only after all phases succeed. Readers retain the
previous snapshot during scanning, failure or cancellation. Progress is based on
actual processed entries. No progress percentage is inferred from elapsed time.
Inventory refresh shares the deployment's heavy-scan lock with external health
checks, so two administrative scans do not saturate the same storage root.

Each published summary also stores item counts and allocation by category/state.
Every category includes all five reference states, including explicit zero counts
and sizes for states with no items. Writers and readers share this single contract.
The existing published snapshot was migrated once without changing its generation
or scan timestamp; the migration script was removed after verification.
Pages return the filtered total from that summary in the same read transaction,
without running a count query or walking the filesystem. The selection control
offers the current page or all filtered results; all-filtered selection stores
only exclusions, remains selected across pages, and resets when filters change.
Cleanup requires an explicit `scope: selected | all`; an empty selection never
implicitly expands to every file.

A synthetic 250,000-row inventory check returned 50-row pages in 2.13 ms median
(2.63 ms maximum over 20 pages, about 18.6 KB per response) on the development host.
These are indexed read timings, not a claim that a first full filesystem scan is
instantaneous. First scans also build manifest and research-event reference caches.

Text manifests cache extracted references by inode/size/mtime/ctime and the set of
local artifact identities. Repeated scans reuse unchanged manifests. Symlinks and
manifest references form edges between indexed items; reachability starts from
live business objects. Outgoing links inside an unreferenced, old input directory
do not indefinitely pin a global feature cache.

Research event references use an append-only ID cursor in the same SQLite index;
subsequent checks read only new events, and deleted sessions lose their cached
references. A textual path is normalized to its indexed owner rather than storing
millions of individual filenames inside a research input directory.

## Reclamation policy

- **In use**: referenced by a dataset image, model, experiment, saved analysis,
  result catalog, file-library record, chat reference or retained workspace.
- **Unused caches**: features/patching data whose source image still exists but
  which has no experiment consumer. Users can reclaim these; they regenerate on
  demand. Deletion also removes corresponding `FeatureArtifact` registrations.
- **Unreferenced**: known artifacts without an owner or incoming live reference.
- **Recent**: writes within 24 hours are retained by administrative scans. Explicit
  object-deletion intents bypass this grace after writers are idle.
- **Managed**: shared model weights, download caches, locks and unrecognized data.

Result catalogs protect derived slide data even when `wsi_slides` no longer has
the original slide. Saved inference rows are consumers even if the orchestration
task is missing. Feature consumers also protect their coordinates/metadata.
MRXS companion directories are indexed independently of the main `.mrxs` file.
The inventory includes research inputs, runtime, models, documents and metadata.

## Durable deletion

Object deletion writes a `StorageTask(task_type='file_cleanup')` in the **same
PostgreSQL transaction** as removing business records. Training/model/analysis,
single/batch image and conversation deletion use this outbox. Model registration
deletion and its file intent are inseparable; training no longer offers a mode
that silently leaves unregistered weights. Bulk intents coalesce before claim.

ResearchWorker owns a `StorageQueue`. It processes/retries pending, interrupted or
failed work under a storage-root writer lock. The operation manifest is durable
before bytes are removed, with completion receipts for each item. Settings
cleanup selects a specific inventory generation; it re-scans, refreshes current
business references and skips changed or newly referenced items. File fingerprints
are checked immediately before removal. Result deletion uses `AIResultStore`'s
cross-process lock and updates its catalog; cache deletion acquires existing cache
locks. Short PostgreSQL SHARE-lock windows close the reference-check/delete race
with new business registrations. Active compute/research defers deletion.
Large directories are atomically moved to private cleanup staging during that
short window; recursive removal happens after releasing the database locks. A
staging receipt allows an interrupted purge to resume. Artifacts retained for
another consumer are revisited when a subsequent object deletion removes that
consumer.

Cleanup jobs are internal and excluded from the general task list and expiration.
Settings displays the latest administrative operation with stop and error state.
Stopping preserves already completed work and prevents the next batch.

Missing images alone never authorize deleting saved inference results or models.
PostgreSQL's existing schema and `StorageTask` are reused; startup does not perform
historical backfills. Database housekeeping is not part of the storage panel.

## Admin API

- `GET /storage/inventory`: completed summary and latest operation.
- `POST /storage/inventory/scan`: durable, deduplicated scan admission (202).
- `GET /storage/inventory/items?category=&state=&cursor=&limit=50`: indexed page.
- `POST /storage/inventory/cleanup`: generation, state, category and explicit scope;
  `selected` requires IDs, `all` accepts excluded IDs (202).
- `DELETE /storage/inventory/operations/{id}`: stop an administrative operation.

All inventory endpoints require an administrator. Storage location, disk-space,
migration, object information, external health and batch registration interfaces
remain under `/storage`. Settings uses `StorageInventoryPanel`.
