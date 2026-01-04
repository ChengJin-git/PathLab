
import timm
import torchvision
import torch
from .base import BaseExtractor
from .checkpoint_manager import get_ckpt_path


class UNIExtractor(BaseExtractor):
    def __init__(self, hf_token: str = ""):
        super().__init__()
        ckpt_path = get_ckpt_path("UNI", hf_token)
        # load backbone
        self.backbone = timm.create_model( "vit_large_patch16_224", img_size=224, patch_size=16, init_values=1e-5, num_classes=0, 
                                          dynamic_img_size=True)
        msg = self.backbone.load_state_dict(torch.load(ckpt_path))
        # print("UNIExtractor loaded:", msg)
        self.backbone.eval()
        self.preprocess =  torchvision.transforms.Compose(
        [
            torchvision.transforms.Resize((224, 224)),
            torchvision.transforms.ToTensor(),
            torchvision.transforms.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)),
        ]
    )
        
        
    @torch.inference_mode()
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
        return 1024
    
    @property
    def default_image_size(self) -> int:
        return 224

    @classmethod
    def build(cls, hf_token: str = "", **kwargs) -> BaseExtractor:
        """Build a CONCHExtractor instance."""
        return cls(hf_token=hf_token)


if __name__ == "__main__":
    token = ""
    extractor = UNIExtractor.build(hf_token=token)
    dummy_input = torch.randn(2, 3, 224, 224)
    output = extractor.forward(dummy_input)
    print(output.shape) 