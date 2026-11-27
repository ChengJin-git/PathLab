import base64
from backend.common import file_lock as fcntl
import hashlib
import json
import threading
import shutil
import zipfile
import warnings
from collections import OrderedDict
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, cast

import numpy as np
from numpy.typing import NDArray
import zarr
from zarr.storage import ZipStore

SCHEMA_VERSION = 1
BUNDLE_DIR_NAME = "ai_results_bundles"

RESULT_ARTIFACT = "result"
ATTENTION_ARTIFACT = "attention"
ATTENTION_RAW_ARTIFACT = "attention_raw"
CAM_ARTIFACT = "cam"
PRED_MASK_ARTIFACT = "pred_mask"
PRED_BINS_ARTIFACT = "pred_bins"
GT_MASK_ARTIFACT = "gt_mask"

ARRAY_ARTIFACTS = {
    ATTENTION_ARTIFACT,
    ATTENTION_RAW_ARTIFACT,
    CAM_ARTIFACT,
    PRED_MASK_ARTIFACT,
    PRED_BINS_ARTIFACT,
    GT_MASK_ARTIFACT,
}
ALL_ARTIFACTS = {RESULT_ARTIFACT, *ARRAY_ARTIFACTS}
_TASK_LOCKS: dict[str, threading.Lock] = {}
_TASK_LOCKS_GUARD = threading.Lock()


class IncompleteAIResultBundleError(RuntimeError):
    """Raised when a caller explicitly asks to reject an incomplete bundle."""


