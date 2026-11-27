"""Load the classifier-head contract written by PatchClassificationTrainer.

Inference entrypoints import this module when executing the requested model.
"""

from pathlib import Path

CLASSIFIER_CHECKPOINT = "classifier_head.pth"


def load_classifier_head(path: Path, device: str):
    import torch
    from .registry import get_classifier

    checkpoint = torch.load(path, map_location=device, weights_only=True)
    head = get_classifier(
        checkpoint["classifier_name"],
        num_classes=checkpoint["num_classes"],
        in_dim=checkpoint.get("extractor_dim") or checkpoint["feature_dim"],
    ).to(device)
    head.load_state_dict(checkpoint["state_dict"])
    return head.eval(), checkpoint


def load_patch_classifiers(
    model_dir: Path,
    config: dict,
    device: str,
    *,
    extractor_name: str = "resnet50",
):
    """Load one extractor and regular/all-fold heads; callers retain aggregation policy."""
    from backend.ai.extractors import get_extractor

    directories = (
        [model_dir / f"fold_{index}" for index in range(int(config["num_folds"]))]
        if config.get("split_type") == "kfold"
        else [model_dir]
    )
    heads = []
    extractor_name = config.get("extractor") or extractor_name
    for directory in directories:
        head, checkpoint = load_classifier_head(directory / CLASSIFIER_CHECKPOINT, device)
        heads.append(head)
        extractor_name = checkpoint.get("extractor_name") or extractor_name
    extractor = get_extractor(extractor_name, pretrained=True).to(device).eval()
    return extractor, heads, extractor_name
