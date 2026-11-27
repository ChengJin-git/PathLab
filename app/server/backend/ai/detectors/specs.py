"""Detection configuration shared by the API, model factory and checkpoints."""

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal

ARCHITECTURES = (
    {
        "id": "fasterrcnn",
        "name": "Faster R-CNN",
        "description": "Two-stage region proposal detector",
    },
    {
        "id": "retinanet",
        "name": "RetinaNet",
        "description": "One-stage detector with focal loss",
    },
    {
        "id": "fcos",
        "name": "FCOS",
        "description": "Anchor-free fully convolutional detector",
    },
)
CNN_BACKBONES = ("resnet18", "resnet34", "resnet50", "resnet101")


def available_backbones():
    from backend.ai.extractors.registry import get_available_extractors

    return [{"id": name, "name": name, "group": "CNN"} for name in CNN_BACKBONES] + [
        {"id": item["id"], "name": item["name"], "group": "Foundation model"}
        for item in get_available_extractors()
        if item.get("supports_spatial") and item["id"] not in CNN_BACKBONES
    ]


class DetectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    architecture: Literal["fasterrcnn", "retinanet", "fcos"] = "fasterrcnn"
    backbone: str = "resnet50"
    pretrained: bool = True
    train_backbone: bool = True
    image_size: int = Field(512, ge=64, le=2048)
    max_detections: int = Field(100, ge=1, le=1000)
    learning_rate: float = Field(0.0001, gt=0, le=1)
    epochs: int = Field(50, ge=1, le=10000)
    batch_size: int = Field(2, ge=1, le=128)
    optimizer: Literal["adam", "adamw", "sgd"] = "adamw"
    early_stopping_patience: int = Field(15, ge=1, le=10000)
    weight_decay: float = Field(0.0001, ge=0, le=1)

    @model_validator(mode="after")
    def supported_backbone(self):
        if self.backbone not in {item["id"] for item in available_backbones()}:
            raise ValueError(f"Unsupported detection backbone: {self.backbone}")
        if self.backbone not in CNN_BACKBONES and not self.pretrained:
            raise ValueError(
                "Foundation model backbones require their pretrained weights"
            )
        return self
