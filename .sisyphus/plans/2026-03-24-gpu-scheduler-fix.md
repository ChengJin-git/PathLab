# GPU Scheduler Fix: Move WSI Patching Outside Concurrency Gate

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix GPU VRAM being reported free while tasks sit in "waiting" state, by moving the CPU-only WSI patching stage outside the `max_concurrent` GPU concurrency gate.

**Architecture:** The WSI training pipeline has three stages: PATCHING (CPU-only), EXTRACTING (GPU), TRAINING (GPU). Currently all three hold a GPU concurrency slot. The fix runs PATCHING as a pre-queue background task, submitting to the GPU queue only after patching completes. Patch tasks (classification/segmentation) have no patching stage and are unaffected — they continue to go directly to the GPU queue.

**Tech Stack:** Python asyncio, FastAPI, SQLAlchemy (asyncpg), pynvml, httpx

> **Working directory for all commands:** `pathlab/pathlab-client/` (i.e., `cd pathlab/pathlab-client` before running any command below)
>
> All file paths in this plan are relative to `pathlab/pathlab-client/`. Full paths from repo root: `pathlab/pathlab-client/server/gateway/pipeline.py`, `pathlab/pathlab-client/server/tests/`, etc.

---

## Root Cause

With `max_concurrent=8` and 8 GPUs:
1. 8 WSI tasks submitted → all 8 enter `_running_tasks` immediately
2. All 8 are in PATCHING (CPU/disk, no GPU usage, can take tens of minutes)
3. GPU VRAM: 100% free across all 8 GPUs
4. Task 9 submitted → `len(_running_tasks) == 8 >= max_concurrent` → **blocked**

## Files Modified

| File | Change |
|------|--------|
| `server/gateway/pipeline.py` | Extract patching into `run_patching_stage()`, add `run_patching_then_submit()`, add `patching_complete` param |
| `server/gateway/task_queue.py` | Add `_patching_tasks` dict, update `cancel_task()`, add GPU -1 logging |
| `server/gateway/routes/training.py` | Branch `_validate_files_and_enqueue` on `data_type` |
| `server/gateway/main.py` | Update `resume_interrupted_tasks` for EXTRACTING/TRAINING vs PATCHING states |

---

## Task 1: Extract `run_patching_stage()` from `run_training_pipeline()`

**Files:**
- Modify: `server/gateway/pipeline.py:774-924`
- Test: `server/tests/test_patching_stage.py` (new)

- [ ] **Step 1: Write failing test for `run_patching_stage`**

```python
# server/tests/test_patching_stage.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock, call

@pytest.mark.asyncio
async def test_run_patching_stage_processes_all_wsis():
    """run_patching_stage iterates over all WSI IDs and calls ensure_coords_ready for each."""
    task_id = "test_task_123"
    wsi_ids = ["wsi_1", "wsi_2", "wsi_3"]
    preprocessing_config = {}

    mock_result = {"num_patches": 100, "cached": False}

    with (
        patch("gateway.pipeline.ensure_coords_ready", return_value=mock_result) as mock_coords,
        patch("gateway.pipeline.TrainingTaskRepository") as mock_repo,
        patch("gateway.pipeline.ScopedLogger") as mock_logger_cls,
    ):
        mock_logger = MagicMock()
        mock_logger_cls.return_value = mock_logger
        mock_session = AsyncMock()
        mock_logger.session.return_value.__aenter__ = AsyncMock(return_value=(AsyncMock(), AsyncMock()))
        mock_logger.session.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_repo.update_status = AsyncMock()
        mock_repo.get_by_id = AsyncMock(return_value=MagicMock(status="patching"))

        from gateway.pipeline import run_patching_stage
        await run_patching_stage(task_id, wsi_ids, preprocessing_config)

    assert mock_coords.await_count == 3

@pytest.mark.asyncio
async def test_run_patching_stage_stops_on_cancelled_status():
    """run_patching_stage raises CancelledError when DB status is CANCELLED."""
    task_id = "test_task_456"
    wsi_ids = ["wsi_1", "wsi_2"]
    preprocessing_config = {}

    with (
        patch("gateway.pipeline.TrainingTaskRepository") as mock_repo,
        patch("gateway.pipeline.ScopedLogger") as mock_logger_cls,
    ):
        mock_logger = MagicMock()
        mock_logger_cls.return_value = mock_logger
        mock_logger.session.return_value.__aenter__ = AsyncMock(return_value=(AsyncMock(), AsyncMock()))
        mock_logger.session.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_repo.update_status = AsyncMock()
        # First call sets PATCHING, second call (per-WSI check) returns CANCELLED
        mock_repo.get_by_id = AsyncMock(return_value=MagicMock(status="cancelled"))

        from gateway.pipeline import run_patching_stage
        import asyncio
        with pytest.raises(asyncio.CancelledError):
            await run_patching_stage(task_id, wsi_ids, preprocessing_config)
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
python -m pytest server/tests/test_patching_stage.py -v
```
Expected: FAIL (ImportError: `run_patching_stage` does not exist yet)

- [ ] **Step 3: Extract `run_patching_stage` in `pipeline.py`**

Add this function BEFORE `run_training_pipeline` (insert before line 534):

