import json
import os
from typing import Callable, Optional
import numpy as np
from torch.utils.data import Dataset
from PIL import Image
import cv2

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
        
    def load_image(self, image_path: str):
        img = Image.open(image_path).convert("RGB")
        return img
    
    def set_transform(self, transform: Callable):
        self.transform = transform

    def generate_label_masks(self, image_size, polygons_list, category_ids):
        # the mask should be H*W, where each pixel value is the category id +1 
        width, height = image_size
        category_mask = np.zeros((1, height, width), dtype=np.uint8)
        for polygon, category_id in zip(polygons_list, category_ids):
            polygon = np.array(polygon, dtype=np.int32).reshape((-1, 2))
            # cv2.fillPoly expects a single 2D array (H, W)
            cv2.fillPoly(category_mask[0], [polygon], category_id+1)
        category_mask = np.transpose(category_mask, (1, 2, 0))  # H x W x C
        return category_mask

    def __getitem__(self, idx: int):
        item = self.image_items[idx]
        image_path = item["image"]
        image = self.load_image(image_path)
        polygons_list = item["segmentation"]
        category_ids = item["category_id"]
        # Generate binary masks for each instance using polygon coordinates
        category_mask = self.generate_label_masks(image.size, polygons_list, category_ids)

        if self.transform:
            image, category_mask = self.transform(image, category_mask)

        return image, category_mask

    def __len__(self) -> int:
        return len(self.image_items)



if __name__ == "__main__":
    # Example usage
    img_dir = "/storage/jmabq/data/DSCC"
    annotations_path = "/storage/jmabq/data/DSCC/seg/train.json"
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
    plt.subplot(1, 2, 1)
    plt.imshow(image)
    plt.title("Image")
    # mask
    
    plt.subplot(1, 2, 2)
    plt.imshow(category_mask[..., 0], cmap='gray', alpha=0.5)
    plt.title(f"Category 1 Mask")
    plt.savefig("sample_visualization.png")