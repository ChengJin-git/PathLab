# Dataset Acquisition Operations Guide

> Operator-facing reference for the acquisition stage. For architectural
> overview see `docs/PROJECT_MEMORY.md` ("Dataset Acquisition" + "Literature-
> Grounded Dataset Discovery").

---

## Provider Matrix

| Provider | Auto-download status | Required policy | Credentials | Notes |
|---|---|---|---|---|
| `direct_http` | Yes for file-like URLs (`.zip` / `.tar.gz` / `.h5` / etc.) | `public_only` if record `access="public"`, `manual_only` if `access="manual"` | none | Rejects landing pages with `not_file_url`. |
| `zenodo` | Yes for explicit file URLs OR resolvable record id (`/api/records/<id>`) | typically `public_only` | none | Metadata resolution runs only in `download()`; `probe()` stays no-network. |
| `huggingface` | Yes via `snapshot_download` | depends on `record.access` | optional HF token for private/gated | Fails cleanly if `huggingface_hub` is not installed. |
| `kaggle` | Yes via Kaggle CLI when explicit manual policy + size budget permit | `manual_only` (PANDA et al. are `access="manual"`) + `--allow-large-downloads` for >20GB | `KAGGLE_USERNAME`+`KAGGLE_KEY` env, or `~/.kaggle/kaggle.json`, or injected `kaggle_json_path` | Subprocess-driven; runner is injectable for tests. PANDA seed is `400 GB`. |
| `gdc` / `tcia` | Manifest / explicit `api.gdc.cancer.gov/data/<uuid>` URLs only | typically `manual_only`; usually large/gated | possibly GDC token later (Phase 5b+) | Portal/project URLs (`portal.gdc.cancer.gov/projects/...`) NEVER bulk-download — return `skipped_policy/gdc_manifest_required`. `tcia` is an alias for the GDC adapter. |
| `github` / `figshare` | Discovery-hint only unless URL maps to `direct_http` (file extension) | N/A | N/A | Dedicated providers are future work. |

`tcia` is intentionally aliased to the same `GDCProvider` instance in the
factory, so legacy seed records using `"provider": "tcia"` reach a meaningful
adapter rather than `no_provider:tcia`.

---

## Operational Flags / Env Vars

| Flag | Env equivalent | Default | Notes |
|---|---|---|---|
| `--auto-acquire-data` | `PATHSCIENTIST_AUTO_ACQUIRE_DATA` | off | Required for the acquisition stage to fire. |
| `--download-policy public_only \| manual_only \| disabled` | `PATHSCIENTIST_DOWNLOAD_POLICY` | `public_only` | `disabled` writes discovery + plan but never enters provider download. |
| `--max-download-size-gb 500` | `PATHSCIENTIST_MAX_DOWNLOAD_SIZE_GB` | `20.0` | PANDA is 400 GB → needs ≥500. |
| `--allow-large-downloads` | `PATHSCIENTIST_ALLOW_LARGE_DOWNLOADS` | off | Opt-in past `max-download-size-gb`. |
| `--dataset-cache-dir /path` | (n/a — passed via `dataset_cache_dir`) | `<persistence_root>/datasets/` | Where curated `datasets.json` lives + raw/prepared roots. |
| `--stop-before-execution` | `PATHSCIENTIST_STOP_BEFORE_EXECUTION` | off | Stops after acquisition writes its artifacts; brief is rendered for review. |
| `--manual-approval` | `PATHSCIENTIST_MANUAL_APPROVAL` | off | Pauses after grounding before execution; orthogonal to stop-before-execution. |
| `PATHSCIENTIST_DATASET_DISCOVERY=0` | env-only | discovery on | Disables literature-grounded discovery extraction (heuristic stays on by default). |

CLI flags `--dataset-discovery` / `--no-dataset-discovery` and
`--allow-auto-ingest` are deferred to Phase 1.5 (user CLI WIP territory).

---

## Audit Artifacts (per workspace)

After `_run_acquisition_stage` runs, the workspace contains:

```
<workspace>/.dataset/
  discovery.json            (literature-grounded candidates pre-merge)
  session_registry.json     (curated + discovered, fed into the scout)
  acquisition_plan.json     (everything considered + selected_dataset_id + status)
  manifest.json             (final outcome — pending / prepared / failed / skipped_policy)
```

`acquisition_plan.json` is written **once before** `provider.download()`
fires (status=`planned`) and **once at the final exit** (status=actual). If
download crashes or `--stop-before-execution` short-circuits, the planned
version is what reviewers read.

Each `considered[i]` entry contains:

```json
{
  "dataset_id": "kaggle:prostate-cancer-grade-assessment",
  "name": "PANDA — Prostate cANcer graDe Assessment",
  "provider": "kaggle",
  "provider_available": true,
  "access": "manual",
  "estimated_size_gb": 400.0,
  "license": "CC-BY-SA-NC-4.0",
  "source_paper_ids": ["doi:10.1038/s41591-021-01620-2"],
  "download": {
    "kind": "kaggle_competition",
    "remote_id": "prostate-cancer-grade-assessment",
    "urls": ["..."],
    "filename": "",
    "checksum_sha256": ""
  },
  "score": 11.0,
  "relevant": true,
  "allowed": false,
  "policy_reason": "access=manual",
  "reasons": ["task_type_match", "organ_match", "asset_match", "keyword:gleason"],
  "tags": ["WSI", "HE", "ISUP", "gleason", "kaggle", "probe:kaggle_credentials_missing"]
}
```

---

## Recipes

### Safe Gleason / PANDA dry run (no download fires)

```bash
PATHSCIENTIST_AUTO_ACQUIRE_DATA=1 \
PATHSCIENTIST_DOWNLOAD_POLICY=disabled \
PATHSCIENTIST_STOP_BEFORE_EXECUTION=1 \
python -m pathscientist.run orchestrator \
  "train a Gleason grading model on prostate WSI"
```

Produces all four `.dataset/*.json` artifacts plus the execution brief
under `.pathscientist/execution_brief.md`. PANDA shows up as the selected
candidate with `policy_reason=disabled`.

### Real Kaggle attempt (PANDA, 400 GB)

Pre-flight: install Kaggle CLI and place credentials.

```bash
pip install kaggle
mkdir -p ~/.kaggle
echo '{"username": "...", "key": "..."}' > ~/.kaggle/kaggle.json
chmod 600 ~/.kaggle/kaggle.json
```

Then:

```bash
export KAGGLE_USERNAME=...
export KAGGLE_KEY=...
PATHSCIENTIST_AUTO_ACQUIRE_DATA=1 \
PATHSCIENTIST_DOWNLOAD_POLICY=manual_only \
PATHSCIENTIST_MAX_DOWNLOAD_SIZE_GB=500 \
PATHSCIENTIST_ALLOW_LARGE_DOWNLOADS=1 \
python -m pathscientist.run orchestrator \
  "train a Gleason grading model on prostate WSI"
```

`probe:kaggle_credentials_present` should appear in the plan entry's
`tags` after probe runs; `acquisition_plan.json["status"]` will progress
through `planned` → final state once `kaggle competitions download -c
prostate-cancer-grade-assessment` returns.

### TCGA-BRCA (GDC manifest required)

Without an explicit `api.gdc.cancer.gov/data/<uuid>` URL or a manifest,
acquisition will return `skipped_policy/gdc_manifest_required` rather
than try to scrape the portal page. To override, materialize a manifest
into a future `gdc_manifest` download spec — Phase 5b territory.

---

## Failure Reasons (acquisition_plan.json `reason` field)

| Reason | Meaning |
|---|---|
| `no_candidate` | Empty registry or all entries policy-rejected before relevance gate. |
| `no_relevant_candidate` | Candidates exist but none match `task_profile` semantics. |
| `access=manual` / `access=public` / `access=gated` | Policy refused on access. |
| `too_large` | `estimated_size_gb > max_download_size_gb` and `allow_large_downloads` not set. |
| `disabled` | `download_policy="disabled"` short-circuited. |
| `no_provider:<name>` | Record's provider has no adapter in the factory (legacy mismatch). |
| `missing_kaggle_credentials` | KaggleProvider.probe returned `probe:kaggle_credentials_missing`; `download()` short-circuited. |
| `kaggle_unsupported_kind:<kind>` | DownloadSpec.kind isn't `kaggle_competition` or `kaggle_dataset`. |
| `kaggle_error:<stderr>` | Kaggle CLI returned non-zero. |
| `gdc_manifest_required` | Only portal/project URLs available; GDC bulk-download requires explicit manifest. |
| `gdc_error:<exception>` | GDC streaming failure. |
| `zenodo_metadata_error:<exception>` | API metadata resolution failed. |
| `zenodo_no_files` | API returned a record with no files. |
| `zenodo_download_error:<exception>` | Streaming the resolved file URL failed. |
| `not_file_url:<url>` | DirectHTTP rejected a landing page. |
| `checksum_mismatch:expected=...,actual=...` | Provider's reported checksum doesn't match the seed's. |
| `no_normalizer:<task_type>` | Acquisition stage couldn't pick a normalizer for the task. |
| `normalize_empty:<error>` | Normalizer rejected the prepared output. |
| `normalize_error:<error>` | Normalizer raised. |

`probe:*` markers do not block acquisition — they're audit-only. Examples:
`probe:file_url_unverified`, `probe:zenodo_resolution_pending`,
`probe:hf_remote_unverified`, `probe:hf_gated`, `probe:kaggle_credentials_missing`,
`probe:gdc_data_urls_present`, `probe:gdc_manifest_required`.

---

## Adding a New Provider

1. Implement `dataset/providers/<name>.py` with `provider_name`, `probe()`,
   `download()`. Probe MUST NOT upgrade access. Download MUST return a
   structured `DownloadResult` rather than raising.
2. Register it in `dataset/providers/factory.py::build_default_providers`.
3. Add tests at `tests/test_dataset_providers_<name>.py`. Inject a fake
   session / runner so unit tests stay offline.
4. If the seed needs a new `DownloadSpec.kind`, also extend
   `_PROVIDER_TO_KIND` in `dataset/discovery_registry.py` and the URL
   patterns in `dataset/discovery_extractor.py` so literature-discovered
   records can flow into the new provider.
