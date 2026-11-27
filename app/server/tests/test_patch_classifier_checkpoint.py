"""Training artifacts must reproduce logits in every patch prediction path."""

import pytest
import torch

from backend.ai.classifiers import get_classifier
from backend.ai.classifiers.checkpoint import load_classifier_head, load_patch_classifiers
from backend.ai.tasks.patch_classification.trainer import PatchClassificationTrainer


@pytest.mark.parametrize("name", ["linear", "mlp", "attention"])
def test_trainer_checkpoint_round_trip_preserves_logits(tmp_path, name):
    torch.manual_seed(42)
    head = get_classifier(name, num_classes=3, in_dim=8).eval()
    features = torch.randn(4, 8)
    trainer = PatchClassificationTrainer(task_id="roundtrip", uploads_root=str(tmp_path), device="cpu")
    trainer._save_checkpoint("resnet50", head, name, 8, 3, 1, 0.001, {}, classes=["a", "b", "c"])
    path = tmp_path / "models/patch_cls_roundtrip/classifier_head.pth"
    loaded, checkpoint = load_classifier_head(path, "cpu")
    assert checkpoint["classifier_name"] == name
    torch.testing.assert_close(loaded(features), head(features), rtol=0, atol=0)


def test_kfold_loader_keeps_all_heads_and_numeric_fold_order(tmp_path, monkeypatch):
    original = []
    for index in range(3):
        head = get_classifier("linear", num_classes=2, in_dim=8).eval()
        original.append(head)
        directory = tmp_path / f"fold_{index}"
        directory.mkdir()
        torch.save({"classifier_name":"linear", "feature_dim":8, "num_classes":2,
                    "state_dict":head.state_dict()}, directory / "classifier_head.pth")
    extractor = torch.nn.Identity()
    monkeypatch.setattr("backend.ai.extractors.get_extractor", lambda name, pretrained: extractor)
    loaded_extractor, heads, name = load_patch_classifiers(
        tmp_path, {"split_type":"kfold", "num_folds":3, "extractor":"resnet50"}, "cpu"
    )
    assert loaded_extractor is extractor and name == "resnet50"
    features = torch.randn(2,8)
    for expected, actual in zip(original, heads, strict=True):
        torch.testing.assert_close(actual(features), expected(features), rtol=0, atol=0)
    (tmp_path / "fold_1/classifier_head.pth").unlink()
    with pytest.raises(FileNotFoundError):
        load_patch_classifiers(tmp_path, {"split_type":"kfold", "num_folds":3}, "cpu")
