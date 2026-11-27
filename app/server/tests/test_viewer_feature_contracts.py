from types import SimpleNamespace
import numpy as np
import pytest
import h5py
from backend.ai.feature_contracts import asset_digest
from backend.services import (
    viewer_features as features,
    viewer_text_encoders as encoders,
)
from test_viewer_workspace import workspace


def assets(root):
    path = root / "tiles.npy"
    np.save(path, np.array([[1, 0], [0, 1]], dtype=np.float32))
    coords = root / "coordinates.h5"
    with h5py.File(coords, "w") as file:
        points = file.create_dataset("coords", data=[[0, 0], [32, 32]])
        points.attrs["patch_size"] = 16
    contract = {
        "model_id": "arbitrary-lab-model",
        "model_revision": "weights-2026",
        "embedding_space": "lab-space",
        "dimensions": 2,
        "preprocessing": "lab-rgb-tiles",
    }
    return path, coords, contract


def test_registered_provider_uses_explicit_space_and_rejects_changed_checkpoint(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(features.Config, "get_uploads_dir", lambda: tmp_path)
    checkpoint = tmp_path / "weights.bin"
    checkpoint.write_bytes(b"v1")
    monkeypatch.setitem(
        encoders._providers,
        "lab-provider",
        lambda contract: lambda text, values: (np.array([0.0, 1.0]), values),
    )
    path, coords, contract = assets(tmp_path)
    contract["text_encoder"] = {
        "provider": "lab-provider",
        "checkpoint": str(checkpoint),
        "revision": asset_digest(checkpoint),
        "aligned_space": "lab-space",
    }
    slide = SimpleNamespace(
        wsi_id="slide",
        width=128,
        height=128,
        associated_files={"viewer_features": [{"feature_path": str(path)}]},
    )
    features.validate_registration(path, coords, contract, slide)
    item = features.available_features(slide)[0]
    assert (
        item["text_similarity"] and features.search(item, query="target")[0]["x"] == 32
    )
    checkpoint.write_bytes(b"v2")
    assert not features.available_features(slide)[0]["text_similarity"]
    with pytest.raises(features.MissingCapability, match="text_alignment"):
        features.search(item, query="target")
    contract["text_encoder"]["aligned_space"] = "unrelated-space"
    features.record_feature_contract(path, contract, coords)
    assert not features.available_features(slide)[0]["text_similarity"]


async def test_registration_rejects_wrong_dimensions_before_writing_manifest(workspace):
    w = workspace
    w.actor.user = w.people[3]
    path, coords, contract = assets(w.root)
    contract["dimensions"] = 3
    result = await w.client.post(
        "/viewer/slides/slide/features",
        json={
            "feature_path": str(path),
            "coordinates_path": str(coords),
            "contract": contract,
        },
    )
    assert result.status_code == 422 and not path.with_suffix(".feature.json").exists()
    contract["dimensions"] = 2
    result = await w.client.post(
        "/viewer/slides/slide/features",
        json={
            "feature_path": str(path),
            "coordinates_path": str(coords),
            "contract": contract,
        },
    )
    assert result.status_code == 200, result.text
    caps = (await w.client.get("/viewer/slides/slide/capabilities")).json()["features"]
    assert (
        len(caps) == 1
        and caps[0]["image_similarity"]
        and not caps[0]["text_similarity"]
    )
    np.save(path, np.ones((3, 2)))
    assert (await w.client.get("/viewer/slides/slide/capabilities")).json()[
        "features"
    ] == []


def test_hole_geometry_roundtrips_standard_coco_mask():
    from backend.annotation.coco_utils import (
        roi_annotations_to_coco,
        coco_to_roi_annotations,
    )
    from pycocotools import mask

    value = {
        "type": "polygon",
        "x": 0,
        "y": 0,
        "width": 40,
        "height": 40,
        "points": [[0, 0], [40, 0], [40, 40], [0, 40]],
        "holes": [[[10, 10], [20, 10], [20, 20], [10, 20]]],
        "label": "T",
    }
    coco = roi_annotations_to_coco(
        {"slide": [value]},
        {"slide": {"width": 64, "height": 64, "file_name": "slide.png"}},
    )
    decoded = mask.decode(coco["annotations"][0]["segmentation"])
    assert decoded[15, 15] == 0 and decoded[5, 5] == 1
    assert (
        coco_to_roi_annotations(coco, {"slide.png": "slide"})["slide"][0]["holes"]
        == value["holes"]
    )


async def test_verified_historical_visual_features_enable_image_search_not_text(
    workspace,
):
    from backend.services.feature_inventory import (
        inspect_artifact,
        upsert_artifacts,
        dataset_feature_summary,
    )

    path, coords, _ = assets(workspace.root)
    item = inspect_artifact(
        path,
        coords,
        "custom-historical-model",
        provenance={
            "source": "native_feature_cache",
            "weights_revision": "not_recorded",
        },
    )
    item["wsi_id"] = "slide"
    async with workspace.db() as db:
        await upsert_artifacts(db, [item])
        await db.commit()
        summary = await dataset_feature_summary(db, ["dataset"])
        assert summary["dataset"][0]["image_count"] == 1
    capabilities = (
        await workspace.client.get("/viewer/slides/slide/capabilities")
    ).json()["features"]
    assert (
        len(capabilities) == 1
        and capabilities[0]["image_similarity"]
        and not capabilities[0]["text_similarity"]
    )
    response = await workspace.client.post(
        "/viewer/slides/slide/search",
        json={
            "feature_id": item["artifact_id"],
            "region": {"type": "rect", "x": 0, "y": 0, "width": 20, "height": 20},
        },
    )
    assert response.json()["status"] == "ready" and response.json()["regions"]
    response = await workspace.client.post(
        "/viewer/slides/slide/search",
        json={"feature_id": item["artifact_id"], "query": "tumor"},
    )
    assert response.json()["reason"] == "text_alignment_unavailable"
