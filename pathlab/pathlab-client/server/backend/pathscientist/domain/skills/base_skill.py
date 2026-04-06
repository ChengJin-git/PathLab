"""
Auto Research Agent — Skill Definition

A Skill bundles: template + environment + constraints + evaluation.
Loaded from YAML files in the skills/ directory.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


@dataclass
class Skill:
    """A self-contained training skill definition."""

    name: str
    description: str

    # Template
    template: str                              # filename in templates/ dir
    modifiable_zones: list[str] = field(default_factory=lambda: ["model", "loss", "hyperparams"])

    # Environment
    extra_packages: list[str] = field(default_factory=list)

    # I/O
    inputs: dict[str, str] = field(default_factory=lambda: {
        "features_dir": "/data/features",
        "splits_file": "/data/splits.json",
    })
    outputs: dict[str, str] = field(default_factory=lambda: {
        "metrics": "/results/metrics.json",
        "model": "/results/best_model.pth",
    })

    # Evaluation
    primary_metric: str = "auc"
    secondary_metrics: list[str] = field(default_factory=lambda: ["accuracy", "f1"])

    # Constraints (injected into LLM prompt)
    constraints: list[str] = field(default_factory=list)

    # Know-How matching tags
    knowhow_tags: list[str] = field(default_factory=list)

    # Dataset configuration
    dataset: dict = field(default_factory=dict)

    # Task type matching
    task_types: list[str] = field(default_factory=lambda: ["classification"])

    # Reference code paths (for Code Agent to read real implementations)
    reference_code: dict[str, str] = field(default_factory=dict)

    def get_template_path(self) -> Path:
        """Absolute path to the template file."""
        templates_dir = Path(__file__).parent.parent / "templates"
        path = templates_dir / self.template
        if not path.exists():
            raise FileNotFoundError(f"Template not found: {path}")
        return path

    def get_template_content(self) -> str:
        """Read template source code."""
        return self.get_template_path().read_text(encoding="utf-8")

    def get_constraints_prompt(self) -> str:
        """Format constraints for injection into LLM prompt."""
        if not self.constraints:
            return ""
        lines = "\n".join(f"  - {c}" for c in self.constraints)
        return f"\nCode constraints (MUST follow):\n{lines}\n"

    def get_install_commands(self) -> list[str]:
        """Generate pip install commands for extra packages."""
        if not self.extra_packages:
            return []
        return ["pip", "install", "--quiet", "--no-warn-script-location"] + self.extra_packages

    def get_feature_dim(self, extractor: str = "") -> int:
        """Get feature dimension for a given extractor, or default."""
        dim_map = self.dataset.get("feature_dim_by_extractor", {})
        if extractor and extractor in dim_map:
            return dim_map[extractor]
        mock = self.dataset.get("mock_generator", {})
        return mock.get("default_feature_dim", 1024)

    def generate_mock_data(self, output_dir: str, extractor: str = "") -> Path:
        """
        Generate mock dataset for testing based on skill's dataset.mock_generator config.
        Returns path to the output directory.
        """
        import json
        import random

        import torch

        out = Path(output_dir)
        features_dir = out / "features"
        features_dir.mkdir(parents=True, exist_ok=True)

        mock_cfg = self.dataset.get("mock_generator", {})
        n_samples = mock_cfg.get("n_samples", 20)
        n_classes = mock_cfg.get("n_classes", 2)
        feat_dim = self.get_feature_dim(extractor)
        patch_range = mock_cfg.get("n_patches_range", [50, 200])

        wsi_ids = [f"mock_{i:03d}" for i in range(n_samples)]

        # Generate features
        for wid in wsi_ids:
            if self.dataset.get("format") == "image_mask_pairs":
                # Segmentation: generate image + mask
                img_size = mock_cfg.get("image_size", [512, 512])
                img = torch.randint(0, 255, (3, *img_size), dtype=torch.uint8)
                mask = torch.randint(0, n_classes, (1, *img_size), dtype=torch.long)
                images_dir = out / "images"
                masks_dir = out / "masks"
                images_dir.mkdir(exist_ok=True)
                masks_dir.mkdir(exist_ok=True)
                torch.save(img, images_dir / f"{wid}.pt")
                torch.save(mask, masks_dir / f"{wid}.pt")
            else:
                # Feature tensors
                n_patches = random.randint(*patch_range) if len(patch_range) == 2 else 100
                feat = torch.randn(n_patches, feat_dim)
                torch.save(feat, features_dir / f"{wid}.pt")

        # Generate splits
        random.shuffle(wsi_ids)
        schema = self.dataset.get("splits_schema", {})
        ratios = schema.get("default_ratios", {"train": 0.7, "val": 0.1, "test": 0.2})
        n_train = int(n_samples * ratios.get("train", 0.7))
        n_val = int(n_samples * ratios.get("val", 0.1))

        splits: dict[str, Any] = {
            "train": wsi_ids[:n_train],
            "val": wsi_ids[n_train:n_train + n_val],
            "test": wsi_ids[n_train + n_val:],
        }

        required_keys = schema.get("required_keys", [])

        if "labels" in required_keys:
            splits["labels"] = {wid: i % n_classes for i, wid in enumerate(wsi_ids)}

        if "survival_times" in required_keys:
            max_time = mock_cfg.get("max_time", 60.0)
            event_rate = mock_cfg.get("event_rate", 0.5)
            splits["survival_times"] = {
                wid: round(random.uniform(1, max_time), 1) for wid in wsi_ids
            }
            splits["event_status"] = {
                wid: (1 if random.random() < event_rate else 0) for wid in wsi_ids
            }

        splits_file = out / "splits.json"
        splits_file.write_text(json.dumps(splits, indent=2))

        return out

    @classmethod
    def from_yaml(cls, path: Path) -> Skill:
        """Load a skill from a YAML file."""
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        env = data.get("environment", {})
        evaluation = data.get("evaluation", {})

        return cls(
            name=data["name"],
            description=data.get("description", ""),
            template=data["template"],
            modifiable_zones=data.get("modifiable_zones", ["model", "loss", "hyperparams"]),
            extra_packages=env.get("extra_packages", []),
            inputs=data.get("inputs", {}),
            outputs=data.get("outputs", {}),
            primary_metric=evaluation.get("primary_metric", "auc"),
            secondary_metrics=evaluation.get("secondary_metrics", []),
            constraints=data.get("constraints", []),
            dataset=data.get("dataset", {}),
            knowhow_tags=data.get("knowhow_tags", []),
            task_types=data.get("task_types", [data.get("task_type", "classification")]),
            reference_code=data.get("reference_code", {}),
        )
