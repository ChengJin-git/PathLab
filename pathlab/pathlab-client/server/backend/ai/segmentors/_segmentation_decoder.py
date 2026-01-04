# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This software may be used and distributed in accordance with
# the terms of the DINOv3 License Agreement.

from enum import Enum
from functools import partial
import torch

from .tools.linear_head import LinearHead


class ModelWithIntermediateLayers(torch.nn.Module):
    def __init__(self, feature_model, n, reshape=False, return_class_token=True):
        super().__init__()
        self.feature_model = feature_model
        self.feature_model.eval()
        self.n = n  # Layer indices (Sequence) or n last layers (int) to take
        self.reshape = reshape
        self.return_class_token = return_class_token

    def forward(self, images):
        with torch.inference_mode():
            features = self.feature_model.forward_intermediates(
                images,
                indices=self.n,
                intermediates_only=True,
                return_prefix_tokens=True,
            )
        # features include patch tokens and cls token, split
        outputs = []
        cls_tokens = []
        
        for output_feat, prefix_tokens in features:
            outputs.append(output_feat)
            if self.return_class_token:
                cls_tokens.append(prefix_tokens[:, 0, :])  # B x C
        if self.return_class_token:
            return tuple(zip(outputs, cls_tokens))
        else:
            return tuple(outputs)

def _get_backbone_out_indices(
    model: torch.nn.Module,
    backbone_out_layers="FOUR_EVEN_INTERVALS",
):
    """
    Get indices for output layers of the ViT backbone. For now there are 3 options available:
    "LAST" : only extract the last layer, used in segmentation tasks with a bn head.
    "FOUR_EVEN_INTERVALS" : extract outputs every 1/4 of the total number of blocks
    Reference outputs in 'FOUR_EVEN_INTERVALS' mode :
    ViT/S (12 blocks): [2, 5, 8, 11]
    ViT/B (12 blocks): [2, 5, 8, 11]
    ViT/L (24 blocks): [5, 11, 17, 23] (classic), [4, 11, 17, 23] (used in the paper)
    ViT/g (40 blocks): [9, 19, 29, 39]
    """
    n_blocks = len(model.blocks)
    if backbone_out_layers == "LAST":
        out_indices = [n_blocks - 1]
    elif backbone_out_layers == "FOUR_LAST":
        out_indices = [i for i in range(n_blocks - 4, n_blocks)]
    elif backbone_out_layers == "FOUR_EVEN_INTERVALS":
        # Take indices that were used in the paper (for ViT/L only)
        if n_blocks == 24:
            out_indices = [4, 11, 17, 23]
        else:
            out_indices = [i * (n_blocks // 4) - 1 for i in range(1, 5)]
    assert all([out_index < n_blocks for out_index in out_indices])
    return out_indices


class FeatureDecoder(torch.nn.Module):
    def __init__(self, segmentation_model: torch.nn.ModuleList):
        super().__init__()
        self.segmentation_model = segmentation_model

    def forward(self, inputs):
        for module in self.segmentation_model:
            inputs = module.forward(inputs)
        return inputs

    def predict(self, inputs, rescale_to=(512, 512)):
        with torch.inference_mode():
            out = self.segmentation_model[0](inputs)  # backbone forward
            out = self.segmentation_model[1].predict(
                out, rescale_to=rescale_to
            )  # decoder head prediction
        return out


def build_segmentation_decoder(
    backbone_model,
    backbone_out_layers="FOUR_EVEN_INTERVALS",
    decoder_type="linear",
    num_classes=150,
):
    """
    Build segmentation model with a backbone and a decoder head.
    Args:
        backbone_model: Dinov3 backbone model, can be created with timm
        backbone_out_layers: which set of layers to take from the backbone, supported "FOUR_EVEN_INTERVALS", "FOUR_LAST", "LAST".
        decoder_type: type of decoder head to use, currently only "linear" is supported
        num_classes: number of output segmentation classes
    Returns:
        segmentation_model: FeatureDecoder model with backbone and decoder head
    """
    backbone_indices_to_use = _get_backbone_out_indices(
        backbone_model, backbone_out_layers
    )
    if decoder_type == "linear":
        backbone_model = ModelWithIntermediateLayers(
            backbone_model,
            n=backbone_indices_to_use,
            reshape=True,
            return_class_token=True,
        )
        # Important: we freeze the backbone
        backbone_model.requires_grad_(False)
        # embed_dim = backbone_model.feature_model.embed_dim
        embed_dim = backbone_model.feature_model.embed_dim
        if isinstance(embed_dim, int):
            if backbone_out_layers in ["FOUR_LAST", "FOUR_EVEN_INTERVALS"]:
                embed_dim = [embed_dim] * 4
            else:
                embed_dim = [embed_dim]
        decoder = LinearHead(
            in_channels=embed_dim,
            n_output_channels=num_classes,
        )
    else:
        raise ValueError(f'Unsupported decoder "{decoder_type}"')

    segmentation_model = FeatureDecoder(
        torch.nn.ModuleList(
            [
                backbone_model,
                decoder,
            ]
        ),
    )
    return segmentation_model
