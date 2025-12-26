import json
import os
import random
from enum import Enum
from typing import Callable, Dict, List, Optional, Union
from torch.utils.data import Dataset

from .dataset_template.segmentation import LABEL_TEMPLATE


def read_images_and_masks(image_dir: str, annotations_full_path: str):
    with open(annotations_full_path) as f:
        all_annotations = json.load(f)
    data = {}
    
    for item in all_annotations["images"]:
        id = item["id"]
        data[id] = {
            "id": None,
            "image": os.path.join(image_dir, item["file_name"]),
            "segmentation": [],
            "bbox": [],
        }
    for item in all_annotations["annotations"]:
        data[item["image_id"]]["id"] = item["image_id"]
        data[item["image_id"]]["segmentation"].append(item["segmentation"])
        data[item["image_id"]]["bbox"].append(item["bbox"])
        
    return list(data.values())


class SegmentationDataset(Dataset):
    def __init__(
        self,
        *,
        split: "CocoCaptions.Split",
        root: Optional[str] = None,
        transforms: Optional[Callable] = None,
        transform: Optional[Callable] = None,
        target_transform: Optional[Callable] = None,
    ) -> None:
        super().__init__(
            root=root,
            transforms=transforms,
            transform=transform,
            target_transform=target_transform,
            image_decoder=ImageDataDecoder,
            target_decoder=TargetDecoder,
        )

        self.image_captions = read_images_and_captions(root, split)

    def get_image_relpath(self, index: int) -> str:
        image_path = self.image_captions[index]["image"]
        return image_path

    def get_image_data(self, index: int) -> bytes:
        image_path = self.get_image_relpath(index)
        with open(image_path, mode="rb") as f:
            image_data = f.read()
        return image_data

    def get_target(self, index: int) -> str:
        return random.choice(self.image_captions[index]["captions"])

    def __len__(self) -> int:
        return len(self.image_captions)