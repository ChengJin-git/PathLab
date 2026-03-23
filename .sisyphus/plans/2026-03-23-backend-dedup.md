# Backend Deduplication & Cohesion Refactor Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate ~600 lines of structural redundancy across the Python backend (database layer, AI task layer, gateway routes, and common utilities) by extracting base classes, mixins, and shared helpers — without changing any behavior.

**Architecture:** All changes are pure refactors: extract identical code into a shared location, update all callsites, run existing tests to confirm no behavior change. New files are only created when justified by 3+ callers. The guiding principle is: every extracted unit must have a single clear name and one clear responsibility.

**Tech Stack:** Python 3.11+, SQLAlchemy 2 async, FastAPI, SQLAlchemy generics via `TypeVar`, existing pytest suite.

**Working directory for all commands:** The worktree already exists at `/home/cjinag/code/PathLab/.worktrees/backend-refactor/pathlab/pathlab-client/`. All `python -m pytest` and `git` commands must be run from this directory:
```bash
cd /home/cjinag/code/PathLab/.worktrees/backend-refactor/pathlab/pathlab-client
```
All file paths in this plan are relative to this directory (e.g., `server/backend/database/models.py` → `/home/cjinag/code/PathLab/.worktrees/backend-refactor/pathlab/pathlab-client/server/backend/database/models.py`).

**Baseline test command:**
```bash
python -m pytest server/tests/ -v -k "not pretrained" --tb=short -q
```
Run this before Task 1 and after each task to confirm no regressions.

---

## Task 1: `TimestampMixin` — eliminate 63 lines of repeated ORM fields

**Files:**
- Modify: `server/backend/database/models.py`

**Context:** All 21 ORM models independently declare `id`, `created_at`, `updated_at`. No mixin exists. SQLAlchemy supports field inheritance via declarative mixins.

- [ ] **Step 1: Read the full `models.py`** to see the exact field declarations and all 21 model class names.

- [ ] **Step 2: Add `TimestampMixin` before the first model class**

  Insert immediately after the `utc_now` function definition:
  ```python
  class TimestampMixin:
      """Mixin that adds id, created_at, updated_at to every ORM model."""
      id = Column(Integer, primary_key=True, autoincrement=True)
      created_at = Column(DateTime, default=utc_now, nullable=False)
      updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
  ```

- [ ] **Step 3: Update every model class to inherit `TimestampMixin`**

  For each class that currently has `id / created_at / updated_at` declared inline:
  1. Change `class Foo(Base):` → `class Foo(TimestampMixin, Base):`
  2. Remove the three repeated column lines from the class body.

  **Important:** Keep ALL other fields, relationships, `__tablename__`, and `__table_args__` exactly as-is. Only remove the three lines and add the mixin.

- [ ] **Step 4: Run tests**
  ```bash
  python -m pytest server/tests/ -v -k "not pretrained" --tb=short -q
  ```
  Expected: all tests pass (same count as baseline).

- [ ] **Step 5: Commit**
  ```bash
  git add server/backend/database/models.py
  git commit -m "refactor(db): extract TimestampMixin to remove 63 lines of repeated ORM fields"
  ```

---

## Task 2: `repositories/utils.py` — shared query helpers

**Files:**
- Create: `server/backend/database/repositories/utils.py`
- Modify: `server/backend/database/repositories/__init__.py` (add export)

**Context:** `paginate_query` (skip+limit guard) appears in ≥4 repos. `apply_user_filter` (`if user_id is not None: query = query.where(...)`) appears in ≥9 repos. Extract both as standalone functions before wiring them into repos.

- [ ] **Step 1: Create `server/backend/database/repositories/utils.py`**
  ```python
  """Shared query utility helpers for all Repository classes."""
  from __future__ import annotations
  from typing import Optional, Any
  from sqlalchemy import asc, desc
  from sqlalchemy.sql import Select


  def paginate_query(
      query: Select,
      skip: int = 0,
      limit: int = 0,
      order_by: Optional[Any] = None,
      descending: bool = True,
  ) -> Select:
      """Apply offset/limit pagination and optional ordering to a SELECT query.

      Args:
          query:      Base SELECT statement.
          skip:       Number of rows to skip (offset). 0 = no offset.
          limit:      Maximum rows to return. 0 = no limit.
          order_by:   SQLAlchemy column expression to order by (e.g. Model.created_at).
          descending: If True, order descending; otherwise ascending. Ignored when order_by is None.
      """
      if order_by is not None:
          query = query.order_by(desc(order_by) if descending else asc(order_by))
      query = query.offset(skip)
      if limit > 0:
          query = query.limit(limit)
      return query


  def apply_user_filter(query: Select, model_class: Any, user_id: Optional[str]) -> Select:
      """Conditionally filter query by user_id when a value is provided."""
      if user_id is not None:
          query = query.where(model_class.user_id == user_id)
      return query
  ```

- [ ] **Step 2: Export from `repositories/__init__.py`**

  Add at the bottom of the imports block:
  ```python
  from .utils import paginate_query, apply_user_filter
  ```
  Also add `"paginate_query"` and `"apply_user_filter"` to `__all__`.

- [ ] **Step 3: Run tests** (no behavior changes yet, just new file)
  ```bash
  python -m pytest server/tests/ -v -k "not pretrained" --tb=short -q
  ```

- [ ] **Step 4: Commit**
  ```bash
  git add server/backend/database/repositories/utils.py \
          server/backend/database/repositories/__init__.py
  git commit -m "refactor(db): add repositories/utils.py with paginate_query and apply_user_filter helpers"
  ```

---

## Task 3: `BaseRepository[T]` — eliminate duplicated CRUD across 4+ repos

