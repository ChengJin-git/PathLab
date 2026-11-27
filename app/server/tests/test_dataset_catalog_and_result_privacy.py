"""Multi-task dataset transactions and ownership on public/shared input images."""

import json
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from backend.auth.models import User
from backend.database.models import (
    Base,
    Dataset,
    DatasetTask,
    WSISlide,
    TrainingTask,
    DataGroup,
    AIResult,
    TrainedModel,
    SegmentationAnnotation,
)
from backend.database.database import get_database_url


@pytest.fixture
async def catalog_db(monkeypatch):
    schema = "test_catalog_" + uuid4().hex
    admin_engine = create_async_engine(get_database_url())
    async with admin_engine.begin() as connection:
        await connection.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_async_engine(
        get_database_url(),
        connect_args={"server_settings": {"search_path": f"{schema},public"}},
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda c: Base.metadata.create_all(c, checkfirst=False)
            )
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            people = [
                User(
                    id=uuid4(),
                    username=name,
                    role=role,
                    hashed_password="fixture",
                    is_active=True,
                )
                for name, role in [
                    ("owner", "pathologist"),
                    ("other", "pathologist"),
                    ("admin", "admin"),
                ]
            ]
            db.add_all(people)
            db.add(
                DataGroup(
                    group_id="classification",
                    name="classification",
                    task_type="patch_classification",
                    data_type="patch",
                    aggregation_level="file",
                )
            )
            await db.commit()
            from gateway.routes import dataset_catalog, wsi

            monkeypatch.setattr(dataset_catalog, "invalidate_chat_context", AsyncMock())
            monkeypatch.setattr(wsi, "invalidate_chat_context", AsyncMock())
            yield db, *people
    finally:
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await admin_engine.dispose()


async def make_dataset(db, owner):
    from gateway.routes.dataset_catalog import create_dataset, DatasetCreate

    result = await create_dataset(
        DatasetCreate(
            name="Shared patches",
            data_type="patch",
            task_types=["patch_classification"],
            is_public=True,
            description="Cytology cohort",
            metadata={"stain": "H&E", "institution": "Provided source"},
        ),
        user=owner,
        db=db,
        workspace_id=None,
    )
    identity = result["dataset_id"]
    db.add_all(
        [
            WSISlide(
                wsi_id=f"image-{i}",
                dataset_id=identity,
                original_filename=f"image-{i}.png",
                wsi_path="/unused",
                data_type="patch",
                width=40,
                height=30,
                label="cell" if i else "normal",
                user_id=str(owner.id),
            )
            for i in range(2)
        ]
    )
    await db.commit()
    return identity


async def test_chat_edits_full_properties_with_metadata_merge_and_parent_validation(
    catalog_db,
):
    from gateway.routes.dataset_catalog import import_labels, LabelImport

    db, owner, other, admin = catalog_db
    identity = await make_dataset(db, owner)
    db.add(
        Dataset(
            dataset_id="parent",
            name="Parent",
            user_id=str(owner.id),
            data_type="patch",
            aggregation_level="file",
            tasks=[DatasetTask(task_type="patch_classification")],
        )
    )
    await db.commit()
    result = await import_labels(
        identity,
        LabelImport(
            revision=1,
            properties={
                "name": "Revised cohort",
                "description": "Provided description",
                "source": "Lung",
                "is_public": False,
                "data_type": "patch",
                "aggregation_level": "file",
                "parent_dataset_id": "parent",
                "acquisition_metadata": {"scanner": "Provided scanner"},
                "metadata": {"stain": "Updated stain"},
                "remove_metadata": ["institution"],
                "task_descriptions": {"patch_classification": "Two class task"},
            },
        ),
        owner,
        db,
        None,
    )
    data = result["dataset"]
    assert (
        data["name"] == "Revised cohort"
        and data["source_organ"] == "Lung"
        and not data["is_public"]
    )
    assert data["metadata"] == {"stain": "Updated stain"}
    assert (
        data["parent_dataset_id"] == "parent"
        and data["acquisition_metadata"]["scanner"] == "Provided scanner"
    )
    assert data["task_descriptions"] == {"patch_classification": "Two class task"}
    with pytest.raises(HTTPException) as invalid:
        await import_labels(
            "parent",
            LabelImport(revision=1, properties={"parent_dataset_id": identity}),
            owner,
            db,
            None,
        )
    assert invalid.value.status_code == 422
    await db.rollback()


