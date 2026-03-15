from __future__ import annotations

from typing import TypeAlias

from fastapi import APIRouter, Depends

from ...backend.auth import current_active_user
from ...backend.ai.extractors.registry import get_available_extractors
from ...backend.ai.aggregators.registry import list_aggregators
from ...backend.ai.segmentors.specs import (
    SUPPORT_ARCHITECTURES,
    SUPPORT_FEATURE_EXTRACTORS,
)

router = APIRouter(prefix="/training", tags=["Training Options"])


OptionMap: TypeAlias = dict[str, str]


_AGGREGATOR_METADATA: dict[str, OptionMap] = {
    "abmil": {
        "name": "ABMIL",
        "description": "Attention-based MIL (recommended)",
        "detail": "Learns importance weights for each patch",
    },
    "meanmil": {
        "name": "MeanMIL",
        "description": "Simple average pooling",
        "detail": "Average of all patch features",
    },
    "maxmil": {
        "name": "MaxMIL",
        "description": "Maximum activation pooling",
        "detail": "Takes maximum across patches",
    },
    "clam_sb": {
        "name": "CLAM-SB",
        "description": "Single Branch CLAM",
        "detail": "Single-branch Instance-level clustering with attention",
    },
    "clam_mb": {
        "name": "Multi Branch CLAM",
        "description": "Multi-branch Instance-level clustering with attention",
        "detail": "Multi-branch Instance-level clustering with attention",
    },
    "dsmil": {
        "name": "DSMIL",
        "description": "Dual-stream MIL",
        "detail": "Combines instance and bag-level features",
    },
    "dtfdmil": {
        "name": "DTFD-MIL",
        "description": "Double-Tier Feature Distillation",
        "detail": "Two-tier pseudo-bag distillation",
    },
    "transmil": {
        "name": "TransMIL",
        "description": "Transformer-based MIL",
        "detail": "Correlation modeling with Transformer",
    },
}

_SEGMENTATION_ARCH_METADATA: dict[str, OptionMap] = {
    "unet": {
        "name": "U-Net",
        "description": "Classic encoder-decoder with skip connections",
    },
    "unetplusplus": {
        "name": "UNet++",
        "description": "Nested U-Net with dense skip connections",
    },
    "manet": {"name": "MANet", "description": "Multi-scale Attention Network"},
    "linknet": {
        "name": "LinkNet",
        "description": "Lightweight encoder-decoder with residual connections",
    },
    "fpn": {
        "name": "FPN",
        "description": "Feature Pyramid Network for multi-scale features",
    },
    "pspnet": {"name": "PSPNet", "description": "Pyramid Scene Parsing Network"},
    "deeplabv3": {"name": "DeepLabV3", "description": "Atrous Spatial Pyramid Pooling"},
    "deeplabv3plus": {
        "name": "DeepLabV3+",
        "description": "DeepLabV3 with decoder module",
    },
    "pan": {"name": "PAN", "description": "Pyramid Attention Network"},
    "upernet": {"name": "UPerNet", "description": "Unified Perceptual Parsing Network"},
    "segformer": {"name": "SegFormer", "description": "Transformer-based segmentation"},
    "dpt": {"name": "DPT", "description": "Dense Prediction Transformer"},
}

