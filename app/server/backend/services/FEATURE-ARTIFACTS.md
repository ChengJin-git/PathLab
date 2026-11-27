# Feature registration and reuse

`FeatureArtifact` is the feature inventory shared by the viewer, chat's `available_features` and
research data preparation. It records file version, row count, dimension, optional coordinates,
source and an optional model contract. Features without coordinates can still be used for analysis
but cannot be located on the slide.

## Producer contract

Feature models declare identity and preprocessing in `backend/ai/feature_contracts.py`; capabilities
are never inferred from directory names, model lists or vector dimensions.

```json
{
  "model_id": "my-lab-encoder",
  "model_revision": "actual-weights-revision",
  "embedding_space": "my-lab-space-v3",
  "dimensions": 768,
  "preprocessing": "RGB; resize=224; normalization=declared-v3"
}
```

Feature files are `.pt` or `.npy` finite 2-D arrays `[N, D]`. Coordinate HDF5 files hold `coords`
`[N, 2]` in original slide pixels, with `patch_size` and `downsample` attributes defining the patch
size.

Built-in extractors implement `get_feature_contract()` and identify their version by the actual
weight digest. `save_features` writes a format-version-1 `.feature.json` binding the feature and
coordinate file versions. Built-in extraction, inference and research registration update the same
inventory.

Administrators can register features with `POST /viewer/slides/{id}/features` (`feature_path`,
`coordinates_path`, `contract`). Files must be in managed storage; the service checks counts,
dimensions, finiteness and image bounds. The research tool `register_features` accepts
`coordinates_dir` and `feature_contract` and records the source.

## Visual search and text localisation

Visual similarity search works within one feature matrix. If an older asset did not record its
weight version, `contract` stays empty and the source may record `weights_revision: not_recorded`;
this does not prove that embedding spaces match across versions and does not enable text search.

Text localisation additionally requires a `text_encoder`:

```json
{
  "provider": "onnx_text",
  "checkpoint": "/managed/models/text/model.onnx",
  "revision": "asset_digest(checkpoint)",
  "tokenizer": "/managed/models/text/tokenizer.json",
  "tokenizer_revision": "asset_digest(tokenizer)",
  "aligned_space": "my-lab-space-v3",
  "image_projection": "identity"
}
```

Replace the placeholder revisions with the real asset digests. `aligned_space` must match the
feature contract, and text encoder, tokenizer, preprocessing and image projection must agree. Equal
visual feature dimensions do not prove image–text alignment.

Built-in providers are `hf_clip`, `open_clip`, `conch` and `onnx_text`, using installed CPU assets.
Add a provider with `register_text_provider(name, loader)`; the loader receives a
`TextEncoderContract` and returns a function `(query, image_features) -> (text_vector,
projected_image_features)`.

Changed file versions, mismatched coordinate counts, missing alignment declarations, unknown
providers and resource limits are reported with a specific reason. Viewer requests never download
models or recompute whole-slide features automatically.

## Resource limits

The search cache is limited to 256 MiB. Visual search memory-maps files up to 2 GiB and processes
2,048 rows per batch with two numeric threads. Text localisation requires a feature matrix of at most
256 MiB and reads coordinates up to 32 MiB. These are resource limits, not response-time guarantees.

Code: `feature_inventory.py`, `viewer_features.py`, `viewer_text_encoders.py`,
`backend/ai/feature_contracts.py`. `test_viewer_feature_contracts.py` covers older assets, file
versions, coordinates, text providers and access boundaries.