async def test_public_readers_cannot_edit_foreign_datasets(catalog_db):
    from gateway.routes.dataset_catalog import import_labels, LabelImport
    from backend.auth.dependencies import get_dataset_with_access

    db, owner, other, admin = catalog_db
    identity = await make_dataset(db, owner)
    dataset = await db.scalar(select(Dataset).where(Dataset.dataset_id == identity))
    dataset.is_public = True
    await db.commit()
    assert await get_dataset_with_access(identity, other, db)
    with pytest.raises(HTTPException) as denied:
        await import_labels(
            identity,
            LabelImport(revision=1, properties={"description": "Unauthorized"}),
            other,
            db,
            None,
        )
    assert denied.value.status_code == 403


async def test_public_slide_listing_and_chat_stats_use_dataset_ownership(catalog_db):
    from backend.database.repositories import WSIRepository
    from backend.auth.dependencies import get_permitted_dataset_ids
    db,owner,other,admin=catalog_db
    identity=await make_dataset(db,owner)
    visible=await get_permitted_dataset_ids(other,db)
    stats=await WSIRepository.get_chat_context_stats(db,user_id=str(other.id),elevated_dataset_ids=visible)
    assert stats['total_count']==2
    dataset=await db.scalar(select(Dataset).where(Dataset.dataset_id==identity))
    dataset.is_public=False
    await db.commit()
    # A contributor's image ownership cannot retain access once the dataset is made private.
    slide=await db.scalar(select(WSISlide).where(WSISlide.wsi_id=='image-0'))
    slide.user_id=str(other.id)
    await db.commit()
    readable=(await db.scalars(select(WSISlide).where(WSIRepository._build_visibility_filter(str(other.id))))).all()
    assert readable==[]


async def test_add_detection_and_segmentation_retains_classification_and_metadata(
    catalog_db,
):
    from gateway.routes.dataset_catalog import import_labels, LabelImport
    from backend.database.repositories import WSIRepository

    db, owner, other, admin = catalog_db
    identity = await make_dataset(db, owner)
    base = {
        "images": [{"id": 1, "file_name": "image-0.png", "width": 40, "height": 30}],
        "categories": [{"id": 7, "name": "nucleus"}],
        "annotations": [
            {"id": 1, "image_id": 1, "category_id": 7, "bbox": [3, 4, 8, 9]}
        ],
    }
    seg = json.loads(json.dumps(base))
    seg["annotations"][0]["segmentation"] = [[3, 4, 11, 4, 11, 13, 3, 13]]
    result = await import_labels(
        identity,
        LabelImport(
            revision=1,
            task_types=["patch_detection", "patch_segmentation"],
            rows=[{"filename": "image-0.png", "metadata": {"scanner": "A"}}],
            annotations={"patch_detection": base, "patch_segmentation": seg},
        ),
        user=owner,
        db=db,
        workspace_id=None,
    )
    assert set(result["dataset"]["task_types"]) == {
        "patch_classification",
        "patch_detection",
        "patch_segmentation",
    }
    assert result["dataset"]["metadata"]["stain"] == "H&E"
    image = await db.scalar(select(WSISlide).where(WSISlide.wsi_id == "image-0"))
    assert image.label == "normal" and image.metadata_fields == {"scanner": "A"}
    annotations = (
        await db.scalars(
            select(SegmentationAnnotation).where(
                SegmentationAnnotation.source_dataset_id == identity
            )
        )
    ).all()
    assert {a.task_type for a in annotations} == {
        "patch_detection",
        "patch_segmentation",
    }
    summary = (
        await WSIRepository.get_datasets(
            db, dataset_id=identity, task_type="patch_detection"
        )
    )[0]
    assert summary["num_coco_categories"] == 1
    assert (
        next(
            task for task in summary["tasks"] if task["task_type"] == "patch_detection"
        )["labelled_count"]
        == 1
    )
    from backend.services.dataset_catalog import load_task_annotations
    from gateway.routes.annotation import get_wsi_ground_truth_annotations

    detection = await load_task_annotations(db, identity, "patch_detection")
    segmentation = await load_task_annotations(db, identity, "patch_segmentation")
    assert "segmentation" not in detection["annotations"][0]
    assert segmentation["annotations"][0]["segmentation"]
    # Public input access includes GT, while predictions still require task ownership.
    gt = await get_wsi_ground_truth_annotations("image-0", other, db, "patch_detection")
    assert gt["record_count"] == 1 and gt["annotations"]["image-0"]
    with pytest.raises(HTTPException) as denied:
        await import_labels(
            identity,
            LabelImport(
                revision=2, rows=[{"filename": "image-0.png", "label": "wrong"}]
            ),
            user=other,
            db=db,
            workspace_id=None,
        )
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException) as stale:
        await import_labels(
            identity, LabelImport(revision=1), user=owner, db=db, workspace_id=None
        )
    assert stale.value.status_code == 409


