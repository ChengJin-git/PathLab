"""Sparse retrieval — SQLite FTS5 index over passage chunks."""
from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from .types import PassageHit

if TYPE_CHECKING:
    from .chunk_store import ChunkStore
    from .types import PassageChunk

logger = logging.getLogger(__name__)


# Plan-2026-04-29 P0-2: a global RAG index reused across sandboxed sessions
# may be on a read-only filesystem. The previous schema-migration path
# raised ``sqlite3.OperationalError: attempt to write a readonly
# database`` on every open, which propagated out of ``__init__`` and
# tore down the entire literature retrieval stack. Now we open r/w when
# possible, fall back to ``mode=ro`` URI when not, and skip schema
# writes — a read-only DB with the expected schema still serves search.
def _is_path_writable(path: Path) -> bool:
    if path.exists():
        return os.access(str(path), os.W_OK)
    return os.access(str(path.parent), os.W_OK)


class SparseChunkIndex:
    """SQLite FTS5 full-text search over passage chunks.

    Plan-2026-04-29 P0-2: handles read-only databases. ``schema_migration_needed``
    is set when the DB is read-only AND the expected newer columns are
    missing — callers can surface this as a status without crashing.
    """

    def __init__(self, db_path: Path):
        self._db_path = Path(db_path)
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Parent dir on a read-only fs — that's fine if the DB already
            # exists, we'll open it read-only below.
            pass

        self._readonly = not _is_path_writable(self._db_path)
        self.schema_migration_needed = False
        self._metadata_columns: set[str] = set()

        if self._readonly and self._db_path.exists():
            # Read-only file: open via URI to avoid sqlite trying to
            # acquire a write lock on the journal.
            self._conn = sqlite3.connect(
                f"file:{self._db_path}?mode=ro", uri=True,
            )
        else:
            self._conn = sqlite3.connect(str(self._db_path))
            # Re-evaluate readonly: a writable path may still be on a
            # read-only mount (sqlite reports it lazily). If the first
            # write fails we'll catch it in _ensure_tables.

        self._needs_rebuild = False
        self._ensure_tables()

    def _read_metadata_columns(self) -> set[str]:
        rows = self._conn.execute("PRAGMA table_info(chunk_meta)").fetchall()
        return {row[1] for row in rows}

    def _ensure_tables(self) -> None:
        # Plan-2026-04-29 P0-2: read-only opens skip CREATE/ALTER. If the
        # tables aren't there, we surface schema_migration_needed=True
        # (caller can decide to bail or use sparse_only=False).
        if self._readonly:
            try:
                self._conn.execute("SELECT 1 FROM chunk_meta LIMIT 1").fetchone()
                self._conn.execute("SELECT 1 FROM chunk_fts LIMIT 1").fetchone()
                self._metadata_columns = self._read_metadata_columns()
                if not {"organ", "task_type"}.issubset(self._metadata_columns):
                    self.schema_migration_needed = True
                    logger.warning(
                        "SparseChunkIndex: read-only DB %s needs metadata schema migration",
                        self._db_path,
                    )
            except sqlite3.OperationalError as e:
                self.schema_migration_needed = True
                logger.warning(
                    "SparseChunkIndex: read-only DB %s lacks expected schema: %s",
                    self._db_path, e,
                )
            return

        try:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS chunk_meta (
                    chunk_id TEXT PRIMARY KEY,
                    paper_id TEXT,
                    page INTEGER,
                    section TEXT,
                    organ TEXT,
                    task_type TEXT,
                    text TEXT
                )
            """)
            self._conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts
                USING fts5(chunk_id, text, content=chunk_meta, content_rowid=rowid)
            """)
            self._ensure_metadata_columns()
            self._metadata_columns = self._read_metadata_columns()
            self._conn.commit()
        except sqlite3.OperationalError as e:
            # Late detection of read-only mount (e.g. NFS export with
            # ro=true). Demote silently to read-only mode so search
            # still works.
            if "readonly" in str(e).lower() or "read-only" in str(e).lower():
                self._readonly = True
                self.schema_migration_needed = True
                logger.warning(
                    "SparseChunkIndex: %s detected read-only at write-time; "
                    "skipping schema migration",
                    self._db_path,
                )
            else:
                raise

    def _ensure_metadata_columns(self) -> None:
        """Add newer metadata columns when opening an older index."""
        columns = self._read_metadata_columns()
        for column in ("organ", "task_type"):
            if column not in columns:
                try:
                    self._conn.execute(
                        f"ALTER TABLE chunk_meta ADD COLUMN {column} TEXT",
                    )
                    self._needs_rebuild = True
                except sqlite3.OperationalError as e:
                    if "readonly" in str(e).lower() or "read-only" in str(e).lower():
                        self._readonly = True
                        self.schema_migration_needed = True
                        logger.warning(
                            "SparseChunkIndex: cannot add column %s (read-only DB %s)",
                            column, self._db_path,
                        )
                        return
                    raise
        self._metadata_columns = self._read_metadata_columns()

    def rebuild(self, chunk_store: ChunkStore) -> int:
        """Drop and rebuild the index from all chunks in the store."""
        if self._readonly:
            logger.warning(
                "SparseChunkIndex.rebuild: refusing to rebuild read-only DB %s",
                self._db_path,
            )
            return 0
        self._conn.execute("DELETE FROM chunk_meta")
        self._conn.execute("DELETE FROM chunk_fts")
        count = 0
        for chunk in chunk_store.iter_all_chunks():
            self._insert_chunk(chunk)
            count += 1
        self._conn.commit()
        self._needs_rebuild = False
        return count

    @property
    def is_readonly(self) -> bool:
        """Whether the underlying DB is open read-only (e.g. on a r/o fs)."""
        return self._readonly

    def count(self) -> int:
        """Return the number of indexed chunks."""
        row = self._conn.execute("SELECT COUNT(*) FROM chunk_meta").fetchone()
        return row[0] if row else 0

    def add_chunks(self, chunks: list[PassageChunk]) -> None:
        """Add chunks incrementally."""
        if self._readonly:
            logger.warning(
                "SparseChunkIndex.add_chunks: refusing to write to read-only DB %s",
                self._db_path,
            )
            return
        for chunk in chunks:
            self._insert_chunk(chunk)
        self._conn.commit()

    def _insert_chunk(self, chunk: PassageChunk) -> None:
        organ = str(chunk.metadata.get("organ", "")) if chunk.metadata else ""
        task_type = str(chunk.metadata.get("task_type", "")) if chunk.metadata else ""
        self._conn.execute(
            "INSERT OR REPLACE INTO chunk_meta (chunk_id, paper_id, page, section, organ, task_type, text) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (chunk.chunk_id, chunk.paper_id, chunk.page, chunk.section, organ, task_type, chunk.text),
        )
        self._conn.execute(
            "INSERT INTO chunk_fts (rowid, chunk_id, text) SELECT rowid, chunk_id, text FROM chunk_meta WHERE chunk_id = ?",
            (chunk.chunk_id,),
        )

    def search(
        self,
        query: str,
        top_k: int = 10,
        organ: str | None = None,
        task_type: str | None = None,
    ) -> list[PassageHit]:
        """Full-text search over chunk text with optional metadata filters."""
        if not query.strip():
            return []

        # Escape FTS5 special characters and build OR query for each term
        terms = query.strip().split()
        fts_query = " OR ".join(f'"{t}"' for t in terms if t)
        if not fts_query:
            return []

        # Build metadata filter clause
        where_extra = ""
        params: list = [fts_query]
        if organ:
            organ_like = f"%{organ.lower()}%"
            if "organ" in self._metadata_columns:
                where_extra += " AND (lower(coalesce(m.organ, '')) LIKE ? OR lower(m.text) LIKE ?)"
                params.extend([organ_like, organ_like])
            else:
                where_extra += " AND lower(m.text) LIKE ?"
                params.append(organ_like)
        if task_type:
            task_like = f"%{task_type.lower()}%"
            if "task_type" in self._metadata_columns:
                where_extra += " AND (lower(coalesce(m.task_type, '')) LIKE ? OR lower(m.text) LIKE ?)"
                params.extend([task_like, task_like])
            else:
                where_extra += " AND lower(m.text) LIKE ?"
                params.append(task_like)
        params.append(top_k)

        try:
            rows = self._conn.execute(f"""
                SELECT m.chunk_id, m.paper_id, m.text, m.page, m.section,
                       rank
                FROM chunk_fts f
                JOIN chunk_meta m ON m.rowid = f.rowid
                WHERE chunk_fts MATCH ?{where_extra}
                ORDER BY rank
                LIMIT ?
            """, params).fetchall()
        except sqlite3.OperationalError:
            return []

        hits = []
        for chunk_id, paper_id, text, page, section, rank in rows:
            # FTS5 rank is negative (closer to 0 = better), convert to positive score
            sparse_score = -rank if rank else 0.0
            hits.append(PassageHit(
                paper_id=paper_id,
                chunk_id=chunk_id,
                text=text,
                score=sparse_score,
                sparse_score=sparse_score,
                page=page,
                section=section or "",
            ))
        return hits

    def close(self) -> None:
        self._conn.close()

    def needs_rebuild(self) -> bool:
        """Whether the on-disk index schema changed and should be rebuilt."""
        return self._needs_rebuild
