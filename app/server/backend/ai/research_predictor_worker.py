"""Task-aware research model worker. Arrays use NPZ; JSON-lines control requests."""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

import numpy as np

ADAPTER_ROOT = Path("/adapter")
EXCHANGE_ROOT = Path("/exchange")


def load_model(path: Path, config: dict):
    spec = config["_prediction"]
    if spec["runtime"] == "python":
        import importlib.util

        entry = ADAPTER_ROOT / spec["entrypoint"]
        sys.path.insert(0, str(entry.parent))
        module_spec = importlib.util.spec_from_file_location("research_adapter", entry)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        predictor = module.load_predictor(str(path), config)

        def predict(inputs, context):
            return predictor.predict(inputs, context)

        return int(getattr(predictor, "feature_dim", 0)), spec["classes"], None, predict
    if spec["runtime"] == "sklearn":
        import joblib
        from threadpoolctl import threadpool_limits

        threadpool_limits(2)
        saved = joblib.load(path)
        scaler = saved.get("scaler") if isinstance(saved, dict) else None
        model = saved["model"] if isinstance(saved, dict) else saved
        if not type(model).__module__.startswith("sklearn."):
            raise ValueError("Expected a sklearn classifier or pipeline")
        dimension = int((scaler if scaler is not None else model).n_features_in_)
        values = list(model.classes_)
        positive = (
            saved.get("positive_label")
            if isinstance(saved, dict)
            else config.get("positive_label")
        )
        config["_available_score_method"] = (
            "predict_proba"
            if hasattr(model, "predict_proba")
            else "sigmoid_decision"
            if len(values) == 2
            else "softmax_decision"
        )

        def predict(x):
            if scaler is not None:
                x = scaler.transform(x)
            if spec["score_method"] == "predict_proba":
                return np.asarray(model.predict_proba(x), dtype=np.float64)
            scores = np.asarray(model.decision_function(x), dtype=np.float64)
            if spec["score_method"] == "sigmoid_decision" and scores.ndim == 1:
                positive_scores = 1 / (1 + np.exp(-np.clip(scores, -700, 700)))
                return np.column_stack([1 - positive_scores, positive_scores])
            if spec["score_method"] != "softmax_decision" or scores.ndim != 2:
                raise ValueError(
                    "Decision score transformation does not match the trained protocol"
                )
            scores -= scores.max(axis=1, keepdims=True)
            exp = np.exp(scores)
            return exp / exp.sum(axis=1, keepdims=True)

        return (
            dimension,
            [v.item() if isinstance(v, np.generic) else v for v in values],
            positive,
            predict,
        )
    if spec["runtime"] == "torch_mlp":
        import torch
        from torch import nn

        torch.set_num_threads(2)
        saved = torch.load(path, map_location="cpu", weights_only=True)
        trained = saved.get("config") or config
        dimension = int(trained["input_dim"])
        state = saved["state_dict"]
        if set(state) == {"weight", "bias"}:
            model = nn.Linear(dimension, int(state["weight"].shape[0]))
        elif set(state) == {"0.weight", "0.bias", "3.weight", "3.bias"}:
            activation = {"relu": nn.ReLU, "gelu": nn.GELU, "tanh": nn.Tanh}[
                spec["activation"]
            ]
            model = nn.Sequential(
                nn.Linear(dimension, int(state["0.weight"].shape[0])),
                activation(),
                nn.Dropout(float(trained.get("dropout", 0.2))),
                nn.Linear(
                    int(state["0.weight"].shape[0]), int(state["3.weight"].shape[0])
                ),
            )
        else:
            raise ValueError(
                "Export a native aggregator checkpoint or a supported linear/MLP predictor"
            )
        model.load_state_dict(state, strict=True)
        model.eval()
        mean, std = saved["mean"].float(), saved["std"].float()
        if (
            mean.shape != (dimension,)
            or std.shape != (dimension,)
            or not torch.isfinite(mean).all()
            or not torch.isfinite(std).all()
            or not (std > 0).all()
        ):
            raise ValueError("Invalid fitted preprocessing parameters")
        labels = [
            label
            for label, _ in sorted(
                trained["label_map"].items(), key=lambda item: item[1]
            )
        ]

        def predict(x):
            with torch.inference_mode():
                logits = model((torch.from_numpy(x).float() - mean) / std)
                if logits.shape[1] == 1:
                    positive = torch.sigmoid(logits)
                    return torch.cat([1 - positive, positive], dim=1).numpy()
                return torch.softmax(logits, dim=1).numpy()

        return dimension, labels, None, predict
    raise ValueError("Unsupported classifier format")


