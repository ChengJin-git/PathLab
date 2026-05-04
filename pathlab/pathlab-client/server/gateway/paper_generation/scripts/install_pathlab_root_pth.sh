#!/usr/bin/env bash
# Install the cross-import shim into paper_generation/.venv/site-packages/.
#
# Without this, `from backend.database ...` and `from gateway.routes ...`
# fail because backend/ and gateway/ live two levels up from this folder.
#
# Re-run after every `uv sync` that destroys/recreates .venv.
#
# This is the dev-time analog of `pip install -e .` for backend/ — but
# backend/ doesn't have its own pyproject.toml so we can't do that.

set -euo pipefail

THIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PAPER_GEN_DIR="$(dirname "${THIS_DIR}")"

if [[ ! -d "${PAPER_GEN_DIR}/.venv" ]]; then
    echo "ERROR: ${PAPER_GEN_DIR}/.venv missing. Run \`uv venv && uv sync\` first." >&2
    exit 1
fi

PY="${PAPER_GEN_DIR}/.venv/bin/python"
SITE_PACKAGES="$("${PY}" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"

cat > "${SITE_PACKAGES}/_pathlab_root.py" <<'PYEOF'
"""Make PathLab `server/` importable from the paper-gen venv.

Auto-loaded via _pathlab_root.pth at Python site init time. Without this,
'from backend.database ...' and 'from gateway.routes ...' would not resolve
because paper_generation/.venv is the venv root.
"""
import sys
from pathlib import Path

_THIS = Path(__file__).resolve()
_p = _THIS.parent
for _ in range(10):
    _p = _p.parent
    if (_p / "backend").is_dir() and (_p / "gateway").is_dir():
        if str(_p) not in sys.path:
            sys.path.insert(0, str(_p))
        break
PYEOF

# .pth files: a line starting with `import` is executed at site init time.
echo 'import _pathlab_root' > "${SITE_PACKAGES}/_pathlab_root.pth"

echo "Installed cross-import shim:"
echo "  ${SITE_PACKAGES}/_pathlab_root.py"
echo "  ${SITE_PACKAGES}/_pathlab_root.pth"

# Smoke test: does it actually work?
"${PY}" - <<'SMOKE'
try:
    from backend.database.models import PaperGenerationRun
    from gateway.paper_generation.routes import router
    print(f"  smoke OK: backend table={PaperGenerationRun.__tablename__}, route prefix={router.prefix}")
except Exception as e:
    print(f"  smoke FAIL: {type(e).__name__}: {e}")
    raise SystemExit(1)
SMOKE