**Files:**
- Create: `server/backend/database/repositories/base.py`
- Modify: `server/backend/database/repositories/dataset.py`
- Modify: `server/backend/database/repositories/wsi.py`
- Modify: `server/backend/database/repositories/training.py`
- Modify: `server/backend/database/repositories/data_group.py`
- Modify: `server/backend/database/repositories/__init__.py`

**Context:** `dataset.py`, `wsi.py`, `training.py`, and `data_group.py` each independently implement `create`, `get_by_id`, `update` (with `updated_at = utc_now()`), and `delete`. Extract into a generic `BaseRepository[T]` that these repos inherit.

- [ ] **Step 1: Read the `create/get_by_id/update/delete` methods from `dataset.py`** to confirm the exact signatures and patterns.

- [ ] **Step 2: Create `server/backend/database/repositories/base.py`**

  **Important design note:** Each repo uses its own UUID field as the lookup key
  (e.g., `DatasetRepository` uses `dataset_id`, `WSIRepository` uses `wsi_id`,
  `TrainingTaskRepository` uses `task_id`). The `BaseRepository` accommodates this
  via a `pk_field` class variable that subclasses override.

  ```python
  """Generic async CRUD base repository for SQLAlchemy 2 + asyncpg."""
  from __future__ import annotations

  from typing import Any, Generic, Optional, Type, TypeVar
  from sqlalchemy import select, update, delete
  from sqlalchemy.ext.asyncio import AsyncSession

  from backend.database.models import utc_now

  T = TypeVar("T")


  class BaseRepository(Generic[T]):
      """Provides generic create/get_by_id/update/delete_by_id for one model.

      Subclasses MUST set both `model` and `pk_field`::

          class DatasetRepository(BaseRepository[Dataset]):
              model = Dataset
              pk_field = "dataset_id"   # the string field name used as lookup key

          class WSIRepository(BaseRepository[WSISlide]):
              model = WSISlide
              pk_field = "wsi_id"
      """

      model: Type[T]       # Subclasses MUST override
      pk_field: str = "id" # Subclasses MUST override with their UUID field name

      # ------------------------------------------------------------------ #
      # Create                                                               #
      # ------------------------------------------------------------------ #
      @classmethod
      async def create(cls, db: AsyncSession, **kwargs: Any) -> T:
          obj = cls.model(**kwargs)
          db.add(obj)
          await db.flush()
          await db.refresh(obj)
          return obj

      # ------------------------------------------------------------------ #
      # Read                                                                 #
      # ------------------------------------------------------------------ #
      @classmethod
      async def get_by_id(cls, db: AsyncSession, pk_value: Any) -> Optional[T]:
          pk_col = getattr(cls.model, cls.pk_field)
          result = await db.execute(select(cls.model).where(pk_col == pk_value))
          return result.scalar_one_or_none()

      # ------------------------------------------------------------------ #
      # Update                                                               #
      # ------------------------------------------------------------------ #
      @classmethod
      async def update(cls, db: AsyncSession, pk_value: Any, **update_data: Any) -> Optional[T]:
          pk_col = getattr(cls.model, cls.pk_field)
          update_data["updated_at"] = utc_now()
          await db.execute(
              update(cls.model).where(pk_col == pk_value).values(**update_data)
          )
          await db.flush()
          return await cls.get_by_id(db, pk_value)

      # ------------------------------------------------------------------ #
      # Delete                                                               #
      # ------------------------------------------------------------------ #
      @classmethod
      async def delete_by_id(cls, db: AsyncSession, pk_value: Any) -> bool:
          pk_col = getattr(cls.model, cls.pk_field)
          result = await db.execute(
              delete(cls.model).where(pk_col == pk_value)
          )
          await db.flush()
          return result.rowcount > 0
  ```

- [ ] **Step 3: Update `dataset.py`, `wsi.py`, `training.py`, `data_group.py`**

  For each of these four files:
  1. Add `from .base import BaseRepository` at the top.
  2. Change `class XxxRepository:` → `class XxxRepository(BaseRepository[Xxx]):` and add:
     ```python
     model = Xxx
     pk_field = "xxx_id"   # e.g. "dataset_id" for Dataset, "wsi_id" for WSISlide
     ```
  3. Remove only the `create`, `get_by_id`, `update`, `delete` methods whose bodies
     are now fully covered by `BaseRepository` — specifically those that:
     - **`create`**: just do `obj = Model(**data); db.add(obj); await db.flush(); return obj`
     - **`get_by_id`**: just do `select(Model).where(Model.pk_field == id)`
     - **`update`**: just set `updated_at = utc_now()` then execute `update(Model).where(...).values(**data)`
     - **`delete`**: just do `delete(Model).where(Model.pk_field == id)`
  4. **Do NOT remove** any method that has extra logic (joins, side-effects, cascade
     deletions, etc.) — those stay in the repo. If the repo's `update` method does more
     than set `updated_at`, keep it and remove the `updated_at` line only (call
     `await cls.update(db, pk_value, ...)` instead if safe).
  5. Update any internal callsite from `delete(...)` to `delete_by_id(...)` if applicable.

- [ ] **Step 4: Export from `__init__.py`**

  Add:
  ```python
  from .base import BaseRepository
  ```

- [ ] **Step 5: Run tests**
  ```bash
  python -m pytest server/tests/ -v -k "not pretrained" --tb=short -q
  ```
  Expected: all pass.

- [ ] **Step 6: Commit**
  ```bash
  git add server/backend/database/repositories/
  git commit -m "refactor(db): introduce BaseRepository[T] generic CRUD, eliminating ~120 lines of duplicated methods"
  ```

---

## Task 4: `BaseRegistry[T]` — merge three identical registries

