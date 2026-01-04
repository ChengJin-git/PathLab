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
        
    @torch.inference_mode()
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

    @classmethod
    def build(cls, hf_token: str = "", **kwargs) -> BaseExtractor:
        """Build a CONCHExtractor instance."""
        return cls(hf_token=hf_token)


if __name__ == "__main__":
    token = ""
    extractor = PathoCLIPExtractor.build(hf_token=token)
    dummy_input = torch.randn(2, 3, 224, 224)
    output = extractor.forward(dummy_input)
    print(output.shape)

    # compare with github code
    model, _, preprocess = open_clip.create_model_and_transforms('ViT-L-14', pretrained='/storage/jmabq/PathLab/pathlab/pathlab-client/server/backend/ai/extractors/checkpoints/PathoCLIP/Patho-CLIP-L.pt')
    model.eval()
    output2 = model.encode_image(dummy_input)
    print(output2.shape)
    # error
    print(torch.abs(output - output2).max())
