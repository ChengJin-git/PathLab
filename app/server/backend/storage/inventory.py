"""Disk-backed, bounded storage inventory. Readers never walk the data tree.

One row per loose artifact or owned directory, not per research input symlink.
Directory fingerprints include every local entry; symlink targets are never stat'd.
Only a completed generation is published. An interrupted scan leaves readers on
the previous generation and cannot authorize deletion.
"""

from __future__ import annotations

from contextlib import contextmanager
from bisect import bisect_left
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
from uuid import uuid4

from backend.common import file_lock

CATEGORIES = (
    "features",
    "patching",
    "images",
    "results",
    "training",
    "models",
    "research",
    "metadata",
    "documents",
    "system",
)
STATES = ("orphaned", "cached", "referenced", "recent", "managed")
IDENTITY = re.compile(
    r"(?<![A-Za-z0-9])(?:[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}"
    r"|(?:wsi|patch|train|extval|binfer|run|analysis|session|conv)_[a-f0-9]{8,64}"
    r"|[a-f0-9]{12,64})(?![A-Za-z0-9])"
)
IMAGE_ID = re.compile(
    r"^(?:[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}|(?:wsi|patch)_[a-f0-9]{8,64})$"
)
TEXT_SUFFIXES = {
    ".json",
    ".jsonl",
    ".csv",
    ".tsv",
    ".yaml",
    ".yml",
    ".toml",
    ".py",
    ".md",
}
GRACE_SECONDS = 24 * 3600


def identity(name: str) -> str:
    if name.startswith("session_"):
        return name.removeprefix("session_")
    for suffix in (
        ".zarr.zip.tmp",
        ".zarr.zip",
        ".zarr",
        ".feature.json",
        "_coords.h5",
        "_mask.png",
    ):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    if "." not in name:
        return name
    return re.sub(r"_s\d+$", "", Path(name).stem).removesuffix("_coco")


def fingerprint(info):
    return f"{info.st_dev}:{info.st_ino}:{info.st_mode}:{info.st_size}:{info.st_mtime_ns}:{info.st_ctime_ns}"


def within_paths(path, roots):
    while path not in {"", ".", "/"}:
        if path in roots:
            return True
        path = os.path.dirname(path)
    return False


def local_walk(root: Path):
    """scandir's no-follow mode avoids NAS calls for millions of input links."""
    pending = [str(root)]
    while pending:
        parent = pending.pop()
        with os.scandir(parent) as entries:
            for entry in entries:
                try:
                    info = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue
                yield entry.path, info
                if stat.S_ISDIR(info.st_mode):
                    pending.append(entry.path)


def measure(path: Path, *, visit=None):
    digest = hashlib.sha256()
    initial = path.lstat()
    result = dict(size=0, allocated=0, files=0, links=0, newest=0.0)
    # An order-independent digest avoids buffering or sorting huge directories.
    checksum = 0
    entries = [(str(path), initial)]
    if stat.S_ISDIR(initial.st_mode):
        from itertools import chain

        entries = chain(entries, local_walk(path))
    for name, info in entries:
        if info.st_dev != initial.st_dev:
            raise ValueError("Storage item crosses a filesystem boundary")
        relative = "." if name == str(path) else name[len(str(path)) + 1 :]
        token = f"{relative}\0{fingerprint(info)}".encode()
        checksum ^= int.from_bytes(hashlib.sha256(token).digest(), "big")
        result["allocated"] += (
            info.st_blocks * 512 if hasattr(info, "st_blocks") else info.st_size
        )
        result["newest"] = max(result["newest"], info.st_mtime, info.st_ctime)
        if not stat.S_ISDIR(info.st_mode):
            result["size"] += info.st_size
            result["links" if stat.S_ISLNK(info.st_mode) else "files"] += 1
        if visit:
            visit(name, info)
    digest.update(checksum.to_bytes(32, "big"))
    return {**result, "fingerprint": digest.hexdigest()}


