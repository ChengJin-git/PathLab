"""Local UTC clock for the collector package.

The collector must be importable without `backend.*` on sys.path. We do not
reuse `backend.database.models.utc_now` at module top-level because that
forces every consumer (tests, M3 PHI scrub, downstream agents) to bootstrap
the PathLab server tree just to load the package.

Implementation matches `backend.database.models.utc_now` exactly: timezone-naive
UTC datetime, compatible with PostgreSQL `TIMESTAMP WITHOUT TIME ZONE` columns.
"""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return current UTC time as a naive datetime (UTC assumed)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
