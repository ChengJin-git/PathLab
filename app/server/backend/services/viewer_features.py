"""Retrieval over explicitly registered feature spaces, independent of model names."""

import hashlib
import json
import threading
from pathlib import Path
from collections import OrderedDict
import numpy as np
from backend.common.config import Config
from backend.ai.feature_contracts import FeatureContract
from . import viewer_text_encoders


class MissingCapability(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def revision(path):
    stat = Path(path).stat()
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def record_feature_contract(path, contract, coords_path=None):
    """Called by a feature producer with its actual model and preprocessing contract."""
    if not contract:
        return
    contract = FeatureContract.model_validate(contract)
    path = Path(path)
    if coords_path is None:
        # This is the standard cache's storage layout, not a model inference rule.
        coords_path = (
            Config.get_uploads_dir()
            / "coordinates"
            / path.parent.name
            / f"{path.stem}_coords.h5"
        )
    coords_path = Path(coords_path)
    if not coords_path.is_file():
        return
    destination = path.with_suffix(".feature.json")
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "version": 1,
                "contract": contract.model_dump(),
                "feature_revision": revision(path),
                "coordinates_path": str(coords_path),
                "coordinates_revision": revision(coords_path),
            },
            ensure_ascii=False,
        )
    )
    temporary.replace(destination)


def available_features(slide):
    root = Config.get_uploads_dir()
    paths = []
    features_root = root / "features"
    if features_root.is_dir():
        for model_dir in features_root.iterdir():
            if not model_dir.is_dir() or model_dir.name.startswith("."):
                continue
            for parameters in model_dir.iterdir():
                if not parameters.is_dir():
                    continue
                path = parameters / f"{slide.wsi_id}.pt"
                if path.with_suffix(".feature.json").is_file():
                    paths.append(path)
    for item in (
        (slide.associated_files or {}).get("autoresearch_features", {}).values()
    ):
        if item.get("feature_path"):
            paths.append(Path(item["feature_path"]))
    for item in (slide.associated_files or {}).get("viewer_features", []):
        if item.get("feature_path"):
            paths.append(Path(item["feature_path"]))
    output = []
    for path in dict.fromkeys(paths):
        try:
            manifest = json.loads(path.with_suffix(".feature.json").read_text())
            if manifest.get("version") != 1:
                continue
            contract = FeatureContract.model_validate(manifest["contract"])
            coords = Path(manifest["coordinates_path"])
            if not path.resolve().is_relative_to(
                root.resolve()
            ) or not coords.resolve().is_relative_to(root.resolve()):
                continue
            if manifest["feature_revision"] != revision(path) or manifest[
                "coordinates_revision"
            ] != revision(coords):
                continue
        except (ValueError, KeyError, OSError):
            continue
        encoder = contract.text_encoder
        aligned = bool(
            encoder
            and encoder.aligned_space == contract.embedding_space
            and viewer_text_encoders.available(encoder)
        )
        identity = hashlib.sha256(str(path).encode()).hexdigest()[:24]
        output.append(
            {
                "id": identity,
                "model_id": contract.model_id,
                "preprocessing_id": contract.preprocessing,
                "image_similarity": True,
                "text_similarity": aligned,
                "reason": None if aligned else "text_alignment_unavailable",
                "revision": manifest["feature_revision"]
                + ":"
                + manifest["coordinates_revision"],
                "path": str(path),
                "coords_path": str(coords),
                "contract": contract.model_dump(),
            }
        )
    return output


_cache = OrderedDict()
_lock = threading.RLock()
MAX_BYTES = 256 * 1024 * 1024


def load_features(item):
    key = item["id"], item["revision"], json.dumps(item["contract"], sort_keys=True)
    if item["revision"] != revision(item["path"]) + ":" + revision(item["coords_path"]):
        raise MissingCapability("feature_coordinates_mismatch")
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    import torch, h5py

    path = Path(item["path"])
    if path.stat().st_size > 2 * 1024 * 1024 * 1024:
        raise MissingCapability("feature_set_too_large")
    if path.suffix == ".npy":
        values = np.load(path, allow_pickle=False, mmap_mode="r")
    else:
        try:
            values = torch.load(path, map_location="cpu", weights_only=True, mmap=True)
        except RuntimeError:
            if path.stat().st_size > MAX_BYTES:
                raise MissingCapability("feature_set_too_large")
            values = torch.load(path, map_location="cpu", weights_only=True)
        if isinstance(values, dict):
            values = values.get("features")
    values = np.asarray(values)
    if values.dtype.kind not in "fiu":
        raise MissingCapability("feature_coordinates_mismatch")
    with h5py.File(item["coords_path"], "r") as file:
        if file["coords"].size * 8 > 32 * 1024 * 1024:
            raise MissingCapability("feature_set_too_large")
        coords = np.asarray(file["coords"], dtype=np.float64)
        attrs = dict(file["coords"].attrs)
    if (
        values.ndim != 2
        or coords.ndim != 2
        or coords.shape[1] != 2
        or len(coords) != len(values)
        or len(values) == 0
        or not np.isfinite(coords).all()
    ):
        raise MissingCapability("feature_coordinates_mismatch")
    if values.shape[1] != item["contract"]["dimensions"]:
        raise MissingCapability("feature_coordinates_mismatch")
    downsample = attrs.get("level_downsample", attrs.get("downsample", 1))
    if isinstance(downsample, (list, tuple, np.ndarray)):
        downsample = float(downsample[0])
    if "patch_size" not in attrs and "read_size" not in attrs:
        raise MissingCapability("feature_coordinates_mismatch")
    size = float(attrs.get("read_size", attrs.get("patch_size"))) * float(downsample)
    if not np.isfinite(size) or size <= 0:
        raise MissingCapability("feature_coordinates_mismatch")
    result = values, coords, size
    if values.nbytes + coords.nbytes <= MAX_BYTES:
        with _lock:
            _cache[key] = result
            while sum(v[0].nbytes + v[1].nbytes for v in _cache.values()) > MAX_BYTES:
                _cache.popitem(last=False)
    return result


