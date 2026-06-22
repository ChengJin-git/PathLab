"""FM Segmentation Decoder Heads.

DPT is provided by segmentation_models_pytorch (smp) and imported directly
in fm_segmentation_model.py. Only UNETR (absent from smp) is defined here.
"""

from .unetr import UNETRDecoder

__all__ = ["UNETRDecoder"]