**Files:**
- Create: `server/backend/ai/common/__init__.py` (if absent)
- Create: `server/backend/ai/common/registry_base.py`
- Modify: `server/backend/ai/aggregators/registry.py`
- Modify: `server/backend/ai/classifiers/registry.py`

**Context:** `aggregators/registry.py` and `classifiers/registry.py` each implement an identical `_REGISTRY` dict + `register_*` / `get_*` / `list_*` pattern. The extractor registry uses lazy loading and is intentionally different — **do NOT touch it**. Extract the common dict management + `register/list` into a `BaseRegistry`, and leave `get_*` in each subclass because the signatures differ.

- [ ] **Step 1: Read `aggregators/registry.py` and `classifiers/registry.py` in full** to confirm the exact structure and ensure no hidden differences.

- [ ] **Step 2: Create `server/backend/ai/common/__init__.py`** (empty, if not already present)

- [ ] **Step 3: Create `server/backend/ai/common/registry_base.py`**
  ```python
  """Generic base for model component registries (aggregators, classifiers, etc.)."""
  from __future__ import annotations

  import logging
  from typing import Dict, Generic, List, Optional, Type, TypeVar

  logger = logging.getLogger(__name__)

  T = TypeVar("T")


  class BaseRegistry(Generic[T]):
      """Dict-backed registry with duplicate-safe register and list operations.

      Subclasses override `build_instance` with their specific instantiation
      signature, and provide a pre-populated `_registry` class variable.

      Example::
          class AggregatorRegistry(BaseRegistry[BaseAggregator]):
              _registry: Dict[str, Type[BaseAggregator]] = {
                  "abmil": ABMILAggregator,
                  ...
              }
      """

      _registry: Dict[str, Type[T]] = {}  # Subclasses must override with a new dict

      @classmethod
      def register(cls, name: str, component_class: Type[T]) -> None:
          """Register a new component class under *name*.

          Raises:
              ValueError: If *name* is already taken.
          """
          if name in cls._registry:
              raise ValueError(f"'{name}' is already registered in {cls.__name__}")
          cls._registry[name] = component_class
          logger.debug("Registered '%s' in %s", name, cls.__name__)

      @classmethod
      def list_names(cls) -> List[str]:
          """Return a sorted list of all registered names."""
          return sorted(cls._registry.keys())

      @classmethod
      def _get_class(cls, name: str) -> Type[T]:
          """Look up a class by name; raise ValueError if not found."""
          key = name.strip().lower() if isinstance(name, str) else name
          if key not in cls._registry:
              available = ", ".join(cls.list_names()) or "<empty>"
              raise ValueError(
                  f"Unknown component '{name}' in {cls.__name__}. "
                  f"Available: {available}"
              )
          return cls._registry[key]
  ```

- [ ] **Step 4: Refactor `aggregators/registry.py`**

  Replace the body with:
  ```python
  from __future__ import annotations
  from typing import Type, List
  from .base import BaseAggregator
  from .abmil import ABMILAggregator
  # ... all existing imports ...
  from backend.ai.common.registry_base import BaseRegistry


  class _AggregatorRegistry(BaseRegistry[BaseAggregator]):
      _registry = {
          "abmil": ABMILAggregator,
          "meanmil": MeanMILAggregator,
          "maxmil": MaxMILAggregator,
          "dsmil": DSMILAggregator,
          "dtfdmil": DTFDAggregator,
          "clam_sb": CLAM_SB,
          "clam_mb": CLAM_MB,
          "transmil": TransMILAggregator,
      }


  # --- Public API (same names as before, backward-compatible) ---

  def register_aggregator(name: str, aggregator_class: Type[BaseAggregator]) -> None:
      _AggregatorRegistry.register(name, aggregator_class)


  def get_aggregator(name: str, in_dim: int, num_classes: int, **kwargs) -> BaseAggregator:
      cls = _AggregatorRegistry._get_class(name)
      return cls.build(in_dim=in_dim, num_classes=num_classes, **kwargs)


  def list_aggregators() -> List[str]:
      return _AggregatorRegistry.list_names()
  ```

- [ ] **Step 5: Refactor `classifiers/registry.py`** — same pattern as Step 4.

- [ ] **Step 6: Run tests**
  ```bash
  python -m pytest server/tests/ -v -k "not pretrained" --tb=short -q
  ```

- [ ] **Step 7: Commit**
  ```bash
  git add server/backend/ai/common/ \
          server/backend/ai/aggregators/registry.py \
          server/backend/ai/classifiers/registry.py
  git commit -m "refactor(ai): introduce BaseRegistry[T] shared by aggregator and classifier registries"
  ```

---

## Task 5: `TaskInterruptionSet` — unify cancellation & permission_revocation structure

**Files:**
- Create: `server/backend/ai/common/task_control.py`
- Modify: `server/backend/ai/cancellation.py`
- Modify: `server/backend/ai/permission_revocation.py`

**Context:** `cancellation.py` and `permission_revocation.py` are structural mirrors: each is a `Set[str]` + `request_*/is_*/clear_*` trio + a custom Exception class. Extract the set-management into `TaskInterruptionSet`; each module keeps only its exception class name and instantiates the shared helper.

- [ ] **Step 1: Read both `cancellation.py` and `permission_revocation.py` in full** to confirm all public API names.