```python
async def run_patching_stage(
    task_id: str,
    wsi_ids: List[str],
    preprocessing_config: Dict[str, Any],
) -> None:
    """
    Run the CPU-only patch coordinate extraction stage.

    Runs OUTSIDE the GPU task queue — does not consume a GPU concurrency slot.
    Cancellation via asyncio.Task.cancel() raises CancelledError at each await point.
    DB status poll (belt-and-suspenders) also stops early if status == CANCELLED.
    """
    logger_manager = ScopedLogger(task_id)

    total_wsi = len(wsi_ids)
    level = preprocessing_config.get("level", 0)
    sthresh = preprocessing_config.get("sthresh", 8)
    mthresh = preprocessing_config.get("mthresh", 7)
    close = preprocessing_config.get("close", 4)
    use_otsu = preprocessing_config.get("use_otsu", False)
    contour_fn = preprocessing_config.get("contour_fn", "four_pt")
    use_padding = preprocessing_config.get("use_padding", True)
    a_t = preprocessing_config.get("a_t", 1)
    a_h = preprocessing_config.get("a_h", 256)
    max_n_holes = preprocessing_config.get("max_n_holes", 100)
    coords_request_params = {
        "level": level,
        "force_recompute": False,
        "sthresh": sthresh,
        "mthresh": mthresh,
        "close": close,
        "use_otsu": use_otsu,
        "contour_fn": contour_fn,
        "use_padding": use_padding,
        "a_t": a_t,
        "a_h": a_h,
        "max_n_holes": max_n_holes,
        "save_mask": True,
    }

    async with logger_manager.session() as (log, db):
        await TrainingTaskRepository.update_status(
            db, task_id, TaskStatus.PATCHING, progress=0
        )
        await log.info(f"Extracting patches from {total_wsi} WSI slides")
        await log.info(f"Level: {level}", metadata={"level": level})

    for idx, wsi_id in enumerate(wsi_ids, 1):
        # Yield control: asyncio.Task.cancel() raises CancelledError here
        await asyncio.sleep(0)

        # Belt-and-suspenders: check DB status for external cancellation signals
        async with logger_manager.session() as (_, db):
            task_record = await TrainingTaskRepository.get_by_id(db, task_id)
            if not task_record or task_record.status == TaskStatus.CANCELLED:
                logger.info(
                    f"[{task_id}] Task cancelled during patch extraction at WSI {idx}/{total_wsi}, stopping"
                )
                raise asyncio.CancelledError()

        try:
            async with logger_manager.session() as (log, db):
                await log.info(
                    f"Processing WSI {idx}/{total_wsi}: {wsi_id}",
                    metadata={"wsi_index": idx, "total_wsi": total_wsi, "wsi_id": wsi_id},
                )

            async def _log_retry(attempt: int, max_retries: int, retry_err: Exception, wait_secs: int):
                async with logger_manager.session() as (log, db):
                    await log.warning(
                        f"[{idx}/{total_wsi}] compute_patches attempt {attempt}/{max_retries} "
                        f"failed for {wsi_id}: {type(retry_err).__name__}. "
                        f"Retrying in {wait_secs}s (cached coords will be used on retry)...",
                        metadata={"wsi_id": wsi_id, "attempt": attempt, "error": str(retry_err)},
                    )

            async def _log_lock_wait(wait_seconds: float):
                async with logger_manager.session() as (log, db):
                    await log.info(
                        f"[{idx}/{total_wsi}] Waiting {wait_seconds:.0f}s for shared coords extraction lock on {wsi_id}",
                        metadata={"wsi_id": wsi_id, "wait_seconds": wait_seconds},
                    )

            result = await ensure_coords_ready(
                wsi_id,
                params=coords_request_params,
                timeout=600.0,
                uploads_root=Config.get_uploads_dir(),
                on_retry=_log_retry,
                on_lock_wait=_log_lock_wait,
            )

            num_patches = result.get("num_patches", 0)
            cached = result.get("cached", False)

            async with logger_manager.session() as (log, db):
                if num_patches == 0:
                    await log.warning(
                        f"[{idx}/{total_wsi}] No tissue patches found for {wsi_id} — "
                        f"the slide may be blank or contain no detectable tissue. "
                        f"It will be skipped during feature extraction.",
                        metadata={"wsi_id": wsi_id, "num_patches": 0, "cached": cached},
                    )
                elif cached:
                    await log.info(
                        f"[{idx}/{total_wsi}] Coords cache hit for {wsi_id}",
                        metadata={"wsi_id": wsi_id, "num_patches": num_patches, "cached": True},
                    )
                else:
                    await log.info(
                        f"[{idx}/{total_wsi}] Extracted {num_patches} patches from {wsi_id}",
                        metadata={"wsi_id": wsi_id, "num_patches": num_patches, "cached": False},
                    )

                progress = int((idx / total_wsi) * 33)
                await TrainingTaskRepository.update_status(
                    db, task_id, TaskStatus.PATCHING, progress=progress
                )

        except asyncio.CancelledError:
            raise
        except Exception as e:
            import traceback as _tb
            err_type = type(e).__name__
            err_msg = str(e) or repr(e)
            err_tb = _tb.format_exc()
            resp_body = ""
            if isinstance(e, httpx.HTTPStatusError):
                try:
                    resp_body = e.response.text[:1000]
                except Exception:
                    resp_body = "(unable to read response body)"
            async with logger_manager.session() as (log, db):
                await log.error(
                    f"Failed to extract patches from {wsi_id}: [{err_type}] {err_msg}",
                    metadata={
                        "wsi_id": wsi_id,
                        "error": err_msg,
                        "error_type": err_type,
                        "response_body": resp_body,
                        "traceback": err_tb,
                    },
                )
            raise

    async with logger_manager.session() as (log, db):
        await log.info(f"Patch extraction completed for all {total_wsi} WSI slides")
```

- [ ] **Step 4: Add `patching_complete: bool = False` to `run_training_pipeline` signature and update WSI branch**

Replace the current `run_training_pipeline` signature and WSI step 1 block:

Old signature (line 534):
```python
async def run_training_pipeline(
    task_id: str,
    data_type: str,
    wsi_ids: List[str],
    preprocessing_config: Dict[str, Any],
    model_config: Dict[str, Any],
    huggingface_token: str = None,
    training_task_type: str = "classification",  # "classification", "survival", or "segmentation"
    assigned_device: str = None,  # GPU device assigned by task queue (e.g., "cuda:0")
    user_id: str = None,  # User who submitted the task (for permission checks)
    user_is_admin: bool = False,  # Whether the submitting user is admin
):
```

