"""Viewer authorization, object concurrency, bounded CPU assistance and generic search."""

from types import SimpleNamespace
from uuid import uuid4
import pytest
import httpx
import numpy as np
from PIL import Image
from fastapi import FastAPI
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from backend.auth.models import User
from backend.database.models import (
    Dataset,
    DatasetTask,
    WSISlide,
    ViewerRegion,
    ViewerOperation,
    TrainingTask,
    DataGroup,
    AITask,
    AnnotationAuditLog,
    SegmentationAnnotation,
    FeatureArtifact,
)
from backend.services import viewer_features, viewer_assistance
from backend.ai.result_store import AIResultStore
from gateway.routes import viewer, heatmap


@pytest.fixture
async def workspace(tmp_path, monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    metadata = MetaData()
    for model in [
        User,
        Dataset,
        DatasetTask,
        WSISlide,
        ViewerRegion,
        ViewerOperation,
        TrainingTask,
        DataGroup,
        AITask,
        AnnotationAuditLog,
        SegmentationAnnotation,
        FeatureArtifact,
    ]:
        model.__table__.to_metadata(metadata)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    people = [
        User(
            id=uuid4(),
            username=name,
            hashed_password="test",
            role="admin" if name == "admin" else "pathologist",
            is_active=True,
        )
        for name in ["owner", "reader", "other", "admin"]
    ]
    image = tmp_path / "image.png"
    Image.new("RGB", (128, 128), "white").save(image)
    async with sessions() as db:
        db.add_all(people)
        db.add_all(
            [
                Dataset(
                    dataset_id="dataset",
                    name="Source",
                    data_type="patch",
                    aggregation_level="file",
                    user_id=str(people[0].id),
                    is_public=True,
                ),
                Dataset(
                    dataset_id="private",
                    name="Private",
                    data_type="patch",
                    aggregation_level="file",
                    user_id=str(people[0].id),
                    is_public=False,
                ),
                Dataset(
                    dataset_id="child",
                    name="Derived",
                    data_type="patch",
                    aggregation_level="file",
                    user_id=str(people[1].id),
                    parent_dataset_id="private",
                    is_public=True,
                ),
            ]
        )
        db.add(
            WSISlide(
                wsi_id="slide",
                wsi_path=str(image),
                dataset_id="dataset",
                user_id=str(people[0].id),
                width=128,
                height=128,
                data_type="patch",
            )
        )
        db.add(
            DataGroup(
                group_id="g",
                name="g",
                data_type="patch",
                aggregation_level="file",
                task_type="patch_classification",
            )
        )
        await db.commit()
    actor = SimpleNamespace(user=people[0])

    async def get_db():
        async with sessions() as db:
            yield db

    app = FastAPI()
    app.include_router(viewer.router)
    app.include_router(heatmap.router)
    app.dependency_overrides[viewer.get_db] = get_db
    app.dependency_overrides[viewer.current_active_user] = lambda: actor.user
    monkeypatch.setattr(viewer_features.Config, "get_uploads_dir", lambda: tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        yield SimpleNamespace(
            client=client, db=sessions, actor=actor, people=people, root=tmp_path
        )
    await engine.dispose()


def change(identity="region", revision=0, label="Tumor", value=True):
    return {
        "id": identity,
        "revision": revision,
        "value": {
            "type": "rect",
            "x": 10,
            "y": 10,
            "width": 40,
            "height": 30,
            "label": label,
            "color": "#6366f1",
        }
        if value
        else None,
    }


async def mutate(w, changes, layer="personal", operation=None):
    return await w.client.post(
        "/viewer/slides/slide/regions",
        json={
            "operation_id": operation or uuid4().hex,
            "layer": layer,
            "changes": changes,
        },
    )


async def test_private_notes_do_not_modify_public_data_and_replay_is_idempotent(
    workspace,
):
    w = workspace
    w.actor.user = w.people[1]
    operation = uuid4().hex
    first = await mutate(w, [change()], operation=operation)
    assert first.status_code == 200, first.text
    assert (await mutate(w, [change()], operation=operation)).json() == first.json()
    w.actor.user = w.people[2]
    assert (await w.client.get("/viewer/slides/slide/regions")).json()["items"] == []
    assert (await mutate(w, [change(revision=1)])).status_code == 404
    w.actor.user = w.people[1]
    assert (await mutate(w, [change(revision=0)])).status_code == 409
    deleted = await mutate(w, [change(revision=1, value=False)])
    assert deleted.json()["changes"][0]["revision"] == 2
    restored = await mutate(w, [change(revision=2)])
    assert (
        restored.status_code == 200 and restored.json()["changes"][0]["revision"] == 3
    )


async def test_team_edits_are_object_scoped_and_atomic(workspace):
    w = workspace
    assert (await mutate(w, [change("a"), change("b")], "shared")).status_code == 200
    w.actor.user = w.people[1]
    assert (await mutate(w, [change("b", 1, "Reader")], "shared")).status_code != 200
    w.actor.user = w.people[0]
    assert (await mutate(w, [change("b", 1, "Updated")], "shared")).status_code == 200
    assert (
        await mutate(w, [change("a", 1, "Independent")], "shared")
    ).status_code == 200
    response = await mutate(
        w, [change("a", 2, "Must rollback"), change("b", 1, "Stale")], "shared"
    )
    assert response.status_code == 409
    items = (await w.client.get("/viewer/slides/slide/regions?layer=shared")).json()[
        "items"
    ]
    assert {r["label"] for r in items} == {"Independent", "Updated"}
    assert (
        await w.client.get(
            "/viewer/slides/slide/regions?layer=shared&x=90&y=90&width=10&height=10"
        )
    ).json()["items"] == []

async def test_catalog_permissions_and_zero_bundle_reads(workspace, monkeypatch):
    w = workspace
    async with w.db() as db:
        for name, person in [("mine", w.people[0]), ("foreign", w.people[2])]:
            db.add(
                TrainingTask(
                    task_id=name,
                    task_name=name,
                    group_id="g",
                    user_id=str(person.id),
                    status="completed",
                )
            )
        await db.commit()
    store = AIResultStore(w.root)
    for name in ["mine", "foreign"]:
        store.write_wsi_result(
            name,
            "slide",
            result={"task_type": "patch_classification", "pred": "A"},
            arrays={"cam": np.ones((8, 8), np.float32)},
        )
    monkeypatch.setattr(
        AIResultStore,
        "read_result",
        lambda *a, **k: pytest.fail("catalog opened bundle"),
    )
    monkeypatch.setattr(
        AIResultStore,
        "artifact_exists",
        lambda *a, **k: pytest.fail("catalog probed bundle"),
    )
    response = await w.client.get("/heatmap/wsi/slide/available")
    assert response.status_code == 200, response.text
    assert [row["task_id"] for row in response.json()["heatmaps"]] == ["mine"]
    store.delete_task("mine")
    assert (await w.client.get("/heatmap/wsi/slide/available")).json()["heatmaps"] == []


def test_visual_search_works_with_arbitrary_model_and_text_is_not_inferred(
    tmp_path, monkeypatch
):
    import torch, h5py

    monkeypatch.setattr(viewer_features.Config, "get_uploads_dir", lambda: tmp_path)
    feature = tmp_path / "features" / "custom-encoder" / "params" / "slide.pt"
    feature.parent.mkdir(parents=True)
    torch.save(torch.tensor([[1.0, 0.0], [0.95, 0.05], [0.0, 1.0]]), feature)
    coords = tmp_path / "coordinates" / "params" / "slide_coords.h5"
    coords.parent.mkdir(parents=True)
    with h5py.File(coords, "w") as file:
        points = file.create_dataset(
            "coords", data=np.array([[0, 0], [100, 100], [200, 200]])
        )
        points.attrs["patch_size"] = 20
    # A directory called CONCH is not proof of a model or a text-aligned space.
    assert (
        viewer_features.available_features(
            SimpleNamespace(wsi_id="slide", associated_files={})
        )
        == []
    )
    viewer_features.record_feature_contract(
        feature,
        {
            "model_id": "custom-encoder",
            "model_revision": "custom-v1",
            "embedding_space": "custom-v1:visual",
            "dimensions": 2,
            "preprocessing": "test-tiles",
        },
        coords,
    )
    available = viewer_features.available_features(
        SimpleNamespace(wsi_id="slide", associated_files={})
    )
    assert (
        len(available) == 1
        and available[0]["model_id"] == "custom-encoder"
        and not available[0]["text_similarity"]
    )
    hits = viewer_features.search(available[0], box=(0, 0, 30, 30))
    assert hits[0]["x"] == 0 and hits[1]["x"] == 100
    with pytest.raises(viewer_features.MissingCapability, match="text_alignment"):
        viewer_features.search(available[0], query="tumor")


def test_cpu_assistance_returns_valid_local_shapes(tmp_path):
    image = np.full((128, 128, 3), 240, np.uint8)
    image[30:90, 35:95] = [80, 35, 80]
    path = tmp_path / "roi.png"
    Image.fromarray(image).save(path)
    slide = SimpleNamespace(wsi_path=str(path), data_type="patch")
    body = viewer_assistance.AssistRequest(
        region={"type": "rect", "x": 0, "y": 0, "width": 128, "height": 128},
        method="wand",
        points=[(50, 50, 1)],
    )
    result = viewer_assistance.assist(slide, body)
    assert result["regions"] and 30 <= result["regions"][0]["x"] <= 40
    assert result["regions"][0]["width"] < 70


async def test_missing_features_handoff_never_starts_extraction(workspace):
    response = await workspace.client.post(
        "/viewer/slides/slide/search", json={"feature_id": "missing", "query": "tumor"}
    )
    assert response.status_code == 200 and response.json()["status"] == "handoff"
