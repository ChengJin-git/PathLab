import os
from typing import Callable, Optional
import numpy as np
from torch.utils.data import Dataset
from PIL import Image
import pandas as pd
import torchvision


def parser_csv_annotations(annotations_full_path: str, force_split = False,
                           train_ratio: float = 0.7,
                           val_ratio: float = 0.1,
                           ):
    
    df = pd.read_csv(annotations_full_path)
    image_items = {}
    categories = set()
    for _, row in df.iterrows():
        image_path = row['image_path']
        class_label = row['class']
        split = row.get('split', None)
        categories.add(class_label)
        image_items[image_path] = (class_label, split)
    
    # get the split if not provided (None), and split the data into train/val/test
    train_items = {}
    val_items = {}
    test_items = {}
    label_mapper = {label: idx for idx, label in enumerate(sorted(categories))}
    
    if force_split or (split is None):
        image_paths = list(image_items.keys())
        np.random.shuffle(image_paths)
        # iterate all classes and split them
        class_to_images = {}
        for image_path in image_paths:
            class_label, _ = image_items[image_path]
            if class_label not in class_to_images:
                class_to_images[class_label] = []
            class_to_images[class_label].append(image_path)

        for class_label, img_list in class_to_images.items():
            n_total = len(img_list)
            n_train = int(n_total * train_ratio)
            n_val = int(n_total * val_ratio)
            train_imgs = img_list[:n_train]
            val_imgs = img_list[n_train:n_train + n_val]
            test_imgs = img_list[n_train + n_val:]
            
            for img in train_imgs:
                train_items[img] = class_label
            for img in val_imgs:
                val_items[img] = class_label
            for img in test_imgs:
                test_items[img] = class_label
    else:
        for image_path, (class_label, split) in image_items.items():
            if split == 'train':
                train_items[image_path] = class_label
            elif split == 'val':
                val_items[image_path] = class_label
            elif split == 'test':
                test_items[image_path] = class_label
                
        # if val_items is empty, move 10% of train_items to val_items
        if len(val_items) == 0:
            n_val = int(len(train_items) * 0.1)
            train_image_paths = list(train_items.keys())
            np.random.shuffle(train_image_paths)
            val_image_paths = train_image_paths[:n_val]
            for img in val_image_paths:
                val_items[img] = train_items[img]
                del train_items[img]

    return train_items, val_items, test_items, label_mapper


class PatchDataset(Dataset):
    """
    A dataset class for image patch tasks.

    Args:
        img_dir: Directory containing image patches.
        annotations: Dict mapping relative image path to class label.
        label_mapper: Dict mapping class label to integer index.
        transform: Optional transform to be applied on a sample.
        extractor: Feature extractor transform (applied after transform).
        mode: 'train', 'val', or 'test'. Defaults to 'train'.
    """
    def __init__(
        self,
        img_dir: str,
        annotations: dict,
        label_mapper: dict,
        transform: Optional[Callable] = None,
        extractor: Optional[Callable] = None,
        mode: str = "train",
    ):
        assert mode in ['train', 'val', 'test'], "mode should be one of 'train', 'val', or 'test'"
        self.img_dir = img_dir
        self.mode = mode
        self.image_items = [
            {"image": os.path.join(self.img_dir, img_path), "category_id": label_mapper[class_label]}
            for img_path, class_label in annotations.items()
        ]

        self.label_mapper = label_mapper
        self.transform = transform
        self.extractor = extractor
        self.total_categories = len(label_mapper)
    
    def print_dataset_stats(self):
        reversed_label_mapper = {idx: label for label, idx in self.label_mapper.items()}
        category_counts = {idx: 0 for idx, _ in reversed_label_mapper.items()}
        for item in self.image_items:
            category_id = item["category_id"]
            category_counts[category_id] += 1
        
        category_counts = {'{} (class {})'.format(reversed_label_mapper[label], label): count for label, count in category_counts.items()}
        return category_counts
        
    def load_image(self, image_path: str):
        img = Image.open(image_path).convert("RGB")
        return img
    
    def set_extractor(self, extractor: Callable):
        self.extractor = extractor

    def __getitem__(self, idx: int):
        item = self.image_items[idx]
        image_path = item["image"]
        image = self.load_image(image_path)
        category_id = item["category_id"]
        if self.transform:
            image = self.transform(image)
        if self.extractor:
            image = self.extractor(image)

        return image, category_id

    def __len__(self) -> int:
        return len(self.image_items)