- [ ] **Step 2: Create `server/backend/ai/common/task_control.py`**
  ```python
  """Generic task-lifecycle control (cancellation, permission revocation, etc.)."""
  from __future__ import annotations

  import logging
  from typing import Set

  logger = logging.getLogger(__name__)


  class TaskInterruptionSet:
      """Thread-safe in-process set of task IDs that should be interrupted.

      A single instance acts as the backing store for one interruption signal
      (e.g. cancellation OR permission revocation).  Two instances means two
      independent signals — callers check each one independently.
      """

      def __init__(self, label: str) -> None:
          """
          Args:
              label: Human-readable name used in log messages (e.g. "cancellation").
          """
          self._label = label
          self._tasks: Set[str] = set()

      def request(self, task_id: str) -> bool:
          """Signal that *task_id* should stop. Returns True always."""
          self._tasks.add(task_id)
          logger.info("%s requested for task %s", self._label, task_id)
          return True

      def is_set(self, task_id: str) -> bool:
          """Return True if *task_id* has an active interruption signal."""
          return task_id in self._tasks

      def clear(self, task_id: str) -> None:
          """Remove the interruption signal once the task has cleaned up."""
          self._tasks.discard(task_id)
  ```

- [ ] **Step 3: Rewrite `cancellation.py`**
  ```python
  """Training Cancellation Mechanism — backed by TaskInterruptionSet."""
  from backend.ai.common.task_control import TaskInterruptionSet

  _cancellation = TaskInterruptionSet("cancellation")


  class TrainingCancelledException(Exception):
      """Raised inside a training loop when the task is cancelled."""


  def request_cancellation(task_id: str) -> bool:
      return _cancellation.request(task_id)


  def is_task_cancelled(task_id: str) -> bool:
      return _cancellation.is_set(task_id)


  def clear_cancellation(task_id: str) -> None:
      _cancellation.clear(task_id)
  ```

- [ ] **Step 4: Rewrite `permission_revocation.py`**
  ```python
  """Permission Revocation Mechanism — backed by TaskInterruptionSet."""
  from backend.ai.common.task_control import TaskInterruptionSet

  _revocation = TaskInterruptionSet("permission_revocation")


  class PermissionRevokedException(Exception):
      """Raised inside a training loop when the task's permission is revoked."""


  def revoke_task_permission(task_id: str) -> bool:
      return _revocation.request(task_id)


  def is_permission_revoked(task_id: str) -> bool:
      return _revocation.is_set(task_id)


  def clear_revocation(task_id: str) -> None:
      _revocation.clear(task_id)
  ```

- [ ] **Step 5: Run tests**
  ```bash
  python -m pytest server/tests/ -v -k "not pretrained" --tb=short -q
  ```

- [ ] **Step 6: Commit**
  ```bash
  git add server/backend/ai/common/task_control.py \
          server/backend/ai/cancellation.py \
          server/backend/ai/permission_revocation.py
  git commit -m "refactor(ai): extract TaskInterruptionSet, unify cancellation and permission_revocation backing store"
  ```

---

## Task 6: `SegmentationTrainer` inheritance + `check_training_interruption`

**Files:**
- Modify: `server/backend/ai/tasks/training_utils.py`
- Modify: `server/backend/ai/tasks/patch_segmentation/trainer.py`
- Modify: `server/backend/ai/tasks/patch_classification/trainer.py`
- Modify: `server/backend/ai/tasks/wsi_classification/trainer.py`
- Modify: `server/backend/ai/tasks/wsi_survival/trainer.py`

**Context:** All 4 trainer training loops check `is_task_cancelled` and `is_permission_revoked` in the same `if batch_count % 50 == 0:` guard. This should be a single function. Additionally, `SegmentationTrainer` doesn't inherit `BaseTrainer` even though it implements the same interface.

- [ ] **Step 1: Read `tasks/training_utils.py`** to see what's already there, then read `patch_classification/trainer.py` to see the exact cancellation+revocation guard pattern.

- [ ] **Step 2: Add `check_training_interruption` to `training_utils.py`**

  Append this function:
  ```python
  def check_training_interruption(task_id: str) -> Optional[str]:
      """Check for cancellation or permission revocation.

      Returns:
          "cancelled"          if cancellation was requested,
          "permission_revoked" if permission was revoked,
          None                 if no interruption.

      Call this inside training loops (e.g. every 50 batches).
      """
      from backend.ai.cancellation import is_task_cancelled
      from backend.ai.permission_revocation import is_permission_revoked

      if is_task_cancelled(task_id):
          return "cancelled"
      if is_permission_revoked(task_id):
          return "permission_revoked"
      return None
  ```

- [ ] **Step 3: Update all 4 trainers to call `check_training_interruption`**

  In each of the 4 trainer files, replace the existing inline guard:
  ```python
  # BEFORE (in each trainer):
  if batch_count % 50 == 0:
      if is_task_cancelled(self.task_id):
          return None, 0, "cancelled"
      if is_permission_revoked(self.task_id):
          return None, 0, "permission_revoked"
  ```
  With:
  ```python
  # AFTER:
  if batch_count % 50 == 0:
      interruption = check_training_interruption(self.task_id)
      if interruption:
          return None, 0, interruption
  ```
  Also add `from backend.ai.tasks.training_utils import check_training_interruption` to each file's imports, and remove the now-unused `from backend.ai.cancellation import is_task_cancelled` and `from backend.ai.permission_revocation import is_permission_revoked` if no longer needed in that file.

- [ ] **Step 4: Make `SegmentationTrainer` inherit `BaseTrainer`**

  In `patch_segmentation/trainer.py`:
  1. Add `from backend.ai.tasks.base import BaseTrainer` import.
  2. Change `class SegmentationTrainer:` → `class SegmentationTrainer(BaseTrainer):`.
  3. Add `task_type = TaskType.PATCH_SEGMENTATION` class variable (import `TaskType` from `backend.ai.schemas`).
  4. Remove the `__init__` method body that duplicates `BaseTrainer.__init__` — call `super().__init__(...)` instead, keeping only SegmentationTrainer-specific init logic.
  5. Keep all methods that are not already in `BaseTrainer` intact.

- [ ] **Step 5: Run tests**
  ```bash
  python -m pytest server/tests/ -v -k "not pretrained" --tb=short -q
  ```

