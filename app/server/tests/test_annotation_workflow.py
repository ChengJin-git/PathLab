"""Reference publication/extraction on the object-based viewer contract."""

from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select
from backend.database.models import SegmentationAnnotation, Dataset
from gateway.routes import annotation
from test_viewer_workspace import workspace, mutate, change


async def test_empty_draft_never_extracts_imported_ground_truth(workspace, monkeypatch):
    w = workspace
    dispatch = AsyncMock()
    monkeypatch.setattr(annotation, "request_preprocessing_service", dispatch)
    from gateway.models import AnnotationExtractRequest
    from fastapi import HTTPException

    async with w.db() as db:
        with pytest.raises(HTTPException) as error:
            await annotation.extract_regions(
                AnnotationExtractRequest(
                    dataset_name="Derived",
                    dataset_scope=True,
                    source_dataset_id="dataset",
                ),
                w.people[0],
                db,
            )
    assert error.value.status_code == 422
    dispatch.assert_not_called()


async def test_reference_publication_keeps_personal_objects_and_rejects_readers(
    workspace,
):
    w = workspace
    await mutate(w, [change()])
    response = await w.client.post(
        "/viewer/slides/slide/reference-labels",
        json={"layer": "personal", "regions": [{"id": "region", "revision": 1}]},
    )
    assert response.status_code == 200, response.text
    assert (await w.client.get("/viewer/slides/slide/regions")).json()["items"][0][
        "label"
    ] == "Tumor"
    async with w.db() as db:
        labels = await annotation.get_wsi_ground_truth_annotations(
            "slide", w.people[0], db, "patch_segmentation"
        )
        assert labels["record_count"] == 1
        assert labels["annotations"]["slide"][0]["label"] == "Tumor"
    w.actor.user = w.people[1]
    await mutate(w, [change("reader-note")])
    response = await w.client.post(
        "/viewer/slides/slide/reference-labels",
        json={"layer": "personal", "regions": [{"id": "reader-note", "revision": 1}]},
    )
    assert response.status_code == 403


async def test_extraction_uses_saved_objects_and_preserves_source_policy(
    workspace, monkeypatch
):
    w = workspace
    await mutate(w, [change()])
    dispatch = AsyncMock()
    monkeypatch.setattr(annotation, "request_preprocessing_service", dispatch)
    monkeypatch.setattr(annotation, "set_task_owner", AsyncMock())
    from gateway.models import AnnotationExtractRequest

    async with w.db() as db:
        result = await annotation.extract_regions(
            AnnotationExtractRequest(
                dataset_name="Derived",
                task_type="patch_classification",
                dataset_scope=True,
                source_dataset_id="dataset",
            ),
            w.people[0],
            db,
        )
    payload = dispatch.await_args.kwargs["json_body"]
    assert payload["parent_dataset_id"] == "dataset" and payload["is_public"] is False
    assert payload["regions"]["slide"][0]["label"] == "Tumor"
    assert result["status"] == "started"


async def test_stale_publication_does_not_override_new_annotations(workspace):
    w = workspace
    await mutate(w, [change()])
    await mutate(w, [change(revision=1, label="Revised")])
    response = await w.client.post(
        "/viewer/slides/slide/reference-labels",
        json={"layer": "personal", "regions": [{"id": "region", "revision": 1}]},
    )
    assert response.status_code == 409
    async with w.db() as db:
        assert await db.scalar(select(SegmentationAnnotation)) is None


async def test_publication_preserves_prior_labels_and_updates_only_explicit_regions(
    workspace,
):
    w = workspace
    await mutate(w, [change("first", label="Existing")])

    async def publish(identity, revision):
        response = await w.client.post(
            "/viewer/slides/slide/reference-labels",
            json={
                "layer": "personal",
                "regions": [{"id": identity, "revision": revision}],
            },
        )
        assert response.status_code == 200, response.text

    await publish("first", 1)
    await mutate(w, [change("second", label="Added")])
    await publish("second", 1)
    await mutate(w, [change("second", revision=1, label="Revised")])
    await publish("second", 2)
    async with w.db() as db:
        payload = await annotation.get_wsi_ground_truth_annotations(
            "slide", w.people[0], db, "patch_segmentation"
        )
        assert sorted(r["label"] for r in payload["annotations"]["slide"]) == [
            "Existing",
            "Revised",
        ]
