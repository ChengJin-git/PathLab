# pip install git+https://github.com/Mahmoodlab/CONCH.git

from conch.open_clip_custom import create_model_from_pretrained
import torch
from .base import BaseExtractor
from .checkpoint_manager import get_ckpt_path


class CONCHExtractor(BaseExtractor):
    def __init__(self, hf_token: str = ""):
        super().__init__()
        ckpt_path = get_ckpt_path("CONCH", hf_token)
        self.checkpoint_path = ckpt_path
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

    def get_feature_contract(self, model_id):
        from backend.ai.feature_contracts import text_feature_contract
        return text_feature_contract(model_id,self.checkpoint_path,self.output_dim,repr(self.preprocess)[:2000],
            provider='conch',architecture='conch_ViT-B-16',projection='provider')

    @property
    def output_dim(self) -> int:
        return 512

    @property
    def spatial_output_dim(self) -> int:
        # encode_image() returns a projected 512-d embedding, while the visual
        # trunk patch tokens used for segmentation stay in the ViT hidden size.
        return 768

    @property
    def default_image_size(self) -> int:
        return 448

    # -- spatial override: CONCH wraps a CoCa model with VisualModel.trunk (timm ViT) --
    @property
    def supports_spatial(self) -> bool:
        return True

    def forward_spatial(self, x: torch.Tensor) -> torch.Tensor:
        import math
        # backbone.visual.trunk is a timm VisionTransformer
        # trunk.forward was replaced with trunk.forward_features, so trunk(x) returns (B, N+1, D)
        trunk = self.backbone.visual.trunk
        tokens = trunk(x)  # (B, 1 + num_patches, D)
        patch_tokens = tokens[:, 1:]  # strip CLS token
        B, N, D = patch_tokens.shape
        H = W = int(math.isqrt(N))
        assert H * W == N
        return patch_tokens.permute(0, 2, 1).reshape(B, D, H, W)

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