- [ ] **Step 6: Commit**
  ```bash
  git add server/backend/ai/tasks/
  git commit -m "refactor(ai): extract check_training_interruption, make SegmentationTrainer inherit BaseTrainer"
  ```

---

## Task 7: `BaseAnalysisRunner` — consolidate 4 analysis modules

**Files:**
- Create: `server/gateway/routes/analysis_base.py`
- Modify: `server/gateway/routes/classification_analysis.py`
- Modify: `server/gateway/routes/segmentation_analysis.py`
- Modify: `server/gateway/routes/survival_analysis.py`
- Modify: `server/gateway/routes/external_validation_analysis.py`

**Context:** All 4 `*_analysis.py` files repeat:
1. `progress_config` default-setting block (~4 lines each)
2. Timestamped `analysis_dir` creation (~3 lines each)
3. `_write_json_sync` result-saving pattern
4. The final `return {"task_id": ..., "analysis_id": ..., ...}` shape

Extract these into a `BaseAnalysisRunner` dataclass/helper in `analysis_base.py`.

- [ ] **Step 1: Read `classification_analysis.py` and `segmentation_analysis.py` in full** to see the exact repeated blocks.

- [ ] **Step 2: Create `server/gateway/routes/analysis_base.py`**
  ```python
  """Shared helpers for all *_analysis route modules."""
  from __future__ import annotations

  import asyncio
  from datetime import datetime, timezone
  from pathlib import Path
  from typing import Any, Dict, Optional

  from backend.common.config import Config


  def resolve_progress_config(
      progress_config: Optional[Dict[str, Any]],
      defaults: Dict[str, Any],
  ) -> Dict[str, Any]:
      """Return progress_config with missing keys filled from *defaults*."""
      if progress_config is None:
          return dict(defaults)
      merged = dict(defaults)
      merged.update(progress_config)
      return merged


  def create_analysis_directory(task_id: str) -> tuple[Path, str]:
      """Create a timestamped output directory for one analysis run.

      Returns:
          (analysis_dir, timestamp_str) — caller can store timestamp as analysis_id.
      """
      timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
      analysis_dir = Config.get_uploads_dir() / "logs" / "analysis" / task_id / timestamp
      analysis_dir.mkdir(parents=True, exist_ok=True)
      return analysis_dir, timestamp


  async def save_analysis_json(path: Path, data: Any) -> None:
      """Write *data* to *path* as JSON in a thread (non-blocking).

      Uses a local relative import to avoid circular imports between analysis modules.
      This function must live inside server/gateway/routes/ so the relative import works.
      """
      from .analysis_metrics import _write_json_sync  # relative import — same package
      await asyncio.to_thread(_write_json_sync, path, data)


  def build_analysis_response(
      task_id: str,
      timestamp: str,
      analysis_dir: Path,
      **extra: Any,
  ) -> Dict[str, Any]:
      """Build the standard analysis response dict."""
      return {
          "task_id": task_id,
          "analysis_id": timestamp,
          "analysis_dir": str(analysis_dir),
          **extra,
      }
  ```

- [ ] **Step 3: Update all 4 analysis modules**

  In each file:
  1. Add `from .analysis_base import resolve_progress_config, create_analysis_directory, save_analysis_json, build_analysis_response`.
  2. Replace the inline `progress_config` defaults block with `progress_config = resolve_progress_config(progress_config, {"start": 20, "ci_start": 30, "ci_end": 95, "has_ci": True})` (using the appropriate defaults for each module).
  3. Replace the inline directory creation block with `analysis_dir, timestamp = create_analysis_directory(task_id)`.
  4. Replace `await asyncio.to_thread(_write_json_sync, analysis_dir / "*.json", data)` with `await save_analysis_json(analysis_dir / "*.json", data)`.
  5. Replace the final `return {... "task_id": task_id, "analysis_id": timestamp ...}` dict with `return build_analysis_response(task_id, timestamp, analysis_dir, summary=summary, ...)`.

- [ ] **Step 4: Run tests**
  ```bash
  python -m pytest server/tests/ -v -k "not pretrained" --tb=short -q
  ```

- [ ] **Step 5: Commit**
  ```bash
  git add server/gateway/routes/analysis_base.py \
          server/gateway/routes/classification_analysis.py \
          server/gateway/routes/segmentation_analysis.py \
          server/gateway/routes/survival_analysis.py \
          server/gateway/routes/external_validation_analysis.py
  git commit -m "refactor(routes): extract BaseAnalysisRunner helpers, eliminate repeated dir/progress/response patterns in 4 analysis modules"
  ```

---

## Task 8: `BaseInferenceRunner` — consolidate 5 inference modules

**Files:**
- Create: `server/gateway/routes/inference_base.py`
- Modify: `server/gateway/routes/inference_wsi_classification.py`
- Modify: `server/gateway/routes/inference_patch_classification.py`
- Modify: `server/gateway/routes/inference_patch_segmentation.py`
- Modify: `server/gateway/routes/inference_wsi_survival.py`
- Modify: `server/gateway/routes/inference_external_validation.py`

**Context:** All 5 `inference_*.py` files repeat device selection, model checkpoint loading, progress callback guard, and result cleanup.

- [ ] **Step 1: Read `inference_wsi_classification.py` and `inference_patch_classification.py` in full** to see exact repetitions.

