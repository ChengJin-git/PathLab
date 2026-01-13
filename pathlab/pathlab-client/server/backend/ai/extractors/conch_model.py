# pip install git+https://github.com/Mahmoodlab/CONCH.git

from conch.open_clip_custom import create_model_from_pretrained
import torch
from .base import BaseExtractor
from .checkpoint_manager import get_ckpt_path


class CONCHExtractor(BaseExtractor):
    def __init__(self, hf_token: str = ""):
        super().__init__()
        ckpt_path = get_ckpt_path("CONCH", hf_token)
        self.backbone, self.preprocess = create_model_from_pretrained('conch_ViT-B-16', ckpt_path)
        
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Extract features from input images.
        
        Args:
            x: Input tensor of shape (B, 3, H, W)
        Returns:
            Feature tensor of shape (B, 512)
        """
        feats = self.backbone.encode_image(x, proj_contrast=False, normalize=False)
        return feats
    
    def get_transforms(self, mode = "eval"):
        return self.preprocess
    
    @property
    def output_dim(self) -> int:
        return 512
    
    @property
    def default_image_size(self) -> int:
        return 448

    @classmethod
    def build(cls, hf_token: str = "", **kwargs) -> BaseExtractor:
        """Build a CONCHExtractor instance."""
        return cls(hf_token=hf_token)


if __name__ == "__main__":
    token = ""
    extractor = CONCHExtractor.build(hf_token=token)
    dummy_input = torch.randn(2, 3, 224, 224)
    output = extractor.forward(dummy_input)
    print(output.shape)  # Expected output shape: (2, 512)