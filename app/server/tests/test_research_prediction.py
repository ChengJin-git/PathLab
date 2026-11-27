"""Prediction contracts cover different tasks, output types and pooling protocols."""

import sys
from pathlib import Path

import numpy as np
import pytest
import torch

from backend.ai.research_predictor_worker import validate_output
from backend.services.research_prediction import (
    PredictionSpec,
    ResearchPredictor,
    prepare_predictor,
    save_manifest,
)


def test_output_validation_distinguishes_task_semantics():
    assert validate_output(
        {"probabilities": [[0.2, 0.8]]},
        {"task_type": "wsi_classification", "classes": ["a", "b"]},
        (5, 3),
    )["probabilities"].shape == (1, 2)
    survival = {"task_type": "wsi_survival", "classes": [], "time_bins": [1, 2, 3]}
    assert (
        validate_output(
            {"risk_score": -2.5, "survival": [0.9, 0.7, 0.4]}, survival, (5, 3)
        )["risk_score"][0]
        == -2.5
    )
    with pytest.raises(ValueError):
        validate_output(
            {"risk_score": 1, "survival": [0.1, 0.9, 0.4]}, survival, (5, 3)
        )
    with pytest.raises(ValueError):
        validate_output({"probabilities": [[0.2, 0.8]]}, survival, (5, 3))
    segmentation = {"task_type": "patch_segmentation", "classes": ["tumor"]}
    assert (
        validate_output({"mask": np.zeros((1, 8, 9))}, segmentation, (8, 9, 3))[
            "mask"
        ].dtype
        == np.uint8
    )
    with pytest.raises(ValueError):
        validate_output({"mask": np.zeros((8, 9))}, segmentation, (8, 9, 3))


def test_task_contract_rejects_unsupported_silent_coercions():
    with pytest.raises(ValueError):
        PredictionSpec(runtime="sklearn", task_type="wsi_survival", pooling="tile_mean")
    with pytest.raises(ValueError):
        PredictionSpec(
            runtime="python",
            task_type="patch_segmentation",
            input_kind="features",
            pooling="none",
            classes=["tumor"],
        )
    with pytest.raises(ValueError):
        PredictionSpec(
            runtime="python", task_type="wsi_survival", pooling="none", time_bins=[5, 1]
        )


@pytest.fixture
def local_worker(monkeypatch):
    """Run the real protocol with the test interpreter; production sandbox tested separately."""
    import subprocess

    from backend.services import research_prediction as service

    original = subprocess.Popen

    def start(command, **kwargs):
        if not isinstance(command, list) or '/worker.py' not in command:
            return original(command, **kwargs)
        mounts = {}
        for index, value in enumerate(command):
            if value == "--bind":
                host, container, _ = command[index + 1].rsplit(":", 2)
                mounts[container] = host
        adapter = mounts.get("/adapter", "")
        bootstrap = (
            "import sys; from pathlib import Path; import numpy as np; "
            "from backend.ai import research_predictor_worker as w; "
            f"w.ADAPTER_ROOT=Path({adapter!r}); w.EXCHANGE_ROOT=Path({mounts['/exchange']!r}); "
            f'sys.argv=["worker",{mounts[command[-2]]!r},{mounts["/config.json"]!r}]; w.main()'
        )
        kwargs["env"] = {**kwargs["env"], "PYTHONPATH": str(Path.cwd())}
        return original([sys.executable, "-c", bootstrap], **kwargs)

    monkeypatch.setattr(service.subprocess, "Popen", start)


@pytest.mark.parametrize(
    "task,input_kind,classes",
    [
        ("wsi_classification", "features", ["a", "b"]),
        ("wsi_survival", "features", []),
        ("patch_classification", "image", ["a", "b"]),
        ("patch_segmentation", "image", ["tumor"]),
    ],
)
def test_python_adapter_roundtrip_all_tasks(
    tmp_path, local_worker, task, input_kind, classes
):
    model = tmp_path / "weights.bin"
    model.write_bytes(b"fixture model")
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "predict.py").write_text("""import numpy as np
class Predictor:
    feature_dim=3
    def __init__(self,config): self.spec=config['_prediction']
    def predict(self,inputs,context):
        task=self.spec['task_type']
        if task.endswith('classification'): return {'probabilities':np.array([[.25,.75]])}
        if task=='wsi_survival': return {'risk_score':np.array([inputs.mean()]),'survival':np.array([.9,.4])}
        return {'mask':np.ones((1,*inputs.shape[:2]),dtype=np.uint8)}
def load_predictor(model_path,config): return Predictor(config)
""")
    spec = {
        "runtime": "python",
        "task_type": task,
        "input_kind": input_kind,
        "pooling": "none",
        "classes": classes,
        "entrypoint": "predict.py",
        "time_bins": [1, 2] if task == "wsi_survival" else [],
    }
    manifest = prepare_predictor(model, "test-encoder", spec, adapter)
    save_manifest(tmp_path, manifest)
    predictor = ResearchPredictor(tmp_path)
    try:
        result = (
            predictor.predict_image(np.zeros((8, 9, 3), dtype=np.uint8))
            if input_kind == "image"
            else predictor.predict_features(torch.ones(5, 3), [2, 3])
        )
        assert (
            "mask"
            if task == "patch_segmentation"
            else "risk_score"
            if task == "wsi_survival"
            else "probabilities"
        ) in result
    finally:
        predictor.close()

    assert predictor.process.process.poll() is not None
    assert not predictor.process.root.exists()
    (adapter / "predict.py").write_text("# changed after validation")
    with pytest.raises(ValueError, match="adapter changed"):
        ResearchPredictor(tmp_path)