- [ ] **Step 2: Create `server/gateway/routes/inference_base.py`**
  ```python
  """Shared helpers for all inference_* route modules."""
  from __future__ import annotations

  from typing import Any, Callable, Awaitable, Optional
  import torch


  def resolve_device(assigned_device: Optional[str] = None) -> str:
      """Return *assigned_device* if given, otherwise auto-detect CUDA/CPU."""
      if assigned_device:
          return assigned_device
      return "cuda" if torch.cuda.is_available() else "cpu"


  def load_model_checkpoint(
      model: Any,
      checkpoint_path: Any,
      device: str,
      state_dict_key: str = "state_dict",
  ) -> Any:
      """Load a PyTorch checkpoint into *model*, move to *device*, set eval mode.

      Args:
          model:            Instantiated PyTorch model.
          checkpoint_path:  Path to .pt / .pth checkpoint file.
          device:           Device string ("cuda" / "cpu").
          state_dict_key:   Key inside the checkpoint dict that holds the state dict.
                            Defaults to "state_dict"; use "model_state_dict" for segmentation.
      Returns:
          The model in eval mode on the target device.
      """
      checkpoint = torch.load(checkpoint_path, map_location=device)
      model.load_state_dict(checkpoint[state_dict_key])
      model = model.to(device)
      model.eval()
      return model


  async def report_progress(
      progress_callback: Optional[Callable[[float], Awaitable[None]]],
      idx: int,
      total: int,
      start: float = 0.1,
      end: float = 0.9,
  ) -> None:
      """Call *progress_callback* with a linearly interpolated value if set."""
      if progress_callback is not None and total > 0:
          value = start + (end - start) * (idx / total)
          await progress_callback(value)
  ```

- [ ] **Step 3: Update all 5 inference modules**

  In each file:
  1. Add `from .inference_base import resolve_device, load_model_checkpoint, report_progress`.
  2. Replace `device = assigned_device if assigned_device else ("cuda" if torch.cuda.is_available() else "cpu")` with `device = resolve_device(assigned_device)`.
  3. Replace the `torch.load` + `load_state_dict` + `model.eval()` block with `model = load_model_checkpoint(model, ckpt_path, device)` (add `state_dict_key="model_state_dict"` where segmentation uses that key).
  4. Replace `if progress_callback and total_items > 0: await progress_callback(0.1 + 0.8 * (idx / total_items))` with `await report_progress(progress_callback, idx, total_items)`.

- [ ] **Step 4: Run tests**
  ```bash
  python -m pytest server/tests/ -v -k "not pretrained" --tb=short -q
  ```

- [ ] **Step 5: Commit**
  ```bash
  git add server/gateway/routes/inference_base.py \
          server/gateway/routes/inference_wsi_classification.py \
          server/gateway/routes/inference_patch_classification.py \
          server/gateway/routes/inference_patch_segmentation.py \
          server/gateway/routes/inference_wsi_survival.py \
          server/gateway/routes/inference_external_validation.py
  git commit -m "refactor(routes): extract inference_base.py helpers, deduplicate device/checkpoint/progress in 5 inference modules"
  ```

---

## Task 9: `backend/common/permissions.py` — unify scattered ownership checks

**Files:**
- Create: `server/backend/common/permissions.py`
- Modify: `server/gateway/routes/chat.py`
- Modify: `server/gateway/routes/chat_feedback.py`

**Context:** `chat.py` has `_require_conversation_write_access` and `chat_feedback.py` has `_require_message_access`. Both load an object from DB, check ownership via `check_data_ownership`, and raise 403/404. Extract into a shared helper so both can call it.

- [ ] **Step 1: Read `chat.py` lines containing `_require_conversation_write_access` and `chat_feedback.py` lines containing `_require_message_access`** in full to confirm the exact logic.

- [ ] **Step 2: Create `server/backend/common/permissions.py`**
  ```python
  """Shared ownership / access-control helpers used across Gateway routes."""
  from __future__ import annotations

  from fastapi import HTTPException
  from sqlalchemy.ext.asyncio import AsyncSession

  from backend.auth.models import User


  def check_data_ownership(resource_owner_id: str | int, user: User) -> bool:
      """Return True if *user* owns *resource* or is a superuser.

      Re-exports the canonical implementation from auth so callers only need
      one import location.
      """
      from backend.auth.users import check_data_ownership as _auth_check
      return _auth_check(str(resource_owner_id), user)


  async def require_conversation_access(
      db: AsyncSession,
      conversation_id: str,
      user: User,
  ) -> None:
      """Raise 404 / 403 if *user* may not read or write to *conversation_id*."""
      from backend.database.repositories import ChatRepository

      conversation = await ChatRepository.get_conversation(db, conversation_id)
      if not conversation:
          raise HTTPException(status_code=404, detail="Conversation not found")
      if not check_data_ownership(conversation.user_id, user):
          raise HTTPException(
              status_code=403,
              detail="You don't have permission to access this conversation",
          )


  async def require_message_access(
      db: AsyncSession,
      message_id: int,
      user: User,
  ) -> None:
      """Raise 404 / 403 if *user* may not access *message_id*."""
      from backend.database.repositories import ChatRepository

      message = await ChatRepository.get_message(db, message_id)
      if not message:
          raise HTTPException(status_code=404, detail="Message not found")
      conversation = message.conversation
      if conversation is None:
          raise HTTPException(status_code=404, detail="Conversation not found")
      if not check_data_ownership(conversation.user_id, user):
          raise HTTPException(
              status_code=403,
              detail="You don't have permission to access this message",
          )
  ```

- [ ] **Step 3: Update `chat.py`**
  1. Add `from backend.common.permissions import require_conversation_access`.
  2. Delete the local `_require_conversation_write_access` function.
  3. Replace all callsites of `_require_conversation_write_access(db, conversation_id, user)` with `await require_conversation_access(db, conversation_id, user)`.

- [ ] **Step 4: Update `chat_feedback.py`**
  1. Add `from backend.common.permissions import require_message_access`.
  2. Delete the local `_require_message_access` function.
  3. Replace all callsites with `await require_message_access(db, message_id, user)`.

