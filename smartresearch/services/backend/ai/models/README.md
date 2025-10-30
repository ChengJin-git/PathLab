# WSI Classification Models

This directory contains the WSI classification inference implementation.

## Directory Structure

```
models/
├── README.md                 # This file
├── requirements.txt          # Dependencies
├── run_inference.py          # Inference entry point (called by AI service)
├── lib/                      # Core library
│   ├── __init__.py          # Unified exports
│   ├── registry.py          # Model registration system
│   ├── extractors.py        # Feature extractors (ResNet50, ViT-L, etc.)
│   └── aggregators.py       # Aggregators (ABMIL, Mean, etc.)
├── checkpoints/             # Model weights (not committed to git)
│   ├── README.md
│   └── .gitkeep
└── configs/                 # Configuration files
    ├── default.json
    └── presets/
        └── vit_large_abmil.json
```

## Architecture

**Separation of Concerns:**
- **WSI Service** (`/smartresearch/services/wsi`): Handles WSI file I/O and tile extraction
- **Models** (`/smartresearch/models`): Handles feature extraction and classification

The models library expects **pre-extracted tiles** from the WSI service.

## Quick Start

### 1. Use Registered Models

```python
from lib import create_extractor, create_aggregator
from PIL import Image

# Assume tiles are provided by WSI service
tiles = [...]  # List[PIL.Image] from WSI service

# Create feature extractor
extractor = create_extractor("resnet50", device="cuda")
print(f"Feature dim: {extractor.get_feature_dim()}")  # 2048

# Extract features
transforms = extractor.get_transforms()
batch = torch.stack([transforms(tile) for tile in tiles])
features = extractor.extract_batch(batch)  # (N, 2048)

# Create aggregator
aggregator = create_aggregator(
    name="abmil",
    feature_dim=2048,
    num_classes=3,
    device="cuda"
)

# Predict
probs, pred, attention = aggregator.predict(features, return_attention=True)
```

### 2. Add New Models (Super Easy!)

Add to `lib/extractors.py`:

```python
@EXTRACTORS.register("resnet101", feature_dim=2048, family="resnet")
def create_resnet101(pretrained: bool = True, device: Optional[str] = None):
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    return TimmExtractor("resnet101", pretrained=pretrained, device=device)
```

Add to `lib/aggregators.py`:

```python
@AGGREGATORS.register("my_aggregator", supports_attention=True)
def create_my_aggregator(feature_dim: int, num_classes: int = 2, device: str = "cuda", **kwargs):
    return MyAggregator(feature_dim=feature_dim, num_classes=num_classes, device=device)
```

That's it! Models are automatically registered, no need to modify other code.

### 3. List Available Models

```python
from lib import list_extractors, list_aggregators

print("Available extractors:", list_extractors())
# ['resnet50', 'vit_large']

print("Available aggregators:", list_aggregators())
# ['abmil', 'mean']
```

## Registered Models

### Feature Extractors
- `resnet50`: ResNet50 (feature_dim=2048)
- `vit_large`: ViT-Large/16 (feature_dim=1024)

### Aggregators
- `abmil`: Attention-based MIL (supports attention weights)
- `mean`: Simple mean pooling

## Using Configuration Files

```python
import json
from lib import create_extractor, create_aggregator

# Load configuration
with open("configs/default.json") as f:
    config = json.load(f)

# Create models
extractor = create_extractor(**config["feature_extractor"])
aggregator = create_aggregator(
    **config["aggregator"],
    feature_dim=extractor.get_feature_dim()
)
```

## Interface (Called by AI Service)

The `run_inference()` function in `run_inference.py` is the main entry point called by the AI service.

**Important:** Tiles must be provided in the `params` dict:

```python
from run_inference import run_inference

# Tiles should be extracted by WSI service
tiles = [...]  # List[PIL.Image] from WSI service

result = run_inference(
    wsi_path="/path/to/slide.svs",  # For reference only
    params={
        "tiles": tiles,              # Pre-extracted tiles (required)
        "feature_model": "resnet50",
        "aggregator": "abmil",
        "batch_size": 64,
        "device": "cuda",
        "checkpoint": None  # Optional
    },
    classes=["LUAD", "LUSC", "Normal"]
)

# Returns:
# {
#     "pred": "LUAD",
#     "probs": {"LUAD": 0.7, "LUSC": 0.2, "Normal": 0.1},
#     "num_tiles": 150
# }
```

**Note:** The WSI service is responsible for:
- Opening WSI files
- Extracting tiles at appropriate magnification
- Tissue detection and filtering
- Providing tiles as PIL.Image objects to the models