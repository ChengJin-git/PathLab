"""COCO boxes in original image coordinates. Empty annotations are valid negatives."""

import json
import math
from pathlib import Path

from PIL import Image
import torch
from torch.utils.data import Dataset
from torchvision.transforms.functional import pil_to_tensor


def coco_targets(payload: dict, classes: list[str]) -> dict[int, dict]:
    categories = payload.get("categories", [])
    category_ids = [item["id"] for item in categories]
    if len(set(category_ids)) != len(category_ids):
        raise ValueError("Duplicate COCO category IDs")
    if any(item.get("name") not in classes for item in categories):
        raise ValueError("COCO categories must match the trained class names")
    labels = {item["id"]: classes.index(item["name"]) + 1 for item in categories}
    images = {item["id"]: item for item in payload["images"]}
    if len(images) != len(payload["images"]):
        raise ValueError("Duplicate COCO image IDs")
    targets = {
        identity: {"boxes": [], "labels": [], "iscrowd": []} for identity in images
    }
    for ann in payload["annotations"]:
        identity = ann["image_id"]
        if identity not in images or ann["category_id"] not in labels:
            raise ValueError("COCO annotation refers to an unknown image/category")
        box = ann.get("bbox")
        if (
            not isinstance(box, list)
            or len(box) != 4
            or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in box)
        ):
            raise ValueError("Detection requires finite COCO bbox=[x,y,width,height]")
        x, y, width, height = box
        image = images[identity]
        if (
            x < 0
            or y < 0
            or width <= 0
            or height <= 0
            or x + width > image["width"] + 1e-4
            or y + height > image["height"] + 1e-4
        ):
            raise ValueError("COCO bounding box is outside the image or has zero area")
        crowd = ann.get("iscrowd", 0)
        if crowd not in (0, 1):
            raise ValueError("COCO iscrowd must be 0 or 1")
        target = targets[identity]
        target["boxes"].append([x, y, x + width, y + height])
        target["labels"].append(labels[ann["category_id"]])
        target["iscrowd"].append(crowd)
    return targets


class DetectionDataset(Dataset):
    def __init__(self, image_dir, annotations_path, classes, *, augment=False):
        self.root = Path(image_dir)
        payload = json.loads(Path(annotations_path).read_text())
        self.images = payload["images"]
        self.targets = coco_targets(payload, classes)
        self.augment = augment

    def __len__(self):
        return len(self.images)

    def __getitem__(self, index):
        info = self.images[index]
        with Image.open(self.root / info["file_name"]) as image:
            if image.size != (info["width"], info["height"]):
                raise ValueError(f"COCO dimensions do not match {info['file_name']}")
            tensor = pil_to_tensor(image.convert("RGB")).float() / 255
        raw = self.targets[info["id"]]
        boxes = torch.tensor(raw["boxes"], dtype=torch.float32).reshape(-1, 4)
        if self.augment and torch.rand(()) < 0.5:
            tensor = tensor.flip(-1)
            boxes[:, [0, 2]] = tensor.shape[-1] - boxes[:, [2, 0]]
        return tensor, {
            "boxes": boxes,
            "labels": torch.tensor(raw["labels"], dtype=torch.int64),
            "iscrowd": torch.tensor(raw["iscrowd"], dtype=torch.int64),
            "image_id": torch.tensor(info["id"]),
        }


def collate_detection(batch):
    return tuple(zip(*batch))
