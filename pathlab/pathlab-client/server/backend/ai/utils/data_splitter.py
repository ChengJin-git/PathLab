import json
import os
import random
from typing import Dict, List, Optional

import numpy as np
from sklearn.model_selection import StratifiedShuffleSplit, StratifiedKFold


def segmentation_data_splitter(
    annotations_full_path: str,
    train_ratio: float = 0.7,
    val_ratio: float = 0.1,
    test_ratio: float = 0.2,
    debug: bool = False,
):
    """
    Split Segmentation format annotations into train/val/test splits.

    Args:
        annotations_full_path: Path to the Segmentation format annotation file
        train_ratio: Ratio for training set (default: 0.7)
        val_ratio: Ratio for validation set (default: 0.1)
        test_ratio: Ratio for test set (default: 0.2)

    Returns:
        Tuple of (train_annotations, val_annotations, test_annotations) paths
    """
    # Validate ratios sum to 1.0
    total_ratio = train_ratio + val_ratio + test_ratio
    if not abs(total_ratio - 1.0) < 1e-6:
        raise ValueError(f"Ratios must sum to 1.0, got {total_ratio}")
    
    # Read the full annotation file
    with open(annotations_full_path, 'r') as f:
        full_data = json.load(f)
    
    # Get metadata and categories
    info = full_data.get("info", {})
    licenses = full_data.get("licenses", [])
    categories = full_data.get("categories", {})
    
    images = full_data.get("images", [])
    annotations = full_data.get("annotations", [])
    
    # Build a mapping of image_id -> list of category_ids
    image_to_categories = {}
    for img in images:
        image_to_categories[img["id"]] = set()
    
    for ann in annotations:
        image_to_categories[ann["image_id"]].add(ann["category_id"])
    
    # Group images by their primary category (the first category in the image)
    category_to_images = {}
    for img in images:
        img_id = img["id"]
        if image_to_categories[img_id]:
            # Use the first category as the primary category for grouping
            primary_category = min(image_to_categories[img_id])
            if primary_category not in category_to_images:
                category_to_images[primary_category] = []
            category_to_images[primary_category].append(img_id)
    
    # Split images by category to maintain class balance
    train_ids = set()
    val_ids = set()
    test_ids = set()
    
    for category_id, image_ids in category_to_images.items():
        # Shuffle images within each category
        shuffled_ids = image_ids.copy()
        random.shuffle(shuffled_ids)
        
        # Calculate split indices for this category
        total = len(shuffled_ids)
        train_count = int(total * train_ratio)
        val_count = int(total * val_ratio)
        
        # Assign to splits
        train_ids.update(shuffled_ids[:train_count])
        val_ids.update(shuffled_ids[train_count:train_count + val_count])
        test_ids.update(shuffled_ids[train_count + val_count:])
    
    # Split images and annotations
    train_images = [img for img in images if img["id"] in train_ids]
    val_images = [img for img in images if img["id"] in val_ids]
    test_images = [img for img in images if img["id"] in test_ids]
    
    train_annotations = [ann for ann in annotations if ann["image_id"] in train_ids]
    val_annotations = [ann for ann in annotations if ann["image_id"] in val_ids]
    test_annotations = [ann for ann in annotations if ann["image_id"] in test_ids]
    
    # Create split annotation structures
    def create_split_data(images_list, annotations_list):
        return {
            "info": info,
            "licenses": licenses,
            "images": images_list,
            "annotations": annotations_list,
            "categories": categories
        }
    
    train_data = create_split_data(train_images, train_annotations)
    val_data = create_split_data(val_images, val_annotations)
    test_data = create_split_data(test_images, test_annotations)
    
    # Save split annotations to files
    base_dir = os.path.dirname(annotations_full_path)
    base_name = os.path.splitext(os.path.basename(annotations_full_path))[0]
    
    train_path = os.path.join(base_dir, f"{base_name}_train.json")
    val_path = os.path.join(base_dir, f"{base_name}_val.json")
    test_path = os.path.join(base_dir, f"{base_name}_test.json")
    
    with open(train_path, 'w') as f:
        json.dump(train_data, f, indent=2)
    with open(val_path, 'w') as f:
        json.dump(val_data, f, indent=2)
    with open(test_path, 'w') as f:
        json.dump(test_data, f, indent=2)
    
    if debug:
        # Print statistics
        print(f"Split annotation files created (with category balance):")
        print(f"  Train: {train_path} ({len(train_images)} images, {len(train_annotations)} annotations)")
        print(f"  Val:   {val_path} ({len(val_images)} images, {len(val_annotations)} annotations)")
        print(f"  Test:  {test_path} ({len(test_images)} images, {len(test_annotations)} annotations)")
        
        # Print category distribution
        for split_name, ids in [("Train", train_ids), ("Val", val_ids), ("Test", test_ids)]:
            category_dist = {}
            for img_id in ids:
                cats = image_to_categories[img_id]
                for cat in cats:
                    category_dist[cat] = category_dist.get(cat, 0) + 1
            print(f"  {split_name} category distribution: {dict(sorted(category_dist.items()))}")
        
    return train_path, val_path, test_path


