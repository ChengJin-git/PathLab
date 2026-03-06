import json
import os
import random
from typing import Any, Dict, List, Optional, Sequence, Set

import numpy as np
from sklearn.model_selection import StratifiedShuffleSplit, StratifiedKFold


MULTILABEL_NEGATIVE_TAG = "__negative__"


def _normalize_coco_categories(categories: Any) -> List[dict]:
    if isinstance(categories, list):
        normalized: List[dict] = []
        for item in categories:
            if not isinstance(item, dict):
                continue
            try:
                category_id = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            normalized.append({"id": category_id, "name": str(item.get("name") or category_id)})
        return normalized

    if isinstance(categories, dict):
        normalized = []
        for key, value in categories.items():
            try:
                category_id = int(key)
            except (TypeError, ValueError):
                continue
            normalized.append({"id": category_id, "name": str(value)})
        return sorted(normalized, key=lambda item: item["id"])

    return []


def _calculate_target_sizes(total_items: int, ratios: Dict[str, float]) -> Dict[str, int]:
    split_names = [name for name, ratio in ratios.items() if ratio > 0]
    if total_items <= 0 or not split_names:
        return {name: 0 for name in ratios}

    if total_items >= len(split_names):
        targets = {name: 1 for name in split_names}
        remaining = total_items - len(split_names)
    else:
        targets = {name: 0 for name in split_names}
        remaining = total_items

    total_ratio = sum(ratios[name] for name in split_names)
    raw_counts = {
        name: (remaining * ratios[name] / total_ratio) if total_ratio > 0 else 0.0
        for name in split_names
    }
    extra_counts = {name: int(np.floor(raw_counts[name])) for name in split_names}
    for name, count in extra_counts.items():
        targets[name] += count

    assigned = sum(targets.values())
    remainder = total_items - assigned
    order = sorted(
        split_names,
        key=lambda name: (raw_counts[name] - extra_counts[name], ratios[name]),
        reverse=True,
    )
    for idx in range(remainder):
        targets[order[idx % len(order)]] += 1

    return {name: targets.get(name, 0) for name in ratios}


def _coerce_multilabel_sets(
    items: Sequence[Any],
    multilabels: Optional[Dict[Any, Sequence[str] | Set[str]]],
) -> Dict[Any, Set[str]]:
    coerced: Dict[Any, Set[str]] = {}
    for item in items:
        raw_labels = multilabels.get(item, set()) if multilabels else set()
        label_set = {str(label) for label in raw_labels if label not in (None, "")}
        coerced[item] = label_set if label_set else {MULTILABEL_NEGATIVE_TAG}
    return coerced


def _greedy_multilabel_assignment(
    items: Sequence[Any],
    multilabels: Optional[Dict[Any, Sequence[str] | Set[str]]],
    targets: Dict[str, int],
    seed: int,
) -> Dict[Any, str]:
    if not items:
        return {}

    rng = random.Random(seed)
    label_sets = _coerce_multilabel_sets(items, multilabels)
    label_totals: Dict[str, int] = {}
    for labels in label_sets.values():
        for label in labels:
            label_totals[label] = label_totals.get(label, 0) + 1

    target_label_counts = {
        split_name: {
            label: label_totals[label] * (targets[split_name] / len(items)) if len(items) > 0 else 0.0
            for label in label_totals
        }
        for split_name in targets
    }

    size_counts = {split_name: 0 for split_name in targets}
    label_counts = {split_name: {label: 0 for label in label_totals} for split_name in targets}

    ordered_items = list(items)
    rng.shuffle(ordered_items)
    ordered_items.sort(
        key=lambda item: (
            -sum(1.0 / max(label_totals[label], 1) for label in label_sets[item]),
            -len(label_sets[item]),
        )
    )

    assignments: Dict[Any, str] = {}
    for item in ordered_items:
        labels = label_sets[item]
        best_split = None
        best_score = None

        for split_name, target_size in targets.items():
            size_need = target_size - size_counts[split_name]
            if target_size == 0:
                size_penalty = -1e9
            elif size_need <= 0:
                size_penalty = size_need * 1000.0
            else:
                size_penalty = size_need * 10.0

            label_need = sum(
                max(target_label_counts[split_name][label] - label_counts[split_name][label], 0.0)
                for label in labels
            )
            novelty_bonus = sum(
                1.0 / max(label_totals[label], 1)
                for label in labels
                if label_counts[split_name][label] == 0
            )
            score = label_need * 100.0 + novelty_bonus * 10.0 + size_penalty

            tie_breaker = rng.random()
            candidate = (score, size_need, tie_breaker)
            if best_score is None or candidate > best_score:
                best_score = candidate
                best_split = split_name

        chosen_split = best_split or next(iter(targets))
        assignments[item] = chosen_split
        size_counts[chosen_split] += 1
        for label in labels:
            label_counts[chosen_split][label] += 1

    return assignments


