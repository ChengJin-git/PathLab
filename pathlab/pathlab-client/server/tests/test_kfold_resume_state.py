from backend.ai.tasks.training_utils import (
    classification_metrics_from_fold_results,
    should_load_resume_checkpoint,
)


def test_kfold_resume_checkpoint_loads_only_matching_fold_state():
    checkpoint = {"type": "kfold", "fold_idx": 1, "epoch": 3}

    assert should_load_resume_checkpoint(checkpoint, fold_idx=1) is True
    assert should_load_resume_checkpoint(checkpoint, fold_idx=2) is False
    assert should_load_resume_checkpoint(checkpoint, fold_idx=None) is False


def test_regular_resume_checkpoint_loads_only_regular_training_state():
    checkpoint = {"epoch": 3}

    assert should_load_resume_checkpoint(checkpoint, fold_idx=None) is True
    assert should_load_resume_checkpoint(checkpoint, fold_idx=1) is False


def test_completed_kfold_metrics_are_rebuilt_once_from_fold_results():
    fold_results = {
        "fold_0": {"val_metrics": {"accuracy": 0.75, "auc": 0.8, "loss": 0.4}},
        "fold_1": {"val_metrics": {"accuracy": 0.5, "auc": None, "loss": 0.7}},
    }

    metrics = classification_metrics_from_fold_results(fold_results)

    assert metrics == {
        "accuracy": [0.75, 0.5],
        "auc": [0.8],
        "loss": [0.4, 0.7],
    }