_SEGMENTATION_BACKBONE_METADATA: dict[str, OptionMap] = {
    "resnet18": {
        "name": "ResNet-18",
        "description": "11M params, lightweight baseline",
        "group": "ResNet",
    },
    "resnet34": {
        "name": "ResNet-34",
        "description": "21M params, good speed/accuracy balance",
        "group": "ResNet",
    },
    "resnet50": {
        "name": "ResNet-50",
        "description": "23M params, standard baseline (recommended)",
        "group": "ResNet",
    },
    "resnet101": {
        "name": "ResNet-101",
        "description": "42M params, higher capacity",
        "group": "ResNet",
    },
    "resnet152": {
        "name": "ResNet-152",
        "description": "58M params, deep model",
        "group": "ResNet",
    },
    "resnext50_32x4d": {
        "name": "ResNeXt-50",
        "description": "22M params, grouped convolutions",
        "group": "ResNeXt",
    },
    "resnext101_32x4d": {
        "name": "ResNeXt-101 (32×4d)",
        "description": "42M params",
        "group": "ResNeXt",
    },
    "resnext101_32x8d": {
        "name": "ResNeXt-101 (32×8d)",
        "description": "86M params, high capacity",
        "group": "ResNeXt",
    },
    "resnext101_32x16d": {
        "name": "ResNeXt-101 (32×16d)",
        "description": "191M params",
        "group": "ResNeXt",
    },
    "resnext101_32x32d": {
        "name": "ResNeXt-101 (32×32d)",
        "description": "466M params",
        "group": "ResNeXt",
    },
    "resnext101_32x48d": {
        "name": "ResNeXt-101 (32×48d)",
        "description": "826M params",
        "group": "ResNeXt",
    },
    "dpn68": {
        "name": "DPN-68",
        "description": "11M params, dual path network",
        "group": "DPN",
    },
    "dpn68b": {
        "name": "DPN-68b",
        "description": "11M params, ImageNet+5k pretrained",
        "group": "DPN",
    },
    "dpn92": {"name": "DPN-92", "description": "34M params", "group": "DPN"},
    "dpn98": {"name": "DPN-98", "description": "58M params", "group": "DPN"},
    "dpn107": {"name": "DPN-107", "description": "84M params", "group": "DPN"},
    "dpn131": {"name": "DPN-131", "description": "76M params", "group": "DPN"},
    "vgg11": {"name": "VGG-11", "description": "9M params", "group": "VGG"},
    "vgg11_bn": {
        "name": "VGG-11 BN",
        "description": "9M params, with batch norm",
        "group": "VGG",
    },
    "vgg13": {"name": "VGG-13", "description": "9M params", "group": "VGG"},
    "vgg13_bn": {
        "name": "VGG-13 BN",
        "description": "9M params, with batch norm",
        "group": "VGG",
    },
    "vgg16": {"name": "VGG-16", "description": "14M params", "group": "VGG"},
    "vgg16_bn": {
        "name": "VGG-16 BN",
        "description": "14M params, with batch norm",
        "group": "VGG",
    },
    "vgg19": {"name": "VGG-19", "description": "20M params", "group": "VGG"},
    "vgg19_bn": {
        "name": "VGG-19 BN",
        "description": "20M params, with batch norm",
        "group": "VGG",
    },
    "senet154": {
        "name": "SENet-154",
        "description": "113M params, squeeze-and-excitation",
        "group": "SE-Net",
    },
    "se_resnet50": {
        "name": "SE-ResNet-50",
        "description": "26M params, channel attention",
        "group": "SE-Net",
    },
    "se_resnet101": {
        "name": "SE-ResNet-101",
        "description": "47M params",
        "group": "SE-Net",
    },
    "se_resnet152": {
        "name": "SE-ResNet-152",
        "description": "64M params",
        "group": "SE-Net",
    },
    "se_resnext50_32x4d": {
        "name": "SE-ResNeXt-50",
        "description": "25M params",
        "group": "SE-Net",
    },
    "se_resnext101_32x4d": {
        "name": "SE-ResNeXt-101",
        "description": "46M params",
        "group": "SE-Net",
    },
    "densenet121": {
        "name": "DenseNet-121",
        "description": "6M params, dense connections",
        "group": "DenseNet",
    },
    "densenet169": {
        "name": "DenseNet-169",
        "description": "12M params",
        "group": "DenseNet",
    },
    "densenet201": {
        "name": "DenseNet-201",
        "description": "18M params",
        "group": "DenseNet",
    },
    "densenet161": {
        "name": "DenseNet-161",
        "description": "26M params",
        "group": "DenseNet",
    },
    "inceptionresnetv2": {
        "name": "Inception-ResNet-V2",
        "description": "54M params",
        "group": "Inception",
    },
    "inceptionv4": {
        "name": "Inception-V4",
        "description": "41M params",
        "group": "Inception",
    },
    "efficientnet-b0": {
        "name": "EfficientNet-B0",
        "description": "4M params, lightweight",
        "group": "EfficientNet",
    },
    "efficientnet-b1": {
        "name": "EfficientNet-B1",
        "description": "6M params",
        "group": "EfficientNet",
    },
    "efficientnet-b2": {
        "name": "EfficientNet-B2",
        "description": "7M params",
        "group": "EfficientNet",
    },
    "efficientnet-b3": {
        "name": "EfficientNet-B3",
        "description": "10M params, good tradeoff",
        "group": "EfficientNet",
    },
    "efficientnet-b4": {
        "name": "EfficientNet-B4",
        "description": "17M params",
        "group": "EfficientNet",
    },
    "efficientnet-b5": {
        "name": "EfficientNet-B5",
        "description": "28M params, high accuracy",
        "group": "EfficientNet",
    },
    "efficientnet-b6": {
        "name": "EfficientNet-B6",
        "description": "40M params",
        "group": "EfficientNet",
    },
    "efficientnet-b7": {
        "name": "EfficientNet-B7",
        "description": "63M params",
        "group": "EfficientNet",
    },
    "mobilenet_v2": {
        "name": "MobileNet-V2",
        "description": "2M params, mobile-optimized",
        "group": "MobileNet",
    },
    "xception": {
        "name": "Xception",
        "description": "20M params, depthwise separable convs",
        "group": "Xception",
    },
    "timm-efficientnet-b0": {
        "name": "timm EfficientNet-B0",
        "description": "4M params, noisy-student available",
        "group": "timm-EfficientNet",
    },
    "timm-efficientnet-b1": {
        "name": "timm EfficientNet-B1",
        "description": "6M params",
        "group": "timm-EfficientNet",
    },
    "timm-efficientnet-b2": {
        "name": "timm EfficientNet-B2",
        "description": "7M params",
        "group": "timm-EfficientNet",
    },
    "timm-efficientnet-b3": {
        "name": "timm EfficientNet-B3",
        "description": "10M params",
        "group": "timm-EfficientNet",
    },
    "timm-efficientnet-b4": {
        "name": "timm EfficientNet-B4",
        "description": "17M params",
        "group": "timm-EfficientNet",
    },
    "timm-efficientnet-b5": {
        "name": "timm EfficientNet-B5",
        "description": "28M params",
        "group": "timm-EfficientNet",
    },
    "timm-efficientnet-b6": {
        "name": "timm EfficientNet-B6",
        "description": "40M params",
        "group": "timm-EfficientNet",
    },
    "timm-efficientnet-b7": {
        "name": "timm EfficientNet-B7",
        "description": "63M params",
        "group": "timm-EfficientNet",
    },
    "timm-efficientnet-b8": {
        "name": "timm EfficientNet-B8",
        "description": "84M params",
        "group": "timm-EfficientNet",
    },
    "timm-efficientnet-l2": {
        "name": "timm EfficientNet-L2",
        "description": "474M params, largest",
        "group": "timm-EfficientNet",
    },
    "timm-tf_efficientnet_lite0": {
        "name": "timm EfficientNet-Lite0",
        "description": "3M params",
        "group": "timm-EfficientNet",
    },
    "timm-tf_efficientnet_lite1": {
        "name": "timm EfficientNet-Lite1",
        "description": "4M params",
        "group": "timm-EfficientNet",
    },
    "timm-tf_efficientnet_lite2": {
        "name": "timm EfficientNet-Lite2",
        "description": "4M params",
        "group": "timm-EfficientNet",
    },
    "timm-tf_efficientnet_lite3": {
        "name": "timm EfficientNet-Lite3",
        "description": "6M params",
        "group": "timm-EfficientNet",
    },
    "timm-tf_efficientnet_lite4": {
        "name": "timm EfficientNet-Lite4",
        "description": "11M params",
        "group": "timm-EfficientNet",
    },
    "timm-skresnet18": {
        "name": "timm SK-ResNet-18",
        "description": "11M params, selective kernel",
        "group": "timm-SKNet",
    },
    "timm-skresnet34": {
        "name": "timm SK-ResNet-34",
        "description": "21M params",
        "group": "timm-SKNet",
    },
    "timm-skresnext50_32x4d": {
        "name": "timm SK-ResNeXt-50",
        "description": "23M params",
        "group": "timm-SKNet",
    },
    "mit_b0": {
        "name": "MiT-B0",
        "description": "3M params, SegFormer backbone, lightweight",
        "group": "MiT",
    },
    "mit_b1": {"name": "MiT-B1", "description": "13M params", "group": "MiT"},
    "mit_b2": {"name": "MiT-B2", "description": "24M params, balanced", "group": "MiT"},
    "mit_b3": {"name": "MiT-B3", "description": "44M params", "group": "MiT"},
    "mit_b4": {
        "name": "MiT-B4",
        "description": "60M params, high capacity",
        "group": "MiT",
    },
    "mit_b5": {
        "name": "MiT-B5",
        "description": "81M params, largest MiT",
        "group": "MiT",
    },
    "mobileone_s0": {
        "name": "MobileOne-S0",
        "description": "4M params, ultra-fast inference",
        "group": "MobileOne",
    },
    "mobileone_s1": {
        "name": "MobileOne-S1",
        "description": "3M params",
        "group": "MobileOne",
    },
    "mobileone_s2": {
        "name": "MobileOne-S2",
        "description": "5M params",
        "group": "MobileOne",
    },
    "mobileone_s3": {
        "name": "MobileOne-S3",
        "description": "8M params",
        "group": "MobileOne",
    },
    "mobileone_s4": {
        "name": "MobileOne-S4",
        "description": "12M params",
        "group": "MobileOne",
    },
}