def get_multilabel_random_splits(
    items: Sequence[Any],
    multilabels: Optional[Dict[Any, Sequence[str] | Set[str]]],
    train_ratio: float = 0.7,
    val_ratio: float = 0.1,
    test_ratio: float = 0.2,
    seed: int = 42,
) -> Dict[Any, str]:
    targets = _calculate_target_sizes(
        len(items),
        {"train": train_ratio, "val": val_ratio, "test": test_ratio},
    )
    return _greedy_multilabel_assignment(items, multilabels, targets, seed)


def get_multilabel_k_fold_splits(
    items: Sequence[Any],
    multilabels: Optional[Dict[Any, Sequence[str] | Set[str]]],
    k: int = 5,
    seed: int = 42,
) -> Dict[Any, str]:
    if k <= 1:
        return {item: "fold_0" for item in items}

    targets = _calculate_target_sizes(
        len(items),
        {f"fold_{idx}": 1.0 for idx in range(k)},
    )
    return _greedy_multilabel_assignment(items, multilabels, targets, seed)


def segmentation_data_splitter(
    annotations_full_path: str,
    train_ratio: float = 0.7,
    val_ratio: float = 0.1,
    test_ratio: float = 0.2,
    seed: int = 42,
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
    categories = _normalize_coco_categories(full_data.get("categories", []))
    
    images = full_data.get("images", [])
    annotations = full_data.get("annotations", [])
    
    category_lookup = {cat["id"]: cat["name"] for cat in categories}

    # Build a mapping of image_id -> set of category names
    image_to_categories = {}
    for img in images:
        image_to_categories[img["id"]] = set()
    
    for ann in annotations:
        image_id = ann.get("image_id")
        if image_id not in image_to_categories:
            continue
        category_id = ann.get("category_id")
        try:
            category_id = int(category_id)
        except (TypeError, ValueError):
            pass
        image_to_categories[image_id].add(category_lookup.get(category_id, str(category_id)))

    split_map = get_multilabel_random_splits(
        [img["id"] for img in images],
        image_to_categories,
        train_ratio=train_ratio,
        val_ratio=val_ratio,
        test_ratio=test_ratio,
        seed=seed,
    )

    train_ids = {img_id for img_id, split in split_map.items() if split == "train"}
    val_ids = {img_id for img_id, split in split_map.items() if split == "val"}
    test_ids = {img_id for img_id, split in split_map.items() if split == "test"}
    
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

    case_multilabels_raw = kwargs.get("multilabels")
    case_multilabels: Optional[Dict[str, Set[str]]] = None
    if case_multilabels_raw:
        case_multilabels = {}
        for case_id, case_wsi_ids in case_to_wsi.items():
            aggregated: Set[str] = set()
            for wsi_id in case_wsi_ids:
                aggregated.update(case_multilabels_raw.get(wsi_id, set()))
            case_multilabels[case_id] = aggregated

    # Split at case level
    if strategy == "k_fold":
        k = kwargs.get("n_splits", 5)
        seed = kwargs.get("seed", 42)
        if case_multilabels:
            case_splits = get_multilabel_k_fold_splits(case_ids, case_multilabels, k=k, seed=seed)
        elif labels:
            case_splits = get_stratified_k_fold_splits(case_ids, labels, k=k, seed=seed)
        else:
            case_splits = get_k_fold_splits(case_ids, k=k, seed=seed)
    else:  # random or default
        ratios = kwargs.get("ratios", {"train": 0.7, "val": 0.1, "test": 0.2})
        seed = kwargs.get("seed", 42)
        if case_multilabels:
            case_splits = get_multilabel_random_splits(
                case_ids,
                case_multilabels,
                train_ratio=ratios.get("train", 0.7),
                val_ratio=ratios.get("val", 0.1),
                test_ratio=ratios.get("test", 0.2),
                seed=seed,
            )
        elif labels:
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
    multilabels: Optional[Dict[str, Sequence[str] | Set[str]]] = None,
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
        if multilabels:
            return get_multilabel_k_fold_splits(wsi_ids, multilabels, k=k, seed=seed)
        if labels:
            return get_stratified_k_fold_splits(wsi_ids, labels, k=k, seed=seed)
        else:
            return get_k_fold_splits(wsi_ids, k=k, seed=seed)

    else:  # random or default
        ratios = kwargs.get("ratios", {"train": 0.7, "val": 0.1, "test": 0.2})
        seed = kwargs.get("seed", 42)
        if multilabels:
            return get_multilabel_random_splits(
                wsi_ids,
                multilabels,
                train_ratio=ratios.get("train", 0.7),
                val_ratio=ratios.get("val", 0.1),
                test_ratio=ratios.get("test", 0.2),
                seed=seed,
            )
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