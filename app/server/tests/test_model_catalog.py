from types import SimpleNamespace

from backend.services.model_catalog import metric_groups, model_capability


def test_research_metrics_preserve_oof_test_and_zero_without_fabricating_loss():
    groups = metric_groups(
        {
            "oof.auc": 0.833333,
            "oof.accuracy": 0.714,
            "test.auc": 0.0,
            "test.accuracy": 0.4,
            "timing.total_fit_seconds": 12,
        }
    )
    assert groups == [
        {"split": "oof", "metrics": {"auc": 0.833333, "accuracy": 0.714}},
        {"split": "test", "metrics": {"auc": 0.0, "accuracy": 0.4}},
    ]
    assert metric_groups({"val_patient_auc": 0.8, "test_slide_auc": 0.1}) == [
        {"split": "val_patient", "metrics": {"auc": 0.8}},
        {"split": "test_slide", "metrics": {"auc": 0.1}},
    ]


def test_research_artifact_status_is_separate_from_disabled_native_model():
    model = SimpleNamespace(
        model_path="model.joblib", val_metrics={"oof": {"auc": 0.7}}
    )
    research = model_capability(
        model,
        SimpleNamespace(model_config={"source": "autoresearch", "session_id": "s"}),
    )
    assert (
        research["inference_ready"] is False
        and research["inference_reason"] == "unsupported_format"
    )
    assert research["research_session_id"] == "s"
    assert (
        model_capability(model, SimpleNamespace(model_config={}))["inference_ready"]
        is True
    )


def test_native_checkpoint_requires_actual_predictor_contract(tmp_path):
    import json

    import torch

    from backend.ai.aggregators import get_aggregator
    from backend.services.model_catalog import validate_research_checkpoint

    network = get_aggregator("abmil", in_dim=8, num_classes=2)
    model = tmp_path / "model.pt"
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {"model": "abmil", "feature_extractor": "conch", "classes": ["A", "B"]}
        )
    )
    torch.save(
        {"state_dict": network.state_dict(), "in_dim": 8, "num_classes": 2}, model
    )
    assert validate_research_checkpoint(model, config, "abmil", "conch")["classes"] == [
        "A",
        "B",
    ]
    torch.save({"state_dict": {}, "in_dim": 8, "num_classes": 2}, model)
    assert validate_research_checkpoint(model, config, "abmil", "conch") is None