_SEGMENTATION_LOSSES: list[OptionMap] = [
    {
        "id": "DiceLoss",
        "name": "Dice Loss",
        "description": "Overlap-based, handles class imbalance well",
    },
    {
        "id": "JaccardLoss",
        "name": "Jaccard Loss (IoU)",
        "description": "IoU-based loss, similar to Dice",
    },
    {
        "id": "TverskyLoss",
        "name": "Tversky Loss",
        "description": "Generalized Dice with adjustable FP/FN weights",
    },
    {
        "id": "FocalLoss",
        "name": "Focal Loss",
        "description": "Down-weights easy examples, focuses on hard cases",
    },
    {
        "id": "LovaszLoss",
        "name": "Lovász Loss",
        "description": "Submodular IoU surrogate, good for imbalanced data",
    },
    {
        "id": "BCE",
        "name": "Binary Cross Entropy",
        "description": "Standard per-pixel binary classification loss",
    },
    {
        "id": "MCCLoss",
        "name": "MCC Loss",
        "description": "Matthews Correlation Coefficient loss",
    },
]

_OPTIMIZERS: list[OptionMap] = [
    {"value": "adam", "label": "Adam"},
    {"value": "sgd", "label": "SGD"},
    {"value": "adamw", "label": "AdamW"},
]


