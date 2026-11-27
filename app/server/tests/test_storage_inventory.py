import pytest
from backend.storage.inventory import Inventory, STATES, measure
from backend.storage.references import References, add_result_catalog
from backend.storage.deletion import remove_item, owned_path

WSI = "wsi_0123456789abcdef"
TASK = "train_0123456789abcdef"


@pytest.fixture
def inventory(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.storage.inventory.GRACE_SECONDS", -1)
    return Inventory(tmp_path)


def put(root, path, content=b"payload"):
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


def entries(inventory):
    return {item["path"]: item for item in inventory.page(limit=100)["items"]}


def test_orphan_input_links_do_not_pin_cache_but_live_experiment_does(inventory):
    feature = put(inventory.root, f"features/uni/hash/{WSI}.pt")
    link = inventory.root / f"training/{TASK}/features/{WSI}.pt"
    link.parent.mkdir(parents=True)
    link.symlink_to(feature)
    refs = References(image_ids={WSI})
    inventory.scan(refs)
    result = entries(inventory)
    assert result[str(feature.relative_to(inventory.root))]["state"] == "cached"
    assert result[f"training/{TASK}"]["state"] == "orphaned"
    refs.owners.add(TASK)
    inventory.scan(refs)
    assert (
        entries(inventory)[str(feature.relative_to(inventory.root))]["state"]
        == "referenced"
    )


def test_result_catalog_protects_deleted_slide_features(inventory):
    import sqlite3

    feature = put(inventory.root, f"features/uni/hash/{WSI}.pt")
    catalog = inventory.root / "ai_results_bundles/catalog.sqlite3"
    catalog.parent.mkdir()
    with sqlite3.connect(catalog) as db:
        db.execute("CREATE TABLE artifacts(task_id TEXT,wsi_id TEXT)")
        db.execute("INSERT INTO artifacts VALUES(?,?)", (TASK, WSI))
    refs = References(owners={TASK})
    add_result_catalog(refs, inventory.root)
    inventory.scan(refs)
    assert (
        entries(inventory)[str(feature.relative_to(inventory.root))]["state"]
        == "referenced"
    )


def test_changed_nested_manifest_updates_references_without_parent_mtime(inventory):
    feature = put(inventory.root, f"features/uni/hash/{WSI}.pt")
    session = "session_abcdef012345"
    manifest = put(
        inventory.root,
        f"autoresearch/autoresearch_sessions/{session}/input.json",
        b"{}",
    )
    refs = References(owners={"abcdef012345"})
    inventory.scan(refs)
    assert (
        entries(inventory)[str(feature.relative_to(inventory.root))]["state"]
        == "orphaned"
    )
    manifest.write_text('{"feature_path": "' + str(feature) + '"}')
    inventory.scan(refs)
    assert (
        entries(inventory)[str(feature.relative_to(inventory.root))]["state"]
        == "referenced"
    )


def test_mrxs_companion_without_main_file_is_reclaimable(inventory):
    identity = "11111111-1111-1111-1111-111111111111"
    put(inventory.root, f"wsi_files/{identity}/Data0000.dat")
    inventory.scan(References())
    item = entries(inventory)[f"wsi_files/{identity}"]
    assert item["state"] == "orphaned"
    assert remove_item(inventory, item) > 0
    assert not (inventory.root / item["path"]).exists()


def test_readers_keep_last_generation_on_scan_failure(inventory):
    put(inventory.root, f"features/uni/hash/{WSI}.pt")
    first = inventory.scan(References())

    def fail(*a, **k):
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError):
        inventory.scan(References(), fail)
    assert inventory.summary()["generation"] == first["generation"]
    assert len(inventory.page()["items"]) == 1


def test_deletion_rejects_changed_file_and_never_follows_external_link(
    inventory, tmp_path
):
    external = put(tmp_path, "outside/data.bin")
    p = put(inventory.root, f"features/uni/hash/{WSI}.pt")
    inventory.scan(References())
    item = entries(inventory)[str(p.relative_to(inventory.root))]
    p.write_bytes(b"changed")
    assert remove_item(inventory, item) is None
    assert p.exists()
    link = inventory.root / "training/orphan"
    link.parent.mkdir()
    link.symlink_to(external)
    assert measure(link)["files"] == 0
    assert measure(link)["links"] == 1
    for path in (
        "../outside/data.bin",
        "features",
        "models/..",
        "models/../..",
        str(tmp_path.parent / "other"),
    ):
        with pytest.raises(ValueError):
            owned_path(inventory.root, path)


