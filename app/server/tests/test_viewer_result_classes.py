import io
import numpy as np
from PIL import Image
from backend.ai.result_store import AIResultStore
from backend.database.models import TrainingTask
from backend.services.result_analysis.previews import render_mask
from test_viewer_workspace import workspace  # noqa: F401


async def test_single_class_and_multichannel_legends_match_rendered_masks(workspace):
    w = workspace
    async with w.db() as db:
        db.add(
            TrainingTask(
                task_id="seg",
                task_name="Segmentation",
                group_id="g",
                user_id=str(w.people[0].id),
                status="completed",
            )
        )
        await db.commit()
    store = AIResultStore(w.root)
    store.write_wsi_result(
        "seg",
        "slide",
        fold_key="fold_1",
        result={
            "task_type": "patch_segmentation",
            "class_names": ["SUPERFICIAL"],
            "image_size": [128, 128],
        },
        arrays={"pred_mask": np.ones((1, 2, 2), np.uint8)},
    )
    items = (await w.client.get("/heatmap/wsi/slide/available")).json()["heatmaps"]
    assert items[0]["classes"] == ["SUPERFICIAL"] and items[0]["class_colors"] == [
        "#e11d48"
    ]
    # The detail endpoint and rendered PNG use the same ordered class palette.
    store.write_wsi_result(
        "seg",
        "slide",
        fold_key="fold_2",
        result={
            "task_type": "patch_segmentation",
            "class_names": ["Cell", "Nucleus"],
            "image_size": [128, 128],
        },
        arrays={"pred_mask": np.ones((2, 2, 2), np.uint8)},
    )
    detail = (
        await w.client.get("/heatmap/wsi/slide/prediction?task_id=seg&fold_key=fold_2")
    ).json()
    assert detail["class_names"] == ["Cell", "Nucleus"]
    for index, color in enumerate(detail["class_colors"]):
        image = Image.open(
            io.BytesIO(
                render_mask(w.root, "seg", "slide", "pred", index, 0.5, "fold_2")
            )
        )
        assert image.getpixel((0, 0))[:3] == tuple(
            int(color[i : i + 2], 16) for i in (1, 3, 5)
        )
    assert detail["class_colors"][0] != detail["class_colors"][1]
