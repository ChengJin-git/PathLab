from __future__ import annotations

from typing import Any

import torch


def _classification_metric_mapping():
    """Import torchmetrics only when classification metrics are requested."""
    from torchmetrics.classification import AUROC, Accuracy, F1Score

    return {
        "accuracy": Accuracy,
        "f1_score": F1Score,
        "auc_roc": AUROC,
    }


class ClassificationMetrics:
    """
    A class to calculate classification metrics such as accuracy, F1 score, and AUC-ROC.
    """

    def __init__(self, num_classes, eval_metrics_cfg):
        self.num_classes = num_classes
        self.eval_metrics_cfg = eval_metrics_cfg

    def init_metrics(self, num_classes, eval_metrics_cfg):
        """
        Build a dictionary of metric objects based on the configuration.
        Args:
            num_classes: Number of classes.
            eval_metrics_cfg: Configuration dictionary for evaluation metrics.
        Returns:
            A dictionary containing metric objects.
        """
        metric_mapping = _classification_metric_mapping()
        metric_fn = {}
        for metric_name, params in eval_metrics_cfg.items():
            metric_fn[metric_name] = metric_mapping[metric_name](
                **params, num_classes=num_classes
            )
        return metric_fn

    def __call__(self, predictions, ground_truths):
        """
        Calculate all metrics based on predictions and ground truths.
        Args:
            predictions: Model predictions.
            ground_truths: Ground truth labels.
        Returns:
            A dictionary containing calculated metric values.
        """
        metrics_fn = self.init_metrics(self.num_classes, self.eval_metrics_cfg)
        results = {}
        for metric_name, metric in metrics_fn.items():
            results[metric_name] = metric(predictions, ground_truths).item()
        return results


def _model_device(model: Any) -> torch.device:
    try:
        return next(model.parameters()).device
    except Exception:
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _survival_risk(output: Any) -> float:
    hazards = output[0] if isinstance(output, (tuple, list)) else output
    if not torch.is_tensor(hazards):
        hazards = torch.as_tensor(hazards)
    hazards = hazards.squeeze(0)
    return float(torch.sigmoid(hazards).sum().detach().cpu())


def _harrell_c_index(times: list[float], events: list[int], risks: list[float]) -> tuple[float, int]:
    concordant = 0.0
    comparable = 0
    for i in range(len(risks)):
        for j in range(i + 1, len(risks)):
            if times[i] == times[j]:
                continue
            if times[i] < times[j] and events[i] == 1:
                shorter, longer = i, j
            elif times[j] < times[i] and events[j] == 1:
                shorter, longer = j, i
            else:
                continue
            comparable += 1
            if risks[shorter] > risks[longer]:
                concordant += 1.0
            elif risks[shorter] == risks[longer]:
                concordant += 0.5
    return (concordant / comparable if comparable else 0.5), comparable


def compute_survival_metrics(
    model,
    features: dict[str, torch.Tensor],
    times: dict[str, float],
    events: dict[str, int],
    sample_ids: list[str],
) -> dict[str, float | int]:
    """Evaluate a survival MIL model and return Harrell C-index metrics."""
    model.eval()
    device = _model_device(model)
    evaluated_times: list[float] = []
    evaluated_events: list[int] = []
    risks: list[float] = []

    with torch.no_grad():
        for sample_id in sample_ids:
            if sample_id not in features or sample_id not in times or sample_id not in events:
                continue
            tensor = features[sample_id]
            if tensor.dim() == 1:
                tensor = tensor.unsqueeze(0)
            output = model(tensor.to(device))
            evaluated_times.append(float(times[sample_id]))
            evaluated_events.append(int(events[sample_id]))
            risks.append(_survival_risk(output))

    c_index, comparable = _harrell_c_index(evaluated_times, evaluated_events, risks)
    return {
        "c_index": round(float(c_index), 4),
        "n_evaluated": len(risks),
        "comparable_pairs": comparable,
    }