def get_stratified_random_splits(
    items: List[str],
    labels: Dict[str, str],
    train_ratio: float = 0.7,
    val_ratio: float = 0.1,
    test_ratio: float = 0.2,
    seed: int = 42,
) -> Dict[str, str]:
    """
    Stratified random split items into train/val/test sets.
    Ensures each class is proportionally represented in all splits.

    Uses sklearn's StratifiedShuffleSplit for proper stratification.

    Args:
        items: List of item IDs (e.g., WSI IDs)
        labels: Dict mapping item_id -> label (class)
        train_ratio: Ratio for training set (default: 0.7)
        val_ratio: Ratio for validation set (default: 0.1)
        test_ratio: Ratio for test set (default: 0.2)
        seed: Random seed for reproducibility

    Returns:
        Dict mapping item_id -> split_label ('train', 'val', 'test')
    """
    if not items:
        return {}

    # Filter items that have labels
    items_with_labels = [item for item in items if item in labels]
    if not items_with_labels:
        # Fallback to non-stratified if no labels
        return get_random_splits(items, train_ratio, val_ratio, test_ratio, seed)

    # Build arrays for sklearn
    X = np.array(items_with_labels)
    y = np.array([labels[item] for item in items_with_labels])

    splits = {}

    # Check if we have enough samples per class for stratification
    unique_classes, class_counts = np.unique(y, return_counts=True)
    min_class_count = class_counts.min()

    # Need at least 2 samples per class for train/test split, 3 for train/val/test
    if min_class_count < 3:
        # Fallback to non-stratified split for very small classes
        return get_random_splits(items, train_ratio, val_ratio, test_ratio, seed)

    # First split: separate test set
    test_size = test_ratio
    train_val_size = train_ratio + val_ratio

    sss1 = StratifiedShuffleSplit(n_splits=1, test_size=test_size, random_state=seed)
    train_val_idx, test_idx = next(sss1.split(X, y))

    # Second split: separate train and val from train_val
    X_train_val = X[train_val_idx]
    y_train_val = y[train_val_idx]

    # Relative val ratio within train_val
    relative_val_ratio = val_ratio / train_val_size

    sss2 = StratifiedShuffleSplit(n_splits=1, test_size=relative_val_ratio, random_state=seed)
    train_idx_in_tv, val_idx_in_tv = next(sss2.split(X_train_val, y_train_val))

    # Assign splits
    for idx in test_idx:
        splits[X[idx]] = "test"
    for idx in train_idx_in_tv:
        splits[X_train_val[idx]] = "train"
    for idx in val_idx_in_tv:
        splits[X_train_val[idx]] = "val"

    return splits


