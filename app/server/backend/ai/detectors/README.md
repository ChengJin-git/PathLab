# Patch detection

PathLab v1.0.8 · Updated 2026-11-06

Canonical task: `patch_detection`, `data_type=patch`, `aggregation_level=file`.
The UI calls this Detection / 检测. Whole-slide detection is not a supported task.

## Models and training

Torchvision supplies Faster R-CNN, RetinaNet and FCOS. ResNet-18/34/50/101 + FPN
can initialize from ImageNet or train from scratch. Existing pathology foundation
extractors with spatial features use a projected feature pyramid and the same
detection heads. `train_backbone` controls real gradient-based fine-tuning versus
freezing; detector/FPN/projection layers remain trainable. FM input normalization
and native image size come from the extractor. Detector resizing maps boxes back
to original image coordinates, including rectangular patches.

The manual training wizard and Chat configuration card share `DetectionConfig`.
GPU stages use the existing scheduler, cancellation and permission-revocation
boundaries. Training selects the checkpoint by validation mAP, saves optimizer /
scheduler / RNG state for restart, supports random or predefined splits, and
generates saved per-image predictions after training. Custom architectures use
the validated Python image predictor contract in `services/RESEARCH-PREDICTORS.md`.

## Data and evaluation

Import COCO `images`, `categories` and `annotations`, with each annotation's
`bbox=[x,y,width,height]`. Every image, including negative images, must be listed.
Category IDs may be sparse; internal labels are one-based in saved class order.
Boxes must be finite, positive-area and inside the image. Crowd targets are
excluded from training targets and use official COCO crowd matching in evaluation.

`pycocotools` computes 101-point mAP over IoU 0.50:0.95, AP50, AP75 and average
recall. Workbench evaluation uses at most 100 saved detections per image. Confidence
and matching-IoU controls change precision, recall, F1 and TP/FP/FN; they do not
threshold the scores used for mAP. No GT is distinct from an annotated empty image.

## Results

Training, batch inference and external validation persist original-coordinate
boxes to AIResult metadata and the task Zarr bundle. The results workbench and
image viewer show predictions even when no CAM/attention artifact exists. Detection
boxes and GT can be toggled and confidence-filtered. The viewer shows actual class names, counts and colors, including single-class outputs, and supports class filtering. Saved one-based labels are converted to class-array indices for display; analysis samples share the
same task-aware preview entry as classification, segmentation and survival.

Analysis jobs are durable CPU subprocesses. Exact owner/workspace/config/source
revision matches reuse existing work; bootstrap jobs report progress and remain
visible in Background tasks after navigation. Segmentation additionally stores
byte-sized probability bins and per-class histograms for exact 0.01-step pixel
threshold changes without inference or full-mask reads during metric computation.

The current schema includes detection task constraints and analysis progress/phase. Startup initializes new databases and validates existing versions without historical backfills; see [database](../../database/README.md).

Tests: `test_patch_detection.py`, `test_result_workbench.py`,
`test_heatmap_task_taxonomy.py`, plus training/import/inference routing regressions.
