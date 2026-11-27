"""Measured metrics and bounded plot data. All calculations use complete inputs."""

from __future__ import annotations

from collections import Counter, defaultdict
import math
import numpy as np

from .contracts import AnalysisConfig, METRIC_BY_ID, family
from .sources import digest


def finite(value):
    if isinstance(value, (float, np.floating)) and not math.isfinite(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {k: finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [finite(v) for v in value]
    return value


def series(name, x, y, **extra):
    # Downsampling affects only visualization, never metric calculations.
    positions = (
        np.unique(np.linspace(0, len(x) - 1, min(800, len(x))).astype(int))
        if len(x)
        else []
    )
    return {
        "name": name,
        "x": [float(x[i]) for i in positions],
        "y": [float(y[i]) for i in positions],
        **extra,
    }


def prepare_rows(rows, config, classes):
    unique = {
        (row["dataset_id"], row.get("sample_id") or row["wsi_id"]): dict(row)
        for row in rows
    }  # newest saved result per image
    prepared = list(unique.values())
    if config.unit == "case":
        grouped = defaultdict(list)
        for row in prepared:
            grouped[
                (
                    row["dataset_id"],
                    row["case_id"] or row.get("sample_id") or row["wsi_id"],
                )
            ].append(row)
        prepared = []
        for members in grouped.values():
            row = dict(members[0])
            labels = {m["label"] for m in members if m.get("label") is not None}
            if len(labels) > 1:
                raise ValueError("A case has conflicting ground-truth labels")
            row["label"] = next(iter(labels), None)
            if (
                all(
                    m.get("probs") and all(c in m["probs"] for c in classes)
                    for m in members
                )
                and classes
            ):
                row["probs"] = {
                    c: float(np.mean([m["probs"][c] for m in members])) for c in classes
                }
            elif len({m.get("pred") for m in members}) > 1:
                raise ValueError(
                    "Case predictions disagree and probabilities are unavailable for aggregation"
                )
            metadata = [m.get("metadata", {}) for m in members]
            row["metadata"] = dict(metadata[0])
            survival_targets = {
                (m.get("event_time"), m.get("event_status"))
                for m in members
                if m.get("event_time") is not None
            }
            if len(survival_targets) > 1:
                raise ValueError("A case has conflicting survival outcomes")
            if (
                config.group_by
                and config.group_by != "age_band"
                and len({str(m.get(config.group_by)) for m in members}) > 1
            ):
                raise ValueError("A case has conflicting subgroup values")
            if all(m.get("risk_score") is not None for m in metadata):
                row["metadata"]["risk_score"] = float(
                    np.mean([m["risk_score"] for m in metadata])
                )
            if all(m.get("surv_probs") for m in metadata):
                if any(
                    m.get("bin_edges") != metadata[0].get("bin_edges") for m in metadata
                ):
                    raise ValueError("A case has inconsistent survival time grids")
                row["metadata"]["surv_probs"] = np.mean(
                    [m["surv_probs"] for m in metadata], axis=0
                ).tolist()
            prepared.append(row)
    output = []
    for row in prepared:
        probs = row.get("probs") or {}
        if probs and classes and all(c in probs for c in classes):
            values = np.array([probs[c] for c in classes], dtype=float)
            if (
                not np.isfinite(values).all()
                or np.any(values < 0)
                or np.any(values > 1)
                or not np.isclose(values.sum(), 1, atol=1e-3)
            ):
                raise ValueError("Prediction probabilities are invalid")
            if len(classes) == 2:
                positive = config.positive_class or classes[-1]
                row["pred"] = (
                    positive
                    if probs[positive] >= config.threshold
                    else next(c for c in classes if c != positive)
                )
            else:
                row["pred"] = classes[int(np.argmax(values))]
            row["confidence"] = float(max(values))
        else:
            row["confidence"] = None
        if config.filters.confidence_max is not None and (
            row["confidence"] is None
            or row["confidence"] > config.filters.confidence_max
        ):
            continue
        if config.filters.errors_only and (
            row.get("label") is None or row.get("pred") == row["label"]
        ):
            continue
        row["sample_id"] = (
            f"{row['dataset_id']}:{row['case_id'] or row.get('sample_id') or row['wsi_id']}"
            if config.unit == "case"
            else f"{row['dataset_id']}:{row.get('sample_id') or row['wsi_id']}"
        )
        output.append(row)
    return output


def classification(rows, config, classes, draw=True):
    from sklearn import metrics as sm
    selected_charts = {chart.id for chart in config.charts} if draw else set()

    labelled = [
        r for r in rows if r.get("label") is not None and r.get("pred") is not None
    ]
    probs = [
        r
        for r in rows
        if r.get("probs") and classes and all(c in r["probs"] for c in classes)
    ]
    probability_ids = {id(r) for r in probs}
    paired = [r for r in labelled if id(r) in probability_ids]
    values, charts = {}, {}
    if probs:
        p = np.array([[r["probs"][c] for c in classes] for r in probs])
        values["mean_confidence"] = float(p.max(axis=1).mean())
        values["entropy"] = float(
            -(p * np.log(np.clip(p, 1e-15, 1))).sum(axis=1).mean()
        )
        if "confidence" in selected_charts:
            counts, bins = np.histogram(p.max(axis=1), bins=np.linspace(0, 1, 21))
            charts["confidence"] = {
                "kind": "bar",
                "series": [series("confidence", (bins[:-1] + bins[1:]) / 2, counts)],
            }
    if "distribution" in selected_charts:
        counts = Counter(r.get("pred") for r in rows if r.get("pred") is not None)
        charts["distribution"] = {
            "kind": "bar",
            "categories": list(counts),
            "series": [{"name": "count", "y": list(counts.values())}],
        }
    if labelled:
        y, pred = [r["label"] for r in labelled], [r["pred"] for r in labelled]
        if set(y + pred) - set(classes):
            raise ValueError(
                "Prediction/GT classes do not match the recorded class order"
            )
        positive = config.positive_class or classes[-1]
        average_args = {"average": config.average, "zero_division": 0}
        if config.average == "binary":
            average_args["pos_label"] = positive
        cm = sm.confusion_matrix(y, pred, labels=classes)
        tp = np.diag(cm)
        fp = cm.sum(axis=0) - tp
        fn = cm.sum(axis=1) - tp
        tn = cm.sum() - tp - fp - fn
        specificity = np.divide(
            tn, tn + fp, out=np.full(len(classes), np.nan), where=tn + fp > 0
        )
        if config.average == "binary":
            spec = specificity[classes.index(positive)]
        elif config.average == "weighted":
            spec = np.average(np.nan_to_num(specificity), weights=cm.sum(axis=1))
        elif config.average == "micro":
            spec = tn.sum() / (tn + fp).sum() if (tn + fp).sum() else np.nan
        else:
            spec = np.nanmean(specificity)
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", (UserWarning, RuntimeWarning))
            balanced = sm.balanced_accuracy_score(y, pred)
            kappa = (
                sm.cohen_kappa_score(y, pred, labels=classes, weights="quadratic")
                if "weighted_kappa" in config.metrics
                else None
            )
        values.update(
            accuracy=sm.accuracy_score(y, pred),
            balanced_accuracy=balanced,
            precision=sm.precision_score(y, pred, **average_args),
            sensitivity=sm.recall_score(y, pred, **average_args),
            f1=sm.f1_score(y, pred, **average_args),
            specificity=spec,
            mcc=sm.matthews_corrcoef(y, pred),
            weighted_kappa=kappa,
        )
        if "confusion" in selected_charts:
            charts["confusion"] = {
                "kind": "matrix",
                "classes": classes,
                "matrix": cm.tolist(),
            }
    if paired:
        y = np.array([classes.index(r["label"]) for r in paired])
        p = np.array([[r["probs"][c] for c in classes] for r in paired])
        truth = np.eye(len(classes))[y]
        values["log_loss"] = sm.log_loss(y, p, labels=list(range(len(classes))))
        values["brier"] = float(np.mean(np.sum((p - truth) ** 2, axis=1)))
        roc, pr, aucs, aps, weights = [], [], [], [], []
        positive_index = classes.index(config.positive_class or classes[-1])
        indices = [positive_index] if len(classes) == 2 else list(range(len(classes)))
        if len(classes) == 2:
            values["brier"] = float(
                np.mean((p[:, positive_index] - truth[:, positive_index]) ** 2)
            )
        for i in indices:
            target = truth[:, i]
            if len(np.unique(target)) != 2:
                continue
            area, ap = (
                sm.roc_auc_score(target, p[:, i]),
                sm.average_precision_score(target, p[:, i]),
            )
            aucs.append(area)
            aps.append(ap)
            weights.append(target.sum())
            if selected_charts & {"roc", "pr"}:
                fpr, tpr, _ = sm.roc_curve(target, p[:, i])
                precision, recall, _ = sm.precision_recall_curve(target, p[:, i])
                roc.append(series(classes[i], fpr, tpr, metric=float(area)))
                pr.append(series(classes[i], recall, precision, metric=float(ap)))
        if aucs and len(aucs) == len(indices):
            weights = weights if config.average == "weighted" else None
            values["auc"] = float(np.average(aucs, weights=weights))
            values["average_precision"] = float(np.average(aps, weights=weights))
            if config.average == "micro" and len(classes) > 2:
                values["auc"] = sm.roc_auc_score(truth.ravel(), p.ravel())
                values["average_precision"] = sm.average_precision_score(
                    truth.ravel(), p.ravel()
                )
        if selected_charts & {"roc", "pr", "calibration", "threshold"}:
            charts["roc"] = {"kind": "line", "series": roc}
            charts["pr"] = {"kind": "line", "series": pr}
            from sklearn.calibration import calibration_curve

            if len(classes) == 2:
                target, scores = truth[:, positive_index], p[:, positive_index]
            else:
                target, scores = (y == p.argmax(axis=1)).astype(int), p.max(axis=1)
            observed, predicted = calibration_curve(target, scores, n_bins=10)
            charts["calibration"] = {
                "kind": "line",
                "series": [
                    series("observed", predicted, observed),
                    series("ideal", [0, 1], [0, 1]),
                ],
            }
            if len(classes) == 2:
                thresholds = np.linspace(0, 1, 101)
                positives = np.sort(scores[target == 1])
                negatives = np.sort(scores[target == 0])
                sensitivities = 1 - np.searchsorted(positives, thresholds, side="left") / len(positives) if len(positives) else np.full(101, np.nan)
                specificities = np.searchsorted(negatives, thresholds, side="left") / len(negatives) if len(negatives) else np.full(101, np.nan)
                charts["threshold"] = {
                    "kind": "line",
                    "series": [
                        series("sensitivity", thresholds, sensitivities),
                        series("specificity", thresholds, specificities),
                    ],
                }
    return finite(values), finite(charts)


def survival(rows, config, classes, draw=True):
    valid = [r for r in rows if r.get("metadata", {}).get("risk_score") is not None]
    labelled = [
        r
        for r in valid
        if r.get("event_time") is not None and r.get("event_status") is not None
    ]
    values, charts = {}, {}
    if valid:
        risks = np.array([r["metadata"]["risk_score"] for r in valid], dtype=float)
        values["mean_risk"] = float(risks.mean())
        if draw:
            counts, bins = np.histogram(risks, bins=20)
            charts["risk"] = {
                "kind": "bar",
                "series": [series("risk", (bins[:-1] + bins[1:]) / 2, counts)],
            }
    if len(labelled) >= 2:
        from sksurv.metrics import concordance_index_censored, integrated_brier_score

        times = np.array([r["event_time"] for r in labelled], dtype=float)
        events = np.array([bool(r["event_status"]) for r in labelled])
        risks = np.array([r["metadata"]["risk_score"] for r in labelled], dtype=float)
        try:
            values["c_index"] = float(
                concordance_index_censored(events, times, risks)[0]
            )
        except ValueError:
            pass
        if "integrated_brier_score" in config.metrics and all(
            r["metadata"].get("surv_probs") and r["metadata"].get("bin_edges")
            for r in labelled
        ):
            grids = [r["metadata"]["bin_edges"] for r in labelled]
            if any(grid != grids[0] for grid in grids):
                raise ValueError("Survival probability time grids differ")
            grid = np.array(grids[0][1:], dtype=float)
            mask = (grid > times.min()) & (grid < times.max())
            if mask.sum() >= 2:
                outcomes = np.array(
                    list(zip(events, times)), dtype=[("event", bool), ("time", float)]
                )
                probabilities = np.array(
                    [r["metadata"]["surv_probs"] for r in labelled], dtype=float
                )
                try:
                    values["integrated_brier_score"] = float(
                        integrated_brier_score(
                            outcomes, outcomes, probabilities[:, mask], grid[mask]
                        )
                    )
                except ValueError:
                    pass
        if draw:
            from sksurv.nonparametric import kaplan_meier_estimator

            cutoff = float(np.median(risks))
            curves = []
            for name, selected in [
                ("high risk", risks >= cutoff),
                ("low risk", risks < cutoff),
            ]:
                if selected.any():
                    x, y = kaplan_meier_estimator(events[selected], times[selected])
                    curves.append(series(name, x, y))
            charts["km"] = {
                "kind": "line",
                "step": True,
                "cutoff": cutoff,
                "series": curves,
            }
    return finite(values), charts


def detection(rows, config, classes, draw=True):
    from .detection_metrics import evaluate_detection
    values, curves = evaluate_detection(
        [row["metadata"]["detection"] for row in rows], classes,
        threshold=config.threshold, iou=config.detection_iou,
    )
    return values, {"detection_pr": {"kind": "line", "series": curves}} if draw else {}


def segmentation(rows, config, classes, draw=True):
    values, charts = {}, {}
    for key in config.metrics:
        raw = key.removeprefix("pixel_")
        samples = [r.get("metadata", {}).get("metrics", {}).get(raw) for r in rows]
        samples = [
            v for v in samples if isinstance(v, (int, float)) and math.isfinite(v)
        ]
        if samples:
            values[key] = float(np.mean(samples))
    if draw:
        series_data = []
        for key in ("iou", "miou", "dice"):
            pairs = [
                (i, r.get("metadata", {}).get("metrics", {}).get(key))
                for i, r in enumerate(rows)
            ]
            pairs = [
                (i, v)
                for i, v in pairs
                if isinstance(v, (int, float)) and math.isfinite(v)
            ]
            if pairs:
                series_data.append(
                    series(key, [v[0] for v in pairs], [v[1] for v in pairs])
                )
        charts["segmentation"] = {"kind": "line", "series": series_data}
    return values, charts


def compute_source(source, rows, config: AnalysisConfig, progress=None):
    details = source["details"]
    classes = details.get("classes", [])
    kind = family(source["task_type"])
    if kind in {"segmentation", "detection"} and config.unit == "case":
        raise ValueError("Segmentation evaluation uses image-level samples")
    rows = prepare_rows(rows, config, classes)
    if kind == "segmentation":
        from .segmentation_thresholds import metrics_at_threshold
        # Calculate once per image, then bootstrap/group on scalar metrics.
        rows = [{**row, "metadata": {**row.get("metadata", {}), "metrics": metrics_at_threshold(
            row.get("metadata", {}), config.threshold)}} for row in rows]
    if not rows:
        raise ValueError("No evaluation samples match the selected split and filters")
    calculator = {
        "classification": classification,
        "survival": survival,
        "segmentation": segmentation,
        "detection": detection,
    }[kind]
    values, charts = calculator(rows, config, classes)
    if progress:
        progress(0.15 if config.interval.enabled else 0.85)
    values["sample_count"] = len(rows)
    measured = {}
    for key in config.metrics:
        definition = METRIC_BY_ID.get(key, {})
        value = values.get(key)
        measured[key] = {
            "value": value,
            "label": definition.get("label", key),
            "unit": definition.get("unit", ""),
            "direction": definition.get("direction", ""),
            "reason": None
            if value is not None
            else "Required data or valid evaluation pairs are unavailable",
        }
    if config.interval.enabled and rows:
        clusters = defaultdict(list)
        for i, row in enumerate(rows):
            identity = (
                (
                    row["dataset_id"],
                    row["case_id"] or row.get("sample_id") or row["wsi_id"],
                )
                if config.interval.unit == "case"
                else i
            )
            clusters[identity].append(row)
        groups = list(clusters.values())
        rng = np.random.default_rng(config.interval.seed)
        boot = defaultdict(list)
        for iteration in range(config.interval.samples):
            sample = [
                row
                for i in rng.integers(0, len(groups), len(groups))
                for row in groups[i]
            ]
            scores, _ = calculator(sample, config, classes, draw=False)
            if progress and (iteration % 5 == 0 or iteration + 1 == config.interval.samples):
                progress(0.15 + 0.7 * (iteration + 1) / config.interval.samples, "bootstrap")
            scores["sample_count"] = len(sample)
            for key, metric in measured.items():
                value = scores.get(key)
                if value is not None and math.isfinite(value):
                    boot[key].append(value)
        alpha = (1 - config.interval.level) / 2
        for key, metric in measured.items():
            samples = boot[key]
            metric["ci_valid_samples"] = len(samples)
            if len(samples) >= max(30, config.interval.samples // 2):
                metric["ci_lower"], metric["ci_upper"] = np.quantile(
                    samples, [alpha, 1 - alpha]
                ).tolist()
    groups = []
    if config.group_by:
        buckets = defaultdict(list)
        for row in rows:
            if config.group_by == "age_band":
                age = row.get("age")
                value = (
                    "missing"
                    if age is None
                    else f"{int(age // 10) * 10}–{int(age // 10) * 10 + 9}"
                )
            else:
                value = str(row.get(config.group_by) or "missing")
            buckets[value].append(row)
        if len(buckets) > 100:
            raise ValueError("Grouping exceeds 100 groups; narrow the selected data")
        for label, members in sorted(buckets.items()):
            scores, _ = calculator(members, config, classes, draw=False)
            scores["sample_count"] = len(members)
            groups.append(
                {
                    "group": label,
                    "count": len(members),
                    "metrics": {key: scores.get(key) for key in config.metrics},
                }
            )
    selection = {chart.id: chart for chart in config.charts}
    charts = {
        key: {**value, "title": selection[key].title, "color": selection[key].color}
        for key, value in charts.items()
        if key in selection
    }
    labelled_count = (
        sum(r.get("label") is not None for r in rows)
        if kind == "classification"
        else sum(bool(r.get("metadata", {}).get("metrics")) for r in rows)
        if kind == "segmentation"
        else sum(r.get("metadata", {}).get("detection", {}).get("target") is not None for r in rows)
        if kind == "detection"
        else sum(
            r.get("event_time") is not None and r.get("event_status") is not None
            for r in rows
        )
    )
    notes = []
    if config.unit == "case":
        notes.append(
            "One sample per dataset/case; classification probabilities and survival risk are averaged across slides."
        )
    if "integrated_brier_score" in values:
        notes.append(
            "IBS uses the evaluation cohort censoring distribution and the saved probability time grid."
        )
    if kind == "segmentation":
        notes.append(
            "Segmentation metrics are macro averages of saved per-image metrics."
        )
    if kind == "detection":
        notes.append("COCO 101-point mAP uses all saved scores and at most 100 detections per image. Confidence and IoU thresholds affect operating-point precision, recall, F1 and matching counts.")
    if labelled_count < len(rows) and kind != "segmentation":
        notes.append(
            f"Ground truth available for {labelled_count}/{len(rows)} samples; supervised metrics use labelled pairs only."
        )
    samples = [
        {
            "task_type": source["task_type"],
            "task_id": source.get("task_id"),
            "fold_key": r.get("split") if str(r.get("split", "")).startswith("fold_") else None,
            "classes": classes,
            "probs": r.get("probs") if kind == "classification" else None,
            **({"risk_score": r.get("metadata", {}).get("risk_score"),
                "event_time": r.get("event_time"), "event_status": r.get("event_status")} if kind == "survival" else {}),
            **({"segmentation_preview": r.get("metadata", {}).get("segmentation_preview", False),
                "has_ground_truth": r.get("metadata", {}).get("has_ground_truth", False),
                "metrics": r.get("metadata", {}).get("metrics", {})} if kind == "segmentation" else {}),
            **({"detection": r["metadata"]["detection"], "image_size": r["metadata"].get("image_size"),
                "classes": classes} if kind == "detection" else {}),
            **{
            k: r.get(k)
            for k in (
                "sample_id",
                "wsi_id",
                "filename",
                "case_id",
                "dataset_id",
                "label",
                "pred",
                "confidence",
                "source",
                "gender",
                "age",
            )
            },
        }
        for r in rows
    ]
    return {
        "source_id": source["source_id"],
        "title": source["title"],
        "revision": source["revision"],
        "count": len(rows),
        "gt_count": labelled_count,
        "sample_fingerprint": digest(sorted(r["sample_id"] for r in rows)),
        "metrics": measured,
        "charts": charts,
        "groups": groups,
        "notes": notes,
        "samples": samples[:50],
        "_samples": samples,
        "_predictions": {
            r["sample_id"]: r.get("pred") for r in rows if kind == "classification" and r.get("pred") is not None
        },
    }


def compare(results, config):
    pairs = []
    for i, left in enumerate(results):
        for right in results[i + 1 :]:
            a, b = left.get("_predictions", {}), right.get("_predictions", {})
            overlap = set(a) & set(b)
            same = bool(left.get("sample_fingerprint")) and left.get(
                "sample_fingerprint"
            ) == right.get("sample_fingerprint")
            pairs.append(
                {
                    "left": left["source_id"],
                    "right": right["source_id"],
                    "same_samples": same,
                    "overlap": len(overlap),
                    "disagreement": sum(a[k] != b[k] for k in overlap) / len(overlap)
                    if overlap
                    else None,
                    "note": "Same evaluation samples"
                    if same
                    else "Evaluation cohorts differ or sample-level evidence is unavailable; descriptive comparison only",
                }
            )
    for result in results:
        result.pop("_predictions", None)
    return pairs
