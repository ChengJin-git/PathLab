# Research model prediction contract

> PathLab v1.0.8 · Updated 2026-11-06

Registration accepts either a validated native PathLab checkpoint or a `prediction`
object with `task_type`, `input_kind`, `runtime`, ordered `classes`, `pooling`,
`score_method`, preprocessing metadata and adapter resources. Architecture and task
are never inferred from the dataset/model display name.

Supported task outputs:

| task_type | Input | Adapter result |
| --- | --- | --- |
| wsi_classification | N×D feature bag | `probabilities`: 1×C, ordered as classes |
| patch_classification | original H×W×3 RGB image | `probabilities`: 1×C |
| wsi_survival | N×D feature bag | scalar `risk_score`, higher means higher risk; optional `survival` aligned with declared `time_bins` |
| patch_detection | original H×W×3 RGB image | `boxes`: N×4 original-pixel xyxy; `labels`: N one-based class indices; `scores`: N probabilities |
| patch_segmentation | original H×W×3 RGB image | binary C×H×W `mask`, channels ordered as classes |

Segmentation adapters may additionally return C×H×W `probabilities` in [0,1],
whose `>0.5` decisions must equal `mask`. These enable adjustable pixel thresholds
and matching mask previews; a binary-mask-only result supports its recorded threshold.

Python adapters expose `load_predictor(model_path, config)`. The returned object has
`feature_dim` for feature inputs and `predict(inputs, context)`. `context` contains
`patch_counts` when pooling is `none`; image transforms and resize-back belong to
the adapter and must reproduce training. `config.device` is the assigned sandbox
GPU (`cuda:0`) or CPU. Use CPU-capable loading for registration validation.

Built-in sklearn and fitted Torch linear/MLP adapters handle WSI classifiers;
other tasks/architectures use the Python interface. sklearn pipelines retain fitted
transforms. Torch exports must declare the trained `activation`. Decision scores
require an explicit sigmoid/softmax declaration and are not described as calibrated
probabilities. `tile_mean_then_slide_mean` gives
each slide equal weight within a case; `tile_mean` weights every tile equally.

Model weights and adapter files are hashed. Registration performs an input/output
roundtrip before publication. Adapters run inside the existing Apptainer ML image
with only model/code/exchange mounts; host pickle loading is avoided. Named arrays
travel through bounded NPY/NPZ files, with small JSON control messages. The host
also validates task output shapes, finite values, probability sums, survival
monotonicity and segmentation mask values. Unsupported formats fail registration
with a concrete error rather than creating a supposedly usable model.

Batch inference and external validation use the same task-aware adapters and write
the existing AIResult/Zarr formats. Results-page regeneration uses this same path.
No attention/CAM is fabricated for classifiers that do not produce one.

Prediction contracts and feature-space contracts serve different consumers. Reusable feature files register through `FeatureArtifact`; text localization additionally requires verified encoder/version/space alignment. A model's name or feature dimension does not establish that relationship. See [feature artifacts](FEATURE-ARTIFACTS.md).

For older models, `python -m backend.services.connect_research_models --spec-file`
accepts a JSON map of model ID to explicit prediction contract. It validates each
model before enabling it; weights and recorded evaluation metrics are preserved.
Reconnection preserves an already-connected model's active/inactive choice. This
command requires a real spec-file argument and the configured sandbox image.

The five platform task types above define the supported result formats. Supporting
a new task requires its own input/output validation and result/analysis integration;
a Python adapter does not automatically make arbitrary outputs usable by the UI.
