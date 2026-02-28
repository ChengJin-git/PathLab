import segmentation_models_pytorch as smp
import torch
from backend.ai.segmentors.loss import get_loss, CombinedLoss
from backend.ai.extractors.registry import list_extractors, get_extractor


SUPPORT_ARCHTECTURES = ['unet', 'unetplusplus', 'manet', 'linknet', 'fpn', 'pspnet', 'deeplabv3', 'deeplabv3plus', 'pan', 'upernet', 'segformer', 'dpt']
SUPPORT_FEATURE_EXTRACTORS = ['resnet18', 'resnet34', 'resnet50', 'resnet101', 'resnet152', 'resnext50_32x4d', 'resnext101_32x4d', 'resnext101_32x8d', 'resnext101_32x16d', 'resnext101_32x32d', 'resnext101_32x48d', 'dpn68', 'dpn68b', 'dpn92', 'dpn98', 'dpn107', 'dpn131', 'vgg11', 'vgg11_bn', 'vgg13', 'vgg13_bn', 'vgg16', 'vgg16_bn', 'vgg19', 'vgg19_bn', 'senet154', 'se_resnet50', 'se_resnet101', 'se_resnet152', 'se_resnext50_32x4d', 'se_resnext101_32x4d', 'densenet121', 'densenet169', 'densenet201', 'densenet161', 'inceptionresnetv2', 'inceptionv4', 'efficientnet-b0', 'efficientnet-b1', 'efficientnet-b2', 'efficientnet-b3', 'efficientnet-b4', 'efficientnet-b5', 'efficientnet-b6', 'efficientnet-b7', 'mobilenet_v2', 'xception', 'timm-efficientnet-b0', 'timm-efficientnet-b1', 'timm-efficientnet-b2', 'timm-efficientnet-b3', 'timm-efficientnet-b4', 'timm-efficientnet-b5', 'timm-efficientnet-b6', 'timm-efficientnet-b7', 'timm-efficientnet-b8', 'timm-efficientnet-l2', 'timm-tf_efficientnet_lite0', 'timm-tf_efficientnet_lite1', 'timm-tf_efficientnet_lite2', 'timm-tf_efficientnet_lite3', 'timm-tf_efficientnet_lite4', 'timm-skresnet18', 'timm-skresnet34', 'timm-skresnext50_32x4d', 'mit_b0', 'mit_b1', 'mit_b2', 'mit_b3', 'mit_b4', 'mit_b5', 'mobileone_s0', 'mobileone_s1', 'mobileone_s2', 'mobileone_s3', 'mobileone_s4']


def is_fm_encoder(encoder_name: str) -> bool:
    """Check whether *encoder_name* refers to a Foundation Model extractor
    that supports spatial feature extraction (i.e. FM-powered segmentation).

    Returns False for traditional CNN encoders (resnet, efficientnet, …) and
    for FM extractors that do not support ``forward_spatial``
    (e.g. resnet50, vit_l_16 in the extractor registry).
    """
    return encoder_name in list_extractors() and encoder_name not in SUPPORT_FEATURE_EXTRACTORS


class Segmentor:
    def __init__(self, architecture: str, encoder_name: str, in_channels: int = 3, classes: int = 1, **kwargs):
        self.is_fm = is_fm_encoder(encoder_name)

        if not self.is_fm:
            # Traditional SMP path
            if architecture not in SUPPORT_ARCHTECTURES:
                raise ValueError(f"Unsupported architecture '{architecture}'. Supported architectures are: {SUPPORT_ARCHTECTURES}")
            if encoder_name not in SUPPORT_FEATURE_EXTRACTORS:
                raise ValueError(f"Unsupported encoder '{encoder_name}'. Supported encoders are: {SUPPORT_FEATURE_EXTRACTORS}")

        self.architecture = architecture
        self.encoder_name = encoder_name
        self.in_channels = in_channels
        self.classes = classes
        self.kwargs = kwargs
        # Cached extractor instance for FM path (avoids loading twice)
        self._fm_extractor = None

    def build_model(self):
        if self.is_fm:
            from backend.ai.segmentors.fm_segmentation_model import FMSegmentationModel

            try:
                extractor = get_extractor(self.encoder_name, pretrained=True, **self.kwargs)
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
            )
            return model

        model = smp.create_model(
            arch=self.architecture,
            encoder_name=self.encoder_name,
            in_channels=self.in_channels,
            classes=self.classes,
            **self.kwargs
        )
        return model

    def get_normalization_params(self):
        if self.is_fm:
            # Use the extractor's own normalization
            extractor = self._fm_extractor
            if extractor is None:
                extractor = get_extractor(self.encoder_name, pretrained=True, **self.kwargs)
            mean = list(extractor.normalization_mean)
            std = list(extractor.normalization_std)
            return mean, std

        params = smp.encoders.get_preprocessing_params(self.encoder_name)
        mean = torch.tensor(params['mean']).view(1, 3, 1, 1)
        std = torch.tensor(params['std']).view(1, 3, 1, 1)
        mean = mean.squeeze().tolist()
        std = std.squeeze().tolist()
        return mean, std

    def build_losses(self, loss_names: list = None, loss_weights: list = None, **kwargs):

        assert len(loss_names) == len(loss_weights) or loss_weights is None, "Length of loss_names and loss_weights must be the same."
        # deafult to DiceLoss if no losses provided
        if loss_names is None:
            loss_names = ['DiceLoss', 'JaccardLoss']
        if loss_weights is None:
            loss_weights = [0.5, 0.5]

        losses = [get_loss(name, **kwargs) for name in loss_names]
        combined_loss = CombinedLoss(losses, loss_weights)
        return combined_loss