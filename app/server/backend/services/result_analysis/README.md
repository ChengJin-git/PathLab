# Results analysis workbench

PathLab v1.0.8 · Updated 2026-11-06

`/results` opens saved results first. Users select a single experiment, explicitly enter
comparison mode for multiple sources, and choose **Add analysis** for a goal-oriented
analysis. Statistical parameters are under **Advanced settings**. Model evaluation and
prediction generation live separately at `/evaluate`.

## Inputs and persistence

- `result_sources` / `result_source_datasets`: indexed titles, task families, prediction
  capabilities, split counts, recorded metrics and provenance. Lists use 20-row pages;
  they do not scan models, feature files, images or analysis directories.
- `result_analyses`: durable queued/running/completed/failed/cancelled work, exact
  configuration, source revisions and measured result document.
- `result_recipes`: owner-scoped reusable settings with revision-checked updates.
- `result_conversations`: owner/workspace-scoped page-assistant history with revisions.

Training completion, model publication, native analysis publication and research
publication update the catalog. Predictions can remain analyzable after model files
are unavailable. Source dataset authorization is rechecked on list, execution, display,
export and assistant access. Deleted dataset identities remain provenance records.

Result ownership is checked separately from image visibility. Administrators can read all sources; pathologists read their own. Public datasets do not expose another user's predictions, models or analysis outputs.

Research outputs use `pathlab-analysis-v1` with optional explicit `tasks` (subtask IDs,
titles, task types and metric/chart keys). Unknown types stay custom; titles are never
used to infer scientific task semantics. Technical run names display their original
research question, with experiment iteration separately visible.

Optional `predictions` declares a JSONL artifact with ordered classes, task type and
evaluation unit. `artifacts.py` validates finite values, probability normalization,
unique sample/split identities, 500,000 rows / 256 MiB bounds and SHA-256. Re-analysis
verifies the published digest. Arbitrary artifact names are never guessed as predictions.

## Execution

`POST /results/workbench/runs` persists a job before submitting a `results.analysis`
descriptor to TaskWorker. Two CPU slots are independent of the GPU scheduler. Each
calculation runs in a killable subprocess with CUDA hidden and CPU thread bounds.
Leaving the page or closing the browser only stops browser polling; it does not cancel
the job. Explicit cancellation kills the subprocess before marking running work cancelled.
Worker startup marks interrupted work, recovers queued work, and periodically redelivers
queued records to cover the database/queue publication window.

`<uploads>/analysis-workbench/<id>/` contains the frozen input, source-code snapshot,
input digest, log, result document, and indexed JSONL sample pages (50 records/page).
Only plot previews are downsampled; metric and bootstrap computation uses complete inputs.

Semantics: explicit split (including OOF), file/case unit, positive class, macro/micro/
weighted/binary averaging, threshold, subgroup and percentile cluster-bootstrap settings.
Case probabilities/risk are equal-slide means with conflicting targets rejected.
Unknown/undefined metrics remain missing, not zero. AP is average precision; multiclass
Brier is the sum over classes. IBS uses the evaluation cohort censoring distribution;
segmentation uses saved per-image metrics and exact 0.01-step threshold histograms;
detection uses COCO bbox matching and mAP, with separate confidence/IoU operating
points. Cohort fingerprints identify paired comparisons. Expanded sample previews
show classification probabilities/CAM, segmentation GT/predicted masks at the
analysis threshold, detection boxes and survival risk/attention when available.

## Page assistant

The Settings-configured LLM receives bounded, authorized summaries and the current
configuration. Its structured response can explain, configure, run or hand off to the
main assistant. Manual and LLM execution use the same validated service. The server
rejects source substitutions, unknown metrics and unsupported task combinations. Read-only
requests cannot submit computations. Results are only described as measured after actual
job completion. Custom code/retraining is handed to the main assistant with resource references.

## Migration and verification

Current schema: `20261105_verified_feature_inventory`. Analysis jobs expose persisted progress and phase in the global Background tasks panel. Matching authorized input revisions/configurations reuse completed calculations. Fresh databases initialize the current schema; existing databases must match its version. Startup performs no historical backfill.

Tests: `server/tests/test_result_workbench.py`, `test_research_analysis.py`, native
classification/survival/segmentation regressions; frontend `ResultsViewerPage.test.tsx`.
The suites cover CPU completion after navigation, sample paging, assistant actions, metric semantics, recipe persistence and responsive layouts.