def test_equal_slide_pooling_is_not_tile_weighted(tmp_path, local_worker):
    import joblib
    from sklearn.linear_model import LogisticRegression

    model = LogisticRegression().fit(
        np.array([[0, 0], [1, 1], [4, 4], [5, 5]]), [0, 0, 1, 1]
    )
    path = tmp_path / "weights.joblib"
    joblib.dump(model, path)
    spec = {
        "runtime": "sklearn",
        "task_type": "wsi_classification",
        "classes": ["a", "b"],
        "pooling": "tile_mean_then_slide_mean",
    }
    save_manifest(tmp_path, prepare_predictor(path, "encoder", spec))
    predictor = ResearchPredictor(tmp_path)
    try:
        features = torch.tensor([[0.0, 0.0], [4.0, 4.0], [4.0, 4.0], [4.0, 4.0]])
        result = predictor.predict_features(features, [1, 3])["probabilities"]
        np.testing.assert_allclose(result, model.predict_proba([[2, 2]]), rtol=1e-6)
        assert not np.allclose(result, model.predict_proba([[3, 3]]))
    finally:
        predictor.close()


@pytest.mark.parametrize(
    "decision,n_classes", [(False, 2), (False, 3), (True, 2), (True, 3)]
)
def test_fitted_pipeline_class_order_and_explicit_scores(
    tmp_path, local_worker, decision, n_classes
):
    import joblib
    from scipy.special import expit, softmax
    from sklearn.datasets import make_classification
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import LinearSVC

    x, y = make_classification(
        n_samples=60,
        n_features=6,
        n_informative=4,
        n_classes=n_classes,
        random_state=19,
    )
    labels = np.array(["zebra", "ant", "mouse"])[:n_classes][y]
    model = make_pipeline(
        StandardScaler(), LinearSVC() if decision else LogisticRegression()
    ).fit(x, labels)
    path = tmp_path / "model.joblib"
    joblib.dump(model, path)
    spec = {
        "runtime": "sklearn",
        "task_type": "wsi_classification",
        "classes": model.classes_.tolist(),
        "pooling": "tile_mean",
        "score_method": ("sigmoid_decision" if n_classes == 2 else "softmax_decision")
        if decision
        else "predict_proba",
    }
    save_manifest(tmp_path, prepare_predictor(path, "encoder", spec))
    predictor = ResearchPredictor(tmp_path)
    inputs = x[:7].astype(np.float32)
    try:
        actual = predictor.predict_features(torch.from_numpy(inputs))["probabilities"]
        if decision:
            scores = model.decision_function(inputs.mean(0, keepdims=True))
            expected = (
                np.column_stack([1 - expit(scores), expit(scores)])
                if n_classes == 2
                else softmax(scores, axis=1)
            )
        else:
            expected = model.predict_proba(inputs.mean(0, keepdims=True))
        np.testing.assert_allclose(actual, expected, rtol=1e-5, atol=1e-7)
    finally:
        predictor.close()
    with pytest.raises(ValueError, match="output order"):
        prepare_predictor(
            path, "encoder", {**spec, "classes": list(reversed(spec["classes"]))}
        )
    path.write_bytes(b"changed weights")
    with pytest.raises(ValueError, match="Model has changed"):
        ResearchPredictor(tmp_path)


def test_torch_normalization_activation_and_probability_parity(tmp_path, local_worker):
    model = torch.nn.Sequential(
        torch.nn.Linear(3, 4),
        torch.nn.Tanh(),
        torch.nn.Dropout(0.2),
        torch.nn.Linear(4, 2),
    ).eval()
    mean, std = torch.tensor([1.0, 2.0, 3.0]), torch.tensor([2.0, 3.0, 4.0])
    path = tmp_path / "model.pt"
    torch.save(
        {
            "state_dict": model.state_dict(),
            "mean": mean,
            "std": std,
            "config": {"input_dim": 3, "label_map": {"b": 1, "a": 0}},
        },
        path,
    )
    spec = {
        "runtime": "torch_mlp",
        "activation": "tanh",
        "task_type": "wsi_classification",
        "classes": ["a", "b"],
        "pooling": "tile_mean",
    }
    save_manifest(tmp_path, prepare_predictor(path, "encoder", spec))
    predictor = ResearchPredictor(tmp_path)
    inputs = torch.tensor([[1.0, 2.0, 3.0], [7.0, 8.0, 9.0]])
    try:
        actual = predictor.predict_features(inputs)["probabilities"]
        with torch.no_grad():
            expected = (
                model((inputs.mean(0, keepdim=True) - mean) / std).softmax(-1).numpy()
            )
        np.testing.assert_allclose(actual, expected, rtol=1e-6)
    finally:
        predictor.close()
