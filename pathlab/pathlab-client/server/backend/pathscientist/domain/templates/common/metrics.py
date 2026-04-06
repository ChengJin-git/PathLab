from torchmetrics.classification import Accuracy, F1Score, AUROC


METRIC_MAPPING = {
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
        metric_fn = {}
        for metric_name, params in eval_metrics_cfg.items():
            metric_fn[metric_name] = METRIC_MAPPING[metric_name](**params, num_classes=num_classes)
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

