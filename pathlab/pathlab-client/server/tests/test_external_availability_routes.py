from unittest.mock import AsyncMock

import pytest


def test_storage_scan_records_external_availability_result(tmp_path, monkeypatch):
    from backend.storage import external_availability
    from gateway.routes import storage_scan

    monkeypatch.setattr(external_availability.Config, "get_uploads_dir", lambda: tmp_path)
    result = {
        "available": [{"wsi_id": "ok-1", "status": "available"}],
        "unavailable": [
            {"wsi_id": "bad-1", "status": "unavailable", "reason": "File not found"}
        ],
    }

    storage_scan._record_external_availability_result(result)

    assert external_availability.get_wsi_availability("ok-1")["status"] == "available"
    assert external_availability.get_wsi_availability("bad-1")["status"] == "unavailable"
    assert external_availability.get_wsi_availability("bad-1")["reason"] == "File not found"


def test_wsi_route_attaches_cached_availability(monkeypatch):
    from gateway.routes import wsi as wsi_routes

    item = {"wsi_id": "bad-1", "dataset_id": "ds-1"}
    monkeypatch.setattr(
        wsi_routes.external_availability,
        "get_wsi_availability",
        lambda _wsi_id: {
            "status": "unavailable",
            "reason": "File not found",
            "checked_at": "2026-06-19T00:00:00Z",
        },
    )

    wsi_routes._attach_cached_availability(item, "/mnt/external/bad-1.svs")

    assert item["availability"]["status"] == "unavailable"
    assert item["availability"]["reason"] == "File not found"


def test_wsi_route_omits_availability_for_uploaded_local_path(tmp_path, monkeypatch):
    from gateway.routes import wsi as wsi_routes

    item = {"wsi_id": "local-1", "dataset_id": "ds-local"}
    uploads_dir = tmp_path / "uploads"
    local_path = uploads_dir / "wsi_files" / "local-1.svs"
    monkeypatch.setattr(
        wsi_routes.external_availability.Config,
        "get_uploads_dir",
        lambda: uploads_dir,
    )
    monkeypatch.setattr(
        wsi_routes.external_availability,
        "get_wsi_availability",
        lambda _wsi_id: {
            "status": "unavailable",
            "reason": "stale cache should not affect uploaded data",
        },
    )

    wsi_routes._attach_cached_availability(item, str(local_path))

    assert "availability" not in item


@pytest.mark.asyncio
async def test_wsi_route_rolls_up_external_dataset_availability_without_file_checks(monkeypatch):
    from gateway.routes import wsi as wsi_routes

    datasets = [
        {"dataset_id": "ds-1", "dataset_name": "External A"},
        {"dataset_id": "ds-local", "dataset_name": "Uploaded"},
    ]
    monkeypatch.setattr(
        wsi_routes.DatasetRepository,
        "get_external_wsi_path_refs_batch",
        AsyncMock(
            return_value={
                "ds-1": [
                    {"wsi_id": "wsi-1", "wsi_path": "/mnt/external/wsi-1.svs"},
                ],
                "ds-local": [],
            }
        ),
    )
    monkeypatch.setattr(
        wsi_routes.external_availability.Config,
        "get_uploads_dir",
        lambda: "/uploads",
    )
    monkeypatch.setattr(
        wsi_routes.external_availability,
        "roll_up_dataset_availability",
        lambda wsi_ids: {
            "status": "unavailable" if "wsi-1" in wsi_ids else "unknown",
            "unavailable_count": 1 if "wsi-1" in wsi_ids else 0,
            "total_count": len(wsi_ids),
        },
    )

    await wsi_routes._attach_dataset_availability(None, datasets)

    assert datasets[0]["availability"]["status"] == "unavailable"
    assert datasets[0]["availability"]["unavailable_count"] == 1
    assert datasets[0]["availability"]["external_count"] == 1
    assert "availability" not in datasets[1]


@pytest.mark.asyncio
async def test_wsi_route_requests_external_only_dataset_refs(monkeypatch):
    from gateway.routes import wsi as wsi_routes

    datasets = [
        {"dataset_id": "ds-external", "dataset_name": "External"},
        {"dataset_id": "ds-local", "dataset_name": "Uploaded"},
    ]
    all_refs = AsyncMock(side_effect=AssertionError("must not bulk-load all WSI refs"))
    external_refs = AsyncMock(
        return_value={
            "ds-external": [
                {"wsi_id": "wsi-external", "wsi_path": "/mnt/external/a.svs"}
            ],
            "ds-local": [],
        }
    )
    monkeypatch.setattr(
        wsi_routes.DatasetRepository,
        "get_wsi_path_refs_batch",
        all_refs,
    )
    monkeypatch.setattr(
        wsi_routes.DatasetRepository,
        "get_external_wsi_path_refs_batch",
        external_refs,
        raising=False,
    )
    monkeypatch.setattr(
        wsi_routes.external_availability,
        "roll_up_dataset_availability",
        lambda wsi_ids: {"status": "available", "total_count": len(wsi_ids)},
    )

    await wsi_routes._attach_dataset_availability(None, datasets)

    external_refs.assert_awaited_once_with(None, ["ds-external", "ds-local"])
    all_refs.assert_not_awaited()
    assert datasets[0]["availability"]["external_count"] == 1
    assert "availability" not in datasets[1]
