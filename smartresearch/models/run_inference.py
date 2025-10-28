"""
WSI Classification Inference Implementation

Uses feature extractors and aggregators from lib for inference.
Expects tiles to be provided by the WSI service.
"""
import torch

from lib import create_extractor, create_aggregator


def run_inference(wsi_path: str, params: dict, classes: list) -> dict:
    """
    Run WSI classification inference

    NOTE: This function expects tiles to be extracted by the WSI service.
    The wsi_path is used to retrieve pre-extracted tiles from the WSI service.

    Args:
        wsi_path: WSI file path (used to fetch tiles from WSI service)
        params: Inference parameters
            {
                "tiles": List[PIL.Image],  # Pre-extracted tiles from WSI service
                "feature_model": "resnet50",  # or "vit_large"
                "aggregator": "abmil",        # or "mean"
                "batch_size": 64,
                "device": "cuda",
                "checkpoint": None  # Optional checkpoint path
            }
        classes: List of class names, e.g. ["LUAD", "LUSC", "Normal"]

    Returns:
        {
            "pred": str,              # Predicted class name
            "probs": dict,            # {class_name: probability}
            "num_tiles": int          # Number of tiles processed
        }
    """
    # Extract parameters
    tiles = params.get("tiles", [])
    feature_model = params.get("feature_model", "resnet50")
    aggregator_name = params.get("aggregator", "abmil")
    batch_size = params.get("batch_size", 64)
    device = params.get("device", "cuda" if torch.cuda.is_available() else "cpu")

    print(f"[Inference] Configuration:")
    print(f"  - Feature extractor: {feature_model}")
    print(f"  - Aggregator: {aggregator_name}")
    print(f"  - Device: {device}")
    print(f"  - Tiles provided: {len(tiles)}")

    num_tiles = len(tiles)

    if num_tiles == 0:
        # No tiles, return uniform probability
        print("[Inference] WARNING: No tiles provided")
        uniform_prob = 1.0 / len(classes)
        return {
            "pred": classes[0],
            "probs": {c: uniform_prob for c in classes},
            "num_tiles": 0
        }

    # Step 1: Create feature extractor
    extractor = create_extractor(feature_model, pretrained=True, device=device)
    feature_dim = extractor.get_feature_dim()
    transforms = extractor.get_transforms()

    print(f"[Inference] Feature dimension: {feature_dim}")

    # Step 2: Extract features in batches
    all_features = []

    for i in range(0, num_tiles, batch_size):
        batch_tiles = tiles[i:i+batch_size]

        # Preprocess
        batch_tensors = [transforms(tile) for tile in batch_tiles]
        batch = torch.stack(batch_tensors, dim=0)

        # Extract features
        features = extractor.extract_batch(batch)
        all_features.append(features.cpu())

    # Concatenate all features
    all_features = torch.cat(all_features, dim=0)  # (num_tiles, feature_dim)
    print(f"[Inference] Feature shape: {all_features.shape}")

    # Step 3: Create aggregator
    aggregator = create_aggregator(
        name=aggregator_name,
        feature_dim=feature_dim,
        num_classes=len(classes),
        device=device,
        checkpoint=params.get("checkpoint")  # Optional: load trained weights
    )

    aggregator.eval()

    # Step 4: Aggregate and predict
    all_features = all_features.to(device)

    with torch.no_grad():
        probs_tensor, pred_idx, _ = aggregator.predict(
            all_features,
            return_attention=(aggregator_name == "abmil")
        )

    # Convert to dictionary format
    probs_array = probs_tensor.cpu().numpy()
    pred_idx = pred_idx.cpu().item()

    probs_dict = {classes[i]: float(probs_array[i]) for i in range(len(classes))}
    pred_class = classes[pred_idx]

    print(f"[Inference] Prediction: {pred_class}")
    print(f"[Inference] Probabilities: {probs_dict}")

    return {
        "pred": pred_class,
        "probs": probs_dict,
        "num_tiles": num_tiles
    }

