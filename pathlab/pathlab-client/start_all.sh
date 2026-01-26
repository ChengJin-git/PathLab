#!/bin/bash
# PathLab Client Startup Script
# Usage: ./start_all.sh

set -e

# Ensure we are in the pathlab-client directory
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "=== Starting PathLab Client (Dev Mode) ==="
echo "Working Directory: $(pwd)"

# Check for node_modules
if [ ! -d "node_modules" ]; then
    echo "Installing Node dependencies..."
    npm install
fi

# Check for Python dependencies (basic check)
if ! python3 -c "import fastapi, uvicorn, PIL, aiosqlite, sqlalchemy" 2>/dev/null; then
    echo "Warning: Some Python dependencies might be missing."
    echo "Please run: pip install -r server/requirements.txt"
fi

# Start the development server
# Database: SQLite (zero-configuration, auto-created)
echo "Starting Electron app..."
echo "Database: SQLite (auto-configured)"
echo "Press Ctrl+C to stop."
npm run dev
