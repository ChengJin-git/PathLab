"""On-demand mask rendering from saved threshold bins; never runs a model."""

import io
import numpy as np
from PIL import Image

from backend.ai.result_store import AIResultStore
from .visuals import class_color


def render_mask(root, task_id, wsi_id, layer, class_index, threshold, fold_key=None):
    store = AIResultStore(root)
    artifact = "gt_mask" if layer == "gt" else "pred_bins"
    if layer == "pred" and not store.artifact_exists(
        task_id, wsi_id, artifact, fold_key
    ):
        if threshold != 0.5:
            raise ValueError(
                "This result contains only a binary mask; regenerate probabilities to change the threshold"
            )
        artifact = "pred_mask"
    array = store.read_array(task_id, wsi_id, artifact, fold_key)
    if array is None or array.ndim != 3 or not 0 <= class_index < array.shape[0]:
        raise ValueError(
            "Saved segmentation preview unavailable; regenerate predictions"
        )
    mask = array[class_index] > (
        round(threshold * 100) if artifact == "pred_bins" else 0
    )
    rgba = np.zeros((*mask.shape, 4), dtype=np.uint8)
    color = class_color(class_index)
    rgba[mask] = [int(color[i : i + 2], 16) for i in (1, 3, 5)] + [150]
    image = Image.fromarray(rgba)
    metadata = store.read_result(task_id, wsi_id, fold_key)
    width, height = metadata["image_size"]
    scale = min(768 / max(width, height), 1)
    image = image.resize(
        (max(1, round(width * scale)), max(1, round(height * scale))),
        Image.Resampling.NEAREST,
    )
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
