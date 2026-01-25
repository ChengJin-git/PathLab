
import timm
import torchvision
import torch
from .base import BaseExtractor
from .checkpoint_manager import get_ckpt_path


class UNI2Extractor(BaseExtractor):
    def __init__(self, hf_token: str = ""):
        super().__init__()
        timm_kwargs = {
            'model_name': 'vit_giant_patch14_224',
            'img_size': 224, 
            'patch_size': 14, 
            'depth': 24,
            'num_heads': 24,
            'init_values': 1e-5, 
            'embed_dim': 1536,
            'mlp_ratio': 2.66667*2,
            'num_classes': 0, 
            'no_embed_class': True,
            'mlp_layer': timm.layers.SwiGLUPacked, 
            'act_layer': torch.nn.SiLU, 
            'reg_tokens': 8, 
            'dynamic_img_size': True
        }
        ckpt_path = get_ckpt_path("UNI2", hf_token)
        self.backbone = timm.create_model(pretrained=False, **timm_kwargs)
        self.backbone.load_state_dict(torch.load(ckpt_path, map_location="cpu"), strict=True)
        self.backbone.eval()
        
        self.preprocess =  torchvision.transforms.Compose(
        [
            torchvision.transforms.Resize((224, 224)),
            torchvision.transforms.ToTensor(),
            torchvision.transforms.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)),
        ]
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
        return feats
    
    def get_transforms(self, mode = "eval"):
        return self.preprocess
    
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
    extractor = UNI2Extractor.build(hf_token=token)
    dummy_input = torch.randn(2, 3, 224, 224)
    output = extractor.forward(dummy_input)
    print(output.shape) 