async def test_results_follow_task_owner_not_public_dataset_or_row_owner(
    catalog_db, monkeypatch
):
    from backend.services.result_access import owned_result_clause
    from backend.services.result_analysis.sources import index_task, authorized_sources
    from backend.database.repositories import AIResultRepository
    from gateway.routes import heatmap, models

    db, owner, other, admin = catalog_db
    identity = await make_dataset(db, owner)
    for name, actor in [("own", owner), ("foreign", other)]:
        db.add(
            TrainingTask(
                task_id=name,
                task_name=name,
                group_id="classification",
                user_id=str(actor.id),
                status="completed",
            )
        )
    await db.flush()
    # Deliberately misleading denormalized user_id must not grant ownership.
    db.add_all(
        [
            AIResult(
                task_id="own", wsi_id="image-0", pred="normal", user_id=str(owner.id)
            ),
            AIResult(
                task_id="foreign",
                wsi_id="image-0",
                pred="secret",
                user_id=str(owner.id),
            ),
        ]
    )
    db.add_all(
        [
            TrainedModel(
                model_id=name,
                task_id=name,
                model_name=name,
                model_path="/unused",
                user_id=str(actor.id),
                classes=["normal", "cell"],
                is_active=True,
            )
            for name, actor in [("own", owner), ("foreign", other)]
        ]
    )
    await db.commit()
    assert (
        await AIResultRepository.get_by_wsi_id(db, "image-0", user=owner)
    ).pred == "normal"
    assert (
        len(
            (await db.scalars(select(AIResult).where(owned_result_clause(admin)))).all()
        )
        == 2
    )
    assert [
        item["model_id"]
        for item in (await models.list_trained_models(user=owner, db=db))["items"]
    ] == ["own"]
    await index_task(db, "own")
    await index_task(db, "foreign")
    await db.commit()
    with pytest.raises(HTTPException):
        await authorized_sources(db, owner, ["task:foreign"])
    assert len(await authorized_sources(db, admin, ["task:foreign"])) == 1
    from backend.ai.result_catalog import ResultCatalog
    monkeypatch.setattr(ResultCatalog,'image',lambda self,sid:[{'task_id':tid,'fold_key':None,'artifact':'result','revision':'1','summary':{'task_type':'patch_classification'}} for tid in ['own','foreign']])
    assert [item['task_id'] for item in (await heatmap.get_available_heatmaps("image-0", owner, db))["heatmaps"]] == ['own']
    assert (
        len((await heatmap.get_available_heatmaps("image-0", admin, db))["heatmaps"])
        == 2
    )
    for handler in [
        heatmap.get_patch_cam,
        heatmap.get_seg_mask,
        heatmap.get_heatmap_thumbnail,
        heatmap.get_heatmap_data,
    ]:
        with pytest.raises(HTTPException) as denied:
            await handler("image-0", task_id="foreign", user=owner, db=db)
        assert denied.value.status_code == 404
    from backend.ai.result_store import AIResultStore
    from backend.services.result_access import select_result_artifact

    monkeypatch.setattr(
        AIResultStore,
        "list_wsi_artifacts",
        lambda self, image: [
            {"task_id": "own", "artifact": "cam"},
            {"task_id": "foreign", "artifact": "cam"},
            {"task_id": "foreign", "artifact": "attention", "fold_key": "fold_0"},
        ],
    )
    assert await select_result_artifact(db, owner, "image-0", None, "cam") == "own"
    with pytest.raises(HTTPException):
        await select_result_artifact(db, owner, "image-0", None, "attention", "fold_0")
    assert (
        await select_result_artifact(db, admin, "image-0", None, "attention", "fold_0")
        == "foreign"
    )


