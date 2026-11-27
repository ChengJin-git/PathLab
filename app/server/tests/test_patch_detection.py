import json

import numpy as np
import pytest
import torch
from PIL import Image

from backend.ai.detectors.specs import DetectionConfig
from backend.ai.detectors.models import build_detector, load_detector, SpatialBackbone
from backend.ai.utils.detection_dataset import DetectionDataset, coco_targets
from backend.ai.task_taxonomy import normalize_task_type
from backend.services.result_analysis.detection_metrics import evaluate_detection
from backend.services.result_analysis.segmentation_thresholds import (
    threshold_counts,
    metrics_at_threshold,
)
from backend.services.result_analysis.compute import compute_source
from backend.services.result_analysis.contracts import AnalysisConfig, ChartSpec


def sample(boxes, scores, *, target_boxes=None):
    return {
        "prediction": {"boxes": boxes, "scores": scores, "labels": [1] * len(boxes)},
        "target": (
            None
            if target_boxes is None
            else {
                "boxes": target_boxes,
                "labels": [1] * len(target_boxes),
                "iscrowd": [0] * len(target_boxes),
            }
        ),
    }


def test_coco_metrics_thresholds_negatives_and_unlabelled():
    samples = [
        sample([[0, 0, 10, 10]], [0.9], target_boxes=[[0, 0, 10, 10]]),
        sample([[0, 0, 10, 10]], [0.6], target_boxes=[]),
        sample([[0, 0, 10, 10]], [0.99]),
    ]
    low, _ = evaluate_detection(samples, ["cell"], threshold=0.5)
    high, _ = evaluate_detection(samples, ["cell"], threshold=0.8)
    assert low["detection_tp"] == high["detection_tp"] == 1
    assert low["detection_fp"] == 1 and high["detection_fp"] == 0
    assert low["map"] == pytest.approx(high["map"])
    assert low["detection_precision"] == 0.5 and high["detection_precision"] == 1
    empty, _ = evaluate_detection(
        [sample([], [], target_boxes=[[0, 0, 10, 10]])], ["cell"]
    )
    assert empty["map"] == 0 and empty["detection_fn"] == 1
    unknown, _ = evaluate_detection([sample([], [])], ["cell"])
    assert "map" not in unknown


def test_iou_threshold_and_crowd_semantics():
    row = sample([[0, 0, 7, 10]], [0.9], target_boxes=[[0, 0, 10, 10]])
    assert evaluate_detection([row], ["cell"], iou=0.5)[0]["detection_tp"] == 1
    assert evaluate_detection([row], ["cell"], iou=0.75)[0]["detection_tp"] == 0
    row["target"]["iscrowd"] = [1]
    values, _ = evaluate_detection([row], ["cell"])
    assert values["detection_fp"] == 0 and values["map"] is None


def test_coco_loader_maps_sparse_ids_and_preserves_negatives(tmp_path):
    Image.new("RGB", (40, 30)).save(tmp_path / "one.png")
    Image.new("RGB", (40, 30)).save(tmp_path / "two.png")
    payload = {
        "images": [
            {"id": 8, "file_name": "one.png", "width": 40, "height": 30},
            {"id": 9, "file_name": "two.png", "width": 40, "height": 30},
        ],
        "categories": [{"id": 72, "name": "cell"}],
        "annotations": [{"image_id": 8, "category_id": 72, "bbox": [3, 4, 5, 6]}],
    }
    path = tmp_path / "annotations.json"
    path.write_text(json.dumps(payload))
    data = DetectionDataset(tmp_path, path, ["cell"])
    image, target = data[0]
    assert image.shape == (3, 30, 40)
    assert target["boxes"].tolist() == [[3, 4, 8, 10]] and target[
        "labels"
    ].tolist() == [1]
    assert data[1][1]["boxes"].shape == (0, 4)
    payload["annotations"][0]["bbox"] = [38, 4, 5, 6]
    with pytest.raises(ValueError, match="outside"):
        coco_targets(payload, ["cell"])
    with pytest.raises(ValueError):
        normalize_task_type(task_type="patch_detection", data_type="wsi")
    with pytest.raises(ValueError):
        normalize_task_type(
            task_type="patch_detection", data_type="patch", aggregation_level="case"
        )


