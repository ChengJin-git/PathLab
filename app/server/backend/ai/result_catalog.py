"""Indexed artifact metadata, transactionally replaced when a bundle is finalized.

The catalog lives next to immutable result bundles. Readers never open bundles or
walk the filesystem. SQLite WAL coordinates synchronous writers across services.
"""

from contextlib import contextmanager
import base64
import json
from pathlib import Path
import sqlite3
import zipfile

SUMMARY_FIELDS = {
    "task_type",
    "task_name",
    "pred",
    "probs",
    "classes",
    "class_names",
    "feature_extractor",
    "aggregator",
    "image_size",
    "cam_size",
    "patch_size",
    "attention_type",
    "num_attention_classes",
    "risk_score",
    "risk_group",
    "has_ground_truth",
    "segmentation_preview",
    "num_classes",
    "metrics",
}


class ResultCatalog:
    def __init__(self, root: Path):
        self.path = Path(root) / "catalog.sqlite3"

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("""CREATE TABLE IF NOT EXISTS artifacts (
                task_id TEXT NOT NULL, wsi_id TEXT NOT NULL, fold_key TEXT NOT NULL,
                artifact TEXT NOT NULL, summary TEXT NOT NULL, revision TEXT NOT NULL,
                PRIMARY KEY(task_id,wsi_id,fold_key,artifact))""")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS artifacts_image ON artifacts(wsi_id,task_id)"
            )
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def replace_bundle(self, task_id, path):
        rows = []
        path = Path(path)
        if path.is_file():
            stat = path.stat()
            revision = f"{stat.st_mtime_ns}:{stat.st_size}"
            with zipfile.ZipFile(path) as archive:
                if not json.loads(archive.read(".zattrs")).get("finalized"):
                    raise ValueError("Cannot index an unfinished result bundle")
                names = set(archive.namelist())
                summaries = {}
                for name in names:
                    parts = name.split("/")
                    if len(parts) != 3 or parts[2] not in {".zattrs", ".zarray"}:
                        continue
                    group, key, marker = parts
                    artifact = "result" if group == "results" else group
                    from .result_store import ALL_ARTIFACTS

                    if artifact not in ALL_ARTIFACTS or marker != (
                        ".zattrs" if artifact == "result" else ".zarray"
                    ):
                        continue
                    try:
                        wsi_id, fold = (
                            base64.urlsafe_b64decode(key + "=" * (-len(key) % 4))
                            .decode()
                            .split("\0", 1)
                        )
                    except (ValueError, UnicodeError):
                        continue
                    if key not in summaries:
                        metadata_name = f"results/{key}/.zattrs"
                        metadata = (
                            json.loads(archive.read(metadata_name)).get(
                                "result_json", {}
                            )
                            if metadata_name in names
                            else {}
                        )
                        summaries[key] = {
                            field: value
                            for field, value in metadata.items()
                            if field in SUMMARY_FIELDS
                        }
                    summary = dict(summaries[key])
                    if artifact == "attention":
                        shape = json.loads(archive.read(name)).get("shape", [])
                        summary["attention_type"] = (
                            "multi_class" if len(shape) == 2 else "single"
                        )
                        summary["num_attention_classes"] = (
                            shape[0] if len(shape) == 2 else None
                        )
                    rows.append(
                        (
                            task_id,
                            wsi_id,
                            fold,
                            artifact,
                            json.dumps(summary, separators=(",", ":")),
                            revision,
                        )
                    )
        with self.connection() as db:
            db.execute("DELETE FROM artifacts WHERE task_id=?", (task_id,))
            db.executemany("INSERT INTO artifacts VALUES(?,?,?,?,?,?)", rows)
        return sorted({row[1] for row in rows})

    def image(self, wsi_id, task_ids=None):
        with self.connection() as db:
            query, params = "SELECT * FROM artifacts WHERE wsi_id=?", [wsi_id]
            if task_ids is not None:
                if not task_ids:
                    return []
                query += " AND task_id IN (" + ",".join("?" for _ in task_ids) + ")"
                params.extend(task_ids)
            rows = db.execute(
                query + " ORDER BY task_id,fold_key,artifact", params
            ).fetchall()
        return [
            {
                **dict(row),
                "summary": json.loads(row["summary"]),
                "fold_key": row["fold_key"] or None,
            }
            for row in rows
        ]

    def remove_task(self, task_id):
        with self.connection() as db:
            db.execute("DELETE FROM artifacts WHERE task_id=?", (task_id,))

    def tasks(self):
        with self.connection() as db:
            return [
                row[0] for row in db.execute("SELECT DISTINCT task_id FROM artifacts")
            ]

    def task_images(self, task_id):
        with self.connection() as db:
            return [
                row[0]
                for row in db.execute(
                    "SELECT DISTINCT wsi_id FROM artifacts WHERE task_id=? ORDER BY wsi_id",
                    (task_id,),
                )
            ]
