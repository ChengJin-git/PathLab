import multiprocessing

from backend.ai.result_store import AIResultStore


def _write_result(uploads, wsi_id, ready, start, finished):
    store = AIResultStore(uploads)
    ready.put(wsi_id)
    if not start.wait(15):
        raise TimeoutError("parent did not release writer")
    store.write_wsi_result("shared-task", wsi_id, result={"wsi_id": wsi_id})
    finished.set()


def test_result_bundle_writers_are_serialized_across_processes(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Queue()
    start = ctx.Event()
    finished = [ctx.Event() for _ in range(3)]
    writers = [
        ctx.Process(target=_write_result, args=(str(tmp_path), f"wsi-{i}", ready, start, finished[i]))
        for i in range(3)
    ]
    store = AIResultStore(tmp_path)
    try:
        with store._task_lock("shared-task"):
            for writer in writers:
                writer.start()
            for _ in writers:
                ready.get(timeout=20)
            start.set()
            # Child processes must honor the parent's file lock, not just their
            # own process-local threading locks.
            assert not any(event.wait(0.2) for event in finished)
        for writer in writers:
            writer.join(timeout=20)
            assert writer.exitcode == 0
        for i in range(3):
            wsi_id = f"wsi-{i}"
            assert store.read_result("shared-task", wsi_id) == {"wsi_id": wsi_id}
        assert store.validate_bundle("shared-task")
        assert store.catalog.task_images('shared-task') == ["wsi-0", "wsi-1", "wsi-2"]
    finally:
        for writer in writers:
            if writer.is_alive():
                writer.terminate()
                writer.join(timeout=5)
        ready.close()


def test_delete_task_recovers_index_and_preserves_other_task(tmp_path):
    store = AIResultStore(tmp_path)
    store.write_wsi_result("delete-me", "wsi-1", result={"pred": "A"})
    store.write_wsi_result("keep-me", "wsi-2", result={"pred": "B"})
    store.delete_task("delete-me")
    assert store.catalog.tasks() == ['keep-me']
    assert store.read_result("keep-me", "wsi-2") == {"pred": "B"}
    assert not store.bundle_path("delete-me").exists()