New signature:
```python
async def run_training_pipeline(
    task_id: str,
    data_type: str,
    wsi_ids: List[str],
    preprocessing_config: Dict[str, Any],
    model_config: Dict[str, Any],
    huggingface_token: str = None,
    training_task_type: str = "classification",  # "classification", "survival", or "segmentation"
    assigned_device: str = None,  # GPU device assigned by task queue (e.g., "cuda:0")
    user_id: str = None,  # User who submitted the task (for permission checks)
    user_is_admin: bool = False,  # Whether the submitting user is admin
    patching_complete: bool = False,  # True when patching was run pre-queue (WSI tasks only)
):
```

Old WSI step 1 block (lines 774-924 — the entire patching loop):
```python
        # Step 1: Patch extraction for WSI-level tasks
        # Note: patch_size and stride are now auto-determined by PrePATH-style tiling
        # based on WSI magnification to ensure consistent physical coverage (~128μm)
        total_wsi = len(wsi_ids)
        level = preprocessing_config.get("level", 0)

        # Tissue segmentation parameters (defaults match constants/training.ts)
        sthresh = preprocessing_config.get("sthresh", 8)
        ...  (entire loop until line 924)
```

New WSI step 1 block (replace lines 774-928 entirely):
```python
        # Step 1: Patch extraction for WSI-level tasks
        # When patching_complete=True, patch extraction was performed pre-queue
        # (before entering the GPU concurrency gate). Skip it here.
        if patching_complete:
            async with logger_manager.session() as (log, db):
                await log.info(
                    f"Patch extraction already complete (pre-queue), "
                    f"skipping patching stage for {len(wsi_ids)} WSI slides"
                )
        else:
            await run_patching_stage(
                task_id=task_id,
                wsi_ids=wsi_ids,
                preprocessing_config=preprocessing_config,
            )
```

- [ ] **Step 5: Run test to confirm it passes**

```bash
python -m pytest server/tests/test_patching_stage.py -v
```
Expected: PASS

- [ ] **Step 6: Run full test suite to check no regressions**

```bash
python -m pytest server/tests/ -v -k "not pretrained"
```
Expected: All pre-existing tests pass

- [ ] **Step 7: Commit**

```bash
git add server/gateway/pipeline.py server/tests/test_patching_stage.py
git commit -m "refactor(pipeline): extract run_patching_stage, add patching_complete param"
```

---

## Task 2: Add `run_patching_then_submit` coordinator to `pipeline.py`

**Files:**
- Modify: `server/gateway/pipeline.py` (add new function near bottom)
- Test: `server/tests/test_patching_stage.py` (extend)

- [ ] **Step 1: Write failing tests for `run_patching_then_submit`**

Add to `server/tests/test_patching_stage.py`:

```python
@pytest.mark.asyncio
async def test_run_patching_then_submit_happy_path():
    """On success: runs patching, sets status to QUEUED, submits to GPU queue."""
    task_id = "test_happy"
    pipeline_kwargs = {
        "data_type": "wsi",
        "wsi_ids": ["wsi_1"],
        "preprocessing_config": {},
        "model_config": {},
        "training_task_type": "classification",
    }

    mock_queue = AsyncMock()
    mock_queue.submit = AsyncMock()

    with (
        patch("gateway.pipeline.run_patching_stage", new_callable=AsyncMock) as mock_patching,
        patch("gateway.pipeline.get_task_queue", return_value=mock_queue),
        patch("gateway.pipeline.TrainingTaskRepository") as mock_repo,
        patch("gateway.pipeline.safe_session") as mock_safe_session,
    ):
        mock_task = MagicMock(status="patching")
        mock_repo.get_by_id = AsyncMock(return_value=mock_task)
        mock_repo.update_status = AsyncMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_safe_session.return_value = ctx

        from gateway.pipeline import run_patching_then_submit
        await run_patching_then_submit(task_id, pipeline_kwargs)

    mock_patching.assert_awaited_once()
    mock_queue.submit.assert_awaited_once()
    # patching_complete=True must be in the submitted kwargs
    submitted_kwargs = mock_queue.submit.call_args.kwargs
    assert submitted_kwargs.get("patching_complete") is True


@pytest.mark.asyncio
async def test_run_patching_then_submit_cancellation():
    """On CancelledError during patching: sets DB status to CANCELLED, re-raises."""
    import asyncio
    task_id = "test_cancel"
    pipeline_kwargs = {"data_type": "wsi", "wsi_ids": ["wsi_1"], "preprocessing_config": {}}

    mock_queue = MagicMock()
    mock_queue.deregister_patching_task = MagicMock()

    with (
        patch("gateway.pipeline.run_patching_stage", side_effect=asyncio.CancelledError),
        patch("gateway.pipeline.get_task_queue", return_value=mock_queue),
        patch("gateway.pipeline.TrainingTaskRepository") as mock_repo,
        patch("gateway.pipeline.safe_session") as mock_safe_session,
    ):
        from backend.ai.schemas.base import TaskStatus
        mock_task = MagicMock(status="patching")
        mock_repo.get_by_id = AsyncMock(return_value=mock_task)
        mock_repo.update_status = AsyncMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_safe_session.return_value = ctx

        from gateway.pipeline import run_patching_then_submit
        with pytest.raises(asyncio.CancelledError):
            await run_patching_then_submit(task_id, pipeline_kwargs)

    # Ensure deregister is called
    mock_queue.deregister_patching_task.assert_called_once_with(task_id)
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest server/tests/test_patching_stage.py::test_run_patching_then_submit_happy_path server/tests/test_patching_stage.py::test_run_patching_then_submit_cancellation -v
```
Expected: FAIL (ImportError)

- [ ] **Step 3: Add `run_patching_then_submit` to `pipeline.py`**

Add this function after `run_patching_stage` and before `run_training_pipeline`:

