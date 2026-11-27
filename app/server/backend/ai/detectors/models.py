"""Torchvision detection heads with interchangeable CNN / pathology FM backbones."""

from collections import OrderedDict
from contextlib import nullcontext

import torch
from torch import nn
from torch.nn import functional as F

from .specs import DetectionConfig, CNN_BACKBONES


class SpatialBackbone(nn.Module):
    """Adapt a fixed-input FM to a feature pyramid without disabling fine-tuning."""

    out_channels = 256

    def __init__(self, extractor, trainable: bool, *, first_stride=4):
        super().__init__()
        self.extractor = extractor
        self.trainable = trainable
        self.first_stride = first_stride
        self.extractor.requires_grad_(trainable)
        self.projection = nn.Conv2d(extractor.spatial_output_dim, self.out_channels, 1)

    def train(self, mode=True):
        super().train(mode)
        if not self.trainable:
            self.extractor.eval()
        return self

    def forward(self, images):
        height, width = images.shape[-2:]
        size = self.extractor.default_image_size
        images = F.interpolate(
            images, size=(size, size), mode="bilinear", align_corners=False
        )
        with nullcontext() if self.trainable else torch.no_grad():
            features = self.extractor.forward_spatial(images)
        features = self.projection(features)
        # Fixed feature sizes are ordered fine-to-coarse for ROIAlign / FCOS.
        return OrderedDict(
            (
                str(i),
                F.interpolate(
                    features,
                    size=(max(1, height // stride), max(1, width // stride)),
                    mode="bilinear",
                    align_corners=False,
                ),
            )
            for i, stride in enumerate(self.first_stride * 2**i for i in range(5))
        )


def build_detector(
    config: DetectionConfig, classes: list[str], *, initialize=True, hf_token=""
):
    from torchvision.models import get_model_weights
    from torchvision.models.detection import FasterRCNN, RetinaNet, FCOS
    from torchvision.models.detection.backbone_utils import resnet_fpn_backbone
    from torchvision.models.detection.anchor_utils import AnchorGenerator
    from torchvision.models.detection.transform import GeneralizedRCNNTransform
    from torchvision.ops import MultiScaleRoIAlign
    from torchvision.ops.feature_pyramid_network import LastLevelP6P7

    if not classes or len(set(classes)) != len(classes):
        raise ValueError("Detection requires unique, nonempty class names")
    mean, std = [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]
    if config.backbone in CNN_BACKBONES:
        weights = (
            get_model_weights(config.backbone).DEFAULT
            if initialize and config.pretrained
            else None
        )
        backbone = resnet_fpn_backbone(
            backbone_name=config.backbone,
            weights=weights,
            trainable_layers=5 if config.train_backbone else 0,
            **(
                {"returned_layers": [2, 3, 4], "extra_blocks": LastLevelP6P7(256, 256)}
                if config.architecture != "fasterrcnn"
                else {}
            ),
        )
    else:
        from backend.ai.extractors.registry import get_extractor

        extractor = get_extractor(
            config.backbone, pretrained=initialize, hf_token=hf_token
        )
        if not extractor.supports_spatial:
            raise ValueError("Detection foundation models must expose spatial features")
        mean, std = list(extractor.normalization_mean), list(
            extractor.normalization_std
        )
        backbone = SpatialBackbone(
            extractor,
            config.train_backbone,
            first_stride=4 if config.architecture == "fasterrcnn" else 8,
        )

    common = dict(backbone=backbone, num_classes=len(classes) + 1)
    sizes = ((16,), (32,), (64,), (128,), (256,))
    ratios = ((0.5, 1.0, 2.0),) * 5
    if config.architecture == "fasterrcnn":
        model = FasterRCNN(
            **common,
            rpn_anchor_generator=AnchorGenerator(sizes, ratios),
            box_roi_pool=MultiScaleRoIAlign(
                ["0", "1", "2", "3"], output_size=7, sampling_ratio=2
            ),
            box_score_thresh=0.001,
            box_detections_per_img=config.max_detections,
        )
    elif config.architecture == "retinanet":
        model = RetinaNet(
            **common,
            anchor_generator=AnchorGenerator(sizes, ratios),
            score_thresh=0.001,
            detections_per_img=config.max_detections,
        )
    else:
        model = FCOS(
            **common,
            anchor_generator=AnchorGenerator(
                ((8,), (16,), (32,), (64,), (128,)), ((1.0,),) * 5
            ),
            score_thresh=0.001,
            detections_per_img=config.max_detections,
        )
    # One square resize shared by training/inference; torchvision scales targets and
    # restores predictions to original image coordinates, including rectangular patches.
    model.transform = GeneralizedRCNNTransform(
        config.image_size,
        config.image_size,
        mean,
        std,
        fixed_size=(config.image_size, config.image_size),
        size_divisible=32,
    )
    return model


def load_detector(path, device):
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    config = DetectionConfig.model_validate(checkpoint["config"])
    classes = checkpoint["classes"]
    model = build_detector(config, classes, initialize=False)
    model.load_state_dict(checkpoint["model_state_dict"], strict=True)
    return model.to(device).eval(), classes
