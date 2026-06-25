import timm
from timm.data import resolve_data_config
from timm.layers import SwiGLUPacked
from timm.data.transforms_factory import create_transform
import torch

from .base import BaseExtractor
from .checkpoint_manager import get_ckpt_path
from .weight_loading import load_state_dict_file


class VirchowExtractor(BaseExtractor):
    def __init__(self, hf_token: str = ""):
        super().__init__()
        timm_kwargs = {
            "model_name": "vit_huge_patch14_224",
            "img_size": 224,
            "init_values": 1e-5,
            "num_classes": 0,
            "mlp_ratio": 5.3375,
            "global_pool": "",
            "dynamic_img_size": True,
        }
        pretrained_cfg = {
            "tag": "virchow_v1",
            "custom_load": False,
            "input_size": [3, 224, 224],
            "fixed_input_size": False,
            "interpolation": "bicubic",
            "crop_pct": 1.0,
            "crop_mode": "center",
            "mean": [0.485, 0.456, 0.406],
            "std": [0.229, 0.224, 0.225],
            "num_classes": 0,
            "pool_size": None,
            "first_conv": "patch_embed.proj",
            "classifier": "head",
            "license": "Apache 2.0",
        }

        ckpt_path = get_ckpt_path("Virchow", hf_token)
        self.backbone = timm.create_model(
            pretrained=False,
            mlp_layer=SwiGLUPacked,
            act_layer=torch.nn.SiLU,
            **timm_kwargs
        )
        self.backbone.load_state_dict(load_state_dict_file(ckpt_path), strict=True)
        self.backbone.eval()
        self.preprocess = create_transform(
            **resolve_data_config(pretrained_cfg=pretrained_cfg)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Extract features from input images.

        Args:
            x: Input tensor of shape (B, 3, H, W)
        Returns:
            Feature tensor of shape (B, 512)
        """
        feats = self.backbone(x)
        class_token = feats[:, 0]    # size: 1 x 1280
        patch_tokens = feats[:, 1:]  # size: 1 x 256 x 1280, tokens 1-4 are register tokens so we ignore those
        # concatenate class token and average pool of patch tokens
        embedding = torch.cat([class_token, patch_tokens.mean(1)], dim=-1)  # size: 1 x 2560
        return embedding

    def get_transforms(self, mode="eval"):
        return self.preprocess

    @property
    def output_dim(self) -> int:
        return 2560

    @property
    def spatial_output_dim(self) -> int:
        # forward() concatenates CLS and pooled patch tokens (1280 + 1280), but
        # forward_spatial() returns raw patch tokens with hidden size 1280.
        return 1280

    @property
    def default_image_size(self) -> int:
        return 224

    @classmethod
    def build(cls, hf_token: str = "", **kwargs) -> BaseExtractor:
        """Build a CONCHExtractor instance."""
        return cls(hf_token=hf_token)


if __name__ == "__main__":
    token = ""
    extractor = VirchowExtractor.build(hf_token=token)
    dummy_input = torch.randn(2, 3, 224, 224)
    output = extractor.forward(dummy_input)
    print(output.shape)

    # model = timm.create_model("hf-hub:paige-ai/Virchow", pretrained=True, mlp_layer=SwiGLUPacked, act_layer=torch.nn.SiLU)
    # model = model.eval()
    # outpu1 = model(dummy_input)  # size: 1 x 257 x 1280
    # error = torch.abs(output - outpu1).max()
    # print("Max error compared to timm hf-hub:", error.item())
