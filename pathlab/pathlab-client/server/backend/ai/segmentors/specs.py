"""Lightweight segmentation capability definitions shared across layers."""

from __future__ import annotations

from typing import Optional

from backend.ai.extractors.registry import extractor_supports_spatial, list_extractors


SUPPORT_ARCHITECTURES = [
    'unet', 'unetplusplus', 'manet', 'linknet', 'fpn', 'pspnet',
    'deeplabv3', 'deeplabv3plus', 'pan', 'upernet', 'segformer', 'dpt'
]

SUPPORT_FEATURE_EXTRACTORS = [
    'resnet18', 'resnet34', 'resnet50', 'resnet101', 'resnet152',
    'resnext50_32x4d', 'resnext101_32x4d', 'resnext101_32x8d',
    'resnext101_32x16d', 'resnext101_32x32d', 'resnext101_32x48d', 'dpn68',
    'dpn68b', 'dpn92', 'dpn98', 'dpn107', 'dpn131', 'vgg11', 'vgg11_bn',
    'vgg13', 'vgg13_bn', 'vgg16', 'vgg16_bn', 'vgg19', 'vgg19_bn', 'senet154',
    'se_resnet50', 'se_resnet101', 'se_resnet152', 'se_resnext50_32x4d',
    'se_resnext101_32x4d', 'densenet121', 'densenet169', 'densenet201',
    'densenet161', 'inceptionresnetv2', 'inceptionv4', 'efficientnet-b0',
    'efficientnet-b1', 'efficientnet-b2', 'efficientnet-b3', 'efficientnet-b4',
    'efficientnet-b5', 'efficientnet-b6', 'efficientnet-b7', 'mobilenet_v2',
    'xception', 'timm-efficientnet-b0', 'timm-efficientnet-b1',
    'timm-efficientnet-b2', 'timm-efficientnet-b3', 'timm-efficientnet-b4',
    'timm-efficientnet-b5', 'timm-efficientnet-b6', 'timm-efficientnet-b7',
    'timm-efficientnet-b8', 'timm-efficientnet-l2', 'timm-tf_efficientnet_lite0',
    'timm-tf_efficientnet_lite1', 'timm-tf_efficientnet_lite2',
    'timm-tf_efficientnet_lite3', 'timm-tf_efficientnet_lite4',
    'timm-skresnet18', 'timm-skresnet34', 'timm-skresnext50_32x4d', 'mit_b0',
    'mit_b1', 'mit_b2', 'mit_b3', 'mit_b4', 'mit_b5', 'mobileone_s0',
    'mobileone_s1', 'mobileone_s2', 'mobileone_s3', 'mobileone_s4'
]


def is_standard_segmentation_backbone(encoder_name: Optional[str]) -> bool:
    return bool(encoder_name) and encoder_name in SUPPORT_FEATURE_EXTRACTORS


def is_fm_segmentation_backbone(encoder_name: Optional[str]) -> bool:
    if not encoder_name:
        return False
    return (
        encoder_name in list_extractors()
        and not is_standard_segmentation_backbone(encoder_name)
        and extractor_supports_spatial(encoder_name)
    )
