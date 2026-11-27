"""COCO bbox evaluation shared by training and the CPU results workbench."""

import contextlib
import io
import math

import numpy as np


def validate_boxes(value, classes, *, prediction=False):
    if not isinstance(value, dict):
        raise ValueError("Detection boxes must be an object")
    keys = (
        {"boxes", "labels", "scores"} if prediction else {"boxes", "labels", "iscrowd"}
    )
    if set(value) != keys:
        raise ValueError(f"Detection fields must be {sorted(keys)}")
    if not all(isinstance(value[key], list) for key in keys):
        raise ValueError("Detection fields must be arrays")
    if len({len(value[key]) for key in keys}) != 1 or len(value["boxes"]) > 10000:
        raise ValueError("Detection arrays must align and contain at most 10,000 boxes")
    for box, label in zip(value["boxes"], value["labels"]):
        if (
            not isinstance(box, list)
            or len(box) != 4
            or not all(isinstance(v, (float, int)) and math.isfinite(v) for v in box)
        ):
            raise ValueError("Detection requires finite xyxy boxes")
        if box[0] < 0 or box[1] < 0 or box[2] <= box[0] or box[3] <= box[1]:
            raise ValueError("Invalid detection box geometry")
        if type(label) is not int or not 1 <= label <= len(classes):
            raise ValueError("Detection labels must be one-based class indices")
    if prediction:
        if any(
            not isinstance(score, (int, float))
            or not math.isfinite(score)
            or not 0 <= score <= 1
            for score in value["scores"]
        ):
            raise ValueError("Detection scores must be finite probabilities")
    elif any(crowd not in (0, 1) for crowd in value["iscrowd"]):
        raise ValueError("Detection iscrowd must be 0 or 1")
    return value


def evaluate_detection(samples, classes, *, threshold=0.5, iou=0.5, max_detections=100):
    """mAP uses all saved scores, thresholds affect operating-point metrics only.

    ``target=None`` means unlabelled; an empty target is an annotated negative image.
    Crowd matching and 101-point AP are delegated to the official COCO evaluator.
    """
    from pycocotools.coco import COCO
    from pycocotools.cocoeval import COCOeval

    images, annotations, predictions = [], [], []
    predicted_count = 0
    for identity, sample in enumerate(samples, 1):
        pred = validate_boxes(sample["prediction"], classes, prediction=True)
        predicted_count += sum(score >= threshold for score in pred["scores"])
        target = sample.get("target")
        if target is None:
            continue
        validate_boxes(target, classes)
        images.append({"id": identity})
        for index, (box, label) in enumerate(zip(target["boxes"], target["labels"])):
            x, y, x2, y2 = box
            annotations.append(
                dict(
                    id=len(annotations) + 1,
                    image_id=identity,
                    category_id=label,
                    bbox=[x, y, x2 - x, y2 - y],
                    area=(x2 - x) * (y2 - y),
                    iscrowd=target["iscrowd"][index],
                )
            )
        ranked = sorted(
            zip(pred["boxes"], pred["labels"], pred["scores"]),
            key=lambda item: item[2],
            reverse=True,
        )[:max_detections]
        for box, label, score in ranked:
            x, y, x2, y2 = box
            predictions.append(
                dict(
                    id=len(predictions) + 1,
                    image_id=identity,
                    category_id=label,
                    bbox=[x, y, x2 - x, y2 - y],
                    area=(x2 - x) * (y2 - y),
                    score=score,
                    iscrowd=0,
                )
            )
    values = {"detection_count": predicted_count}
    if not images:
        return values, []

    def run(thresholds):
        with contextlib.redirect_stdout(io.StringIO()):
            gt, dt = COCO(), COCO()
            categories = [{"id": i, "name": name} for i, name in enumerate(classes, 1)]
            gt.dataset = dict(
                images=images, categories=categories, annotations=annotations
            )
            dt.dataset = dict(
                images=images, categories=categories, annotations=predictions
            )
            gt.createIndex()
            dt.createIndex()
            evaluator = COCOeval(gt, dt, "bbox")
            evaluator.params.iouThrs = np.array(thresholds)
            evaluator.params.maxDets = [1, min(10, max_detections), max_detections]
            evaluator.evaluate()
            evaluator.accumulate()
            return evaluator

    # Match once for the union of COCO and operating-point IoUs; reuse the
    # expensive per-image box overlaps for both summary and threshold metrics.
    standard = np.linspace(0.5, 0.95, 10)
    thresholds = np.unique(np.round(np.r_[standard, iou], 8))
    evaluator = run(thresholds)
    standard_indices = [int(np.argmin(abs(thresholds - value))) for value in standard]
    operating_index = int(np.argmin(abs(thresholds - iou)))
    precision = evaluator.eval["precision"][standard_indices, :, :, 0, -1]
    recall = evaluator.eval["recall"][standard_indices, :, 0, -1]

    def mean_defined(array):
        valid = array[array >= 0]
        return float(valid.mean()) if valid.size else None

    values.update(
        map=mean_defined(precision),
        map_50=mean_defined(precision[0]),
        map_75=mean_defined(precision[5]),
        mar=mean_defined(recall),
    )
    tp = fp = targets = 0
    for result in evaluator.evalImgs:
        if result is None or result["aRng"] != evaluator.params.areaRng[0]:
            continue
        keep = (np.array(result["dtScores"]) >= threshold) & ~result["dtIgnore"][
            operating_index
        ]
        tp += int(((result["dtMatches"][operating_index] > 0) & keep).sum())
        fp += int(((result["dtMatches"][operating_index] == 0) & keep).sum())
        targets += int((~result["gtIgnore"].astype(bool)).sum())
    fn = targets - tp
    values.update(
        detection_tp=tp,
        detection_fp=fp,
        detection_fn=fn,
        detection_precision=tp / (tp + fp) if tp + fp else None,
        detection_recall=tp / targets if targets else None,
        detection_f1=2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
    )
    curves = []
    for index, name in enumerate(classes):
        y = evaluator.eval["precision"][operating_index, :, index, 0, -1]
        keep = y >= 0
        if keep.any():
            curves.append(
                {
                    "name": name,
                    "x": evaluator.params.recThrs[keep].tolist(),
                    "y": y[keep].tolist(),
                }
            )
    return values, curves