async def test_preprocessing_result_routes_reject_direct_requests(monkeypatch):
    from backend.preprocessing.heatmap_routes import router
    from backend.common.internal_requests import internal_headers

    monkeypatch.setenv("PATHLAB_INTERNAL_SECRET", "test-secret")
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        for endpoint in (
            "heatmap",
            "heatmap_thumbnail",
            "patch_cam",
            "seg_mask",
        ):
            response = await client.get(f"/wsi/shared/{endpoint}")
            assert response.status_code == 403
        assert (await client.get('/wsi/shared/available_heatmaps')).status_code==404
    from backend.common.internal_requests import require_internal_request
    from starlette.requests import Request

    headers = internal_headers("GET", "/wsi/shared/seg_mask")
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/wsi/shared/seg_mask",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        }
    )
    await require_internal_request(request)
    signed = internal_headers("GET", "/wsi/shared/seg_mask", {"task_id": "own"})
    tampered = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/wsi/shared/seg_mask",
            "query_string": b"task_id=foreign",
            "headers": [(k.lower().encode(), v.encode()) for k, v in signed.items()],
        }
    )
    with pytest.raises(HTTPException):
        await require_internal_request(tampered)


async def test_patch_rejects_wsi_tasks_and_edits_do_not_clear_other_labels(catalog_db):
    from gateway.routes.dataset_catalog import DatasetCreate
    from gateway.routes.wsi import update_dataset_properties
    from gateway.models import DatasetPropertiesRequest

    with pytest.raises(ValueError):
        DatasetCreate(name="bad", data_type="wsi", task_types=["patch_detection"])
    db, owner, other, admin = catalog_db
    identity = await make_dataset(db, owner)
    result = await update_dataset_properties(
        identity,
        DatasetPropertiesRequest(
            task_types=["patch_classification", "patch_detection"], revision=1
        ),
        owner,
        db,
        None,
    )
    assert result["dataset"]["revision"] == 2
    assert (
        await db.scalar(select(WSISlide.label).where(WSISlide.wsi_id == "image-0"))
        == "normal"
    )


async def test_chat_edit_rolls_back_properties_when_labels_are_invalid(catalog_db):
    from gateway.routes import dataset_catalog as routes
    from backend.database.repositories import DatasetRepository

    db, owner, other, admin = catalog_db
    identity = await make_dataset(db, owner)

    async def session():
        try:
            yield db
        except Exception:
            await db.rollback()
            raise

    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.get_db] = session
    app.dependency_overrides[routes.current_active_user] = lambda: owner
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/wsi/datasets/{identity}/labels",
            json={
                "revision": 1,
                "properties": {"description": "Must roll back"},
                "rows": [{"filename": "missing.png", "label": "wrong"}],
            },
        )
        assert response.status_code == 422
        dataset = await DatasetRepository.get_by_id(db, identity)
        assert dataset.description == "Cytology cohort" and dataset.revision == 1


async def test_survival_labels_coexist_with_classification_and_reject_case_conflicts(
    catalog_db,
):
    from gateway.routes.dataset_catalog import (
        DatasetCreate,
        create_dataset,
        LabelImport,
        import_labels,
    )

    db, owner, other, admin = catalog_db
    result = await create_dataset(
        DatasetCreate(
            name="Follow-up",
            data_type="wsi",
            aggregation_level="case",
            task_types=["wsi_classification", "wsi_survival"],
        ),
        owner,
        db,
        None,
    )
    identity = result["dataset_id"]
    db.add_all(
        [
            WSISlide(
                wsi_id=f"slide-{i}",
                dataset_id=identity,
                wsi_path="/unused",
                original_filename=f"{i}.svs",
                data_type="wsi",
                label="tumour",
                case_id="case-1",
                user_id=str(owner.id),
            )
            for i in range(2)
        ]
    )
    await db.commit()
    await import_labels(
        identity,
        LabelImport(
            revision=1,
            rows=[
                {"filename": f"{i}.svs", "event_time": 0, "event_status": 0}
                for i in range(2)
            ],
        ),
        owner,
        db,
        None,
    )
    assert (
        await db.scalar(select(WSISlide.label).where(WSISlide.wsi_id == "slide-0"))
        == "tumour"
    )
    with pytest.raises(HTTPException) as conflict:
        await import_labels(
            identity,
            LabelImport(
                revision=2,
                rows=[{"filename": "0.svs", "event_time": 4, "event_status": 1}],
            ),
            owner,
            db,
            None,
        )
    assert conflict.value.status_code == 422
    await db.rollback()
