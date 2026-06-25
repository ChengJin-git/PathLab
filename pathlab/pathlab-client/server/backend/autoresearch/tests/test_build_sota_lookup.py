"""SOTA Plan Correction #3: ``_build_sota_lookup`` cache path lives under
``session.persistence_root``, not the process cwd or a nonexistent
``config.persistence_root``.

Pre-fix, ``getattr(config, "persistence_root", ".") or "."`` silently rooted
the cache at the process working directory because ``AutoResearchConfig``
has no such field — the cache leaked across sessions and could land
anywhere the process happened to be invoked from.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"


def test_build_sota_lookup_cache_path_is_session_scoped(tmp_path):
    from persistence_helpers import make_test_config

    from autoresearch.orchestrator.runner import _build_sota_lookup
    from autoresearch.runtime.session import AutoResearchSession

    session = AutoResearchSession(persistence_root=tmp_path)
    config = make_test_config(tmp_path)
    # Avoid network init in the test; no_online_sota is not a declared field
    # on AutoResearchConfig yet (lands later in T11), so set as attribute.
    config.no_online_sota = True  # type: ignore[attr-defined]

    lookup = _build_sota_lookup(session, config, literature_store=None)

    assert lookup is not None
    assert lookup._cache._path == tmp_path / "sota_cache.json"


def test_build_sota_lookup_returns_none_when_persistence_root_empty(tmp_path):
    """Default ``Path()`` is the sentinel for an unrooted session — the
    builder must refuse rather than silently writing to cwd."""
    from persistence_helpers import make_test_config

    from autoresearch.orchestrator.runner import _build_sota_lookup
    from autoresearch.runtime.session import AutoResearchSession

    session = AutoResearchSession(persistence_root=Path())
    config = make_test_config(tmp_path)
    config.no_online_sota = True  # type: ignore[attr-defined]

    lookup = _build_sota_lookup(session, config, literature_store=None)

    assert lookup is None
