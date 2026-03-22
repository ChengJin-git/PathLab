#!/bin/bash
# Build the PathLab Python sidecar using PyInstaller (onedir mode).
#
# Prerequisites:
#   pip install pyinstaller pyinstaller-hooks-contrib
#   pip install -r server/requirements.txt
#
# Run from pathlab-client/ (repo root of the client):
#   bash build-python.sh
#
# Output:
#   server/dist/main/          <- onedir bundle (directory)
#   server/dist/main/main      <- the executable inside the bundle
#
# Electron packaging picks up:
#   extraResources: { from: "server/dist/main", to: "server/main" }
# and sidecar-manager spawns:
#   <resourcesPath>/server/main/main

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

echo "=== PathLab Python sidecar build ==="
echo "Working directory: $PROJECT_DIR"

# Verify pyinstaller is available
if ! command -v pyinstaller &>/dev/null; then
    echo "ERROR: pyinstaller not found."
    echo "Install it with: pip install pyinstaller pyinstaller-hooks-contrib"
    exit 1
fi

echo "PyInstaller: $(pyinstaller --version)"
echo "Python:      $(python3 --version)"

# Clean previous build artifacts to avoid stale cache issues
echo "Cleaning previous build..."
rm -rf server/dist/main server/build/main

echo "Running PyInstaller..."
pyinstaller \
    --distpath server/dist \
    --workpath server/build \
    --noconfirm \
    server/main.spec

echo ""
echo "=== Build complete ==="
echo "Output directory: server/dist/main/"
ls -lh server/dist/main/main 2>/dev/null && echo "Executable OK" || echo "WARNING: main executable not found"
du -sh server/dist/main/ 2>/dev/null || true