@pytest.mark.parametrize("architecture", ["fasterrcnn", "retinanet", "fcos"])
def test_detector_backward_and_checkpoint_roundtrip(architecture, tmp_path):
    torch.set_num_threads(2)
    config = DetectionConfig(
        architecture=architecture, backbone="resnet18", pretrained=False, image_size=64
    )
    model = build_detector(config, ["cell"])
    images = [torch.rand(3, 64, 80)]
    targets = [
        {"boxes": torch.tensor([[2.0, 3.0, 30.0, 35.0]]), "labels": torch.tensor([1])}
    ]
    losses = model(images, targets)
    loss = sum(losses.values())
    assert torch.isfinite(loss)
    loss.backward()
    assert any(
        p.grad is not None and p.grad.abs().sum() > 0
        for p in model.backbone.parameters()
    )
    path = tmp_path / "detector.pth"
    torch.save(
        {
            "config": config.model_dump(),
            "classes": ["cell"],
            "model_state_dict": model.state_dict(),
        },
        path,
    )
    restored, classes = load_detector(path, "cpu")
    with torch.no_grad():
        output = restored(images)[0]
    assert classes == ["cell"] and set(output) == {"boxes", "labels", "scores"}
    assert torch.all(output["boxes"][:, 2] <= 80) and torch.all(
        output["boxes"][:, 3] <= 64
    )


@pytest.mark.parametrize("trainable", [True, False])
def test_foundation_backbone_finetuning_receives_gradients(trainable):
    class Extractor(torch.nn.Module):
        default_image_size, spatial_output_dim = 32, 8

        def __init__(self):
            super().__init__()
            self.layer = torch.nn.Conv2d(3, 8, 4, stride=4)

        def forward_spatial(self, images):
            return self.layer(images)

    backbone = SpatialBackbone(Extractor(), trainable).train()
    sum(
        features.mean() for features in backbone(torch.rand(1, 3, 64, 64)).values()
    ).backward()
    assert (backbone.extractor.layer.weight.grad is not None) == trainable
    assert backbone.extractor.training == trainable


def test_segmentation_threshold_statistics_match_direct_pixels():
    rng = np.random.default_rng(42)
    probs = rng.random((2, 23, 31)).astype(np.float32)
    probs[0, 0, :3] = [0, 0.5, 1]
    target = rng.random(probs.shape) > 0.7
    counts = threshold_counts(probs, target)
    for threshold in (0, 0.13, 0.5, 0.78, 1):
        values = metrics_at_threshold({"threshold_counts": counts}, threshold)
        pred = probs > threshold
        tp = (pred & target).sum((1, 2))
        fp = (pred & ~target).sum((1, 2))
        fn = (~pred & target).sum((1, 2))
        assert values["dice"] == pytest.approx((2 * tp / (2 * tp + fp + fn)).mean())


def test_binary_analysis_threshold_changes_confusion_not_auc():
    rows = [
        {
            "dataset_id": "d",
            "wsi_id": str(i),
            "case_id": None,
            "label": label,
            "pred": "yes",
            "probs": {"no": 1 - p, "yes": p},
        }
        for i, (label, p) in enumerate(
            [("yes", 0.7), ("no", 0.6), ("yes", 0.9), ("no", 0.1)]
        )
    ]
    source = {
        "source_id": "s",
        "title": "test",
        "revision": "1",
        "task_type": "patch_classification",
        "details": {"classes": ["no", "yes"]},
    }

    def run(threshold):
        return compute_source(
            source,
            rows,
            AnalysisConfig(
                threshold=threshold,
                average="binary",
                metrics=["accuracy", "auc"],
                charts=[ChartSpec(id="confusion")],
            ),
        )

    low, high = run(0.5), run(0.65)
    assert low["metrics"]["accuracy"]["value"] == 0.75
    assert high["metrics"]["accuracy"]["value"] == 1
    assert high["metrics"]["auc"] == low["metrics"]["auc"]
    assert high["charts"]["confusion"]["matrix"] != low["charts"]["confusion"]["matrix"]