- [ ] **Step 5: Run tests**
  ```bash
  python -m pytest server/tests/ -v -k "not pretrained" --tb=short -q
  ```

- [ ] **Step 6: Commit**
  ```bash
  git add server/backend/common/permissions.py \
          server/gateway/routes/chat.py \
          server/gateway/routes/chat_feedback.py
  git commit -m "refactor(auth): extract backend/common/permissions.py, deduplicate chat ownership checks"
  ```

---

## Task 10: Pydantic base models — eliminate repeated request model fields

**Files:**
- Modify: `server/gateway/models.py`

**Context:** Two groups of Pydantic request models share 6–9 fields each:
- Group 1: `UploadByPathRequest` ≈ `StartBatchImportRequest` — share `dataset_id, dataset_name, source_organ, aggregation_level, task_type, is_public, default_label, default_event_time, default_event_status`.
- Group 2: `WSIMetadataUpdateRequest` ≈ `StartBatchUpdateMetadataRequest` — share `label, case_id, age, gender, event_time, event_status`.

- [ ] **Step 1: Read `server/gateway/models.py` in full** to confirm the exact field names and types in both model groups.

- [ ] **Step 2: Extract `BaseDatasetRequest`**

  Before `UploadByPathRequest`, add:
  ```python
  class BaseDatasetRequest(BaseModel):
      """Common fields shared by dataset upload and batch import requests."""
      dataset_id: Optional[str] = None
      dataset_name: Optional[str] = None
      source_organ: Optional[str] = None
      aggregation_level: Optional[str] = None
      task_type: Optional[str] = None
      is_public: bool = False
      default_label: Optional[str] = None
      default_event_time: Optional[float] = None
      default_event_status: Optional[int] = None
  ```
  Then make `UploadByPathRequest(BaseDatasetRequest)` and `StartBatchImportRequest(BaseDatasetRequest)`, removing the shared fields from each.

- [ ] **Step 3: Extract `BaseWSIMetadataFields`**

  Similarly:
  ```python
  class BaseWSIMetadataFields(BaseModel):
      label: Optional[str] = None
      case_id: Optional[str] = None
      age: Optional[float] = None
      gender: Optional[str] = None
      event_time: Optional[float] = None
      event_status: Optional[int] = None
  ```
  Make `WSIMetadataUpdateRequest(BaseWSIMetadataFields)` and `StartBatchUpdateMetadataRequest(BaseWSIMetadataFields)`.

- [ ] **Step 4: Run tests**
  ```bash
  python -m pytest server/tests/ -v -k "not pretrained" --tb=short -q
  ```

- [ ] **Step 5: Commit**
  ```bash
  git add server/gateway/models.py
  git commit -m "refactor(gateway): add BaseDatasetRequest and BaseWSIMetadataFields Pydantic base models"
  ```

---

## Task 11: `PaginationParams` — standardize two naming conventions

**Files:**
- Modify: `server/gateway/dependencies.py`
- Modify: `server/gateway/routes/wsi.py` (and any other route using `skip/limit` or `page/page_size` as raw Query params)

**Context:** Routes use two different pagination naming conventions (`page/page_size` vs `skip/limit`). Introduce one `PaginationParams` dependency class that canonically uses `page/page_size` and computes `skip` automatically.

- [ ] **Step 1: Read `server/gateway/dependencies.py` in full**, then grep for `page_size` and `skip` across the gateway routes to find all usages.

- [ ] **Step 2: Add `PaginationParams` to `dependencies.py`**
  ```python
  from fastapi import Query
  from pydantic import BaseModel

  class PaginationParams(BaseModel):
      """Canonical pagination dependency for all list endpoints."""
      page: int = Query(default=1, ge=1, description="1-indexed page number")
      page_size: int = Query(default=20, ge=1, le=1000, description="Items per page")

      @property
      def skip(self) -> int:
          return (self.page - 1) * self.page_size

      @property
      def limit(self) -> int:
          return self.page_size
  ```

- [ ] **Step 3: Update each route that uses raw `skip: int = 0, limit: int = N` Query params**

  Replace:
  ```python
  async def list_things(skip: int = Query(0), limit: int = Query(100), ...):
      items = await Repo.list(db, skip=skip, limit=limit)
  ```
  With:
  ```python
  from ..dependencies import PaginationParams
  async def list_things(pagination: PaginationParams = Depends(), ...):
      items = await Repo.list(db, skip=pagination.skip, limit=pagination.limit)
  ```

  **Only migrate endpoints that use purely generic skip/limit.** Leave endpoints that have custom `upload_limit`/`task_limit` fields (e.g., `stats.py`) untouched.

- [ ] **Step 4: Run tests**
  ```bash
  python -m pytest server/tests/ -v -k "not pretrained" --tb=short -q
  ```

- [ ] **Step 5: Commit**
  ```bash
  git add server/gateway/dependencies.py server/gateway/routes/
  git commit -m "refactor(gateway): add PaginationParams dependency, standardize pagination across list endpoints"
  ```

---

## Task 12: Shared `httpx` clients — eliminate per-call client creation

**Files:**
- Modify: `server/gateway/main.py`
- Modify: `server/gateway/dependencies.py`
- Modify: `server/gateway/utils.py`
- Modify: `server/gateway/pipeline.py`

**Context:** Every call to the AI or Preprocessing service creates a fresh `httpx.AsyncClient`. Replace with two long-lived clients stored on `app.state`, injected via `Depends()`.

- [ ] **Step 1: Read `gateway/main.py`** (specifically the lifespan/startup block) and `gateway/utils.py` in full.

