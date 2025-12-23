#!/bin/bash
# Build the python sidecar
# Ensure pyinstaller is installed: pip install pyinstaller

echo "Building Python sidecar..."
pyinstaller --onefile --name main --distpath server/dist server/main.py
echo "Build complete."
