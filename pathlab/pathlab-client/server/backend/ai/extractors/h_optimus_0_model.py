import timm
import torchvision
import torch
from .base import BaseExtractor
from .checkpoint_manager import get_ckpt_path


class H_Optimus_0Extractor(BaseExtractor):
    def __init__(self, hf_token: str = ""):
        super().__init__()
        ckpt_path = "local-dir:" + get_ckpt_path("H-Optimus-0", hf_token)
        # load backbone
        self.backbone = timm.create_model(
        ckpt_path, pretrained=True, init_values=1e-5, dynamic_img_size=False)
        self.backbone.eval()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        with torch.autocast(device_type=x.device.type, dtype=torch.float16):
            feats = self.backbone(x)
        return feats

    def get_transforms(self, mode="eval"):
        return torchvision.transforms.Compose(
            [
                torchvision.transforms.Resize(
                    224, interpolation=torchvision.transforms.InterpolationMode.BICUBIC
                ),
                torchvision.transforms.ToTensor(),
                torchvision.transforms.Normalize(
                    mean=(0.707223, 0.578729, 0.703617),
                    std=(0.211883, 0.230117, 0.177517),
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
    extractor = H_Optimus_0Extractor.build(hf_token=token)
    dummy_input = torch.randn(2, 3, 224, 224)
    output = extractor.forward(dummy_input)
    print(output.shape)