- [ ] **Step 2: Add shared clients to `gateway/main.py` lifespan**

  In the `lifespan` context manager (or startup event), before `yield`:
  ```python
  import httpx
  from .dependencies import AI_SERVICE_URL, PREPROCESSING_SERVICE_URL  # relative import — same package

  app.state.ai_client = httpx.AsyncClient(
      base_url=AI_SERVICE_URL,
      timeout=httpx.Timeout(connect=5.0, read=300.0, write=30.0, pool=5.0),
  )
  app.state.preprocessing_client = httpx.AsyncClient(
      base_url=PREPROCESSING_SERVICE_URL,
      timeout=httpx.Timeout(connect=5.0, read=120.0, write=30.0, pool=5.0),
  )
  ```
  After `yield`, add cleanup:
  ```python
  await app.state.ai_client.aclose()
  await app.state.preprocessing_client.aclose()
  ```

- [ ] **Step 3: Add `Depends`-style getters to `dependencies.py`**
  ```python
  from fastapi import Request

  def get_ai_client(request: Request) -> httpx.AsyncClient:
      return request.app.state.ai_client

  def get_preprocessing_client(request: Request) -> httpx.AsyncClient:
      return request.app.state.preprocessing_client
  ```

- [ ] **Step 4: Update `utils.py` and `pipeline.py`**

  For each function that currently does `async with httpx.AsyncClient(...) as client:`:
  1. Add the appropriate client as a parameter: `client: httpx.AsyncClient = Depends(get_ai_client)`.
  2. Remove the `async with httpx.AsyncClient(...)` wrapper.
  3. Use `client` directly.

  **Note:** Functions in `utils.py` that are not FastAPI route functions will need the client passed in explicitly rather than via `Depends()`. Update their call sites accordingly.

- [ ] **Step 5: Run tests**
  ```bash
  python -m pytest server/tests/ -v -k "not pretrained" --tb=short -q
  ```

- [ ] **Step 6: Commit**
  ```bash
  git add server/gateway/main.py \
          server/gateway/dependencies.py \
          server/gateway/utils.py \
          server/gateway/pipeline.py
  git commit -m "refactor(gateway): replace per-call httpx.AsyncClient with shared lifespan clients"
  ```

---

## Task 13: `config.py` SRP — separate configuration from side effects

**Files:**
- Create: `server/backend/common/settings_store.py`
- Modify: `server/backend/common/config.py`
- Modify: `server/gateway/main.py`

**Context:** `config.py` currently handles (1) reading/writing the `storage.json` config file on disk and (2) creating upload directories. These are side effects that belong elsewhere.

- [ ] **Step 1: Read `server/backend/common/config.py` in full** to identify which methods read/write files and which create directories.

- [ ] **Step 2: Create `server/backend/common/settings_store.py`**

  Move `_read_config`, `_write_config`, `_get_storage_config_file` from `config.py` into this new file as module-level functions. Export them. Keep the same logic exactly.

  ```python
  """Persistent key-value settings store backed by a JSON file on disk."""
  from __future__ import annotations
  import json
  from pathlib import Path
  from typing import Any, Dict


  def _get_storage_config_file() -> Path:
      ...  # move the existing implementation here


  def read_config() -> Dict[str, Any]:
      ...  # move _read_config


  def write_config(data: Dict[str, Any]) -> None:
      ...  # move _write_config
  ```

- [ ] **Step 3: Update `config.py`**
  1. Delete `_read_config`, `_write_config`, `_get_storage_config_file` from `config.py`.
  2. In every `config.py` method that previously called those three functions, import and call the equivalents from `settings_store` instead:
     ```python
     from backend.common.settings_store import read_config, write_config
     ```
  3. **Keep** `ensure_directories` as a `@classmethod` on `Config` — do not delete it. Its body stays unchanged. Only its *invocation* site moves (see Step 4).

- [ ] **Step 4: Move invocation of `ensure_directories` to `gateway/main.py`**

  **Goal:** `ensure_directories()` should be called explicitly during Gateway startup, not implicitly at import time or inside `config.py` module initialization.

  In `gateway/main.py`, find where the `lifespan` startup block begins (just before `yield`) and add:
  ```python
  from backend.common.config import Config
  Config.ensure_directories()
  ```
  Then remove any existing call to `Config.ensure_directories()` (or `ensure_directories()`) from `config.py`'s module body or `__init_subclass__`/class-level code if it exists there. If `config.py` never calls it at import time, this step is a no-op.

  **End state:** `Config.ensure_directories()` is a method that exists on the class, is called once in the Gateway lifespan, and is NOT called inside `config.py` itself.

- [ ] **Step 5: Run tests**
  ```bash
  python -m pytest server/tests/ -v -k "not pretrained" --tb=short -q
  ```

- [ ] **Step 6: Commit**
  ```bash
  git add server/backend/common/settings_store.py \
          server/backend/common/config.py \
          server/gateway/main.py
  git commit -m "refactor(common): extract settings_store.py from config.py, move ensure_directories to gateway lifespan"
  ```

---

## Final Verification

After all 13 tasks are complete:

- [ ] **Run full test suite**
  ```bash
  python -m pytest server/tests/ -v -k "not pretrained" --tb=short
  ```
  All tests must pass with the same count as the baseline.

- [ ] **Check for any remaining `async with httpx.AsyncClient` patterns**
  ```bash
  grep -rn "async with httpx.AsyncClient" server/gateway/
  ```
  Expected: 0 results.

- [ ] **Verify no `TimestampMixin` fields remain in model bodies**
  ```bash
  grep -n "primary_key=True" server/backend/database/models.py | wc -l
  ```
  Expected: 1 (the mixin itself).

- [ ] **Check `SegmentationTrainer` now inherits `BaseTrainer`**
  ```bash
  grep "class SegmentationTrainer" server/backend/ai/tasks/patch_segmentation/trainer.py
  ```
  Expected: `class SegmentationTrainer(BaseTrainer):`
