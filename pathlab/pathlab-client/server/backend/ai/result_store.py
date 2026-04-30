import base64
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
LEGACY_DIR_NAME = "ai_results"

RESULT_ARTIFACT = "result"
ATTENTION_ARTIFACT = "attention"
ATTENTION_RAW_ARTIFACT = "attention_raw"
CAM_ARTIFACT = "cam"
PRED_MASK_ARTIFACT = "pred_mask"

ARRAY_ARTIFACTS = {
    ATTENTION_ARTIFACT,
    ATTENTION_RAW_ARTIFACT,
    CAM_ARTIFACT,
    PRED_MASK_ARTIFACT,
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
        self.legacy_dir = self.uploads_dir / LEGACY_DIR_NAME
        self.staging_root = self.bundle_dir / ".staging"
        self.index_path = self.bundle_dir / ".wsi_index.json"
        self.bundle_dir.mkdir(parents=True, exist_ok=True)
        self.legacy_dir.mkdir(parents=True, exist_ok=True)
        self.staging_root.mkdir(parents=True, exist_ok=True)

    def bundle_path(self, task_id: str) -> Path:
        return self.bundle_dir / f"{task_id}.zarr.zip"

    def staging_path(self, task_id: str) -> Path:
        return self.staging_root / f"{task_id}.zarr"

    def legacy_result_path(
        self, task_id: str, wsi_id: str, fold_key: str | None = None
    ) -> Path:
        filename = (
            f"train_{task_id}_{fold_key}_result.json"
            if fold_key
            else f"train_{task_id}_result.json"
        )
        return self.legacy_dir / wsi_id / filename

    def legacy_array_path(
        self, task_id: str, wsi_id: str, artifact: str, fold_key: str | None = None
    ) -> Path:
        if artifact not in ARRAY_ARTIFACTS:
            raise ValueError(f"unsupported array artifact: {artifact}")
        filename = (
            f"train_{task_id}_{fold_key}_{artifact}.npy"
            if fold_key
            else f"train_{task_id}_{artifact}.npy"
        )
        return self.legacy_dir / wsi_id / filename

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
                artifact_group.create_array(
                    item_key,
                    data=np.asarray(array),
                    overwrite=True,
                    attributes=item_attrs,
                )

            self._merge_wsi_id(root, task_id, wsi_id, update_index=update_index)
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
        elif not self.staging_path(task_id).exists():
            raise FileNotFoundError(f"staging bundle not found: {self.staging_path(task_id)}")

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
            try:
                root = zarr.open_group(store=store, mode="w", zarr_format=2)
            except TypeError:
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
            artifact_group.create_array(
                item_key,
                data=np.asarray(array),
                chunks=tuple(int(dim) for dim in np.asarray(array).shape) or "auto",
                overwrite=True,
                attributes=item_attrs,
            )
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
                if strict:
                    raise FileNotFoundError(self.bundle_path(task_id))
                return self._read_legacy_result(task_id, wsi_id, fold_key)

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
                if strict:
                    raise FileNotFoundError(self.bundle_path(task_id))
                return np.load(self.legacy_array_path(task_id, wsi_id, artifact, fold_key))
            array_obj = self._open_array_path(root, f"{artifact}/{self._item_key(wsi_id, fold_key)}")
            return cast(NDArray[Any], np.asarray(array_obj))

    def list_results(self, task_id: str) -> list[str]:
        with self._finalized_bundle(task_id, strict=False) as root:
            if root is not None:
                return sorted(cast(list[str], root.attrs.get("wsi_ids", [])))
        rebuilt = self.rebuild_wsi_index(task_id)
        return rebuilt if isinstance(rebuilt, list) else []

    def list_wsi_artifacts(self, wsi_id: str) -> list[dict[str, str]]:
        artifacts: list[dict[str, str]] = []
        for bundle in sorted(self.bundle_dir.glob("*.zarr.zip")):
            task_id = bundle.name.removesuffix(".zarr.zip")
            artifacts.extend(self.list_task_wsi_artifacts(task_id, wsi_id))
        return artifacts

    def list_task_wsi_artifacts(self, task_id: str, wsi_id: str) -> list[dict[str, str]]:
        artifacts: list[dict[str, str]] = []
        bundle = self.bundle_path(task_id)
        if not bundle.exists():
            return artifacts
        with self._finalized_bundle(task_id, strict=False) as root:
            if root is None:
                return artifacts
            for artifact, group_name in (
                (RESULT_ARTIFACT, "results"),
                (ATTENTION_ARTIFACT, ATTENTION_ARTIFACT),
                (ATTENTION_RAW_ARTIFACT, ATTENTION_RAW_ARTIFACT),
                (CAM_ARTIFACT, CAM_ARTIFACT),
                (PRED_MASK_ARTIFACT, PRED_MASK_ARTIFACT),
            ):
                group = self._open_group_path(root, group_name)
                if group is None:
                    continue
                for item_name in group.keys():
                    item = group.get(item_name)
                    attrs = getattr(item, "attrs", {})
                    if attrs.get("wsi_id") != wsi_id:
                        continue
                    entry = {"task_id": task_id, "artifact": artifact}
                    fold_key = attrs.get("fold_key")
                    if fold_key:
                        entry["fold_key"] = str(fold_key)
                    artifacts.append(entry)
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
        if strict:
            return False
        if artifact == RESULT_ARTIFACT:
            return self.legacy_result_path(task_id, wsi_id, fold_key).exists()
        return self.legacy_array_path(task_id, wsi_id, artifact, fold_key).exists()

    def delete_task(self, task_id: str) -> None:
        self.bundle_path(task_id).unlink(missing_ok=True)
        shutil.rmtree(self.staging_path(task_id), ignore_errors=True)
        for wsi_dir in self.legacy_dir.iterdir() if self.legacy_dir.exists() else []:
            if not wsi_dir.is_dir():
                continue
            for path in wsi_dir.glob(f"train_{task_id}*_result.json"):
                path.unlink(missing_ok=True)
            for artifact in ARRAY_ARTIFACTS:
                (wsi_dir / f"train_{task_id}_{artifact}.npy").unlink(missing_ok=True)
        index = self._load_index()
        index.pop(task_id, None)
        self._save_index(index)

    def delete_wsi(self, wsi_id: str) -> None:
        shutil.rmtree(self.legacy_dir / wsi_id, ignore_errors=True)
        for task_id in list(self._load_index()):
            self.rebuild_wsi_index(task_id)

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
        task_ids = [task_id] if task_id is not None else self._discover_task_ids()
        index = self._load_index()
        last_wsi_ids: list[str] = []
        for current_task_id in task_ids:
            if current_task_id is None:
                continue
            wsi_ids = self._list_task_wsi_ids(current_task_id)
            index[current_task_id] = wsi_ids
            last_wsi_ids = wsi_ids
        self._save_index(index)
        return last_wsi_ids if task_id is not None else index

    def _finalize_task_bundle(self, task_id: str) -> Path:
        staging = self.staging_path(task_id)
        if not staging.exists():
            raise FileNotFoundError(f"staging bundle not found: {staging}")
        root = self._open_staging_group(task_id, overwrite=False)
        self._ensure_root_attrs(root, task_id)
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

    def _task_lock(self, task_id: str) -> threading.Lock:
        with _TASK_LOCKS_GUARD:
            lock = _TASK_LOCKS.get(task_id)
            if lock is None:
                lock = threading.Lock()
                _TASK_LOCKS[task_id] = lock
            return lock

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
        try:
            return zarr.open_group(str(path), zarr_format=2, **kwargs)
        except TypeError:
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
        if update_index:
            self._update_index(task_id, merged)

    def _read_legacy_result(
        self, task_id: str, wsi_id: str, fold_key: str | None = None
    ) -> dict[str, Any]:
        path = self.legacy_result_path(task_id, wsi_id, fold_key)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        fold_files = sorted(path.parent.glob(f"train_{task_id}_fold_*_result.json"))
        if fold_files:
            return json.loads(fold_files[0].read_text(encoding="utf-8"))
        raise FileNotFoundError(path)

    def _list_task_wsi_ids(self, task_id: str) -> list[str]:
        with self._finalized_bundle(task_id, strict=False) as root:
            if root is not None:
                return sorted(cast(list[str], root.attrs.get("wsi_ids", [])))
        wsi_ids: list[str] = []
        for wsi_dir in self.legacy_dir.iterdir() if self.legacy_dir.exists() else []:
            if wsi_dir.is_dir() and (
                (wsi_dir / f"train_{task_id}_result.json").exists()
                or list(wsi_dir.glob(f"train_{task_id}_fold_*_result.json"))
            ):
                wsi_ids.append(wsi_dir.name)
        return sorted(set(wsi_ids))

    def _discover_task_ids(self) -> list[str]:
        task_ids = [path.name.removesuffix(".zarr.zip") for path in self.bundle_dir.glob("*.zarr.zip")]
        for wsi_dir in self.legacy_dir.iterdir() if self.legacy_dir.exists() else []:
            if not wsi_dir.is_dir():
                continue
            for result_file in wsi_dir.glob("train_*_result.json"):
                name = result_file.name.removeprefix("train_").removesuffix("_result.json")
                if "_fold_" in name:
                    name = name.split("_fold_", 1)[0]
                task_ids.append(name)
        return sorted(set(task_ids))

    def _item_key(self, wsi_id: str, fold_key: str | None = None) -> str:
        raw = f"{wsi_id}\0{fold_key or ''}"
        return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")

    def _load_index(self) -> dict[str, list[str]]:
        if not self.index_path.exists():
            return {}
        return cast(dict[str, list[str]], json.loads(self.index_path.read_text(encoding="utf-8")))

    def _save_index(self, data: dict[str, list[str]]) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(
            json.dumps(data, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )

    def _update_index(self, task_id: str, wsi_ids: list[str]) -> None:
        index = self._load_index()
        index[task_id] = sorted(set(wsi_ids))
        self._save_index(index)
