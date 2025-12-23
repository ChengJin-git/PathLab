#!/bin/bash
# PathHub Client Startup Script
# Usage: ./start_all.sh

set -e

# Ensure we are in the pathhub-client directory
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "=== Starting PathHub Client (Dev Mode) ==="
echo "Working Directory: $(pwd)"

# Check for node_modules
if [ ! -d "node_modules" ]; then
    echo "Installing Node dependencies..."
    npm install
fi

# Check for Python dependencies (basic check)
if ! python3 -c "import fastapi, uvicorn, PIL" 2>/dev/null; then
    echo "Warning: Some Python dependencies might be missing."
    echo "Please run: pip install fastapi uvicorn pillow"
    # read -p "Press Enter to continue anyway, or Ctrl+C to abort..."
fi

# Start the development server
echo "Starting Electron app..."
echo "Press Ctrl+C to stop."
npm run dev