def test_detector_trainer_runs_epoch_and_cleans_resume_checkpoint(tmp_path):
    from backend.ai.tasks.patch_detection import DetectionTrainer

    torch.set_num_threads(2)
    Image.new("RGB", (80, 64), "white").save(tmp_path / "image.png")
    payload = {
        "images": [{"id": 1, "file_name": "image.png", "width": 80, "height": 64}],
        "categories": [{"id": 9, "name": "cell"}],
        "annotations": [
            {"id": 1, "image_id": 1, "category_id": 9, "bbox": [10, 10, 30, 30]}
        ],
    }
    annotations = tmp_path / "coco.json"
    annotations.write_text(json.dumps(payload))
    dataset = {
        split: {"image_dir": str(tmp_path), "annotations_path": str(annotations)}
        for split in ("train", "val", "test")
    }
    config = DetectionConfig(
        backbone="resnet18", pretrained=False, image_size=64, batch_size=1, epochs=1
    )
    trainer = DetectionTrainer(
        "smoke",
        config.model_dump(),
        dataset,
        ["cell"],
        tmp_path / "model",
        device="cpu",
    )
    progress = []
    try:
        result = trainer.train(lambda *args: progress.append(args))
        assert result["best_epoch"] == 1 and len(progress) == 1
        assert (tmp_path / "model" / "best_model.pth").is_file()
        assert not (tmp_path / "model" / "resume_checkpoint.pth").exists()
        assert result["test_metrics"]["map"] is not None
    finally:
        trainer.release_resources()


def test_mask_preview_matches_threshold_and_original_aspect_ratio(tmp_path):
    import io
    from backend.ai.result_store import AIResultStore
    from backend.services.result_analysis.segmentation_thresholds import (
        probability_bins,
    )
    from backend.services.result_analysis.previews import render_mask

    probability = np.array([[[0.2, 0.6], [0.8, 1.0]]], dtype=np.float32)
    AIResultStore(tmp_path).write_wsi_result(
        "seg",
        "image",
        result={"image_size": [80, 40]},
        arrays={
            "pred_bins": probability_bins(probability),
            "gt_mask": np.ones((1, 2, 2), dtype=np.uint8),
        },
    )
    low = Image.open(io.BytesIO(render_mask(tmp_path, "seg", "image", "pred", 0, 0.5)))
    high = Image.open(io.BytesIO(render_mask(tmp_path, "seg", "image", "pred", 0, 0.9)))
    assert low.size == high.size == (80, 40)
    assert (np.asarray(low)[..., 3] > 0).sum() == 2400
    assert (np.asarray(high)[..., 3] > 0).sum() == 800


def test_detection_python_predictor_output_contract():
    from backend.ai.research_predictor_worker import validate_output

    spec = {"task_type": "patch_detection", "classes": ["cell"]}
    output = {
        "boxes": np.array([[2.0, 3.0, 10.0, 12.0]]),
        "labels": np.array([1]),
        "scores": np.array([0.9]),
    }
    assert set(validate_output(output, spec, (20, 30, 3))) == set(output)
    with pytest.raises(ValueError, match="original image"):
        validate_output(output, spec, (8, 30, 3))


def test_external_detection_cache_uses_source_model_identity(tmp_path):
    from backend.ai.result_store import AIResultStore
    from gateway.routes.results import _check_existing_extval_results_from_store

    AIResultStore(tmp_path).write_wsi_result(
        "extval_detection", "image", result={
            "task_id": "extval_detection", "model_task_id": "trained",
            "validation_task_id": "extval_detection", "task_type": "patch_detection",
            "detection": sample([], []),
        }, arrays={},
    )
    count, identity, missing = _check_existing_extval_results_from_store(
        tmp_path, ["image"], "trained", "patch_detection", "patch"
    )
    assert (count, identity, missing) == (1, "extval_detection", [])