def get_stratified_k_fold_splits(
    items: List[str],
    labels: Dict[str, str],
    k: int = 5,
    seed: int = 42,
) -> Dict[str, str]:
    """
    Stratified K-Fold split - assigns fold indices while maintaining class balance.

    Uses sklearn's StratifiedKFold for proper stratification.

    Args:
        items: List of item IDs (e.g., WSI IDs)
        labels: Dict mapping item_id -> label (class)
        k: Number of folds (default: 5)
        seed: Random seed for reproducibility

    Returns:
        Dict mapping item_id -> 'fold_N' (e.g., 'fold_0', 'fold_1')
    """
    if not items:
        return {}

    # Filter items that have labels
    items_with_labels = [item for item in items if item in labels]
    if not items_with_labels:
        # Fallback to non-stratified if no labels
        return get_k_fold_splits(items, k, seed)

    # Build arrays for sklearn
    X = np.array(items_with_labels)
    y = np.array([labels[item] for item in items_with_labels])

    # Check if we have enough samples per class for k-fold
    unique_classes, class_counts = np.unique(y, return_counts=True)
    min_class_count = class_counts.min()

    # Need at least k samples per class for k-fold
    if min_class_count < k:
        # Reduce k to min_class_count, or fallback to non-stratified
        if min_class_count >= 2:
            k = min_class_count
        else:
            return get_k_fold_splits(items, k, seed)

    splits = {}
    skf = StratifiedKFold(n_splits=k, shuffle=True, random_state=seed)

    for fold_idx, (_, test_idx) in enumerate(skf.split(X, y)):
        for idx in test_idx:
            splits[X[idx]] = f"fold_{fold_idx}"

    return splits


def get_random_splits(
    items: list,
    train_ratio: float = 0.7,
    val_ratio: float = 0.1,
    test_ratio: float = 0.2,
    seed: int = 42,
) -> dict:
    """
    Non-stratified random split (fallback when labels not available).
    Returns a dict mapping item -> split_label ('train', 'val', 'test').
    """
    if not items:
        return {}

    random.seed(seed)
    shuffled = items.copy()
    random.shuffle(shuffled)

    total = len(shuffled)
    n_train = int(total * train_ratio)
    n_val = int(total * val_ratio)

    splits = {}
    for i, item in enumerate(shuffled):
        if i < n_train:
            splits[item] = "train"
        elif i < n_train + n_val:
            splits[item] = "val"
        else:
            splits[item] = "test"

    return splits


def get_k_fold_splits(
    items: list,
    k: int = 5,
    seed: int = 42,
) -> dict:
    """
    Non-stratified K-Fold split (fallback when labels not available).
    Returns a dict mapping item -> 'fold_N'.
    """
    if not items:
        return {}

    random.seed(seed)
    shuffled = items.copy()
    random.shuffle(shuffled)

    splits = {}
    for i, item in enumerate(shuffled):
        fold_idx = i % k
        splits[item] = f"fold_{fold_idx}"

    return splits


