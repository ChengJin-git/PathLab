import torch
from PIL import Image
import open_clip

from .base import BaseExtractor
from .checkpoint_manager import get_ckpt_path


class PathoCLIPExtractor(BaseExtractor):
    def __init__(self, hf_token: str = ""):
        super().__init__()
        self.local_model_dir = get_ckpt_path("PathoCLIP", hf_token)
        self.backbone, _, self.preprocess = open_clip.create_model_and_transforms("ViT-L-14", pretrained=self.local_model_dir)
        self.backbone.eval()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        outputs = self.backbone.encode_image(x)
        return outputs

    def get_transforms(self, mode="eval"):
        return self.preprocess

    @property
    def output_dim(self) -> int:
        return 768

    @property
    def default_image_size(self) -> int:
        return 224

    # -- spatial override: open_clip VisionTransformer --
    @property
    def supports_spatial(self) -> bool:
        return True

    def forward_spatial(self, x: torch.Tensor) -> torch.Tensor:
        import math
        visual = self.backbone.visual
        tokens = visual._embeds(x)        # (B, 1 + N, D) with CLS prepended
        tokens = visual.transformer(tokens)  # (B, 1 + N, D)
        tokens = visual.ln_post(tokens) if not visual.final_ln_after_pool else tokens
        patch_tokens = tokens[:, 1:]       # strip CLS token
        B, N, D = patch_tokens.shape
        H = W = int(math.isqrt(N))
        assert H * W == N
        return patch_tokens.permute(0, 2, 1).reshape(B, D, H, W)

    @classmethod
    def build(cls, hf_token: str = "", **kwargs) -> BaseExtractor:
        """Build a PathoCLIPExtractor instance."""
        return cls(hf_token=hf_token)
