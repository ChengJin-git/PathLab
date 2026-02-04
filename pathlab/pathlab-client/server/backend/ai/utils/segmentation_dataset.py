import json
import os
from typing import Callable, Optional, Tuple
import numpy as np
import torch
from torchvision.transforms import v2
from torchvision import tv_tensors
from torch.utils.data import Dataset
from PIL import Image
import cv2


def get_transforms(split: str, size: Tuple[int, int] = (1024, 1024), normalization_mean: Optional[list] = None, normalization_std: Optional[list] = None) -> Callable:
    """
    Get transforms for segmentation tasks.
    
    Args:
        split: "train", "val", or "test"
        size: Target size (H, W)
    """
    transforms = []
    
    # Base transforms
    transforms.append(v2.ToDtype(torch.float32, scale=True)) # Scale [0, 255] -> [0, 1] for images
    
    if split == "train":
        transforms.extend([
            v2.RandomResizedCrop(size, scale=(0.8, 1.0), antialias=True),
            v2.RandomHorizontalFlip(p=0.5),
            v2.RandomVerticalFlip(p=0.5),
            v2.RandomRotation(degrees=15),
            v2.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2, hue=0.1), # Only applies to Image
        ])
    else:
        transforms.extend([
            v2.Resize(size, antialias=True),
        ])
        
    # Normalization (ImageNet stats) - Only applies to Image
    transforms.append(
        v2.Normalize(mean=normalization_mean or [0.485, 0.456, 0.406], std=normalization_std or [0.229, 0.224, 0.225])
    )
    
    return v2.Compose(transforms)


def read_images_and_masks(image_dir: str, annotations_full_path: str):
    with open(annotations_full_path) as f:
        all_annotations = json.load(f)
    data = {}
    categories = all_annotations.get("categories", {})
    
    for item in all_annotations["images"]:
        id = item["id"]
        data[id] = {
            "id": None,
            "image": os.path.join(image_dir, item["file_name"]),
            "segmentation": [],
            "category_id": [],
            "bbox": [],
        }
    for item in all_annotations["annotations"]:
        data[item["image_id"]]["id"] = item["image_id"]
        data[item["image_id"]]["segmentation"].append(item["segmentation"])
        data[item["image_id"]]["category_id"].append(item["category_id"])
        data[item["image_id"]]["bbox"].append(item["bbox"])
        
    return list(data.values()), categories



class SegmentationDataset(Dataset):
    """
    A dataset class for image segmentation tasks.
    The annotations file is expected to be prepared in format defined at dataset_template/segmentation_annotations.json.
    The annotations file should be divided into "train", "val, and "test" splits. 
    This class accepts image directory and annotations file split(train/val/test) path to load the data.
    """
    def __init__(self,
        img_dir: Optional[str] = None,
        annotations_path: Optional[str] = None,
        transform: Optional[Callable] = None,
    ):
        self.img_dir = img_dir
        self.annotations_path = annotations_path
        self.transform = transform # we use torchvision.transforms v2
        self.image_items, self.categories = read_images_and_masks(img_dir, annotations_full_path=annotations_path)
        self.total_categories = len(self.categories)
        self.cat_id_to_index = {cat['id']: i for i, cat in enumerate(self.categories)}
        
    def load_image(self, image_path: str):
        img = Image.open(image_path).convert("RGB")
        return img
    
    def set_transform(self, transform: Callable):
        self.transform = transform

    def generate_label_masks(self, image_size, polygons_list, category_ids):
        width, height = image_size
        mask = np.zeros((self.total_categories, height, width), dtype=np.float32)

        for polygons, cat_id in zip(polygons_list, category_ids):
            if cat_id not in self.cat_id_to_index:
                continue
            idx = self.cat_id_to_index[cat_id]
            
            for poly in polygons:
                pts = np.array(poly, dtype=np.int32).reshape((-1, 2))
                cv2.fillPoly(mask[idx], [pts], 1.0)
        
        return mask

    def __getitem__(self, idx: int):
        item = self.image_items[idx]
        image_path = item["image"]
        image = self.load_image(image_path)
        polygons_list = item["segmentation"]
        category_ids = item["category_id"]
        # Generate binary masks for each instance using polygon coordinates
        category_mask = self.generate_label_masks(image.size, polygons_list, category_ids)

        if self.transform:
            # Prepare inputs for torchvision v2 transforms
            # Wrap image and mask in tv_tensors to ensure correct transform behavior
            # ToImage() converts PIL -> tv_tensors.Image (Tensor)
            image = v2.ToImage()(image) 
            category_mask = tv_tensors.Mask(category_mask)
            image, category_mask = self.transform(image, category_mask)

        return image, category_mask

    def __len__(self) -> int:
        return len(self.image_items)



if __name__ == "__main__":
    # Example usage
    img_dir = "/jhcnas6/Cytology/Public/SegPC/seg/train"
    annotations_path = "/jhcnas6/Cytology/Public/SegPC/seg/train.json"
    dataset = SegmentationDataset(
        img_dir=img_dir,
        annotations_path=annotations_path,
    )
    print(f"Number of samples in dataset: {len(dataset)}")
    
    # visualize a sample
    import matplotlib.pyplot as plt
    image, category_mask = dataset[10]
    total_categories = dataset.total_categories
    plt.figure(figsize=(12, 6))
    plt.subplot(1, 3, 1)
    plt.imshow(image)
    plt.title("Image")
    # mask
    
    plt.subplot(1, 3, 2)
    print(category_mask.shape)
    plt.imshow(category_mask[0], cmap='gray', alpha=0.5)
    plt.title(f"Category 1 Mask")
    
    plt.subplot(1, 3, 3)
    plt.imshow(category_mask[1], cmap='gray', alpha=0.5)
    plt.title(f"Category 2 Mask")
    plt.savefig("sample_visualization.png")