def split_case_dataset(
    wsi_ids: List[str],
    case_id_map: Dict[str, str],
    strategy: str = "random",
    labels: Optional[Dict[str, str]] = None,
    **kwargs
) -> Dict[str, str]:
    """
    Split a dataset at the case level, ensuring all slides from the same case
    are assigned to the same split. This prevents data leakage in case-level datasets.

    The function first groups WSI IDs by case_id, then splits at the case level,
    and finally propagates the split assignment to all slides in each case.

    Args:
        wsi_ids: List of WSI IDs to split
        case_id_map: Dict mapping wsi_id -> case_id
        strategy: 'random', 'k_fold', or 'manual'
        labels: Optional dict mapping case_id -> label for stratified splitting
                (Note: labels should be keyed by case_id, not wsi_id)
        **kwargs:
            - ratios (dict): {'train': 0.7, 'val': 0.1, 'test': 0.2} for random
            - n_splits (int): K for k_fold
            - manual_splits (dict): {wsi_id: split_label} for manual
            - seed (int): Random seed

    Returns:
        Dict mapping wsi_id -> split_label, where all slides in the same case
        have the same split_label
    """
    if not wsi_ids:
        return {}

    # For manual strategy, return as-is (user is responsible for case consistency)
    if strategy == "manual":
        return kwargs.get("manual_splits", {})

    # Group WSI IDs by case_id
    case_to_wsi: Dict[str, List[str]] = {}
    for wsi_id in wsi_ids:
        case_id = case_id_map.get(wsi_id, wsi_id)  # Fallback to wsi_id if no case_id
        if case_id not in case_to_wsi:
            case_to_wsi[case_id] = []
        case_to_wsi[case_id].append(wsi_id)

    # Get unique case IDs
    case_ids = list(case_to_wsi.keys())

    # Split at case level
    if strategy == "k_fold":
        k = kwargs.get("n_splits", 5)
        seed = kwargs.get("seed", 42)
        if labels:
            case_splits = get_stratified_k_fold_splits(case_ids, labels, k=k, seed=seed)
        else:
            case_splits = get_k_fold_splits(case_ids, k=k, seed=seed)
    else:  # random or default
        ratios = kwargs.get("ratios", {"train": 0.7, "val": 0.1, "test": 0.2})
        seed = kwargs.get("seed", 42)
        if labels:
            case_splits = get_stratified_random_splits(
                case_ids,
                labels,
                train_ratio=ratios.get("train", 0.7),
                val_ratio=ratios.get("val", 0.1),
                test_ratio=ratios.get("test", 0.2),
                seed=seed
            )
        else:
            case_splits = get_random_splits(
                case_ids,
                train_ratio=ratios.get("train", 0.7),
                val_ratio=ratios.get("val", 0.1),
                test_ratio=ratios.get("test", 0.2),
                seed=seed
            )

    # Propagate case-level splits to all slides in each case
    wsi_splits: Dict[str, str] = {}
    for case_id, wsi_list in case_to_wsi.items():
        split_label = case_splits.get(case_id, "train")
        for wsi_id in wsi_list:
            wsi_splits[wsi_id] = split_label

    return wsi_splits


def split_wsi_dataset(
    wsi_ids: list,
    strategy: str = "random",
    labels: Optional[Dict[str, str]] = None,
    **kwargs
) -> dict:
    """
    Main entry point for splitting a dataset of WSI IDs at the slide level.

    NOTE: For case-level datasets, use split_case_dataset() instead to ensure
    all slides from the same case are in the same split (prevents data leakage).

    Supports stratified splitting when labels are provided.

    Args:
        wsi_ids: List of WSI IDs
        strategy: 'random', 'k_fold', or 'manual'
        labels: Optional dict mapping wsi_id -> label for stratified splitting
        **kwargs:
            - ratios (dict): {'train': 0.7, 'val': 0.1, 'test': 0.2} for random
            - n_splits (int): K for k_fold
            - manual_splits (dict): {wsi_id: split_label} for manual
            - seed (int): Random seed

    Returns:
        dict: {wsi_id: split_label}
    """
    if not wsi_ids:
        return {}

    if strategy == "manual":
        # Return provided manual splits
        return kwargs.get("manual_splits", {})

    elif strategy == "k_fold":
        k = kwargs.get("n_splits", 5)
        seed = kwargs.get("seed", 42)
        if labels:
            return get_stratified_k_fold_splits(wsi_ids, labels, k=k, seed=seed)
        else:
            return get_k_fold_splits(wsi_ids, k=k, seed=seed)

    else:  # random or default
        ratios = kwargs.get("ratios", {"train": 0.7, "val": 0.1, "test": 0.2})
        seed = kwargs.get("seed", 42)
        if labels:
            return get_stratified_random_splits(
                wsi_ids,
                labels,
                train_ratio=ratios.get("train", 0.7),
                val_ratio=ratios.get("val", 0.1),
                test_ratio=ratios.get("test", 0.2),
                seed=seed
            )
        else:
            return get_random_splits(
                wsi_ids,
                train_ratio=ratios.get("train", 0.7),
                val_ratio=ratios.get("val", 0.1),
                test_ratio=ratios.get("test", 0.2),
                seed=seed
            )