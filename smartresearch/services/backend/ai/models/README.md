# WSI Classification Models

This directory contains the WSI classification inference implementation.

## Directory Structure

```
models/
├── README.md                 # This file
├── requirements.txt          # Dependencies
├── run_inference.py          # Inference entry point (called by AI service)
├── lib/                      # Core library (NEW: Modular architecture)
│   ├── __init__.py          # Unified exports
│   ├── registry.py          # Model registration system
│   ├── base/                # Base classes
│   │   ├── extractor.py    # BaseExtractor abstract class
│   │   └── aggregator.py   # BaseAggregator abstract class
│   ├── extractors/          # Feature extractors (each model in its own file)
│   │   ├── __init__.py     # Auto-discovery
│   │   ├── resnet.py       # ResNet family
│   │   └── vit.py          # ViT family
│   └── aggregators/         # Aggregators (each model in its own file)
│       ├── __init__.py     # Auto-discovery
│       ├── abmil.py        # ABMIL
│       └── mean.py         # Mean pooling
└── checkpoints/             # Model weights (not committed to git)
    ├── README.md
    └── .gitkeep
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

### 2. Add New Models

**NEW: Modular Architecture** - Each model is in its own file!

**Add a new feature extractor** - Create `lib/extractors/ctranspath.py`:

```python
"""CTransPath - Pathology-specific feature extractor"""
import torch
from ..registry import EXTRACTORS
from ..base import BaseExtractor

class CTransPath(BaseExtractor):
    def __init__(self, pretrained=True, device="cuda"):
        super().__init__(device)
        # Your model implementation
        ...

    def forward(self, x):
        return self.model(x)

    def get_feature_dim(self):
        return 768

    def get_transforms(self):
        # Return preprocessing transforms
        ...

@EXTRACTORS.register("ctranspath", feature_dim=768, family="pathology")
def create_ctranspath(pretrained=True, device=None):
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    return CTransPath(pretrained, device)
```

**Add a new aggregator** - Create `lib/aggregators/transmil.py`:

```python
"""TransMIL - Transformer-based MIL"""
import torch
from ..registry import AGGREGATORS
from ..base import BaseAggregator

class TransMIL(BaseAggregator):
    def __init__(self, feature_dim, num_classes=2, device="cuda"):
        super().__init__(feature_dim, num_classes, device)
        # Your model implementation
        ...

    def forward(self, features):
        # Return (logits, attention)
        ...

@AGGREGATORS.register("transmil", supports_attention=True)
def create_transmil(feature_dim, num_classes=2, device="cuda", **kwargs):
    return TransMIL(feature_dim, num_classes, device)
```

That's it! New models are **automatically discovered and registered**. No need to modify any other files!

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
- `resnet101`: ResNet101 (feature_dim=2048)
- `resnet152`: ResNet152 (feature_dim=2048)
- `vit_base`: ViT-Base/16 (feature_dim=768)
- `vit_large`: ViT-Large/16 (feature_dim=1024)

### Aggregators
- `abmil`: Attention-based MIL (supports attention weights)
- `mean`: Simple mean pooling

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