```python
async def run_patching_then_submit(task_id: str, pipeline_kwargs: dict) -> None:
    """
    Coordinator for WSI tasks: run CPU-only patching outside the GPU gate, then
    submit the GPU pipeline (feature extraction + training) to the task queue.

    Lifecycle:
      PENDING → PATCHING (set by run_patching_stage) → QUEUED (submitted to GPU queue)

    Called as a background asyncio.Task registered with TaskQueueManager._patching_tasks.
    Cancellation via asyncio.Task.cancel() propagates as CancelledError; the handler
    updates DB status to CANCELLED and deregisters from the queue manager.
    """
    # Lazy import to avoid circular dependency at module load time
    from .task_queue import get_task_queue, TaskType

    try:
        await run_patching_stage(
            task_id=task_id,
            wsi_ids=pipeline_kwargs["wsi_ids"],
            preprocessing_config=pipeline_kwargs.get("preprocessing_config", {}),
        )

        # Belt-and-suspenders: confirm not cancelled before submitting to GPU queue
        async with safe_session() as db:
            task_record = await TrainingTaskRepository.get_by_id(db, task_id)
            if not task_record or task_record.status == TaskStatus.CANCELLED:
                logger.info(
                    f"[{task_id}] Task cancelled after patching completion, not submitting to GPU queue"
                )
                return

        # Patching done — submit GPU pipeline to queue with patching_complete=True
        gpu_kwargs = {**pipeline_kwargs, "patching_complete": True}
        task_queue = get_task_queue()
        await task_queue.submit(
            task_id=task_id,
            task_type=TaskType.TRAINING,
            coro_func=run_training_pipeline,
            **gpu_kwargs,
        )

        async with safe_session() as db:
            await TrainingTaskRepository.update_status(
                db, task_id, TaskStatus.QUEUED, progress=33
            )
            await db.commit()

        logger.info(
            f"[{task_id}] Patching complete, submitted to GPU queue (progress=33%)"
        )

    except asyncio.CancelledError:
        logger.info(f"[{task_id}] Pre-queue patching cancelled")
        try:
            async with safe_session() as db:
                task_record = await TrainingTaskRepository.get_by_id(db, task_id)
                if task_record and task_record.status not in (
                    TaskStatus.CANCELLED,
                    TaskStatus.FAILED,
                    TaskStatus.COMPLETED,
                ):
                    await TrainingTaskRepository.update_status(
                        db, task_id, TaskStatus.CANCELLED
                    )
                    await db.commit()
        except Exception as db_err:
            logger.error(
                f"[{task_id}] Failed to update cancelled status after patching cancellation: {db_err}"
            )
        raise

    except Exception as e:
        import traceback as _tb
        err_msg = str(e) or repr(e)
        logger.error(f"[{task_id}] Pre-queue patching failed: [{type(e).__name__}] {err_msg}")
        try:
            async with safe_session() as db:
                task_record = await TrainingTaskRepository.get_by_id(db, task_id)
                if task_record and task_record.status not in (
                    TaskStatus.CANCELLED,
                    TaskStatus.FAILED,
                    TaskStatus.COMPLETED,
                ):
                    await TrainingTaskRepository.update_status(
                        db,
                        task_id,
                        TaskStatus.FAILED,
                        error_message=f"Patch extraction failed: [{type(e).__name__}] {err_msg}",
                    )
                    await db.commit()
        except Exception as db_err:
            logger.error(
                f"[{task_id}] Failed to update failed status after patching error: {db_err}"
            )

    finally:
        # Always deregister from queue manager regardless of outcome
        try:
            from .task_queue import get_task_queue
            get_task_queue().deregister_patching_task(task_id)
        except Exception:
            pass
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
python -m pytest server/tests/test_patching_stage.py -v
```
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add server/gateway/pipeline.py server/tests/test_patching_stage.py
git commit -m "feat(pipeline): add run_patching_then_submit pre-queue coordinator"
```

---

## Task 3: Add pre-queue patching task tracking to `TaskQueueManager`

**Files:**
- Modify: `server/gateway/task_queue.py`
- Test: `server/tests/test_task_queue_patching.py` (new)

- [ ] **Step 1: Write failing tests**

```python
# server/tests/test_task_queue_patching.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def fresh_queue():
    """Create a fresh TaskQueueManager (reset singleton state)."""
    from gateway.task_queue import TaskQueueManager
    TaskQueueManager._instance = None
    TaskQueueManager._initialized = False
    queue = TaskQueueManager(max_concurrent=2, gpu_count=2)
    return queue


@pytest.mark.asyncio
async def test_register_and_cancel_patching_task(fresh_queue):
    """cancel_task cancels a registered pre-queue patching task."""
    queue = fresh_queue
    queue._condition = asyncio.Condition()
    queue._vram_condition = asyncio.Condition()

    # Create a real asyncio task that stays alive until cancelled
    async def _forever():
        while True:
            await asyncio.sleep(1)

    task = asyncio.create_task(_forever())
    queue.register_patching_task("task_abc", task)

    assert queue.is_task_in_queue("task_abc")

    cancelled = await queue.cancel_task("task_abc")

    assert cancelled is True
    assert "task_abc" not in queue._patching_tasks
    # The asyncio task should be cancelled
    await asyncio.sleep(0)  # let event loop process cancellation
    assert task.cancelled()


@pytest.mark.asyncio
async def test_is_task_in_queue_includes_patching(fresh_queue):
    """is_task_in_queue returns True for pre-queue patching tasks."""
    queue = fresh_queue
    mock_task = MagicMock()
    queue.register_patching_task("task_xyz", mock_task)

    assert queue.is_task_in_queue("task_xyz") is True
    assert queue.is_task_in_queue("unknown_task") is False


@pytest.mark.asyncio
async def test_get_status_includes_patching_count(fresh_queue):
    """get_status includes patching_count and patching_task_ids."""
    queue = fresh_queue
    mock_task = MagicMock()
    queue.register_patching_task("task_patching", mock_task)

    with patch("backend.common.gpu_utils.get_all_gpu_info", return_value=[]), \
         patch("backend.common.gpu_utils.check_vram_available", return_value=(True, 8000.0, "ok")):
        status = queue.get_status()

    assert status["patching_count"] == 1
    assert "task_patching" in status["patching_task_ids"]


