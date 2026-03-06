# Copyright (c) 2025 PathLab
# PathLab API client for fetching datasets and models information

import os
import httpx
from typing import Optional
from src.config import PATHLAB_API_URL

import logging

logger = logging.getLogger(__name__)

# Cache for API responses (simple in-memory cache)
_cache = {
    "datasets": None,
    "models": None,
    "feature_extractors": None,
    "aggregators": None,
}


def get_pathlab_api_url() -> str:
    """Get PathLab API base URL from environment or config."""
    return os.getenv("PATHLAB_API_URL", PATHLAB_API_URL or "http://localhost:8765")


async def fetch_datasets(token: Optional[str] = None) -> list[dict]:
    """
    Fetch available datasets from PathLab API.
    
    Returns:
        List of dataset info: [{"name": "...", "file_count": ..., "task_type": ...}, ...]
    """
    try:
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{get_pathlab_api_url()}/wsi/datasets",
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                datasets = data.get("items", [])
                # Format for prompt display
                return [
                    {
                        "name": ds.get("dataset_name", "Unknown"),
                        "file_count": ds.get("file_count", 0),
                        "task_type": ds.get("dataset_type", "classification"),
                        "data_level": ds.get("data_level", "file"),
                    }
                    for ds in datasets
                ]
            else:
                logger.warning(f"Failed to fetch datasets: {response.status_code}")
                return []
    except Exception as e:
        logger.error(f"Error fetching datasets from PathLab: {e}")
        return []


async def fetch_trained_models(token: Optional[str] = None) -> list[dict]:
    """
    Fetch trained models from PathLab API.
    
    Returns:
        List of model info: [{"name": "...", "task_type": ..., "extractor": ..., "aggregator": ...}, ...]
    """
    try:
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{get_pathlab_api_url()}/models",
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                models = data.get("items", [])
                return [
                    {
                        "name": m.get("model_name", "Unknown"),
                        "task_type": m.get("task_type", "classification"),
                        "extractor": m.get("extractor", "Unknown"),
                        "aggregator": m.get("aggregator", "Unknown"),
                        "is_default": m.get("is_default", False),
                    }
                    for m in models
                ]
            else:
                logger.warning(f"Failed to fetch models: {response.status_code}")
                return []
    except Exception as e:
        logger.error(f"Error fetching models from PathLab: {e}")
        return []


def get_supported_feature_extractors() -> list[dict]:
    """
    Get list of supported feature extractors in PathLab.
    This is static information based on PathLab's capabilities.
    
    Returns:
        List of extractor info with name, source, and description
    """
    return [
        {"name": "UNI", "source": "Mahmood Lab", "description": "General pathology foundation model"},
        {"name": "UNI2", "source": "Mahmood Lab", "description": "Improved UNI with larger training data"},
        {"name": "CONCH", "source": "Mahmood Lab", "description": "Contrastive learning on histopathology"},
        {"name": "Virchow", "source": "Paige AI", "description": "Large-scale pathology foundation model"},
        {"name": "Virchow2", "source": "Paige AI", "description": "Enhanced Virchow model"},
        {"name": "H-Optimus", "source": "Bioptimus", "description": "Optimized for H&E images"},
        {"name": "Phikon", "source": "Owkin", "description": "Self-supervised pathology model"},
        {"name": "PLIP", "source": "Stanford", "description": "Pathology Language-Image Pre-training"},
        {"name": "GigaPath", "source": "Microsoft", "description": "Billion-scale pathology model"},
        {"name": "Prov-GigaPath", "source": "Microsoft/Providence", "description": "Clinical-scale GigaPath"},
        {"name": "CHIEF", "source": "Harvard", "description": "Clinical histopathology foundation model"},
        {"name": "CTransPath", "source": "Tencent AI Lab", "description": "Contrastive learning transformer"},
        {"name": "ResNet50", "source": "ImageNet", "description": "Classic ResNet pretrained on ImageNet"},
        {"name": "ViT-B/16", "source": "Google", "description": "Vision Transformer base model"},
        {"name": "DINOv2", "source": "Meta AI", "description": "Self-supervised vision transformer"},
        {"name": "Lunit-DINO", "source": "Lunit", "description": "Pathology-specific DINO"},
        {"name": "Kaiko", "source": "Kaiko.ai", "description": "Medical imaging foundation model"},
    ]


