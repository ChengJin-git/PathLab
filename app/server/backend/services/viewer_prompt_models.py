"""Optional installed prompt models. Config contains local assets, never download URLs."""

from functools import lru_cache
from pathlib import Path
import hashlib
import threading
import json
import numpy as np
from backend.common.config import Config


def models():
    root = Config.get_uploads_dir() / "viewer_models"
    values = []
    if root.is_dir():
        for path in root.glob("*/model.json"):
            try:
                item = json.loads(path.read_text())
                item["encoder"] = str(path.parent / item["encoder"])
                item["decoder"] = str(path.parent / item["decoder"])
                values.append(item)
            except (ValueError, KeyError, OSError):
                continue
    return [
        item
        for item in values
        if isinstance(item, dict)
        and item.get("id")
        and item.get("family") == "efficient_sam"
        and Path(item.get("encoder", "")).is_file()
        and Path(item.get("decoder", "")).is_file()
    ]


@lru_cache(maxsize=2)
def sessions(encoder, decoder, revision):
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    return (
        ort.InferenceSession(
            encoder, sess_options=options, providers=["CPUExecutionProvider"]
        ),
        ort.InferenceSession(
            decoder, sess_options=options, providers=["CPUExecutionProvider"]
        ),
    )


_embedding = None
_model_lock = threading.Lock()


def segment(identity, image, points):
    with _model_lock:
        return _segment(identity, image, points)


def _segment(identity, image, points):
    import cv2

    global _embedding
    item = next((item for item in models() if item["id"] == identity), None)
    if item is None:
        raise ValueError("prompt_model_unavailable")
    revision = f"{Path(item['encoder']).stat().st_mtime_ns}:{Path(item['decoder']).stat().st_mtime_ns}"
    encoder, decoder = sessions(item["encoder"], item["decoder"], revision)
    key = identity, revision, hashlib.sha256(image.tobytes()).hexdigest()
    h, w = image.shape[:2]
    if _embedding is None or _embedding[0] != key:
        tensor = image.astype("float32").transpose(2, 0, 1)[None] / 255
        _embedding = key, encoder.run(None, {encoder.get_inputs()[0].name: tensor})[0]
    if not points:
        points = [(w * 0.1, h * 0.1, 2), (w * 0.9, h * 0.9, 3)]
    coordinates = np.array([[[x, y] for x, y, _ in points]], dtype="float32")[None]
    labels = np.array([[[label for _, _, label in points]]], dtype="float32")
    values = {
        "image_embeddings": _embedding[1],
        "batched_point_coords": coordinates,
        "batched_point_labels": labels,
        "orig_im_size": np.array([h, w], dtype="int64"),
    }
    names = {input.name for input in decoder.get_inputs()}
    if not names <= values.keys():
        raise ValueError("prompt_model_contract_mismatch")
    feeds = {
        input.name: values[input.name].astype(
            "int64" if input.type == "tensor(int64)" else "float32"
        )
        for input in decoder.get_inputs()
    }
    outputs = decoder.run(None, feeds)
    masks = outputs[0].reshape(-1, *outputs[0].shape[-2:])
    index = (
        int(np.argmax(outputs[1]))
        if len(outputs) > 1 and outputs[1].size == len(masks)
        else 0
    )
    return cv2.resize(masks[index], (w, h)) > 0