def test_deregister_patching_task(fresh_queue):
    """deregister_patching_task removes task from _patching_tasks."""
    queue = fresh_queue
    mock_task = MagicMock()
    queue.register_patching_task("task_dereg", mock_task)
    assert "task_dereg" in queue._patching_tasks

    queue.deregister_patching_task("task_dereg")
    assert "task_dereg" not in queue._patching_tasks
    # Calling again is idempotent
    queue.deregister_patching_task("task_dereg")
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest server/tests/test_task_queue_patching.py -v
```
Expected: FAIL (AttributeError: `register_patching_task` not found)

- [ ] **Step 3: Add `_patching_tasks` dict and methods to `TaskQueueManager.__init__`**

In `task_queue.py`, in `TaskQueueManager.__init__`, after `self._bad_gpus: set = set()` (line 108), add:

```python
        self._patching_tasks: Dict[str, asyncio.Task[Any]] = {}  # pre-queue patching tasks
```

- [ ] **Step 4: Add `register_patching_task` and `deregister_patching_task` methods**

Add after `get_bad_gpus` method (after line 196):

```python
    def register_patching_task(self, task_id: str, task: "asyncio.Task[Any]") -> None:
        """Register a pre-queue patching asyncio.Task for cancellation tracking."""
        self._patching_tasks[task_id] = task
        logger.info(
            f"Pre-queue patching task {task_id} registered. "
            f"Active patching tasks: {len(self._patching_tasks)}"
        )

    def deregister_patching_task(self, task_id: str) -> None:
        """Remove a pre-queue patching task after completion or cancellation."""
        removed = self._patching_tasks.pop(task_id, None)
        if removed is not None:
            logger.debug(f"Pre-queue patching task {task_id} deregistered")
```

- [ ] **Step 5: Update `cancel_task` to check `_patching_tasks` first**

In `cancel_task` method (currently line 798), add pre-queue check at the top of the method body:

```python
    async def cancel_task(self, task_id: str) -> bool:
        # Check pre-queue patching tasks (before entering GPU queue)
        if task_id in self._patching_tasks:
            patching_task = self._patching_tasks.pop(task_id)
            patching_task.cancel()
            logger.info(f"Pre-queue patching task {task_id} cancelled")
            await self._notify_queue_state_changed()
            return True

        if task_id in self._running_tasks:
            task = self._running_tasks[task_id]
            task.cancel()
            logger.info(f"Task {task_id} cancelled")
            await self._notify_queue_state_changed()
            return True

        if await self.cancel_pending_task(task_id):
            return True

        return False
```

- [ ] **Step 6: Update `is_task_in_queue` to include patching tasks**

Replace the current `is_task_in_queue` method (line 783):

```python
    def is_task_in_queue(self, task_id: str) -> bool:
        """Check if a task is tracked (patching pre-queue, pending in queue, or running)."""
        return (
            task_id in self._running_tasks
            or task_id in self._pending_tasks
            or task_id in self._patching_tasks
        )
```

- [ ] **Step 7: Update `get_status` to include patching info**

In `get_status` method (line 706), add patching counts to the status dict:

After `"running_task_ids": list(self._running_tasks.keys()),` and before `"pending_task_ids"`:

```python
            "patching_count": len(self._patching_tasks),
            "patching_task_ids": list(self._patching_tasks.keys()),
```

- [ ] **Step 8: Add warning log to `_select_optimal_gpu` when returning -1**

At the end of `_select_optimal_gpu`, before `return best_gpu` (the final Strategy 2 return, line 260), add:

```python
        if best_gpu < 0:
            logger.warning(
                f"_select_optimal_gpu: no suitable GPU found. "
                f"Checked {len(gpu_info_list)} GPU(s), required {self.min_vram_mb:.0f} MB free. "
                f"Bad GPUs: {sorted(self._bad_gpus)}, "
                f"GPUs with running tasks: {sorted(gpus_with_tasks)}"
            )
        return best_gpu
```

- [ ] **Step 9: Run tests to confirm pass**

```bash
python -m pytest server/tests/test_task_queue_patching.py -v
```
Expected: All PASS

- [ ] **Step 10: Run full test suite**

```bash
python -m pytest server/tests/ -v -k "not pretrained"
```
Expected: All pass

- [ ] **Step 11: Commit**

```bash
git add server/gateway/task_queue.py server/tests/test_task_queue_patching.py
git commit -m "feat(task_queue): add pre-queue patching task tracking and cancel support"
```

---

## Task 4: Update `_validate_files_and_enqueue` to route WSI vs patch tasks

**Files:**
- Modify: `server/gateway/routes/training.py:181-240`
- Test: `server/tests/test_training_routing.py` (new)

- [ ] **Step 1: Write failing test**

```python
# server/tests/test_training_routing.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call


@pytest.mark.asyncio
async def test_wsi_task_launches_pre_queue_patching():
    """WSI tasks launch run_patching_then_submit and register with queue manager."""
    pipeline_kwargs = {
        "data_type": "wsi",
        "wsi_ids": ["wsi_1", "wsi_2"],
        "preprocessing_config": {},
        "model_config": {},
        "training_task_type": "classification",
    }
    mock_queue = MagicMock()
    mock_queue.register_patching_task = MagicMock()
    mock_queue.submit = AsyncMock()

    with (
        patch("gateway.routes.training.get_task_queue", return_value=mock_queue),
        patch("gateway.routes.training.run_patching_then_submit", new_callable=AsyncMock) as mock_patching,
        patch("gateway.routes.training._check_file_accessibility", return_value=[]),
        patch("gateway.routes.training.TrainingTaskRepository") as mock_repo,
        patch("gateway.routes.training.TrainingLogger"),
    ):
        mock_repo.update_status = AsyncMock()

        from gateway.routes.training import _validate_files_and_enqueue
        await _validate_files_and_enqueue(
            task_id="task_wsi",
            paths_to_check=[],
            uploads_dir="/uploads",
            pipeline_kwargs=pipeline_kwargs,
        )

    # Queue submit should NOT be called (patching_then_submit handles submission)
    mock_queue.submit.assert_not_awaited()
    # register_patching_task should be called
    mock_queue.register_patching_task.assert_called_once()