def get_supported_mil_aggregators() -> list[dict]:
    """
    Get list of supported MIL aggregators in PathLab.
    
    Returns:
        List of aggregator info with name and description
    """
    return [
        {"name": "ABMIL", "description": "Attention-Based Multiple Instance Learning"},
        {"name": "CLAM", "description": "Clustering-constrained Attention MIL (SB/MB variants)"},
        {"name": "TransMIL", "description": "Transformer-based MIL with positional encoding"},
        {"name": "DSMIL", "description": "Dual-stream MIL with instance and bag classifiers"},
        {"name": "DTFD-MIL", "description": "Double-Tier Feature Distillation MIL"},
        {"name": "MHIM-MIL", "description": "Multi-Head Instance-level MIL"},
        {"name": "MeanPool", "description": "Simple mean pooling baseline"},
        {"name": "MaxPool", "description": "Simple max pooling baseline"},
    ]


def format_datasets_for_prompt(datasets: list[dict]) -> str:
    """Format datasets list for prompt display."""
    if not datasets:
        return "No datasets available. User needs to upload WSI files first."
    
    lines = []
    for ds in datasets[:10]:  # Limit to 10 for prompt size
        task = ds.get("task_type", "classification")
        count = ds.get("file_count", 0)
        lines.append(f"  - {ds['name']}: {count} files ({task})")
    
    if len(datasets) > 10:
        lines.append(f"  - ... and {len(datasets) - 10} more datasets")
    
    return "\n".join(lines)


def format_models_for_prompt(models: list[dict]) -> str:
    """Format models list for prompt display."""
    if not models:
        return "No trained models yet. User needs to train models first."
    
    lines = []
    for m in models[:10]:
        default_mark = " (default)" if m.get("is_default") else ""
        lines.append(f"  - {m['name']}: {m.get('extractor', '?')} + {m.get('aggregator', '?')}{default_mark}")
    
    if len(models) > 10:
        lines.append(f"  - ... and {len(models) - 10} more models")
    
    return "\n".join(lines)


def format_extractors_for_prompt() -> str:
    """Format feature extractors list for prompt display."""
    extractors = get_supported_feature_extractors()
    lines = []
    for e in extractors:
        lines.append(f"  - {e['name']} ({e['source']}): {e['description']}")
    return "\n".join(lines)


def format_aggregators_for_prompt() -> str:
    """Format MIL aggregators list for prompt display."""
    aggregators = get_supported_mil_aggregators()
    lines = []
    for a in aggregators:
        lines.append(f"  - {a['name']}: {a['description']}")
    return "\n".join(lines)


# Synchronous versions for template rendering (uses cached data)
def get_datasets_for_prompt() -> str:
    """Get formatted datasets string for prompt (uses cache)."""
    if _cache["datasets"] is not None:
        return format_datasets_for_prompt(_cache["datasets"])
    return "Datasets: Loading... (please refresh)"


def get_models_for_prompt() -> str:
    """Get formatted models string for prompt (uses cache)."""
    if _cache["models"] is not None:
        return format_models_for_prompt(_cache["models"])
    return "Models: Loading... (please refresh)"


def get_extractors_for_prompt() -> str:
    """Get formatted extractors string for prompt."""
    return format_extractors_for_prompt()


def get_aggregators_for_prompt() -> str:
    """Get formatted aggregators string for prompt."""
    return format_aggregators_for_prompt()


def get_extractor_count() -> int:
    """Get the number of supported feature extractors."""
    return len(get_supported_feature_extractors())


def get_aggregator_count() -> int:
    """Get the number of supported MIL aggregators."""
    return len(get_supported_mil_aggregators())


async def refresh_pathlab_cache(token: Optional[str] = None):
    """Refresh the PathLab data cache."""
    _cache["datasets"] = await fetch_datasets(token)
    _cache["models"] = await fetch_trained_models(token)
    _cache["feature_extractors"] = get_supported_feature_extractors()
    _cache["aggregators"] = get_supported_mil_aggregators()
    logger.info(f"PathLab cache refreshed: {len(_cache['datasets'])} datasets, {len(_cache['models'])} models")
