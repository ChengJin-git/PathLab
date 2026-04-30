from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import numpy as np

from .result_store import AIResultStore, ARRAY_ARTIFACTS
from ..common.config import Config

_RESULT_RE = re.compile(r"^train_(?P<task>.+?)(?:_(?P<fold>fold_\d+))?_result\.json$")
_ARRAY_RE = re.compile(
    r"^train_(?P<task>.+?)(?:_(?P<fold>fold_\d+))?_(?P<artifact>attention_raw|attention|cam|pred_mask)\.npy$"
)


def migrate_legacy_ai_results(
    uploads_dir: Path | None = None,
    *,
    execute: bool = False,
    validate: bool = True,
    rollback_log: Path | None = None,
) -> dict[str, Any]:
    root = Path(uploads_dir) if uploads_dir is not None else Config.get_uploads_dir()
    legacy_root = root / "ai_results"
    store = AIResultStore(root)
    tasks = _collect_legacy_tasks(legacy_root)
    summary: dict[str, Any] = {
        "uploads_dir": str(root),
        "dry_run": not execute,
        "tasks": {},
    }
    rollback_bundles: list[str] = []

    for task_id, entries in sorted(tasks.items()):
        valid_artifacts = sum(
            1 + len(entry.get("array_paths", entry.get("arrays", {})))
            for entry in entries
            if entry.get("result")
        )
        task_summary: dict[str, Any] = {
            "status": "planned",
            "valid_artifacts": valid_artifacts,
            "migrated_wsi_count": len({entry["wsi_id"] for entry in entries}),
        }
        marker = _marker_path(root, task_id)
        if (
            execute
            and marker.exists()
            and store.validate_bundle(task_id)
            and _bundle_has_expected_artifacts(store, task_id, entries)
        ):
            task_summary["status"] = "already_migrated"
            summary["tasks"][task_id] = task_summary
            rollback_bundles.append(str(store.bundle_path(task_id)))
            continue
        if execute:
            store.write_task_bundle(task_id, items=_load_array_payloads(entries))
            if validate and not store.validate_bundle(task_id):
                raise RuntimeError(f"AI result bundle validation failed for task {task_id}")
            marker.write_text(
                json.dumps({"schema_version": 1, "task_id": task_id}, sort_keys=True),
                encoding="utf-8",
            )
            task_summary["status"] = "migrated"
            rollback_bundles.append(str(store.bundle_path(task_id)))
        summary["tasks"][task_id] = task_summary

    if execute and rollback_log is not None:
        rollback_log.parent.mkdir(parents=True, exist_ok=True)
        rollback_log.write_text(
            json.dumps({"bundles": rollback_bundles}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return summary


def _collect_legacy_tasks(legacy_root: Path) -> dict[str, list[dict[str, Any]]]:
    entries: dict[tuple[str, str, str | None], dict[str, Any]] = {}
    if not legacy_root.exists():
        return {}

    for result_file in legacy_root.rglob("train_*_result.json"):
        match = _RESULT_RE.match(result_file.name)
        if not match:
            continue
        try:
            result = json.loads(result_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        task_id = match.group("task")
        fold_key = match.group("fold")
        wsi_id = str(result_file.parent.relative_to(legacy_root))
        key = (task_id, wsi_id, fold_key)
        entry = entries.setdefault(
            key,
            {"wsi_id": wsi_id, "fold_key": fold_key, "arrays": {}},
        )
        entry["result"] = result

    for array_file in legacy_root.rglob("train_*.npy"):
        match = _ARRAY_RE.match(array_file.name)
        if not match:
            continue
        task_id = match.group("task")
        fold_key = match.group("fold")
        artifact = match.group("artifact")
        if artifact not in ARRAY_ARTIFACTS:
            continue
        wsi_id = str(array_file.parent.relative_to(legacy_root))
        key = (task_id, wsi_id, fold_key)
        entry = entries.setdefault(
            key,
            {"wsi_id": wsi_id, "fold_key": fold_key, "array_paths": {}},
        )
        entry.setdefault("array_paths", {})[artifact] = array_file

    tasks: dict[str, list[dict[str, Any]]] = {}
    for (task_id, _wsi_id, _fold_key), entry in entries.items():
        if "result" not in entry:
            continue
        clean_entry = {
            "wsi_id": entry["wsi_id"],
            "result": entry["result"],
            "array_paths": entry.get("array_paths", {}),
        }
        if entry.get("fold_key"):
            clean_entry["fold_key"] = entry["fold_key"]
        tasks.setdefault(task_id, []).append(clean_entry)
    return tasks


def _bundle_has_expected_artifacts(
    store: AIResultStore, task_id: str, entries: list[dict[str, Any]]
) -> bool:
    requested_items = [
        (str(entry["wsi_id"]), str(entry["fold_key"]) if entry.get("fold_key") else None)
        for entry in entries
    ]
    expected_artifacts = {"result"}
    for entry in entries:
        expected_artifacts.update(entry.get("array_paths", {}).keys())

    presence = store.task_artifact_presence_for_items(
        task_id,
        items=requested_items,
        artifacts=expected_artifacts,
    )
    for entry in entries:
        item = (
            str(entry["wsi_id"]),
            str(entry["fold_key"]) if entry.get("fold_key") else None,
        )
        if item not in presence.get("result", set()):
            return False
        for artifact in entry.get("array_paths", {}):
            if item not in presence.get(artifact, set()):
                return False
    return True


def _load_array_payloads(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    loaded_entries: list[dict[str, Any]] = []
    for entry in entries:
        arrays: dict[str, Any] = {}
        for artifact, array_path in entry.get("array_paths", {}).items():
            try:
                arrays[artifact] = np.load(array_path)
            except (OSError, ValueError):
                continue
        loaded_entry = {
            "wsi_id": entry["wsi_id"],
            "result": entry["result"],
            "arrays": arrays,
        }
        if entry.get("fold_key"):
            loaded_entry["fold_key"] = entry["fold_key"]
        loaded_entries.append(loaded_entry)
    return loaded_entries


def _marker_path(uploads_dir: Path, task_id: str) -> Path:
    return uploads_dir / "ai_results_bundles" / f".migration_{task_id}.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate legacy AI results to Zarr bundles")
    parser.add_argument("--uploads-dir", type=Path, default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--rollback-log", type=Path, default=None)
    args = parser.parse_args()

    summary = migrate_legacy_ai_results(
        args.uploads_dir,
        execute=args.execute,
        validate=args.validate,
        rollback_log=args.rollback_log,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
