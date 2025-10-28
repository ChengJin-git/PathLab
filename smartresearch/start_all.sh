#!/usr/bin/env bash
# SmartResearch - One-click startup script
# Usage: bash smartresearch/start_all.sh

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== SmartResearch Startup ==="
echo "Repository root: $REPO_ROOT"
echo ""

# Check Python
if ! command -v python &> /dev/null; then
    echo "Error: python not found"
    exit 1
fi

# Check if uvicorn is available
if ! python -c "import uvicorn" 2>/dev/null; then
    echo "Error: uvicorn not installed. Run: pip install fastapi uvicorn"
    exit 1
fi

# Check if npm is available for frontend
if ! command -v npm &> /dev/null; then
    echo "Warning: npm not found. Frontend will not start."
    SKIP_FRONTEND=1
fi

# Create uploads directories if not exist
mkdir -p smartresearch/uploads/metadata
mkdir -p smartresearch/uploads/ai_results
mkdir -p smartresearch/uploads/tasks
mkdir -p smartresearch/uploads/thumbnails
mkdir -p smartresearch/uploads/patches

echo "Starting services..."
echo ""

# Start Gateway (port 6100)
echo "[1/4] Starting Gateway on http://0.0.0.0:6100"
python -m uvicorn smartresearch.services.gateway.main:app --host 0.0.0.0 --port 6100 --reload > /tmp/smartresearch_gateway.log 2>&1 &
GATEWAY_PID=$!
echo "  PID: $GATEWAY_PID"

# Start WSI Service (port 6101)
echo "[2/4] Starting WSI Service on http://0.0.0.0:6101"
python -m uvicorn smartresearch.services.backend.wsi.main:app --host 0.0.0.0 --port 6101 --reload > /tmp/smartresearch_wsi.log 2>&1 &
WSI_PID=$!
echo "  PID: $WSI_PID"

# Start AI Service (port 6102)
echo "[3/4] Starting AI Service on http://0.0.0.0:6102"
python -m uvicorn smartresearch.services.backend.ai.main:app --host 0.0.0.0 --port 6102 --reload > /tmp/smartresearch_ai.log 2>&1 &
AI_PID=$!
echo "  PID: $AI_PID"

# Start Frontend (port 5173)
if [ -z "$SKIP_FRONTEND" ]; then
    echo "[4/4] Starting Frontend on http://0.0.0.0:5173"
    cd smartresearch/services/frontend

    # Install deps if node_modules missing
    if [ ! -d "node_modules" ]; then
        echo "  Installing frontend dependencies..."
        npm install > /tmp/smartresearch_frontend_install.log 2>&1
    fi

    npm run dev -- --host 0.0.0.0 > /tmp/smartresearch_frontend.log 2>&1 &
    FRONTEND_PID=$!
    echo "  PID: $FRONTEND_PID"
    cd "$REPO_ROOT"
else
    echo "[4/4] Frontend skipped (npm not found)"
    FRONTEND_PID=""
fi

echo ""
echo "=== All services started ==="
echo ""
echo "Gateway:  http://0.0.0.0:6100"
echo "WSI:      http://0.0.0.0:6101"
echo "AI:       http://0.0.0.0:6102"
if [ -n "$FRONTEND_PID" ]; then
    echo "Frontend: http://0.0.0.0:5173"
fi
echo ""
echo "Logs:"
echo "  Gateway:  tail -f /tmp/smartresearch_gateway.log"
echo "  WSI:      tail -f /tmp/smartresearch_wsi.log"
echo "  AI:       tail -f /tmp/smartresearch_ai.log"
if [ -n "$FRONTEND_PID" ]; then
    echo "  Frontend: tail -f /tmp/smartresearch_frontend.log"
fi
echo ""
echo "To stop all services:"
echo "  kill $GATEWAY_PID $WSI_PID $AI_PID${FRONTEND_PID:+ $FRONTEND_PID}"
echo ""
echo "Or use: bash smartresearch/stop_all.sh"
echo ""

# Save PIDs for stop script
cat > /tmp/smartresearch_pids.txt <<EOF
GATEWAY_PID=$GATEWAY_PID
WSI_PID=$WSI_PID
AI_PID=$AI_PID
FRONTEND_PID=$FRONTEND_PID
EOF

echo "Press Ctrl+C to view logs (services will keep running in background)"
echo ""

# Wait a bit and show initial logs
sleep 2
echo "=== Initial logs ==="
echo ""
echo "--- Gateway ---"
tail -n 5 /tmp/smartresearch_gateway.log 2>/dev/null || echo "No logs yet"
echo ""
echo "--- AI ---"
tail -n 5 /tmp/smartresearch_ai.log 2>/dev/null || echo "No logs yet"
echo ""

if [ -n "$FRONTEND_PID" ]; then
    echo "--- Frontend ---"
    tail -n 5 /tmp/smartresearch_frontend.log 2>/dev/null || echo "No logs yet"
    echo ""
fi

echo "All services running. Check logs above for any errors."