@router.get("/options", dependencies=[Depends(current_active_user)])
async def get_training_options():
    feature_extractors = get_available_extractors()

    aggregators: list[dict[str, str]] = []
    for agg_id in list_aggregators():
        meta = _AGGREGATOR_METADATA.get(
            agg_id,
            {
                "name": agg_id,
                "description": f"MIL aggregator: {agg_id}",
                "detail": "",
            },
        )
        aggregators.append({"id": agg_id, **meta})

    segmentation_architectures: list[dict[str, str]] = []
    for arch_id in SUPPORT_ARCHITECTURES:
        meta = _SEGMENTATION_ARCH_METADATA.get(
            arch_id,
            {"name": arch_id, "description": f"Segmentation architecture: {arch_id}"},
        )
        segmentation_architectures.append({"id": arch_id, **meta})

    segmentation_backbones: list[dict[str, str]] = []
    for backbone_id in SUPPORT_FEATURE_EXTRACTORS:
        meta = _SEGMENTATION_BACKBONE_METADATA.get(
            backbone_id,
            {
                "name": backbone_id,
                "description": f"Segmentation backbone: {backbone_id}",
                "group": "Other",
            },
        )
        segmentation_backbones.append({"id": backbone_id, **meta})

    return {
        "feature_extractors": feature_extractors,
        "aggregators": aggregators,
        "segmentation_architectures": segmentation_architectures,
        "segmentation_backbones": segmentation_backbones,
        "segmentation_losses": _SEGMENTATION_LOSSES,
        "optimizers": _OPTIMIZERS,
    }