@pytest.mark.asyncio
async def test_patch_task_submits_directly_to_queue():
    """Patch tasks submit directly to GPU queue without pre-queue patching."""
    pipeline_kwargs = {
        "data_type": "patch",
        "wsi_ids": ["img_1"],
        "preprocessing_config": {},
        "model_config": {},
        "training_task_type": "classification",
    }
    mock_queue = AsyncMock()
    mock_queue.register_patching_task = MagicMock()

    with (
        patch("gateway.routes.training.get_task_queue", return_value=mock_queue),
        patch("gateway.routes.training.run_patching_then_submit", new_callable=AsyncMock) as mock_patching,
        patch("gateway.routes.training._check_file_accessibility", return_value=[]),
        patch("gateway.routes.training.TrainingTaskRepository") as mock_repo,
        patch("gateway.routes.training.safe_session") as mock_safe,
        patch("gateway.routes.training.TrainingLogger"),
    ):
        mock_repo.update_status = AsyncMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_safe.return_value = ctx

        from gateway.routes.training import _validate_files_and_enqueue
        await _validate_files_and_enqueue(
            task_id="task_patch",
            paths_to_check=[],
            uploads_dir="/uploads",
            pipeline_kwargs=pipeline_kwargs,
        )

    mock_queue.submit.assert_awaited_once()
    mock_patching.assert_not_awaited()
    mock_queue.register_patching_task.assert_not_called()
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest server/tests/test_training_routing.py -v
```
Expected: FAIL

- [ ] **Step 3: Update `_validate_files_and_enqueue` in `routes/training.py`**

Add import at top of file:

```python
from ..pipeline import run_training_pipeline, run_patching_then_submit
```

Replace the submission block in `_validate_files_and_enqueue` (lines 218-240):

Old:
```python
    task_queue = get_task_queue()
    await task_queue.submit(
        task_id=task_id,
        task_type=TaskType.TRAINING,
        coro_func=run_training_pipeline,
        **pipeline_kwargs,
    )

    async with safe_session() as db:
        await TrainingTaskRepository.update_status(
            db, task_id, TaskStatus.QUEUED, progress=0
        )
        await db.commit()

    await training_logger.info(
        "[Queue] Task submitted to training queue, waiting for available worker/GPU resources",
        metadata={
            "status": TaskStatus.QUEUED,
            "task_type": pipeline_kwargs.get("training_task_type"),
            "data_type": pipeline_kwargs.get("data_type"),
            "wsi_count": len(pipeline_kwargs.get("wsi_ids", [])),
        },
    )
```

New:
```python
    task_queue = get_task_queue()

    if pipeline_kwargs.get("data_type") == "wsi":
        # WSI tasks: run CPU-only patch extraction BEFORE consuming a GPU concurrency slot.
        # This prevents GPU slots from being held during the (potentially long) patching phase.
        patching_coro = run_patching_then_submit(task_id, pipeline_kwargs)
        patching_task = asyncio.create_task(patching_coro)
        task_queue.register_patching_task(task_id, patching_task)

        await training_logger.info(
            "[PreQueue] Starting patch extraction before GPU queue submission",
            metadata={
                "status": TaskStatus.PATCHING,
                "task_type": pipeline_kwargs.get("training_task_type"),
                "data_type": "wsi",
                "wsi_count": len(pipeline_kwargs.get("wsi_ids", [])),
            },
        )
    else:
        # Patch tasks (classification/segmentation): no patching stage, go directly to GPU queue.
        await task_queue.submit(
            task_id=task_id,
            task_type=TaskType.TRAINING,
            coro_func=run_training_pipeline,
            **pipeline_kwargs,
        )

        async with safe_session() as db:
            await TrainingTaskRepository.update_status(
                db, task_id, TaskStatus.QUEUED, progress=0
            )
            await db.commit()

        await training_logger.info(
            "[Queue] Patch task submitted to GPU queue, waiting for available worker/GPU resources",
            metadata={
                "status": TaskStatus.QUEUED,
                "task_type": pipeline_kwargs.get("training_task_type"),
                "data_type": pipeline_kwargs.get("data_type"),
                "wsi_count": len(pipeline_kwargs.get("wsi_ids", [])),
            },
        )
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
python -m pytest server/tests/test_training_routing.py -v
```
Expected: All PASS

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest server/tests/ -v -k "not pretrained"
```
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add server/gateway/routes/training.py server/tests/test_training_routing.py
git commit -m "feat(training): route WSI tasks through pre-queue patching before GPU submission"
```

---

## Task 5: Update `resume_interrupted_tasks` in `main.py`

**Files:**
- Modify: `server/gateway/main.py:506-638`
- Test: `server/tests/test_resume_tasks.py` (new)

- [ ] **Step 1: Write failing tests**

```python
# server/tests/test_resume_tasks.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from backend.ai.schemas.base import TaskStatus


def _make_task(task_id, status, data_type="wsi", task_type="classification"):
    task = MagicMock()
    task.task_id = task_id
    task.task_name = f"Task {task_id}"
    task.status = status
    task.preprocessing_config = {}
    task.model_config = {}
    task.classes = []
    task.data_group = MagicMock()
    task.data_group.data_type = data_type
    task.data_group.task_type = task_type
    return task


