# Performance and responsiveness

This page describes how the application stays responsive and how to measure it. Performance
numbers must come from measurements on the target system; data size, GPU load, browser cache,
network and disk all affect them.

## Implementation

- Chat is loaded with the workbench and keeps its instance; other routes and analysis charts load on
  demand, and ExcelJS only for conversion and export. The PWA precaches the entry and caches visited
  routes at run time.
- `/datasets` and `/upload` show layout skeletons during authentication, module loading and data
  fetching; navigation hover or focus preloads their code.
- The results page reads paginated `result_sources` metadata; the first screen does not query all
  slides, model files or analysis directories. Analysis details, history, sample pages and charts
  load separately; evaluation candidates are checked for compatibility on the server.
- Statistical analyses run in separate CPU processes and continue after leaving the page; only the
  current analysis and a lightweight background list are polled.
- Storage statistics return the persisted snapshot immediately; one background scan with
  `os.scandir` publishes atomically. Changing directories invalidates older scans. Without a first
  snapshot the page shows "calculating" rather than zero.
- Dataset edits report success as soon as they are saved; lists and filters refresh in the
  background, and invalidated caches reject late writes.
- Viewer result lists query the SQLite WAL catalog and permissions and open layer content on demand,
  never every ZIP, HDF5 or attention array.
- Annotations are queried per slide and viewport: 50 per list page, 500 per canvas batch, at most
  2,000 on the canvas; saves use revisions and idempotent operation IDs.
- Feature search reuses `FeatureArtifact`; local assistance runs on the CPU with bounded caches
  ([VIEWER.md](../../server/backend/services/VIEWER.md)).
- Deleting a conversation removes it in the client at once; the API only waits for the database
  commit and a retryable worker finishes process and file clean-up.
- Chat uses bounded, access-checked retrieval and short caches; optional RAG warm-up never blocks a
  conversation.
- GPU admission is controlled by resource estimates and memory leases; waiting jobs do not occupy
  execution slots ([GPU-SCHEDULING.md](../../server/task_worker/GPU-SCHEDULING.md)).

## Measuring

1. Use the same production build, data snapshot and role; record browser, CPU/GPU, network and
   storage.
2. Record cold and warm caches separately, with fixed network conditions and a known service-worker
   state.
3. Record three moments: API response, page interactive and background task finished. "Submitted" is
   not "computed".
4. Check task and slide counts and output consistency, then compare medians and ranges over several
   runs.
5. Use a dedicated account and isolated data; remove scripts, credentials, screenshots and outputs
   afterwards.

Related tests: backend `test_result_workbench.py`, `test_storage_stats_snapshot.py`,
`test_mutation_responsiveness.py`, `test_annotation_workflow.py`, `test_chat_deletion.py`,
`test_viewer_*.py`, and the frontend cache, background SSE, data repository and browser tests
([test/README.md](../../test/README.md)).
