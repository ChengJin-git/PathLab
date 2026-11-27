from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects.postgresql import dialect

from backend.services.workspaces import WorkspaceScope
from gateway.routes.image_recommendations import recommendation_query, router
from backend.auth import current_active_user
from backend.database import get_db


def actor(admin=False):
    return SimpleNamespace(id="owner", is_admin=lambda: admin)


def sql(query):
    return str(query.compile(dialect=dialect(), compile_kwargs={"literal_binds": True}))


def test_all_area_recommendations_are_bounded_and_read_authorized():
    statement = sql(
        recommendation_query(
            actor(), WorkspaceScope(), limit=3, label="Tumor", data_type="patch"
        )
    )
    assert "LIMIT 3" in statement
    assert "datasets.is_public" in statement
    assert "lower(wsi_slides.label) = 'tumor'" in statement
    assert "count(" not in statement.lower()
    assert "wsi_path" not in statement


def test_empty_workspace_and_admin_scope_do_not_widen():
    statement = sql(
        recommendation_query(
            actor(True),
            WorkspaceScope(workspace_id="empty", dataset_ids=()),
            dataset_id="foreign",
        )
    )
    assert "1 != 1" in statement
    assert "'foreign'" in statement


def test_prediction_filters_use_latest_owned_result_and_keep_false_zero_values():
    statement = sql(
        recommendation_query(
            actor(),
            WorkspaceScope(),
            pred="Normal",
            correct_prediction=False,
            event_status=0,
            task_id="train_1",
            limit=5,
        )
    )
    assert "JOIN LATERAL" in statement
    assert "ai_results.user_id = 'owner'" not in statement
    assert "training_tasks.user_id = 'owner'" in statement
    assert "ORDER BY ai_results.created_at DESC, ai_results.id DESC" in statement
    assert "event_status = 0" in statement
    assert "!= lower" in statement
    assert "label IS NOT NULL" in statement
    assert "LIMIT 5" in statement


def test_endpoint_returns_one_bounded_projection_without_detail_requests():
    app = FastAPI()
    app.include_router(router, prefix="/wsi")
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(
        mappings=lambda: SimpleNamespace(
            all=lambda: [
                {
                    "wsi_id": "wsi_1",
                    "dataset_id": "ds_1",
                    "original_filename": "sample.svs",
                    "result_prediction": "Tumor",
                }
            ]
        )
    )
    app.dependency_overrides[current_active_user] = lambda: actor(True)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        response = client.get(
            "/wsi/recommendations?limit=3&has_predictions=true&event_status=0"
        )
        assert response.status_code == 200
        assert response.json()["items"][0]["file_extension"] == ".svs"
        assert response.json()["items"][0]["result_prediction"] == "Tumor"
        assert client.get("/wsi/recommendations?limit=10001").status_code == 422
    assert db.execute.await_count == 1


def test_mask_class_handles_null_metadata_and_filters_before_limit():
    statement = sql(recommendation_query(actor(True), WorkspaceScope(), segmentation_class="Tumor", result_task_type="patch_segmentation", task_id="task", limit=3))
    assert "jsonb_typeof" in statement and "jsonb_build_array()" in statement
    assert "lower(anon_2.value) = 'tumor'" in statement
    assert "data_groups.task_type = 'patch_segmentation'" in statement
    assert "ai_results.task_id = 'task'" in statement
    assert statement.endswith("LIMIT 3")
