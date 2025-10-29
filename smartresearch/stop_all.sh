#!/usr/bin/env bash
# SmartResearch - Stop all services
# Usage: bash smartresearch/stop_all.sh

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "=========================================="
echo "Stopping SmartResearch services"
echo "=========================================="
echo ""

# Function to kill processes (only smartresearch related)
kill_processes() {
    local pattern=$1
    local description=$2

    pids=$(ps aux | grep -E "$pattern" | grep -v grep | awk '{print $2}' || true)

    if [ -n "$pids" ]; then
        echo "  Found $description processes:"
        for pid in $pids; do
            cmd=$(ps -p $pid -o cmd= 2>/dev/null || echo "unknown")
            echo "    PID $pid: ${cmd:0:80}"
            kill -9 "$pid" 2>/dev/null || true
        done
        return 0
    else
        return 1
    fi
}

echo "[1/3] Stopping backend services (uvicorn + smartresearch)..."
if kill_processes "uvicorn.*smartresearch" "uvicorn"; then
    echo "✓ Backend services stopped"
else
    echo "  No uvicorn processes found"
fi
echo ""

echo "[2/3] Stopping frontend (only from smartresearch/services/frontend)..."
# Only kill node/vite processes running in smartresearch/services/frontend directory
frontend_pids=$(ps aux | grep -E "node.*smartresearch/services/frontend|vite.*smartresearch/services/frontend|npm.*smartresearch/services/frontend" | grep -v grep | awk '{print $2}' || true)

if [ -n "$frontend_pids" ]; then
    echo "  Found frontend processes:"
    for pid in $frontend_pids; do
        cmd=$(ps -p $pid -o cmd= 2>/dev/null || echo "unknown")
        echo "    PID $pid: ${cmd:0:80}"
        kill -9 "$pid" 2>/dev/null || true
    done
    echo "✓ Frontend stopped"
else
    echo "  No frontend processes found"
fi
echo ""

# Clean up PID file
rm -f /tmp/smartresearch_pids.txt

echo "[3/3] Checking SmartResearch ports (6100, 6101, 6102)..."
# Only check backend ports, not 5173 (frontend might be used by other projects)
for port in 6100 6101 6102; do
    pid=$(lsof -ti :$port 2>/dev/null || true)
    if [ -n "$pid" ]; then
        cmd=$(ps -p $pid -o cmd= 2>/dev/null || echo "unknown")
        # Check parent process too (for multiprocessing spawned processes)
        ppid=$(ps -p $pid -o ppid= 2>/dev/null | tr -d ' ' || echo "")
        parent_cmd=$(ps -p $ppid -o cmd= 2>/dev/null || echo "")

        # Kill if it's a smartresearch process or child of smartresearch
        if echo "$cmd" | grep -q "smartresearch" || echo "$parent_cmd" | grep -q "smartresearch"; then
            echo "  Port $port used by SmartResearch (PID $pid), killing..."
            kill -9 "$pid" 2>/dev/null || true
        else
            echo "  ⚠ Port $port used by non-SmartResearch process (PID $pid), skipping"
            echo "    Command: ${cmd:0:80}"
        fi
    fi
done
echo "✓ Backend ports cleared"
echo ""

# Stop PostgreSQL
DOCKER_COMPOSE_CMD=""
if command -v docker-compose &> /dev/null; then
    DOCKER_COMPOSE_CMD="docker-compose"
elif docker compose version &> /dev/null; then
    DOCKER_COMPOSE_CMD="docker compose"
fi

if [ -n "$DOCKER_COMPOSE_CMD" ]; then
    if $DOCKER_COMPOSE_CMD ps postgres 2>/dev/null | grep -q "Up"; then
        echo "PostgreSQL is running. Do you want to stop it? (y/N)"
        read -r response
        if [[ "$response" =~ ^[Yy]$ ]]; then
            echo "Stopping PostgreSQL..."
            $DOCKER_COMPOSE_CMD down
            echo "✓ PostgreSQL stopped."
        else
            echo "PostgreSQL left running."
            echo "To stop manually: $DOCKER_COMPOSE_CMD down"
        fi
    fi
fi

echo ""
echo "=========================================="
echo "✓ SmartResearch services stopped"
echo "=========================================="

# Clean up log files (optional)
# rm -f /tmp/smartresearch_*.log