@pytest.mark.asyncio
async def test_resume_wsi_extracting_task_skips_patching():
    """WSI task in EXTRACTING state resumes with patching_complete=True."""
    task = _make_task("task_ext", TaskStatus.EXTRACTING, data_type="wsi")

    mock_queue = AsyncMock()
    mock_queue.submit = AsyncMock()
    mock_repo = AsyncMock()
    mock_repo.get_interrupted_tasks = AsyncMock(return_value=[task])
    mock_repo.get_wsi_ids = AsyncMock(return_value=["wsi_1"])
    mock_repo.try_claim_for_resume = AsyncMock(return_value=True)

    with (
        patch("gateway.main.TrainingTaskRepository", mock_repo),
        patch("gateway.main.get_task_queue", return_value=mock_queue),
        patch("gateway.main.wait_for_services_ready", return_value=True),
        patch("gateway.main.run_patching_then_submit", new_callable=AsyncMock) as mock_patching,
        patch("gateway.main.get_db") as mock_get_db,
    ):
        db_mock = AsyncMock()
        db_mock.commit = AsyncMock()
        mock_get_db.return_value.__aiter__ = lambda self: iter([db_mock])

        from gateway.main import resume_interrupted_tasks
        await resume_interrupted_tasks()

    # Should submit to GPU queue with patching_complete=True
    mock_queue.submit.assert_awaited_once()
    submitted_kwargs = mock_queue.submit.call_args.kwargs
    assert submitted_kwargs.get("patching_complete") is True
    # Should NOT launch pre-queue patching
    mock_patching.assert_not_awaited()


@pytest.mark.asyncio
async def test_resume_wsi_patching_task_reruns_patching():
    """WSI task in PATCHING state resumes via pre-queue patching (cached = fast)."""
    task = _make_task("task_patch_state", TaskStatus.PATCHING, data_type="wsi")

    mock_queue = MagicMock()
    mock_queue.submit = AsyncMock()
    mock_queue.register_patching_task = MagicMock()
    mock_repo = AsyncMock()
    mock_repo.get_interrupted_tasks = AsyncMock(return_value=[task])
    mock_repo.get_wsi_ids = AsyncMock(return_value=["wsi_1"])
    mock_repo.try_claim_for_resume = AsyncMock(return_value=True)

    with (
        patch("gateway.main.TrainingTaskRepository", mock_repo),
        patch("gateway.main.get_task_queue", return_value=mock_queue),
        patch("gateway.main.wait_for_services_ready", return_value=True),
        patch("gateway.main.run_patching_then_submit", new_callable=AsyncMock) as mock_patching,
        patch("gateway.main.get_db") as mock_get_db,
        patch("gateway.main.asyncio") as mock_asyncio,
    ):
        db_mock = AsyncMock()
        db_mock.commit = AsyncMock()
        mock_get_db.return_value.__aiter__ = lambda self: iter([db_mock])
        mock_patching_task = MagicMock()
        mock_asyncio.create_task.return_value = mock_patching_task

        from gateway.main import resume_interrupted_tasks
        await resume_interrupted_tasks()

    # Should launch pre-queue patching, NOT submit directly to GPU queue
    mock_queue.submit.assert_not_awaited()
    mock_queue.register_patching_task.assert_called_once()


@pytest.mark.asyncio
async def test_resume_patch_task_submits_to_queue():
    """Patch task resumes by submitting directly to GPU queue."""
    task = _make_task("task_patch_cls", TaskStatus.TRAINING, data_type="patch")

    mock_queue = AsyncMock()
    mock_queue.submit = AsyncMock()
    mock_repo = AsyncMock()
    mock_repo.get_interrupted_tasks = AsyncMock(return_value=[task])
    mock_repo.get_wsi_ids = AsyncMock(return_value=["img_1"])
    mock_repo.try_claim_for_resume = AsyncMock(return_value=True)

    with (
        patch("gateway.main.TrainingTaskRepository", mock_repo),
        patch("gateway.main.get_task_queue", return_value=mock_queue),
        patch("gateway.main.wait_for_services_ready", return_value=True),
        patch("gateway.main.run_patching_then_submit", new_callable=AsyncMock) as mock_patching,
        patch("gateway.main.get_db") as mock_get_db,
    ):
        db_mock = AsyncMock()
        db_mock.commit = AsyncMock()
        mock_get_db.return_value.__aiter__ = lambda self: iter([db_mock])

        from gateway.main import resume_interrupted_tasks
        await resume_interrupted_tasks()

    mock_queue.submit.assert_awaited_once()
    mock_patching.assert_not_awaited()
    # patching_complete not set for patch tasks (or False by default)
    submitted_kwargs = mock_queue.submit.call_args.kwargs
    assert submitted_kwargs.get("patching_complete", False) is False
```

- [ ] **Step 2: Run to confirm failure**

```bash
python -m pytest server/tests/test_resume_tasks.py -v
```
Expected: FAIL

- [ ] **Step 3: Update `resume_interrupted_tasks` in `main.py`**

Add import at top of `main.py`:
```python
from .pipeline import run_training_pipeline, run_patching_then_submit
```

Replace the `else:` block (the non-`external_validation` branch, lines 619-638) in `resume_interrupted_tasks`:

Old:
```python
                    else:
                        pipeline_kwargs = {
                            "data_type": data_type,
                            "wsi_ids": wsi_ids,
                            "preprocessing_config": task.preprocessing_config or {},
                            "model_config": task.model_config or {},
                            "huggingface_token": None,
                            "training_task_type": task_type,  # Use same param name as pipeline
                        }
                        await task_queue.submit(
                            task_id=task.task_id,
                            task_type=TaskType.TRAINING,
                            coro_func=run_training_pipeline,
                            **pipeline_kwargs,
                        )
