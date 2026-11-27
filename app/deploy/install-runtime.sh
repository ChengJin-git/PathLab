#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == "--help" ]]; then
    echo "Usage: bash deploy/install-runtime.sh BUNDLE NEW_VENV [EXACT_SOURCE_PYTHON]"
    exit 0
fi
if [[ $# -lt 2 ]]; then
    echo "Usage: bash deploy/install-runtime.sh BUNDLE NEW_VENV [EXACT_SOURCE_PYTHON]"
    exit 2
fi
args=(install --bundle "$1" --target "$2")
if [[ $# -gt 2 ]]; then args+=(--python "$3"); fi
python3 "$HERE/runtime_bundle.py" "${args[@]}"