def validate_registration(path, coords, contract, slide):
    """Validate external producers before a capability becomes discoverable."""
    item = {
        "id": hashlib.sha256(str(path).encode()).hexdigest()[:24],
        "revision": revision(path) + ":" + revision(coords),
        "path": str(path),
        "coords_path": str(coords),
        "contract": contract,
    }
    values, points, size = load_features(item)
    for start in range(0, len(values), 2048):
        if not np.isfinite(values[start : start + 2048]).all():
            raise MissingCapability("feature_coordinates_mismatch")
    if (
        (points < 0).any()
        or (slide.width and (points[:, 0] + size > slide.width + 0.01).any())
        or (slide.height and (points[:, 1] + size > slide.height + 0.01).any())
    ):
        raise MissingCapability("feature_coordinates_mismatch")
    record_feature_contract(path, contract, coords)


def search(item, *, query="", box=None, negative_boxes=(), limit=5):
    from threadpoolctl import threadpool_limits

    with threadpool_limits(limits=2):
        return _search(
            item, query=query, box=box, negative_boxes=negative_boxes, limit=limit
        )


def _search(item, *, query="", box=None, negative_boxes=(), limit=5):
    values, coords, size = load_features(item)
    if query:
        if values.nbytes > MAX_BYTES:
            raise MissingCapability("feature_set_too_large")
        if not item["text_similarity"]:
            raise MissingCapability("text_alignment_unavailable")
        contract = FeatureContract.model_validate(item["contract"])
        try:
            vector, values = viewer_text_encoders.encode(
                contract.text_encoder, query, values
            )
        except (ValueError, OSError, ImportError, RuntimeError):
            raise MissingCapability("text_alignment_unavailable") from None
    else:
        if not box:
            raise MissingCapability("select_example")
        x, y, width, height = box
        centers = coords + size / 2
        selected = (
            (coords[:, 0] < x + width)
            & (coords[:, 0] + size > x)
            & (coords[:, 1] < y + height)
            & (coords[:, 1] + size > y)
        )
        if not selected.any():
            raise MissingCapability("no_features_in_selection")

        def mean_for(mask):
            total = np.zeros(values.shape[1], dtype=np.float64)
            count = 0
            for start in range(0, len(values), 2048):
                batch = np.asarray(
                    values[start : start + 2048][mask[start : start + 2048]],
                    dtype=np.float32,
                )
                if len(batch):
                    if not np.isfinite(batch).all():
                        raise MissingCapability("feature_coordinates_mismatch")
                    total += (
                        batch
                        / np.maximum(np.linalg.norm(batch, axis=1, keepdims=True), 1e-8)
                    ).sum(axis=0)
                    count += len(batch)
            return total / max(count, 1)

        vector = mean_for(selected)
        for nx, ny, nw, nh in negative_boxes:
            negative = (
                (centers[:, 0] >= nx)
                & (centers[:, 0] <= nx + nw)
                & (centers[:, 1] >= ny)
                & (centers[:, 1] <= ny + nh)
            )
            if negative.any():
                vector -= mean_for(negative)
    if values.shape[1] != len(vector):
        raise MissingCapability("feature_coordinates_mismatch")
    unit = vector / max(np.linalg.norm(vector), 1e-8)
    scores = np.empty(len(values), dtype=np.float32)
    for start in range(0, len(values), 2048):
        batch = np.asarray(values[start : start + 2048], dtype=np.float32)
        if not np.isfinite(batch).all():
            raise MissingCapability("feature_coordinates_mismatch")
        scores[start : start + len(batch)] = (batch @ unit) / np.maximum(
            np.linalg.norm(batch, axis=1), 1e-8
        )
    regions = []
    for index in np.argsort(-scores):
        x, y = map(float, coords[index])
        if any(abs(r["x"] - x) < size and abs(r["y"] - y) < size for r in regions):
            continue
        regions.append(
            {
                "id": f"feature-{index}",
                "type": "rect",
                "x": x,
                "y": y,
                "width": size,
                "height": size,
                "score": float(scores[index]),
            }
        )
        if len(regions) >= limit:
            break
    return regions
