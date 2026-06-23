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

# Validate Aslide native libraries are present in the bundle
echo ""
echo "=== Validating Aslide native libraries ==="
_opencv_dir="server/dist/main/_internal/Aslide/opencv/lib"
_sdpc_dir="server/dist/main/_internal/Aslide/sdpc/lib"
_kfb_dir="server/dist/main/_internal/Aslide/kfb/lib"
_tron_dir="server/dist/main/_internal/Aslide/tron/lib"

_missing=0
for _lib_dir in "$_opencv_dir" "$_sdpc_dir" "$_kfb_dir" "$_tron_dir"; do
    if [ -d "$_lib_dir" ]; then
        _count=$(find "$_lib_dir" -name '*.so*' -type f 2>/dev/null | wc -l)
        echo "  [OK] $_lib_dir: $_count .so files"
    else
        echo "  [MISSING] $_lib_dir"
        _missing=1
    fi
done

if [ "$_missing" -eq 1 ]; then
    echo ""
    echo "ERROR: Aslide native libraries missing from PyInstaller bundle!"
    echo "SDPC/KFB/TMAP slide formats will NOT work in the packaged app."
    echo "Check that Aslide is installed: pip install git+https://github.com/MrPeterJin/Aslide.git@main"
    echo "Then rebuild."
    exit 1
fi
echo "Aslide validation passed."
