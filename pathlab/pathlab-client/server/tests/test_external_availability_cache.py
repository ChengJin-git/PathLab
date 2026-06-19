def test_cache_defaults_unknown_for_missing_entry(tmp_path, monkeypatch):
    from backend.storage import external_availability as availability

    monkeypatch.setattr(availability.Config, "get_uploads_dir", lambda: tmp_path)

    status = availability.get_wsi_availability("wsi-1")

    assert status["status"] == "unknown"
    assert status["reason"] is None


def test_cache_persists_unavailable_and_dataset_rollup(tmp_path, monkeypatch):
    from backend.storage import external_availability as availability

    monkeypatch.setattr(availability.Config, "get_uploads_dir", lambda: tmp_path)
    availability.record_wsi_availability(
        "wsi-1",
        status="unavailable",
        reason="External storage not responding",
        checked_by="admin_scan",
    )

    status = availability.get_wsi_availability("wsi-1")
    assert status["status"] == "unavailable"
    assert status["reason"] == "External storage not responding"
    assert status["checked_by"] == "admin_scan"

    rollup = availability.roll_up_dataset_availability(["wsi-1", "wsi-2"])
    assert rollup["status"] == "unavailable"
    assert rollup["unavailable_count"] == 1
    assert rollup["total_count"] == 2


def test_corrupted_cache_is_ignored(tmp_path, monkeypatch):
    from backend.storage import external_availability as availability

    monkeypatch.setattr(availability.Config, "get_uploads_dir", lambda: tmp_path)
    (tmp_path / ".external_availability_cache.json").write_text(
        "{broken", encoding="utf-8"
    )

    assert availability.get_wsi_availability("wsi-1")["status"] == "unknown"


def test_unavailable_cooldown_blocks_repeated_open(tmp_path, monkeypatch):
    from backend.storage import external_availability as availability

    monkeypatch.setattr(availability.Config, "get_uploads_dir", lambda: tmp_path)
    availability.record_wsi_availability(
        "wsi-1",
        status="unavailable",
        reason="File not found",
        checked_by="open_failure",
    )

    assert availability.should_short_circuit_open("wsi-1") is True


def test_scan_records_dataset_availability_rollup(tmp_path, monkeypatch):
    from backend.storage import external_availability as availability

    monkeypatch.setattr(availability.Config, "get_uploads_dir", lambda: tmp_path)

    availability.record_many_from_scan(
        {
            "available": [
                {"wsi_id": "wsi-ok", "dataset_id": "ds-external", "status": "available"}
            ],
            "unavailable": [
                {
                    "wsi_id": "wsi-bad",
                    "dataset_id": "ds-external",
                    "status": "unavailable",
                    "reason": "File not found",
                }
            ],
        }
    )

    dataset_status = availability.get_dataset_availability("ds-external")

    assert dataset_status["status"] == "unavailable"
    assert dataset_status["reason"] == "File not found"
    assert dataset_status["total_count"] == 2
    assert dataset_status["unavailable_count"] == 1
    assert availability.get_dataset_availability("missing")["status"] == "unknown"


def test_scan_records_availability_in_single_cache_write(tmp_path, monkeypatch):
    from backend.storage import external_availability as availability

    monkeypatch.setattr(availability.Config, "get_uploads_dir", lambda: tmp_path)
    original_save_cache = availability._save_cache
    save_calls = []

    def _count_save(cache):
        save_calls.append(cache)
        original_save_cache(cache)

    monkeypatch.setattr(availability, "_save_cache", _count_save)

    availability.record_many_from_scan(
        {
            "available": [
                {"wsi_id": "wsi-ok-1", "dataset_id": "ds-external"},
                {"wsi_id": "wsi-ok-2", "dataset_id": "ds-external"},
            ],
            "unavailable": [
                {"wsi_id": "wsi-bad", "dataset_id": "ds-external", "reason": "File not found"}
            ],
        }
    )

    assert len(save_calls) == 1
    assert availability.get_wsi_availability("wsi-bad")["status"] == "unavailable"
    assert availability.get_dataset_availability("ds-external")["unavailable_count"] == 1
