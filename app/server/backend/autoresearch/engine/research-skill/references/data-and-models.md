# Data acquisition and model registration

## Datasets

- Choose data with PathTrove first. The `pathtrove_*` tools (skills `pathtrove-best-data`,
  `pathtrove-data`) cover 350+ public pathology datasets, challenges and benchmarks: cohort sizes,
  labels, licences, access requirements, tested download routes and label files. Turn the chosen
  resource's download guide into the `acquire_dataset` record; `pathtrove_label_fetch` saves a
  sha256-verified label file into the workspace. PathTrove is partial and can be wrong: verify
  decision-critical values at the primary source, and search elsewhere when it has no fit.
- `search_datasets` finds local and public candidates; prefer existing data and cached features.
  `prepare_dataset` materialises a manifest for an authorised Data Repo dataset. `acquire_dataset`
  schedules a durable download and registration (GDC, Kaggle, Hugging Face, Zenodo, Dataverse,
  SciDB, HTTP). Never bypass logins, applications or licences.
- `provider` is one of huggingface, zenodo, kaggle, gdc, dataverse, scidb, direct_http; direct_http
  fetches exactly the files in `download.urls`. For a Hugging Face repository, set `download.include`
  to the paths the study reads (for example `['camelyon17/gigapath/*']`); a large repository is
  refused without it and the error lists its layout. Downloads are checked against free disk space.
- Pre-extracted features and tables without whole slides are not registered in the Data Repo; they
  are mounted read-only (the result gives `mounted_at`) and used directly.
- Pass the full acquisition record: stable source ID, name, provider/source_url, access, verified
  organs, licence, task/asset types, aggregation level. Use `Unknown` for genuinely unstated organ
  or licence and tell the user. Supply the authoritative `annotations_file` and column mapping for
  patient/survival tables or COCO segmentation, and a source-defined `splits_file` when one exists.
- A downloaded archive is not a training dataset: check `metadata_complete`, `missing_metadata`,
  `training_ready`, `split_ready`, `missing_annotations`, then `prepare_dataset` and verify file and
  label coverage. Keep patient groups together.
- Public sources default to public Data Repo visibility; honour explicit private requests.

## Model registration

Register reusable models with an explicit `prediction` contract: task_type, input_kind, runtime,
classes in output order, feature pooling and score_method. Declare the trained activation for
torch_mlp exports. sklearn pipelines keep their fitted transforms; a decision-function score is not
`predict_proba`. Custom architectures supply `adapter_dir` with a Python entrypoint exposing
`load_predictor(model_path, config)`, returning `feature_dim` for feature inputs and
`predict(inputs, context)` (`context.patch_counts` for unpooled bags). Outputs: classification
probabilities `[1, C]`; survival one `risk_score` (higher is riskier), optionally a non-increasing
curve on declared `time_bins`; segmentation a binary mask `[C, H, W]` at original size. The adapter
owns preprocessing and must match training. Run a real inference round trip before finishing
registration. Never infer architecture, label order or pooling from names.