def main():
    with contextlib.redirect_stdout(sys.stderr):
        path = Path(sys.argv[1])
        config = json.loads(Path(sys.argv[2]).read_text())
        dimension, model_classes, positive, predict = load_model(path, config)
        if (
            config["_prediction"]["input_kind"] == "features"
            and not 1 <= dimension <= 65536
        ):
            raise ValueError("Invalid feature dimension")
    print(
        json.dumps(
            {
                "feature_dim": dimension,
                "model_classes": model_classes,
                "positive_label": positive,
                "score_method": config.get("_available_score_method"),
            }
        ),
        flush=True,
    )
    for line in sys.stdin:
        try:
            request = json.loads(line)
            spec = config["_prediction"]
            x = np.load(EXCHANGE_ROOT / "input.npy", allow_pickle=False)
            if not np.isfinite(x).all():
                raise ValueError("Nonfinite input")
            if spec["input_kind"] == "features":
                x = x.astype(np.float32, copy=False)
                if x.ndim != 2 or x.shape[1] != dimension or not 1 <= len(x) <= 2000000:
                    raise ValueError("Invalid input features")
            elif x.ndim != 3 or x.shape[2] != 3 or max(x.shape[:2]) > 16384:
                raise ValueError("Expected an RGB image array")
            with contextlib.redirect_stdout(sys.stderr):
                result = (
                    predict(x, request)
                    if spec["runtime"] == "python"
                    else {"probabilities": predict(x)}
                )
            result = validate_output(result, spec, x.shape)
            np.savez(EXCHANGE_ROOT / "output.npz", **result)
            print(json.dumps({"ok": True}), flush=True)
        except Exception as exc:  # noqa: BLE001 - bounded worker protocol error response
            import traceback

            traceback.print_exc(file=sys.stderr)
            print(json.dumps({"error": type(exc).__name__}), flush=True)


def validate_output(result, spec, input_shape):
    if not isinstance(result, dict):
        raise TypeError("Predictor must return a dict of named arrays")
    arrays = {key: np.asarray(value) for key, value in result.items()}
    if any(
        value.dtype.kind not in "biuf" or not np.isfinite(value).all()
        for value in arrays.values()
    ):
        raise ValueError("Output must contain finite numeric arrays")
    task = spec["task_type"]
    if task.endswith("classification"):
        probs = arrays.get("probabilities")
        if (
            probs is None
            or probs.shape != (1, len(spec["classes"]))
            or np.any(probs < 0)
            or not np.allclose(probs.sum(axis=1), 1, atol=1e-5)
        ):
            raise ValueError("Expected one ordered probability vector")
        return {"probabilities": probs}
    if task == "wsi_survival":
        risk = arrays.get("risk_score")
        if risk is None or risk.size != 1:
            raise ValueError(
                "Survival requires a scalar risk_score (higher means higher risk)"
            )
        output = {"risk_score": risk.reshape(1)}
        if "survival" in arrays:
            curve = arrays["survival"].reshape(-1)
            if (
                len(curve) != len(spec["time_bins"])
                or np.any((curve < 0) | (curve > 1))
                or np.any(np.diff(curve) > 1e-6)
            ):
                raise ValueError("Invalid survival curve/time bins")
            output["survival"] = curve
        return output
    if task == "patch_detection":
        if set(arrays) != {"boxes", "labels", "scores"}:
            raise ValueError("Detection requires boxes, labels and scores")
        boxes, labels, scores = arrays["boxes"], arrays["labels"], arrays["scores"]
        if boxes.ndim != 2 or boxes.shape[1] != 4 or labels.shape != (len(boxes),) or scores.shape != (len(boxes),) or len(boxes) > 10000:
            raise ValueError("Detection output requires aligned N×4, N, N arrays")
        if labels.dtype.kind not in "iu" or np.any((labels < 1) | (labels > len(spec["classes"]))):
            raise ValueError("Detection labels must be one-based integer class indices")
        if np.any((scores < 0) | (scores > 1)) or np.any(boxes < 0) or np.any(boxes[:, 2:] <= boxes[:, :2]) or np.any(boxes[:, [0, 2]] > input_shape[1]) or np.any(boxes[:, [1, 3]] > input_shape[0]):
            raise ValueError("Detection boxes must fit the original image and scores must be in [0,1]")
        return arrays
    mask = arrays.get("mask")
    if (
        mask is None
        or mask.shape != (len(spec["classes"]), *input_shape[:2])
        or not np.isin(mask, [0, 1]).all()
    ):
        raise ValueError(
            "Segmentation requires binary C,H,W masks at original image size"
        )
    output = {"mask": mask.astype(np.uint8)}
    if "probabilities" in arrays:
        probabilities = arrays["probabilities"]
        if probabilities.shape != mask.shape or np.any((probabilities < 0) | (probabilities > 1)) or not np.array_equal(probabilities > 0.5, mask.astype(bool)):
            raise ValueError("Segmentation probabilities must match mask shape and its >0.5 decisions")
        output["probabilities"] = probabilities
    return output


if __name__ == "__main__":
    main()
