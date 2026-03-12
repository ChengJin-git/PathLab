from __future__ import annotations

from typing import Any, Optional

from backend.ai.extractors import get_extractor
from backend.ai.extractors.registry import extractor_supports_spatial
from backend.ai.segmentors.specs import is_fm_segmentation_backbone

DEFAULT_NON_FM_PATCH_RESIZE = 512
DEFAULT_FM_PATCH_RESIZE_FALLBACK = 224


def resolve_patch_resize_size(
    model_name: Optional[str],
    *,
    hf_token: Optional[str] = None,
    is_segmentation_backbone: bool = False,
) -> int:
    """Resolve target patch resize size.

    Rules:
    - FM / spatial extractor: use extractor.default_image_size
    - non-FM patch model: use DEFAULT_NON_FM_PATCH_RESIZE (512)
    - segmentation backbones use FM-segmentation capability checks
    """
    if not model_name:
        return DEFAULT_NON_FM_PATCH_RESIZE

    is_fm = (
        is_fm_segmentation_backbone(model_name)
        if is_segmentation_backbone
        else extractor_supports_spatial(model_name)
    )
    if not is_fm:
        return DEFAULT_NON_FM_PATCH_RESIZE

    kwargs: dict[str, Any] = {"pretrained": True}
    if hf_token:
        kwargs["hf_token"] = hf_token

    try:
        extractor = get_extractor(model_name, **kwargs)
        image_size = int(getattr(extractor, "default_image_size", DEFAULT_FM_PATCH_RESIZE_FALLBACK) or DEFAULT_FM_PATCH_RESIZE_FALLBACK)
        return image_size if image_size > 0 else DEFAULT_FM_PATCH_RESIZE_FALLBACK
    except Exception:
        return DEFAULT_FM_PATCH_RESIZE_FALLBACK


def build_patch_classification_transform(
    extractor: Any,
    target_size: int,
    *,
    mode: str = "eval",
):
    import torchvision.transforms as T

    mean = list(getattr(extractor, "normalization_mean", (0.485, 0.456, 0.406)))
    std = list(getattr(extractor, "normalization_std", (0.229, 0.224, 0.225)))

    transforms = []
    if mode == "train":
        transforms.extend([
            T.RandomHorizontalFlip(p=0.5),
            T.RandomVerticalFlip(p=0.5),
            T.RandomApply([T.RandomRotation(degrees=90)], p=0.5),
            T.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2, hue=0.1),
        ])

    transforms.extend([
        T.Resize((target_size, target_size)),
        T.ToTensor(),
        T.Normalize(mean=mean, std=std),
    ])
    return T.Compose(transforms)