class Inventory:
    def __init__(self, root: Path):
        self.root = Path(root).absolute()
        self.directory = self.root / ".storage-inventory"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "inventory.sqlite3"
        if (self.directory / "ready").exists() and self.path.exists():
            return
        with (self.directory / "init.lock").open("a+b") as handle, self.connect() as db:
            file_lock.flock(handle.fileno(), file_lock.LOCK_EX)
            db.executescript("""
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS items(
                    generation TEXT NOT NULL,id TEXT NOT NULL,path TEXT NOT NULL,
                    category TEXT NOT NULL,owner TEXT NOT NULL,kind TEXT NOT NULL,
                    size INTEGER NOT NULL,allocated INTEGER NOT NULL,files INTEGER NOT NULL,
                    links INTEGER NOT NULL,newest REAL NOT NULL,fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL,reason TEXT NOT NULL,
                    PRIMARY KEY(generation,id));
                CREATE INDEX IF NOT EXISTS items_page ON items(generation,category,state,allocated DESC,id);
                CREATE INDEX IF NOT EXISTS items_state_page ON items(generation,state,allocated DESC,id);
                CREATE INDEX IF NOT EXISTS items_size_page ON items(generation,allocated DESC,id);
                CREATE INDEX IF NOT EXISTS items_owner ON items(generation,owner,category);
                CREATE INDEX IF NOT EXISTS items_path ON items(generation,path);
                CREATE TABLE IF NOT EXISTS edges(
                    generation TEXT NOT NULL,source TEXT NOT NULL,target TEXT NOT NULL,
                    kind TEXT NOT NULL,PRIMARY KEY(generation,source,target,kind));
                CREATE INDEX IF NOT EXISTS edges_target ON edges(generation,target,source);
                CREATE INDEX IF NOT EXISTS edges_kind_target ON edges(generation,kind,target,source);
                CREATE TABLE IF NOT EXISTS item_ids(generation TEXT,item_id TEXT,identity TEXT,
                    PRIMARY KEY(generation,identity,item_id));
                CREATE TABLE IF NOT EXISTS reachable(generation TEXT,item_id TEXT,reason TEXT,
                    PRIMARY KEY(generation,item_id));
                CREATE TABLE IF NOT EXISTS manifests(
                    path TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,refs TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS operations(
                    task_id TEXT NOT NULL,item_id TEXT NOT NULL,path TEXT NOT NULL,
                    allocated INTEGER NOT NULL,status TEXT NOT NULL,error TEXT,fingerprint TEXT,
                    PRIMARY KEY(task_id,item_id));
                CREATE TABLE IF NOT EXISTS event_references(session_id TEXT,kind TEXT,target TEXT,
                    PRIMARY KEY(session_id,kind,target));
            """)
            db.commit()
            (self.directory / "ready").touch()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=30000")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @contextmanager
    def lock(self):
        inspections = self.root / ".storage-inspections"
        inspections.mkdir(exist_ok=True)
        with (
            (inspections / "heavy-scan.lock").open("a+b") as heavy,
            (self.directory / "write.lock").open("a+b") as handle,
        ):
            file_lock.flock(heavy.fileno(), file_lock.LOCK_EX | file_lock.LOCK_NB)
            file_lock.flock(handle.fileno(), file_lock.LOCK_EX | file_lock.LOCK_NB)
            try:
                yield
            finally:
                file_lock.flock(handle.fileno(), file_lock.LOCK_UN)
                file_lock.flock(heavy.fileno(), file_lock.LOCK_UN)

    def summary(self):
        with self.connect() as db:
            value = db.execute("SELECT value FROM meta WHERE key='summary'").fetchone()
            return (
                json.loads(value[0])
                if value
                else {
                    "generation": None,
                    "categories": [],
                    "size": 0,
                    "allocated": 0,
                    "files": 0,
                    "links": 0,
                    "scanned_at": None,
                }
            )

    def page(self, category=None, state=None, cursor=None, limit=50):
        limit = min(max(limit, 1), 100)
        query, args = "SELECT * FROM items WHERE generation=?", []
        if category:
            query += " AND category=?"
            args.append(category)
        if state:
            query += " AND state=?"
            args.append(state)
        if cursor:
            try:
                size, key = cursor.split(":", 1)
                size = int(size)
            except (ValueError, TypeError) as exc:
                raise ValueError("Invalid storage cursor") from exc
            query += " AND (allocated<? OR (allocated=? AND id>?))"
            args.extend([size, size, key])
        query += " ORDER BY allocated DESC,id LIMIT ?"
        with self.connect() as db:
            # Read counts and the page from one published generation. Counts are
            # pre-aggregated; selecting all never enumerates IDs in a request.
            db.execute("BEGIN")
            saved = db.execute("SELECT value FROM meta WHERE key='summary'").fetchone()
            summary = (
                json.loads(saved[0])
                if saved
                else {"generation": None, "categories": []}
            )
            generation = summary["generation"]
            groups = [
                group
                for group in summary["categories"]
                if not category or group["category"] == category
            ]
            total = sum(
                group["states"][state]["items"] if state else group["items"]
                for group in groups
            )
            allocated = sum(
                group["states"][state]["allocated"] if state else group["allocated"]
                for group in groups
            )
            rows = [
                dict(row) for row in db.execute(query, [generation, *args, limit + 1])
            ]
        more = len(rows) > limit
        rows = rows[:limit]
        return {
            "generation": generation,
            "items": rows,
            "total": total,
            "allocated": allocated,
            "next_cursor": f"{rows[-1]['allocated']}:{rows[-1]['id']}"
            if more
            else None,
        }

    def roots(self):
        """Yield non-overlapping deletion units; unknown content is inventory-only."""
        layouts = {
            "features": ("features", 3),
            "coordinates": ("patching", 2),
            "masks": ("patching", 1),
            "patches": ("patching", 1),
            "wsi_files": ("images", 1),
            "metadata": ("metadata", 1),
            "annotations": ("metadata", 1),
            "training": ("training", 1),
            "models": ("models", 1),
            "ai_results_bundles": ("results", 1),
            "logs/training": ("training", 1),
            "logs/analysis": ("results", 2),
            "analysis-workbench": ("results", 1),
            "reports": ("documents", 1),
            "chat-files": ("documents", 2),
            "chat_patch_inference": ("results", 1),
            "autoresearch/autoresearch_sessions": ("research", 1),
            "autoresearch/runtime": ("research", 1),
            "autoresearch/pathlab_datasets/session_inputs": ("research", 1),
            "autoresearch/dataset_cache": ("research", 1),
        }
        for relative, (category, depth) in layouts.items():
            base = self.root / relative
            if base.is_symlink() or not base.is_dir():
                continue
            pending = [(base, depth)]
            while pending:
                parent, remaining = pending.pop()
                with os.scandir(parent) as entries:
                    for entry in entries:
                        p = Path(entry.path)
                        if entry.name == ".locks":
                            yield p, "system", "managed"
                        elif (
                            relative == "metadata"
                            and entry.name
                            in {
                                "annotation_summaries",
                                "ground_truth_previews",
                                "drafts",
                            }
                            and entry.is_dir(follow_symlinks=False)
                        ):
                            pending.append((p, 1))
                        elif (
                            relative == "autoresearch/autoresearch_sessions"
                            and entry.name == "model_artifacts"
                            and entry.is_dir(follow_symlinks=False)
                        ):
                            pending.append((p, 1))
                        elif (
                            relative == "ai_results_bundles"
                            and entry.name == ".staging"
                            and entry.is_dir(follow_symlinks=False)
                        ):
                            pending.append((p, 1))
                        elif remaining > 1 and entry.is_dir(follow_symlinks=False):
                            pending.append((p, remaining - 1))
                        else:
                            kind = "artifact"
                            if (
                                entry.name.startswith(".")
                                or relative == "autoresearch/dataset_cache"
                            ):
                                kind = "managed"
                            if (
                                relative == "ai_results_bundles"
                                and not entry.name.endswith((".zarr.zip", ".zarr"))
                            ):
                                kind = "managed"
                            yield p, category, kind
        covered = {name.split("/")[0] for name in layouts}
        for entry in self.root.iterdir():
            if entry.name not in covered and entry.name not in {
                ".storage-inventory",
                ".storage-inspections",
            }:
                yield entry, "system", "managed"
        # Shared research tools/caches are visible but never treated as orphan outputs.
        research = self.root / "autoresearch"
        if research.is_dir():
            known = {
                "autoresearch_sessions",
                "runtime",
                "pathlab_datasets",
                "dataset_cache",
            }
            for entry in research.iterdir():
                if entry.name not in known:
                    yield entry, "system", "managed"
        logs = self.root / "logs"
        if logs.is_dir():
            for entry in logs.iterdir():
                if entry.name not in {"training", "analysis"}:
                    yield entry, "system", "managed"
        inputs = research / "pathlab_datasets"
        if inputs.is_dir():
            for entry in inputs.iterdir():
                if entry.name != "session_inputs":
                    yield entry, "system", "managed"

    def scan(self, references, progress=lambda *a, **k: None, *, deleted_paths=()):
        generation = uuid4().hex
        started = time.time()
        processed = 0
        unit_count = 0
        last_update = 0.0
        deleted_paths = set(deleted_paths)
        # Text often contains millions of unrelated hashes/IDs. Retain only
        # identities that can resolve to a local deletion unit in this generation.
        known_ids = set()
        known_paths = set()
        for path, _, _ in self.roots():
            owner = identity(path.name)
            known_paths.add(str(path.relative_to(self.root)))
            known_ids.add(owner)
            known_ids.update(IDENTITY.findall(owner))
        ordered_paths = sorted(known_paths)
        scope = hashlib.sha256("\0".join(ordered_paths).encode()).hexdigest()

        resolved_paths = {}

        def resolve_path(value):
            value = os.path.normpath(value)
            if value in resolved_paths:
                return resolved_paths[value]
            relative = (
                value[len(str(self.root)) + 1 :]
                if value.startswith(str(self.root) + os.sep)
                else os.path.relpath(value, self.root)
            )
            if relative.startswith("../"):
                return None
            prefix = relative.rstrip("/") + "/"
            index = bisect_left(ordered_paths, prefix)
            if index < len(ordered_paths) and ordered_paths[index].startswith(prefix):
                # Shared top-level roots only describe configuration.
                return relative if relative.count("/") >= 2 else None
            while relative not in {"", ".", "/"}:
                if relative in known_paths:
                    resolved_paths[value] = relative
                    return relative
                relative = os.path.dirname(relative)
            return None

        with self.connect() as db:

            def interrupt():
                try:
                    progress(processed, None, "references")
                except (InterruptedError, RuntimeError):
                    return 1
                return 0

            db.set_progress_handler(interrupt, 100000)
            db.execute(
                "DELETE FROM items WHERE generation != COALESCE((SELECT json_extract(value,'$.generation') FROM meta WHERE key='summary'),'')"
            )
            db.execute(
                "DELETE FROM edges WHERE generation != COALESCE((SELECT json_extract(value,'$.generation') FROM meta WHERE key='summary'),'')"
            )
            db.execute(
                "DELETE FROM item_ids WHERE generation != COALESCE((SELECT json_extract(value,'$.generation') FROM meta WHERE key='summary'),'')"
            )
            db.execute(
                "DELETE FROM reachable WHERE generation != COALESCE((SELECT json_extract(value,'$.generation') FROM meta WHERE key='summary'),'')"
            )
            for p, category, kind in self.roots():
                relative = str(p.relative_to(self.root))
                key = hashlib.sha256(relative.encode()).hexdigest()[:32]
                owner = identity(p.name)
                targets = set()

                def visit(name, info):
                    nonlocal processed, last_update
                    processed += 1
                    if stat.S_ISLNK(info.st_mode):
                        target = os.path.normpath(
                            os.path.join(os.path.dirname(name), os.readlink(name))
                        )
                        if target.startswith(str(self.root) + os.sep):
                            resolved = resolve_path(target)
                            if resolved:
                                targets.add((resolved, "path"))
                    elif (
                        kind != "managed"
                        and stat.S_ISREG(info.st_mode)
                        and category in {"research", "training", "models", "results"}
                        and Path(name).suffix.lower() in TEXT_SUFFIXES
                    ):
                        # Metadata extraction is cached by file identity, not parent mtime.
                        self._manifest(
                            db,
                            name,
                            info,
                            targets,
                            known_ids,
                            scope,
                            resolve_path,
                            lambda: progress(processed, None, category),
                        )
                    now = time.monotonic()
                    if now - last_update >= 0.5:
                        progress(processed, None, category)
                        last_update = now

                try:
                    info = measure(p, visit=visit)
                except FileNotFoundError:
                    # An active writer removed this unit during the scan. It
                    # cannot become a deletion candidate in this generation.
                    continue
                explicit = within_paths(relative, deleted_paths)
                state, reason = initial_state(
                    owner, category, kind, info, references, started, explicit=explicit
                )
                db.execute(
                    "INSERT INTO items VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        generation,
                        key,
                        relative,
                        category,
                        owner,
                        kind,
                        info["size"],
                        info["allocated"],
                        info["files"],
                        info["links"],
                        info["newest"],
                        info["fingerprint"],
                        state,
                        reason,
                    ),
                )
                db.executemany(
                    "INSERT OR IGNORE INTO item_ids VALUES(?,?,?)",
                    (
                        (generation, key, value)
                        for value in {owner, *IDENTITY.findall(owner)}
                    ),
                )
                if state in {"referenced", "recent", "managed"}:
                    db.execute(
                        "INSERT INTO reachable VALUES(?,?,?)", (generation, key, reason)
                    )
                db.executemany(
                    "INSERT OR IGNORE INTO edges VALUES(?,?,?,?)",
                    ((generation, key, target, kind) for target, kind in targets),
                )
                unit_count += 1
                if unit_count % 512 == 0:
                    db.commit()
            self._resolve(db, generation, references, progress)
            self._publish(db, generation, started)
            db.execute("DELETE FROM items WHERE generation != ?", (generation,))
            db.execute("DELETE FROM edges WHERE generation != ?", (generation,))
            db.execute("DELETE FROM item_ids WHERE generation != ?", (generation,))
            db.execute("DELETE FROM reachable WHERE generation != ?", (generation,))
        progress(processed, processed, "complete", force=True)
        return self.summary()

    def _resolve(self, db, generation, references, progress):
        owners = {
            row["path"]: row["id"]
            for row in db.execute(
                "SELECT path,id FROM items WHERE generation=?", (generation,)
            )
        }
        ordered = sorted(owners)

        def has_descendants(path):
            prefix = path.rstrip("/") + "/"
            index = bisect_left(ordered, prefix)
            return index < len(ordered) and ordered[index].startswith(prefix)

        def destination(path):
            while path not in {"", ".", "/"}:
                if path in owners:
                    return owners[path]
                path = os.path.dirname(path)
            return None

        for path in references.paths:
            key = destination(path)
            if key:
                db.execute(
                    "INSERT OR IGNORE INTO reachable VALUES(?,?,?)",
                    (generation, key, "path"),
                )
            elif path.count("/") >= 1 and has_descendants(path):
                prefix = path.rstrip("/") + "/"
                db.execute(
                    """INSERT OR IGNORE INTO reachable SELECT generation,id,'path' FROM items
                    WHERE generation=? AND path>=? AND path<?""",
                    (generation, prefix, prefix + "\uffff"),
                )
        # Resolve each distinct path once, even when millions of symlinks share it.
        db.execute(
            "CREATE TEMP TABLE destinations(target TEXT PRIMARY KEY,item_id TEXT)"
        )
        paths = db.execute(
            "SELECT DISTINCT target FROM edges WHERE generation=? AND kind='path'",
            (generation,),
        )
        processed = 0
        while batch := paths.fetchmany(512):
            db.executemany(
                "INSERT INTO destinations VALUES(?,?)",
                ((row[0], destination(row[0])) for row in batch),
            )
            processed += len(batch)
            progress(processed, None, "references")
        db.execute(
            "CREATE TEMP TABLE adjacency(source TEXT,target TEXT,PRIMARY KEY(source,target))"
        )
        db.execute(
            """INSERT OR IGNORE INTO adjacency SELECT e.source,d.item_id
            FROM edges e JOIN destinations d ON d.target=e.target
            WHERE e.generation=? AND e.kind='path' AND d.item_id IS NOT NULL AND e.source!=d.item_id""",
            (generation,),
        )
        db.execute(
            """INSERT OR IGNORE INTO adjacency SELECT e.source,i.item_id
            FROM edges e JOIN item_ids i ON i.generation=e.generation AND i.identity=e.target
            WHERE e.generation=? AND e.kind='id' AND e.source!=i.item_id""",
            (generation,),
        )
        db.execute(
            """INSERT OR IGNORE INTO adjacency SELECT f.id,p.id FROM items f JOIN items p
            ON p.generation=f.generation AND p.owner=f.owner AND p.category IN ('patching','metadata')
            WHERE f.generation=? AND f.category='features'""",
            (generation,),
        )
        # Directory inputs can contain multiple loose cache items. Resolve these
        # by the indexed path range instead of traversing the directory again.
        for row in db.execute("SELECT target FROM destinations WHERE item_id IS NULL"):
            target = row[0]
            if target.count("/") < 2 or not has_descendants(target):
                continue
            prefix = target.rstrip("/") + "/"
            db.execute(
                """INSERT OR IGNORE INTO adjacency SELECT e.source,i.id FROM edges e JOIN items i
                ON i.generation=e.generation AND i.path>=? AND i.path<?
                WHERE e.generation=? AND e.kind='path' AND e.target=?""",
                (prefix, prefix + "\uffff", generation, target),
            )
        db.execute("CREATE TEMP TABLE frontier(item_id TEXT PRIMARY KEY)")
        db.execute("CREATE TEMP TABLE next_frontier(item_id TEXT PRIMARY KEY)")
        db.execute(
            "INSERT INTO frontier SELECT item_id FROM reachable WHERE generation=?",
            (generation,),
        )
        while True:
            db.execute("DELETE FROM next_frontier")
            result = db.execute(
                """INSERT OR IGNORE INTO next_frontier SELECT a.target FROM frontier f
                CROSS JOIN adjacency a ON a.source=f.item_id WHERE NOT EXISTS
                (SELECT 1 FROM reachable r WHERE r.generation=? AND r.item_id=a.target)""",
                (generation,),
            )
            if not result.rowcount:
                break
            db.execute(
                "INSERT OR IGNORE INTO reachable SELECT ?,item_id,'reference' FROM next_frontier",
                (generation,),
            )
            db.execute("DELETE FROM frontier")
            db.execute("INSERT INTO frontier SELECT item_id FROM next_frontier")
        db.execute("DROP TABLE frontier")
        db.execute("DROP TABLE next_frontier")
        db.execute(
            """UPDATE items SET state='referenced',reason=(SELECT reason FROM reachable r
            WHERE r.generation=items.generation AND r.item_id=items.id)
            WHERE generation=? AND state IN ('cached','orphaned') AND EXISTS
            (SELECT 1 FROM reachable r WHERE r.generation=items.generation AND r.item_id=items.id)""",
            (generation,),
        )
        db.execute("DROP TABLE adjacency")
        db.execute("DROP TABLE destinations")

    def revalidate(self, refs, progress=lambda *a, **k: None, *, deleted_paths=()):
        generation = self.summary()["generation"]
        deleted_paths = set(deleted_paths)
        with self.connect() as db:
            db.execute("DELETE FROM reachable WHERE generation=?", (generation,))
            rows = db.execute("SELECT * FROM items WHERE generation=?", (generation,))
            while batch := rows.fetchmany(512):
                for row in batch:
                    explicit = within_paths(row["path"], deleted_paths)
                    state, reason = initial_state(
                        row["owner"],
                        row["category"],
                        row["kind"],
                        row,
                        refs,
                        time.time(),
                        explicit=explicit,
                    )
                    db.execute(
                        "UPDATE items SET state=?,reason=? WHERE generation=? AND id=?",
                        (state, reason, generation, row["id"]),
                    )
                    if state in {"managed", "referenced", "recent"}:
                        db.execute(
                            "INSERT INTO reachable VALUES(?,?,?)",
                            (generation, row["id"], reason),
                        )
            self._resolve(db, generation, refs, progress)
            self._publish(db, generation, time.time())
        return self.summary()

    def _manifest(
        self, db, name, info, targets, known_ids, scope, resolve_path, progress
    ):
        relative = os.path.relpath(name, self.root)
        token = fingerprint(info) + ":" + scope
        row = db.execute(
            "SELECT refs,fingerprint FROM manifests WHERE path=?", (relative,)
        ).fetchone()
        if row and row["fingerprint"] == token:
            targets.update(map(tuple, json.loads(row["refs"])))
            return
        found = set()
        root_pattern = re.compile(
            re.escape(str(self.root)) + r"/[^\s\"'<>`\[\]{}(),;]+"
        )
        with open(name, encoding="utf-8", errors="replace") as stream:
            tail = ""
            while chunk := stream.read(256 * 1024):
                value = tail + chunk
                found.update(
                    (match, "id")
                    for match in IDENTITY.findall(value)
                    if match in known_ids
                )
                for match in root_pattern.findall(value):
                    resolved = resolve_path(match.rstrip(".:"))
                    if resolved:
                        found.add((resolved, "path"))
                tail = value[-4096:]
                progress()
        if fingerprint(os.stat(name, follow_symlinks=False)) + ":" + scope != token:
            raise RuntimeError("Manifest changed during reference scan; retrying")
        db.execute(
            "INSERT OR REPLACE INTO manifests VALUES(?,?,?)",
            (relative, token, json.dumps(list(found))),
        )
        targets.update(found)

    def _publish(self, db, generation, started):
        rows = db.execute(
            """SELECT category,state,count(*) AS items,sum(size) AS size,
            sum(allocated) AS allocated,sum(files) AS files,sum(links) AS links
            FROM items WHERE generation=? GROUP BY category,state""",
            (generation,),
        ).fetchall()
        categories = {}
        for row in rows:
            cat = categories.setdefault(
                row["category"],
                dict(
                    category=row["category"],
                    size=0,
                    allocated=0,
                    files=0,
                    links=0,
                    items=0,
                    reclaimable=0,
                    orphaned=0,
                    cached=0,
                    states={state: {"items": 0, "allocated": 0} for state in STATES},
                ),
            )
            for field in ("size", "allocated", "files", "links", "items"):
                cat[field] += row[field]
            cat["states"][row["state"]] = {
                "items": row["items"],
                "allocated": row["allocated"],
            }
            if row["state"] in {"orphaned", "cached"}:
                cat["reclaimable"] += row["allocated"]
                cat[row["state"]] += row["allocated"]
        summary = dict(
            generation=generation,
            scanned_at=started,
            categories=list(categories.values()),
        )
        for field in ("size", "allocated", "files", "links"):
            summary[field] = sum(cat[field] for cat in categories.values())
        db.execute(
            "INSERT OR REPLACE INTO meta VALUES('summary',?)", (json.dumps(summary),)
        )


def initial_state(owner, category, kind, info, refs, started, *, explicit=False):
    if kind == "managed":
        return "managed", "managed"
    if owner in refs.owners or any(
        token in refs.owners for token in IDENTITY.findall(owner)
    ):
        return "referenced", "owner"
    if owner in refs.used_ids or any(
        token in refs.used_ids for token in IDENTITY.findall(owner)
    ):
        return "referenced", "experiment"
    if category not in {"features", "patching"} and owner in refs.image_ids:
        return "referenced", "image"
    if not explicit and info["newest"] > started - GRACE_SECONDS:
        return "recent", "recent"
    if category in {"features", "patching"} and IMAGE_ID.fullmatch(owner):
        return (
            ("cached", "rebuildable")
            if owner in refs.image_ids
            else ("orphaned", "unreferenced")
        )
    if category in {
        "images",
        "metadata",
        "features",
        "patching",
    } and not IMAGE_ID.fullmatch(owner):
        return "managed", "unrecognized"
    return "orphaned", "unreferenced"
