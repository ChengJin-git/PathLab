import torch
from torchvision import transforms

from .base import BaseExtractor
from .checkpoint_manager import get_ckpt_path


class OpenMidnightExtractor(BaseExtractor):
    def __init__(self, hf_token: str = ""):
        super().__init__()
        self.local_model_dir = get_ckpt_path("OpenMidnight", hf_token)
        self.backbone = torch.hub.load('facebookresearch/dinov2', 'dinov2_vitg14_reg')
        # Required because dinov2 is baseline 392 and we are baseline 224 resolution
        checkpoint = torch.load(self.local_model_dir, map_location="cpu")
        pos_embed = checkpoint["pos_embed"]
        self.backbone.pos_embed = torch.nn.parameter.Parameter(pos_embed)
        self.backbone.load_state_dict(checkpoint, strict=True)
        self.backbone.eval()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Extract features from input images.

        Args:
            x: Input tensor of shape (B, 3, H, W)
        Returns:
            Feature tensor of shape (B, 512)
        """
        with torch.autocast(device_type=x.device.type, dtype=torch.float16):
            outputs = self.backbone(x)
        return outputs

    def get_transforms(self, mode="eval"):
        return transforms.Compose(
            [
                transforms.Resize((224, 224)),
                transforms.ToTensor(),
                transforms.Normalize(
                    mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)
                ),
            ]
        )

    @property
    def output_dim(self) -> int:
        return 1536

    @property
    def default_image_size(self) -> int:
        return 224

    @classmethod
    def build(cls, hf_token: str = "", **kwargs) -> BaseExtractor:
        """Build a CONCHExtractor instance."""
        return cls(hf_token=hf_token)


if __name__ == "__main__":
    token = ""
    extractor = OpenMidnightExtractor.build(hf_token=token)
    dummy_input = torch.randn(2, 3, 224, 224)
    output = extractor.forward(dummy_input)
    print(output.shape)
