"""One CPU-only resource model for queue admission and GPU pipeline stages.

These are peak-memory planning estimates, not measured guarantees. Runtime probes
remain authoritative. A declared/measured peak can increase the reservation.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MODEL_WEIGHTS_MB = {
    "resnet50": 200,
    "plip": 400,
    "patho_clip": 400,
    "conch": 600,
    "phikon": 800,
    "vit_l_16": 1200,
    "uni": 1500,
    "mstar": 1500,
    "gpfm": 1500,
    "phikon2": 1800,
    "virchow": 3000,
    "virchow2": 3000,
    "conch15": 3000,
    "h-optimus-0": 4000,
    "uni2": 5000,
    "openmidnight": 5500,
    "h-optimus-1": 6000,
    "smartccs": 1500,
    "smartcyto": 500,
    "kronos": 200,
}


class GpuWorkload(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    operation: Literal[
        "feature_extraction",
        "patch_classification",
        "segmentation",
        "detection",
        "mil_training",
        "inference",
        "custom",
    ]
    model: str = Field(default="", max_length=120)
    batch_size: int = Field(default=1, ge=1, le=65536)
    image_size: int | None = Field(default=None, ge=16, le=16384)
    bag_size: int = Field(default=32768, ge=1, le=2000000)
    feature_dim: int = Field(default=1024, ge=1, le=65536)
    input_bytes: int | None = Field(default=None, ge=1)
    trainable: bool = False
    peak_vram_mb: float | None = Field(default=None, ge=256, le=1048576)

    @model_validator(mode="after")
    def known_workload(self):
        if self.operation == "custom" and self.peak_vram_mb is None:
            raise ValueError(
                "Custom GPU code requires peak_vram_mb based on its model/input size or a measured pilot."
            )
        return self


@dataclass(frozen=True)
class GpuEstimate:
    required_mb: float
    operation: str
    model_mb: float
    activation_mb: float
    overhead_mb: float
    basis: str

    def public(self):
        return asdict(self)


def estimate_gpu(workload: GpuWorkload, minimum_mb: float = 2000) -> GpuEstimate:
    model = workload.model.strip().lower()
    weights = float(MODEL_WEIGHTS_MB.get(model, 1500))
    overhead = 768.0
    if workload.operation == "custom":
        weights, activation = 0.0, 0.0
        basis = "declared_peak"
    elif workload.operation == "mil_training":
        # Frozen embeddings, not the image encoder. Include input copies,
        # intermediate activations, gradients and aggregator optimizer states.
        weights = 256.0
        tensor_bytes = (
            workload.input_bytes
            or workload.batch_size * workload.bag_size * workload.feature_dim * 4
        )
        activation = tensor_bytes / 1024**2 * 4
        if model in {"transmil", "transformer"}:
            activation *= 2
        basis = "embedding_tensor_and_aggregator"
    else:
        per_sample = 384.0 if workload.operation == "detection" else 256.0 if workload.operation == "segmentation" else 50.0
        image_size = workload.image_size or model_image_size(model, workload.operation)
        activation = workload.batch_size * per_sample * (image_size / 224) ** 2
        if workload.trainable:
            weights *= 4  # FP32 parameters, gradients, Adam moments
            activation *= 2
        basis = "model_weights_and_image_batch"
    required = max(
        float(minimum_mb),
        (weights + activation + overhead) * 1.15,
        float(workload.peak_vram_mb or 0),
    )
    if not math.isfinite(required):
        raise ValueError("Invalid GPU memory requirement")
    return GpuEstimate(
        math.ceil(required), workload.operation, weights, activation, overhead, basis
    )


def model_image_size(model: str, operation: str) -> int:
    if model.lower() in {"conch", "conch15"}:
        return 448
    if operation in {"segmentation", "patch_classification"} and model.lower() in {
        "resnet50",
        "vit_l_16",
    }:
        return 512
    if operation == "segmentation" and model.lower() not in MODEL_WEIGHTS_MB:
        return 512
    return 224


def task_workload(task_type: str, kwargs: dict[str, Any]) -> GpuWorkload:
    """Normalize existing platform task metadata once, without source-specific math."""
    if kwargs.get("resources"):
        return GpuWorkload.model_validate(kwargs["resources"])
    pre = kwargs.get("preprocessing_config") or {}
    model = kwargs.get("model_config") or {}
    kind = str(kwargs.get("training_task_type") or kwargs.get("model_task_type") or "")
    name = (
        pre.get("feature_extractor")
        or model.get("feature_extractor")
        or model.get("backbone")
        or kwargs.get("feature_extractor")
        or ""
    )
    if kind == "patch_detection":
        operation = "detection"
        name = model.get("backbone", name)
        batch = model.get("batch_size", kwargs.get("batch_size", 2))
    elif "segmentation" in kind:
        operation = "segmentation"
        batch = model.get("batch_size", kwargs.get("batch_size", 1))
    elif kind in {"wsi_classification", "wsi_survival"} and not pre.get(
        "feature_extractor"
    ):
        operation, batch = "mil_training", 1
        name = model.get("aggregator", "abmil")
    else:
        operation = "patch_classification" if task_type == "training" else "inference"
        batch = (
            model.get("batch_size")
            or pre.get("feature_batch_size")
            or kwargs.get("batch_size")
            or 1
        )
    return GpuWorkload(
        operation=operation,
        model=str(name),
        batch_size=batch,
        image_size=model.get("image_size"),
        trainable=bool(model.get("train_backbone", False)),
    )