class PatchDatasetFromDB(Dataset):
    """
    A dataset class for patch classification using absolute paths from database.

    Unlike PatchDataset which uses relative paths with img_dir,
    this class uses absolute paths directly from the database (wsi_path).

    Args:
        annotations: Dict mapping absolute image path to class label.
        label_mapper: Dict mapping class label to integer index.
        transform: Optional transform to be applied on a sample.
        extractor: Feature extractor transform (applied after transform).
        mode: 'train', 'val', or 'test'. Defaults to 'train'.
    """
    def __init__(
        self,
        annotations: dict,
        label_mapper: dict,
        transform: Optional[Callable] = None,
        extractor: Optional[Callable] = None,
        mode: str = "train",
    ):
        assert mode in ['train', 'val', 'test'], "mode should be one of 'train', 'val', or 'test'"
        self.mode = mode
        # annotations is {absolute_path: class_label}
        self.image_items = [
            {"image": img_path, "category_id": label_mapper[class_label]}
            for img_path, class_label in annotations.items()
        ]

        self.label_mapper = label_mapper
        self.transform = transform
        self.extractor = extractor
        self.total_categories = len(label_mapper)

    def print_dataset_stats(self):
        reversed_label_mapper = {idx: label for label, idx in self.label_mapper.items()}
        category_counts = {idx: 0 for idx in reversed_label_mapper.keys()}
        for item in self.image_items:
            category_id = item["category_id"]
            category_counts[category_id] += 1

        category_counts = {
            '{} (class {})'.format(reversed_label_mapper[label], label): count
            for label, count in category_counts.items()
        }
        return category_counts

    def load_image(self, image_path: str):
        img = Image.open(image_path).convert("RGB")
        return img

    def set_extractor(self, extractor: Callable):
        self.extractor = extractor

    def __getitem__(self, idx: int):
        item = self.image_items[idx]
        image_path = item["image"]
        image = self.load_image(image_path)
        category_id = item["category_id"]
        if self.transform:
            image = self.transform(image)
        if self.extractor:
            image = self.extractor(image)

        return image, category_id

    def __len__(self) -> int:
        return len(self.image_items)


def build_datasets(cfg: dict):
    """
    Build PatchDataset from config.
    Args:
        cfg: Configuration dictionary containing dataset parameters.
    """
    image_root = cfg['dataset']['image_root']
    annotations_path = cfg['dataset']['annotation_path']
    train_ratio = cfg['dataset'].get('train', 0.7)
    val_ratio = cfg['dataset'].get('val', 0.1)
    force_split = cfg['dataset'].get('force_split', False)
    
    transforms = []
    if 'random_resized_crop' in cfg['transforms']['train']:
        transforms.append(torchvision.transforms.RandomResizedCrop(**cfg['transforms']['train']['random_resized_crop']))
    if 'random_horizontal_flip' in cfg['transforms']['train']:
        transforms.append(torchvision.transforms.RandomHorizontalFlip(**cfg['transforms']['train']['random_horizontal_flip']))
    if 'random_vertical_flip' in cfg['transforms']['train']:
        transforms.append(torchvision.transforms.RandomVerticalFlip(**cfg['transforms']['train']['random_vertical_flip']))
    if 'color_jitter' in cfg['transforms']['train']:
        transforms.append(torchvision.transforms.ColorJitter(**cfg['transforms']['train']['color_jitter']))
    
    transforms = torchvision.transforms.Compose(transforms)
    
    train_items, val_items, test_items, label_mapper = parser_csv_annotations(
        annotations_full_path=annotations_path,
        force_split=force_split,
        train_ratio=train_ratio,
        val_ratio=val_ratio,
    )
    train_dataset = PatchDataset(
        img_dir=image_root,
        annotations=train_items,
        label_mapper=label_mapper,
        transform=transforms,
        mode='train',
    )
    val_dataset = PatchDataset(
        img_dir=image_root,
        annotations=val_items,
        label_mapper=label_mapper,
        mode='val',
    )
    test_dataset = PatchDataset(
        img_dir=image_root,
        annotations=test_items,
        label_mapper=label_mapper,
        mode='test',
    )
    return train_dataset, val_dataset, test_dataset


if __name__ == "__main__":
    import omegaconf
    import json
    cfg_path = '/storage/jmabq/PathLab/pathlab/pathlab-client/server/backend/ai/tasks/patch_classification/default_config.json'
    cfg = omegaconf.OmegaConf.load(cfg_path)
    cfg = omegaconf.OmegaConf.to_container(cfg, resolve=True)
    train_dataset, val_dataset, test_dataset = build_datasets(cfg)
    print(f"Number of train samples in dataset: {len(train_dataset)}")
    print(f"Number of validation samples in dataset: {len(val_dataset)}")
    print(f"Number of test samples in dataset: {len(test_dataset)}")
    
    # # visualize a sample
    # import matplotlib.pyplot as plt
    # image, category_mask = train_dataset[10]
    # total_categories = train_dataset.total_categories
    # plt.figure(figsize=(12, 6))
    # plt.subplot(1, 1, 1)
    # plt.imshow(image)
    # plt.title("Image")
    # plt.savefig("sample_visualization.png")