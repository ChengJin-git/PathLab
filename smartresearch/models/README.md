# WSI Classification Models

This directory contains the WSI classification inference implementation.

## Interface

Create a file `run_inference.py` with the following function:

```python
def run_inference(wsi_path: str, params: dict, classes: list) -> dict:
    """
    Run WSI classification inference
    
    Args:
        wsi_path: Full path to WSI file (e.g., "/path/to/slide.svs")
        params: Inference parameters
            {
                "tile_size": 256,
                "stride": 256,
                "feature_model": "resnet50_imagenet",
                "aggregator": "mean",
                "batch_size": 64,
                "device": "cuda"
            }
        classes: List of class names (sorted), e.g., ["LUAD", "LUSC", "Normal"]
    
    Returns:
        {
            "pred": str,              # Predicted class name
            "probs": dict,            # {class_name: probability}
            "num_tiles": int          # Optional: number of tiles processed
        }
    """
    # Your implementation here
    pass
```

## Example Stub Implementation

```python
def run_inference(wsi_path: str, params: dict, classes: list) -> dict:
    """Minimal stub that returns uniform probabilities"""
    import random
    
    # Simulate processing
    num_tiles = random.randint(100, 500)
    
    # Uniform probabilities
    uniform_prob = 1.0 / len(classes)
    probs = {c: uniform_prob for c in classes}
    
    # Random prediction
    pred = random.choice(classes)
    probs[pred] = 0.9  # Boost predicted class
    
    # Normalize
    total = sum(probs.values())
    probs = {k: v/total for k, v in probs.items()}
    
    return {
        "pred": pred,
        "probs": probs,
        "num_tiles": num_tiles
    }
```

## Notes

- If `run_inference.py` doesn't exist, the system falls back to stub mode (uses metadata label)
- You can use any libraries you need (torch, openslide, etc.)
- The function will be called synchronously, so keep it reasonably fast or implement async if needed
- Error handling: if your function raises an exception, the system falls back to stub mode

