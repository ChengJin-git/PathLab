from typing import Any
import segmentation_models_pytorch as smp
import torch
from backend.ai.segmentors.loss import get_loss, CombinedLoss
from backend.ai.extractors.registry import get_extractor
from backend.ai.segmentors.specs import (
    SUPPORT_ARCHITECTURES,
    SUPPORT_FEATURE_EXTRACTORS,
    is_fm_segmentation_backbone,
)


SUPPORT_ARCHTECTURES = SUPPORT_ARCHITECTURES


def is_fm_encoder(encoder_name: str) -> bool:
    """Check whether *encoder_name* refers to a Foundation Model extractor
    that supports spatial feature extraction (i.e. FM-powered segmentation).

    Returns False for traditional CNN encoders (resnet, efficientnet, …) and
    for FM extractors that do not support ``forward_spatial``
    (e.g. resnet50, vit_l_16 in the extractor registry).
    """
    return is_fm_segmentation_backbone(encoder_name)


class Segmentor:
    def __init__(
        self,
        architecture: str,
        encoder_name: str,
        in_channels: int = 3,
        classes: int = 1,
        decoder_type: str = "conv",
        decoder_kwargs: dict | None = None,
        **kwargs,
    ):
        self.is_fm = is_fm_encoder(encoder_name)

        if not self.is_fm:
            # Traditional SMP path
            if architecture not in SUPPORT_ARCHTECTURES:
                raise ValueError(
                    f"Unsupported architecture '{architecture}'. Supported architectures are: {SUPPORT_ARCHTECTURES}"
                )
            if encoder_name not in SUPPORT_FEATURE_EXTRACTORS:
                raise ValueError(
                    f"Unsupported encoder '{encoder_name}'. Supported encoders are: {SUPPORT_FEATURE_EXTRACTORS}"
                )

        self.architecture = architecture
        self.encoder_name = encoder_name
        self.in_channels = in_channels
        self.classes = classes
        self.decoder_type = decoder_type
        self.decoder_kwargs = decoder_kwargs or {}
        self.kwargs = kwargs
        self._fm_extractor = None

    def build_model(self):
        if self.is_fm:
            from backend.ai.segmentors.fm_segmentation_model import FMSegmentationModel

            try:
                extractor = get_extractor(
                    self.encoder_name, pretrained=True, **self.kwargs
                )
            except (FileNotFoundError, OSError, Exception) as exc:
                raise RuntimeError(
                    f"Failed to load Foundation Model '{self.encoder_name}'. "
                    f"Please ensure the model weights are downloaded locally. "
                    f"Original error: {exc}"
                ) from exc

            if not extractor.supports_spatial:
                raise ValueError(
                    f"FM extractor '{self.encoder_name}' does not support spatial "
                    "feature extraction required for segmentation."
                )
            self._fm_extractor = extractor
            model = FMSegmentationModel(
                extractor=extractor,
                classes=self.classes,
                input_size=extractor.default_image_size,
                decoder_type=self.decoder_type,
                decoder_kwargs=self.decoder_kwargs,
            )
            return model

        model = smp.create_model(
            arch=self.architecture,
            encoder_name=self.encoder_name,
            in_channels=self.in_channels,
            classes=self.classes,
            **self.kwargs,
        )
        return model

    def get_normalization_params(self):
        if self.is_fm:
            # Use the extractor's own normalization
            extractor = self._fm_extractor
            if extractor is None:
                extractor = get_extractor(
                    self.encoder_name, pretrained=True, **self.kwargs
                )
            mean = list(extractor.normalization_mean)
            std = list(extractor.normalization_std)
            return mean, std

        params = smp.encoders.get_preprocessing_params(self.encoder_name)
        mean = torch.tensor(params["mean"]).view(1, 3, 1, 1)
        std = torch.tensor(params["std"]).view(1, 3, 1, 1)
        mean = mean.squeeze().tolist()
        std = std.squeeze().tolist()
        return mean, std

    def build_losses(
        self, loss_names: list[Any] = None, loss_weights: list[Any] = None, **kwargs
    ):

        assert len(loss_names) == len(loss_weights) or loss_weights is None, (
            "Length of loss_names and loss_weights must be the same."
        )
        # deafult to DiceLoss if no losses provided
        if loss_names is None:
            loss_names = ["DiceLoss", "JaccardLoss"]
        if loss_weights is None:
            loss_weights = [0.5, 0.5]

        losses = [get_loss(name, **kwargs) for name in loss_names]
        combined_loss = CombinedLoss(losses, loss_weights)
        return combined_loss