```

New:
```python
                    else:
                        pipeline_kwargs = {
                            "data_type": data_type,
                            "wsi_ids": wsi_ids,
                            "preprocessing_config": task.preprocessing_config or {},
                            "model_config": task.model_config or {},
                            # Token not persisted for security. If HF model not yet cached,
                            # user must re-submit with their token.
                            "huggingface_token": None,
                            "training_task_type": task_type,
                        }

                        if data_type == "wsi" and task.status in (
                            TaskStatus.EXTRACTING,
                            TaskStatus.TRAINING,
                        ):
                            # Task was already past patching when interrupted.
                            # Submit directly to GPU queue and skip re-running patching.
                            # feature extraction / training use force_recompute=False so they
                            # resume from where they left off via cached features/checkpoints.
                            gpu_kwargs = {**pipeline_kwargs, "patching_complete": True}
                            await task_queue.submit(
                                task_id=task.task_id,
                                task_type=TaskType.TRAINING,
                                coro_func=run_training_pipeline,
                                **gpu_kwargs,
                            )
                            logger.info(
                                f"  - Resumed at GPU stage (patching already done, "
                                f"submitting with patching_complete=True)"
                            )

                        elif data_type == "wsi":
                            # PENDING / QUEUED / PATCHING / RESUMING WSI task:
                            # re-run patching pre-queue. Coordinates are cached so
                            # patching is nearly instant (cache hits).
                            patching_coro = run_patching_then_submit(
                                task.task_id, pipeline_kwargs
                            )
                            patching_task = asyncio.create_task(patching_coro)
                            task_queue.register_patching_task(task.task_id, patching_task)
                            logger.info(
                                f"  - Resumed at patching stage (pre-queue, "
                                f"status was '{task.status}')"
                            )

                        else:
                            # Patch task (data_type == "patch"):
                            # No patching stage — submit directly to GPU queue.
                            await task_queue.submit(
                                task_id=task.task_id,
                                task_type=TaskType.TRAINING,
                                coro_func=run_training_pipeline,
                                **pipeline_kwargs,
                            )
                            logger.info(
                                f"  - Patch task resumed directly to GPU queue "
                                f"(data_type=patch, no patching stage)"
                            )
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
python -m pytest server/tests/test_resume_tasks.py -v
```
Expected: All PASS

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest server/tests/ -v -k "not pretrained"
```
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add server/gateway/main.py server/tests/test_resume_tasks.py
git commit -m "fix(scheduler): WSI patching runs outside GPU concurrency gate, fix task resume"
```

---

## Task 6: Final verification

- [ ] **Step 1: Run lsp diagnostics on all changed files**

```bash
python -m py_compile server/gateway/pipeline.py server/gateway/task_queue.py server/gateway/routes/training.py server/gateway/main.py
```
Expected: No output (no syntax errors)

- [ ] **Step 2: Run full test suite one last time**

```bash
python -m pytest server/tests/ -v -k "not pretrained" --tb=short
```
Expected: All pass

- [ ] **Step 3: Verify status flow is correct (manual trace)**

Trace the status transitions for a new 8-GPU WSI task submission:

```
HTTP POST /tasks/training (data_type=wsi)
  → DB: status=PENDING
  → asyncio.create_task(_validate_files_and_enqueue)
     → file check passes
     → asyncio.create_task(run_patching_then_submit) ← NEW: no GPU slot consumed
     → queue.register_patching_task(task_id, task)
     → returns (task is now PENDING, pre-queue patching running)

run_patching_then_submit:
  → run_patching_stage() → DB: status=PATCHING, progress=0..33%
  → patching loop completes (all wsi_ids processed)
  → DB: status=QUEUED, progress=33%
  → task_queue.submit(run_training_pipeline, patching_complete=True) ← GPU slot acquired here
  → deregister_patching_task

task_queue._worker_loop:
  → Waits for slot: len(_running_tasks) < max_concurrent
  → Assigns GPU, calls run_training_pipeline(patching_complete=True)
    → Logs "Patch extraction already complete, skipping"
    → AI service: feature extraction → DB: status=EXTRACTING
    → AI service: WSI training → DB: status=TRAINING
    → DB: status=COMPLETED
```

Expected: GPU slot is consumed ONLY during EXTRACTING + TRAINING phases.

- [ ] **Step 4: Verify patch task is unaffected (manual trace)**

```
HTTP POST /tasks/training (data_type=patch)
  → DB: status=PENDING
  → asyncio.create_task(_validate_files_and_enqueue)
     → file check passes
     → task_queue.submit(run_training_pipeline) ← submits directly, no pre-queue patching
     → DB: status=QUEUED, progress=0

task_queue._worker_loop:
  → Waits for slot: len(_running_tasks) < max_concurrent
  → Assigns GPU, calls run_training_pipeline(patching_complete=False)
    → data_type == "patch" → skips patching code path entirely
    → AI service: patch classification/segmentation → DB: status=TRAINING
    → DB: status=COMPLETED
```

Expected: Patch tasks unchanged — direct GPU queue submission.

- [ ] **Step 5: Final commit if any cleanup needed**

```bash
git status
# if any files modified during review:
git add -p
git commit -m "chore: cleanup after GPU scheduler fix"
```

---

## Summary of Changes

| Component | Change | Why |
|-----------|--------|-----|
| `run_patching_stage()` | New function (extracted from `run_training_pipeline`) | Isolate CPU-only patching for pre-queue execution |
| `run_patching_then_submit()` | New coordinator function | Orchestrate pre-queue patching → GPU queue submission |
| `run_training_pipeline()` | Added `patching_complete: bool = False` | Skip patching when already done pre-queue |
| `TaskQueueManager._patching_tasks` | New dict tracking pre-queue tasks | Enable cancellation of tasks not yet in the GPU queue |
| `cancel_task()` | Checks `_patching_tasks` first | Correct cancellation for PATCHING-state tasks |
| `is_task_in_queue()` | Includes `_patching_tasks` | Correct active-task detection |
| `get_status()` | Adds `patching_count`, `patching_task_ids` | Visibility into pre-queue patching tasks |
| `_select_optimal_gpu()` | Adds warning log on -1 return | Fix silent failure diagnosis |
| `_validate_files_and_enqueue()` | Branches on `data_type` | WSI → pre-queue patching; patch → direct to queue |
| `resume_interrupted_tasks()` | Branches on `data_type` + status | Correct resume path for each task state |