class AIResultStore:
    """Task-level Zarr ZipStore for AI result artifacts only."""

    def __init__(self, uploads_dir: Path):
        self.uploads_dir = Path(uploads_dir)
        self.bundle_dir = self.uploads_dir / BUNDLE_DIR_NAME
        self.staging_root = self.bundle_dir / ".staging"
        from .result_catalog import ResultCatalog
        self.catalog = ResultCatalog(self.bundle_dir)
        self.bundle_dir.mkdir(parents=True, exist_ok=True)
        self.staging_root.mkdir(parents=True, exist_ok=True)

    def bundle_path(self, task_id: str) -> Path:
        return self.bundle_dir / f"{task_id}.zarr.zip"

    def staging_path(self, task_id: str) -> Path:
        return self.staging_root / f"{task_id}.zarr"

    def write_wsi_result(
        self,
        task_id: str,
        wsi_id: str,
        result: dict[str, Any] | None = None,
        arrays: dict[str, NDArray[Any]] | None = None,
        fold_key: str | None = None,
        finalize: bool = True,
        update_index: bool = True,
    ) -> Path | None:
        with self._task_lock(task_id):
            self._hydrate_staging_from_bundle(task_id)
            root = self._open_staging_group(task_id, overwrite=False)
            self._ensure_root_attrs(root, task_id)
            item_key = self._item_key(wsi_id, fold_key)

            if result is not None:
                results_group = root.require_group("results")
                if item_key in results_group:
                    del results_group[item_key]
                item_group = results_group.require_group(item_key)
                item_group.attrs["wsi_id"] = wsi_id
                if fold_key:
                    item_group.attrs["fold_key"] = fold_key
                item_group.attrs["result_json"] = result

            for artifact, array in (arrays or {}).items():
                if artifact not in ARRAY_ARTIFACTS:
                    raise ValueError(f"unsupported array artifact: {artifact}")
                artifact_group = root.require_group(artifact)
                if item_key in artifact_group:
                    del artifact_group[item_key]
                item_attrs: dict[str, Any] = {"wsi_id": wsi_id}
                if fold_key:
                    item_attrs["fold_key"] = fold_key
                stored_array = artifact_group.create_dataset(
                    item_key,
                    data=np.asarray(array),
                    overwrite=True,
                )
                stored_array.attrs.update(item_attrs)

            if update_index:
                self._merge_wsi_id(root, task_id, wsi_id, update_index=True)
            if finalize:
                return self._finalize_task_bundle(task_id)
            return None

    def write_task_bundle(
        self,
        task_id: str,
        items: list[dict[str, Any]] | None = None,
        task_type: str | None = None,
    ) -> Path:
        if items is not None:
            return self._write_task_bundle_direct(task_id, items, task_type)
        with self._task_lock(task_id):
            return self._finalize_task_bundle(task_id)

    def _write_task_bundle_direct(
        self, task_id: str, items: list[dict[str, Any]], task_type: str | None
    ) -> Path:
        with self._task_lock(task_id):
            shutil.rmtree(self.staging_path(task_id), ignore_errors=True)
            tmp_zip = self.bundle_path(task_id).with_name(f"{task_id}.zarr.zip.tmp")
            final_zip = self.bundle_path(task_id)
            tmp_zip.unlink(missing_ok=True)
            store = ZipStore(str(tmp_zip), mode="w")
            root = zarr.open_group(store=store, mode="w", zarr_version=2)
            try:
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore",
                        message=r"Duplicate name: .*",
                        category=UserWarning,
                        module="zipfile",
                    )
                    self._ensure_root_attrs(root, task_id)
                    if task_type:
                        root.attrs["task_type"] = task_type
                    for item in items:
                        self._write_item_to_group(root, item)
                    root.attrs["finalized"] = True
            finally:
                store.close()
            self._dedupe_zip_entries(tmp_zip)
            tmp_zip.replace(final_zip)
            self.rebuild_wsi_index(task_id)
            return final_zip

    def _write_item_to_group(self, root: zarr.Group, item: dict[str, Any]) -> None:
        wsi_id = str(item["wsi_id"])
        fold_key = cast(str | None, item.get("fold_key"))
        item_key = self._item_key(wsi_id, fold_key)
        result = cast(dict[str, Any] | None, item.get("result"))
        if result is not None:
            results_group = root.require_group("results")
            if item_key in results_group:
                del results_group[item_key]
            item_group = results_group.require_group(item_key)
            item_group.attrs["wsi_id"] = wsi_id
            if fold_key:
                item_group.attrs["fold_key"] = fold_key
            item_group.attrs["result_json"] = result
        for artifact, array in cast(dict[str, NDArray[Any]], item.get("arrays") or {}).items():
            if artifact not in ARRAY_ARTIFACTS:
                raise ValueError(f"unsupported array artifact: {artifact}")
            artifact_group = root.require_group(artifact)
            if item_key in artifact_group:
                del artifact_group[item_key]
            item_attrs: dict[str, Any] = {"wsi_id": wsi_id}
            if fold_key:
                item_attrs["fold_key"] = fold_key
            stored_array = artifact_group.create_dataset(
                item_key,
                data=np.asarray(array),
                chunks=tuple(int(dim) for dim in np.asarray(array).shape) or "auto",
                overwrite=True,
            )
            stored_array.attrs.update(item_attrs)
        root.attrs["wsi_ids"] = sorted(
            set(cast(list[str], root.attrs.get("wsi_ids", []))) | {wsi_id}
        )

    def read_result(
        self,
        task_id: str,
        wsi_id: str,
        fold_key: str | None = None,
        strict: bool = False,
    ) -> dict[str, Any]:
        with self._finalized_bundle(task_id, strict=strict) as root:
            if root is None:
                raise FileNotFoundError(self.bundle_path(task_id))

            result_group = self._open_group_path(root, f"results/{self._item_key(wsi_id, fold_key)}")
            return cast(dict[str, Any], result_group.attrs["result_json"])

    def read_array(
        self,
        task_id: str,
        wsi_id: str,
        artifact: str,
        fold_key: str | None = None,
        strict: bool = False,
    ) -> NDArray[Any]:
        if artifact not in ARRAY_ARTIFACTS:
            raise ValueError(f"unsupported array artifact: {artifact}")
        with self._finalized_bundle(task_id, strict=strict) as root:
            if root is None:
                raise FileNotFoundError(self.bundle_path(task_id))
            array_obj = self._open_array_path(root, f"{artifact}/{self._item_key(wsi_id, fold_key)}")
            return cast(NDArray[Any], np.asarray(array_obj))

    def list_results(self, task_id: str) -> list[str]:
        return self.catalog.task_images(task_id)

    def list_wsi_artifacts(self, wsi_id: str) -> list[dict[str, str]]:
        return [{key: row[key] for key in ('task_id','artifact','fold_key') if row[key] is not None}
                for row in self.catalog.image(wsi_id)]

    def list_task_wsi_artifacts(self, task_id: str, wsi_id: str) -> list[dict[str, str]]:
        return self.list_task_artifacts_for_wsis(task_id, [wsi_id]).get(wsi_id, [])

    def list_task_artifacts_for_wsis(
        self, task_id: str, wsi_ids: list[str]
    ) -> dict[str, list[dict[str, str]]]:
        """Read a finalized bundle directory once for a bounded group of slides."""
        wanted = set(wsi_ids)
        artifacts: dict[str, list[dict[str, str]]] = {wsi_id: [] for wsi_id in wanted}
        if not wanted:
            return artifacts
        bundle = self.bundle_path(task_id)
        if not bundle.exists():
            return artifacts
        if self.staging_path(task_id).exists():
            return artifacts
        with zipfile.ZipFile(bundle, mode="r") as zf:
            names = set(zf.namelist())
            try:
                root_attrs = cast(
                    dict[str, object], json.loads(zf.read(".zattrs").decode("utf-8"))
                )
            except KeyError:
                return artifacts
            if not bool(root_attrs.get("finalized", False)):
                return artifacts
            for name in names:
                parts = name.split("/")
                if len(parts) != 3:
                    continue
                group_name, item_key, marker_name = parts
                artifact = RESULT_ARTIFACT if group_name == "results" else group_name
                if artifact not in ALL_ARTIFACTS:
                    continue
                expected_marker = (
                    ".zattrs" if artifact == RESULT_ARTIFACT else ".zarray"
                )
                if marker_name != expected_marker:
                    continue
                decoded = self._decode_item_key(item_key)
                if decoded is None:
                    continue
                decoded_wsi_id, fold_key = decoded
                if decoded_wsi_id not in wanted:
                    continue
                entry = {"task_id": task_id, "artifact": artifact}
                if fold_key:
                    entry["fold_key"] = fold_key
                artifacts[decoded_wsi_id].append(entry)
        for entries in artifacts.values():
            entries.sort(
                key=lambda item: (
                    str(item.get("artifact", "")),
                    str(item.get("fold_key") or ""),
                )
            )
        return artifacts

    def task_artifact_presence_for_items(
        self,
        task_id: str,
        items: list[tuple[str, str | None]],
        artifacts: set[str],
    ) -> dict[str, set[tuple[str, str | None]]]:
        presence: dict[str, set[tuple[str, str | None]]] = {
            artifact: set() for artifact in artifacts
        }
        bundle = self.bundle_path(task_id)
        if not bundle.exists():
            raise FileNotFoundError(bundle)
        if self.staging_path(task_id).exists():
            raise IncompleteAIResultBundleError(task_id)
        with zipfile.ZipFile(bundle, mode="r") as zf:
            names = set(zf.namelist())
            root_attrs = cast(
                dict[str, object], json.loads(zf.read(".zattrs").decode("utf-8"))
            )
            if not bool(root_attrs.get("finalized", False)):
                raise IncompleteAIResultBundleError(task_id)
            for artifact in artifacts:
                group_name = "results" if artifact == RESULT_ARTIFACT else artifact
                marker_name = ".zattrs" if artifact == RESULT_ARTIFACT else ".zarray"
                for wsi_id, fold_key in items:
                    item_key = self._item_key(wsi_id, fold_key)
                    if f"{group_name}/{item_key}/{marker_name}" in names:
                        presence[artifact].add((wsi_id, fold_key))
        return presence

    def artifact_exists(
        self,
        task_id: str,
        wsi_id: str,
        artifact: str,
        fold_key: str | None = None,
        strict: bool = False,
    ) -> bool:
        if artifact not in ALL_ARTIFACTS:
            raise ValueError(f"unsupported artifact: {artifact}")
        item_key = self._item_key(wsi_id, fold_key)
        with self._finalized_bundle(task_id, strict=strict) as root:
            if root is not None:
                if artifact == RESULT_ARTIFACT:
                    return self._path_exists(root, f"results/{item_key}")
                return self._path_exists(root, f"{artifact}/{item_key}")
        return False

    def delete_task(self, task_id: str) -> dict[str, Any]:
        with self._task_lock(task_id):
            bundle = self.bundle_path(task_id)
            staging = self.staging_path(task_id)
            deleted_files = [str(bundle)] if bundle.is_file() else []
            deleted_dirs = [str(staging)] if staging.is_dir() else []
            total_size = bundle.stat().st_size if deleted_files else 0
            if deleted_dirs:
                total_size += sum(p.stat().st_size for p in staging.rglob("*") if p.is_file())
            bundle.unlink(missing_ok=True)
            if deleted_dirs:
                shutil.rmtree(staging)
            self.catalog.remove_task(task_id)
            return {"deleted_files": deleted_files, "deleted_dirs": deleted_dirs, "total_size": total_size}

    def delete_wsi(self, wsi_id: str) -> None:
        for task_id in {item['task_id'] for item in self.catalog.image(wsi_id)}:
            self.delete_wsi_result(task_id,wsi_id)

    def delete_wsi_result(self, task_id: str, wsi_id: str) -> dict[str, Any]:
        with self._task_lock(task_id):
            bundle = self.bundle_path(task_id)
            if not bundle.exists():
                return {"deleted": False, "removed_artifacts": [], "bundle_removed": False, "size_before": 0, "size_after": 0}

            size_before = bundle.stat().st_size
            self._hydrate_staging_from_bundle(task_id)
            root = self._open_staging_group(task_id, overwrite=False)
            removed_artifacts: list[str] = []
            removed_any = False
            remaining_wsi_ids = set(cast(list[str], root.attrs.get("wsi_ids", [])))

            for artifact in ALL_ARTIFACTS:
                group_name = "results" if artifact == RESULT_ARTIFACT else artifact
                group = self._open_group_path(root, group_name)
                if group is None:
                    continue
                for item_key in list(group.keys()):
                    decoded = self._decode_item_key(str(item_key))
                    if decoded is None or decoded[0] != wsi_id:
                        continue
                    del group[str(item_key)]
                    removed_artifacts.append(artifact)
                    removed_any = True

            if not removed_any:
                shutil.rmtree(self.staging_path(task_id), ignore_errors=True)
                return {"deleted": False, "removed_artifacts": [], "bundle_removed": False, "size_before": size_before, "size_after": size_before}

            remaining_wsi_ids.discard(wsi_id)
            root.attrs["wsi_ids"] = sorted(remaining_wsi_ids)
            if remaining_wsi_ids:
                self._finalize_task_bundle(task_id)
                size_after = bundle.stat().st_size
                return {
                    "deleted": True,
                    "removed_artifacts": sorted(set(removed_artifacts)),
                    "bundle_removed": False,
                    "size_before": size_before,
                    "size_after": size_after,
                }

            shutil.rmtree(self.staging_path(task_id), ignore_errors=True)
            bundle.unlink(missing_ok=True)
            self.catalog.remove_task(task_id)
            return {
                "deleted": True,
                "removed_artifacts": sorted(set(removed_artifacts)),
                "bundle_removed": True,
                "size_before": size_before,
                "size_after": 0,
            }

    def bundle_stats(self, task_id: str) -> dict[str, Any]:
        bundle = self.bundle_path(task_id)
        return {
            "task_id": task_id,
            "exists": bundle.exists(),
            "path": str(bundle),
            "size_bytes": bundle.stat().st_size if bundle.exists() else 0,
            "wsi_count": len(self.list_results(task_id)) if bundle.exists() else 0,
        }

    def validate_bundle(self, task_id: str) -> bool:
        with self._finalized_bundle(task_id, strict=False) as root:
            if root is None:
                return False
            return (
                root.attrs.get("schema_version") == SCHEMA_VERSION
                and bool(root.attrs.get("finalized", False))
                and root.attrs.get("source") == "zarr_zip"
            )

    def rebuild_wsi_index(self, task_id: str | None = None) -> list[str] | dict[str, list[str]]:
        if task_id is not None:
            return self.catalog.replace_bundle(task_id,self.bundle_path(task_id))
        return {identity:self.catalog.replace_bundle(identity,self.bundle_path(identity))
                for identity in self._discover_task_ids()}

    def _finalize_task_bundle(self, task_id: str) -> Path:
        staging = self.staging_path(task_id)
        if not staging.exists():
            raise FileNotFoundError(f"staging bundle not found: {staging}")
        root = self._open_staging_group(task_id, overwrite=False)
        self._ensure_root_attrs(root, task_id)
        root.attrs["wsi_ids"] = self._collect_staged_wsi_ids(root)
        root.attrs["finalized"] = True

        tmp_zip = self.bundle_path(task_id).with_name(f"{task_id}.zarr.zip.tmp")
        final_zip = self.bundle_path(task_id)
        tmp_zip.unlink(missing_ok=True)
        with zipfile.ZipFile(tmp_zip, mode="w", compression=zipfile.ZIP_STORED) as zf:
            for file_path in staging.rglob("*"):
                if file_path.is_file():
                    zf.write(file_path, file_path.relative_to(staging))
        tmp_zip.replace(final_zip)
        shutil.rmtree(staging, ignore_errors=True)
        self.rebuild_wsi_index(task_id)
        return final_zip

    def _dedupe_zip_entries(self, zip_path: Path) -> None:
        deduped_path = zip_path.with_suffix(zip_path.suffix + ".deduped")
        entries: OrderedDict[str, bytes] = OrderedDict()
        with zipfile.ZipFile(zip_path, mode="r") as src:
            for name in src.namelist():
                entries[name] = src.read(name)
        with zipfile.ZipFile(deduped_path, mode="w", compression=zipfile.ZIP_STORED) as dst:
            for name, payload in entries.items():
                dst.writestr(name, payload)
        deduped_path.replace(zip_path)

    def _hydrate_staging_from_bundle(self, task_id: str) -> None:
        staging = self.staging_path(task_id)
        if staging.exists() or not self.bundle_path(task_id).exists():
            return
        staging.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(self.bundle_path(task_id), mode="r") as zf:
            self._extract_bundle_members_safely(zf, staging)
        root = self._open_staging_group(task_id, overwrite=False)
        root.attrs["finalized"] = False

    @contextmanager
    def _task_lock(self, task_id: str) -> Iterator[None]:
        # Gateway deletions and AI/Worker writers run in different processes.
        # A thread lock alone cannot protect the shared staging tree or temp ZIP.
        lock_key = str(self.bundle_path(task_id).resolve())
        with _TASK_LOCKS_GUARD:
            lock = _TASK_LOCKS.get(lock_key)
            if lock is None:
                lock = threading.Lock()
                _TASK_LOCKS[lock_key] = lock
        with lock:
            lock_dir = self.bundle_dir / ".locks"
            lock_dir.mkdir(parents=True, exist_ok=True)
            lock_name = hashlib.sha256(task_id.encode()).hexdigest()
            # Keep lock files: unlinking them would allow two locks for one task.
            with (lock_dir / lock_name).open("a+b") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _open_staging_group(self, task_id: str, overwrite: bool) -> zarr.Group:
        kwargs = {"mode": "w" if overwrite else "a"}
        return self._open_group(self.staging_path(task_id), **kwargs)

    def _open_finalized_bundle(self, task_id: str, strict: bool) -> zarr.Group | None:
        warnings.warn(
            "_open_finalized_bundle leaks ZipStore handles; use _finalized_bundle instead",
            DeprecationWarning,
            stacklevel=2,
        )
        bundle = self.bundle_path(task_id)
        if bundle.exists():
            store = ZipStore(str(bundle), mode="r")
            root = zarr.open_group(store=store, mode="r")
            if bool(root.attrs.get("finalized", False)):
                return root
            if strict:
                raise IncompleteAIResultBundleError(task_id)
            return None
        if self.staging_path(task_id).exists() and strict:
            raise IncompleteAIResultBundleError(task_id)
        return None

    @contextmanager
    def _finalized_bundle(
        self, task_id: str, strict: bool
    ) -> Iterator[zarr.Group | None]:
        bundle = self.bundle_path(task_id)
        if bundle.exists():
            store = ZipStore(str(bundle), mode="r")
            try:
                root = zarr.open_group(store=store, mode="r")
                if bool(root.attrs.get("finalized", False)):
                    yield root
                elif strict:
                    raise IncompleteAIResultBundleError(task_id)
                else:
                    yield None
            finally:
                store.close()
            return
        if self.staging_path(task_id).exists() and strict:
            raise IncompleteAIResultBundleError(task_id)
        yield None

    def _extract_bundle_members_safely(
        self, zf: zipfile.ZipFile, target_dir: Path
    ) -> None:
        target_root = target_dir.resolve()
        for member in zf.infolist():
            name = member.filename
            member_path = PurePosixPath(name)
            if (
                not name
                or "\\" in name
                or member_path.is_absolute()
                or ".." in member_path.parts
            ):
                raise ValueError(f"unsafe bundle member: {name}")
            destination = (target_dir / Path(*member_path.parts)).resolve()
            if target_root != destination and target_root not in destination.parents:
                raise ValueError(f"unsafe bundle member: {name}")
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member, "r") as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target)

    def _open_group(self, path: Path, **kwargs: Any) -> zarr.Group:
        return zarr.open_group(str(path), zarr_version=2, **kwargs)

    def _open_group_path(self, root: zarr.Group, path: str) -> zarr.Group:
        return cast(zarr.Group, root.get(path))

    def _open_array_path(self, root: zarr.Group, path: str) -> Any:
        return root.get(path)

    def _path_exists(self, root: zarr.Group, path: str) -> bool:
        return root.get(path) is not None

    def _ensure_root_attrs(self, root: zarr.Group, task_id: str) -> None:
        root.attrs.setdefault("schema_version", SCHEMA_VERSION)
        root.attrs.setdefault("task_id", task_id)
        root.attrs.setdefault("created_at", datetime.now(UTC).isoformat())
        root.attrs.setdefault("finalized", False)
        root.attrs.setdefault("wsi_ids", [])
        root.attrs.setdefault("source", "zarr_zip")

    def _merge_wsi_id(
        self, root: zarr.Group, task_id: str, wsi_id: str, update_index: bool = True
    ) -> None:
        merged = sorted(set(cast(list[str], root.attrs.get("wsi_ids", []))) | {wsi_id})
        root.attrs["wsi_ids"] = merged

    def _list_task_wsi_ids(self, task_id: str) -> list[str]:
        with self._finalized_bundle(task_id, strict=False) as root:
            if root is not None:
                return sorted(cast(list[str], root.attrs.get("wsi_ids", [])))
        return []

    def _collect_staged_wsi_ids(self, root: zarr.Group) -> list[str]:
        wsi_ids = set(cast(list[str], root.attrs.get("wsi_ids", [])))
        for group_name in ("results", *ARRAY_ARTIFACTS):
            group = root.get(group_name)
            if group is None:
                continue
            for item_key in cast(zarr.Group, group).keys():
                decoded = self._decode_item_key(str(item_key))
                if decoded is not None:
                    wsi_ids.add(decoded[0])
        return sorted(wsi_ids)

    def _discover_task_ids(self) -> list[str]:
        return sorted(path.name.removesuffix(".zarr.zip") for path in self.bundle_dir.glob("*.zarr.zip"))

    def _item_key(self, wsi_id: str, fold_key: str | None = None) -> str:
        raw = f"{wsi_id}\0{fold_key or ''}"
        return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")

    def _decode_item_key(self, item_key: str) -> tuple[str, str | None] | None:
        padding = "=" * (-len(item_key) % 4)
        try:
            raw = base64.urlsafe_b64decode(f"{item_key}{padding}").decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None
        if "\0" not in raw:
            return None
        wsi_id, fold_key = raw.split("\0", 1)
        return wsi_id, fold_key or None