def test_keyset_pages_and_summary_never_rescan_files(inventory, monkeypatch):
    for i in range(120):
        put(inventory.root, f"metadata/wsi_{i:016x}.json")
    inventory.scan(References())
    monkeypatch.setattr(
        "backend.storage.inventory.local_walk",
        lambda *_: (_ for _ in ()).throw(AssertionError("read walked disk")),
    )
    first = inventory.page("metadata", "orphaned")
    second = inventory.page("metadata", "orphaned", first["next_cursor"])
    assert len(first["items"]) == len(second["items"]) == 50
    assert first["total"] == second["total"] == 120
    assert first["allocated"] == second["allocated"]
    assert inventory.page("features", "orphaned")["total"] == 0
    assert not {x["id"] for x in first["items"]} & {x["id"] for x in second["items"]}
    assert inventory.summary()["files"] == 120


def test_every_category_publishes_all_states_and_empty_filters_return_zero(inventory):
    put(inventory.root, f"features/uni/hash/{WSI}.pt")
    put(inventory.root, "models/owned/weights.pth")
    put(inventory.root, "models/orphan/weights.pth")
    put(inventory.root, "extractor_checkpoints/uni/model.pth")
    summary = inventory.scan(References(image_ids={WSI}, owners={"owned"}))
    for category in summary["categories"]:
        assert set(category["states"]) == set(STATES)
        assert (
            sum(item["items"] for item in category["states"].values())
            == category["items"]
        )
        assert (
            sum(item["allocated"] for item in category["states"].values())
            == category["allocated"]
        )
        for state in STATES:
            response = inventory.page(category["category"], state)
            assert response["total"] == category["states"][state]["items"]
            assert response["allocated"] == category["states"][state]["allocated"]
            assert response["total"] == len(response["items"])
    for state in STATES:
        result = inventory.page(state=state)
        assert result["total"] == sum(
            cat["states"][state]["items"] for cat in summary["categories"]
        )
    assert inventory.page(state="recent")["items"] == []
    assert inventory.page(state="recent")["total"] == 0
    assert inventory.page(state="recent")["allocated"] == 0


def test_recent_workspace_protects_its_inputs(inventory, monkeypatch):
    monkeypatch.setattr("backend.storage.inventory.GRACE_SECONDS", 86400)
    feature = put(inventory.root, f"features/uni/hash/{WSI}.pt")
    p = inventory.root / "training/train_abcdef0123456789/input.pt"
    p.parent.mkdir(parents=True)
    p.symlink_to(feature)
    inventory.scan(References())
    assert all(
        row["state"] in {"recent", "referenced"} for row in inventory.page()["items"]
    )


def test_cache_lock_in_another_process_prevents_removal(inventory):
    from backend.common import file_lock

    feature = put(inventory.root, f"features/uni/hash/{WSI}.pt")
    inventory.scan(References())
    item = entries(inventory)[str(feature.relative_to(inventory.root))]
    lock = inventory.root / f"features/.locks/uni/hash/{WSI}.lock"
    lock.parent.mkdir(parents=True)
    # A second descriptor is sufficient for flock's distinct open-file lock.
    with lock.open("a+b") as handle:
        file_lock.flock(handle.fileno(), file_lock.LOCK_EX)
        assert remove_item(inventory, item) is None
    assert feature.exists()


def test_explicit_deletion_bypasses_grace_without_losing_reference_protection(
    inventory, monkeypatch
):
    monkeypatch.setattr("backend.storage.inventory.GRACE_SECONDS", 86400)
    put(inventory.root, "models/owned/weights")
    inventory.scan(References(), deleted_paths={"models/owned"})
    assert entries(inventory)["models/owned"]["state"] == "orphaned"
    inventory.scan(References(owners={"owned"}), deleted_paths={"models/owned"})
    assert entries(inventory)["models/owned"]["state"] == "referenced"


def test_manifest_cache_reuses_unchanged_text(inventory, monkeypatch):
    import builtins

    p = put(
        inventory.root,
        "autoresearch/autoresearch_sessions/session_abcdef012345/input.json",
        b'{"input":"none"}',
    )
    inventory.scan(References(owners={"abcdef012345"}))
    original = builtins.open

    def blocked(file, *args, **kwargs):
        if str(file) == str(p):
            raise AssertionError("unchanged manifest was reread")
        return original(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", blocked)
    inventory.scan(References(owners={"abcdef012345"}))
