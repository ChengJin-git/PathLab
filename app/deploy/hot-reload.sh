#!/bin/bash
# PathLab hot reload (rolling restart)
# Usage:
#   ./hot-reload.sh frontend          # rebuild the web client only (no downtime)
#   ./hot-reload.sh backend           # rolling restart of all backend services
#   ./hot-reload.sh gateway           # restart Gateway only
#   ./hot-reload.sh preprocessing     # restart Preprocessing only
#   ./hot-reload.sh ai                # restart AI only
#   ./hot-reload.sh all               # web client + rolling backend restart

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SERVER_DIR="$PROJECT_DIR/server"
RENDERER_DIR="$PROJECT_DIR/src/renderer"
LOG_DIR="$PROJECT_DIR/logs"

source "$SCRIPT_DIR/python-runtime.sh"
select_pathlab_python

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

# Service definitions
declare -A SERVICE_PORT=( [gateway]=6100 [preprocessing]=6101 [ai]=6102 )
declare -A SERVICE_APP=( [gateway]="gateway.main:app" [preprocessing]="backend.preprocessing.main:app" [ai]="backend.ai.main:app" )
declare -A SERVICE_PATTERN=( [gateway]="uvicorn.*gateway" [preprocessing]="uvicorn.*preprocessing" [ai]="uvicorn.*ai" )

# Load .env if exists
if [ -f "$SERVER_DIR/.env" ]; then set -a; source "$SERVER_DIR/.env"; set +a; fi

# Ensure env vars
export GATEWAY_PORT=6100 PREPROCESSING_PORT=6101 AI_PORT=6102
export DEFAULT_ADMIN_PASSWORD="${DEFAULT_ADMIN_PASSWORD:-admin}"
export PREPROCESSING_SERVICE_URL="http://127.0.0.1:6101" AI_SERVICE_URL="http://127.0.0.1:6102"

mkdir -p "$LOG_DIR"

# ============================================================
reload_frontend() {
    echo -e "${CYAN}[Frontend]${NC} Building..."
    cd "$PROJECT_DIR"

    local vite_bin="$PROJECT_DIR/node_modules/vite/bin/vite.js"
    if [ ! -d "node_modules" ] || [ ! -f "$vite_bin" ]; then
        echo "  Node dependencies missing or incomplete, running npm ci..."
        npm ci --silent
    fi

    local dist_dir="$RENDERER_DIR/dist"
    local tmp_dir="$RENDERER_DIR/dist_new_$$"

    cd "$RENDERER_DIR"
    if ! node "$vite_bin" build --config vite.config.ts --outDir "$tmp_dir" 2>&1 | tail -5; then
        echo -e "${RED}[Frontend]${NC} Build failed; the live dist directory was not replaced"
        rm -rf "$tmp_dir"
        exit 1
    fi

    if [ ! -d "$tmp_dir" ]; then
        echo -e "${RED}[Frontend]${NC} Build produced no output directory: $tmp_dir"
        exit 1
    fi

    cp -r public/assets "$tmp_dir/" 2>/dev/null || true
    cp -r public/images "$tmp_dir/" 2>/dev/null || true

    # Atomic swap
    local old_dir="$RENDERER_DIR/dist_old_$$"
    [ -d "$dist_dir" ] && mv "$dist_dir" "$old_dir"
    mv "$tmp_dir" "$dist_dir"
    rm -rf "$old_dir"

    echo -e "${GREEN}[Frontend]${NC} ✓ Updated (no downtime; users see it on reload)"
}

# ============================================================
restart_service() {
    local name=$1
    local port=${SERVICE_PORT[$name]}
    local app=${SERVICE_APP[$name]}
    local pattern=${SERVICE_PATTERN[$name]}

    echo -e "${CYAN}[$name]${NC} Restarting (port $port)..."

    local workers=1 extra_args=""
    if [ "$name" = "preprocessing" ]; then
        workers=${PREPROCESSING_WORKERS:-4}
        extra_args="--limit-max-requests ${PREPROCESSING_MAX_REQUESTS:-500}"
    fi

    # Gracefully stop old process
    local old_pids=$(pgrep -f "$pattern" 2>/dev/null || true)
    if [ -n "$old_pids" ]; then
        echo "  Stopping old process (PID: $old_pids)..."
        # 1) stop the child process tree (uvicorn workers)
        for pid in $old_pids; do
            pkill -9 -P "$pid" 2>/dev/null || true
        done
        # 2) SIGTERM the main process
        for pid in $old_pids; do kill -TERM "$pid" 2>/dev/null || true; done
        for i in {1..10}; do
            pgrep -f "$pattern" > /dev/null 2>&1 || break
            sleep 0.5
        done
        # 3) SIGKILL if it is still running
        for pid in $old_pids; do kill -9 "$pid" 2>/dev/null || true; done
        sleep 0.5
    fi

    # clean up the old process tree from the PID file (catches orphaned children)
    if [ -f "$LOG_DIR/${name}.pid" ]; then
        local old_main_pid=$(cat "$LOG_DIR/${name}.pid" 2>/dev/null)
        if [ -n "$old_main_pid" ] && kill -0 "$old_main_pid" 2>/dev/null; then
            echo "  Stopping old process tree (PID: $old_main_pid)"
            pkill -9 -P "$old_main_pid" 2>/dev/null || true
            kill -9 "$old_main_pid" 2>/dev/null || true
        fi
    fi

    # free the port with retries (same logic as start.sh)
    local max_retries=5
    for retry in $(seq 1 $max_retries); do
        sleep 1
        local port_pids=$(ss -tlnp 2>/dev/null | grep ":$port " | grep -oP 'pid=\K[0-9]+' | sort -u)
        if [ -z "$port_pids" ]; then
            break
        fi
        if [ "$retry" -lt "$max_retries" ]; then
            echo -e "  ${YELLOW}Port $port still in use (PID: $port_pids), forcing... (attempt $retry/$max_retries)${NC}"
            for pid in $port_pids; do kill -9 "$pid" 2>/dev/null || true; done
        fi
    done

    # final check
    if ss -tlnp 2>/dev/null | grep -q ":$port "; then
        echo -e "${RED}[$name]${NC} ✗ Port $port could not be freed; run manually: sudo fuser -k ${port}/tcp"
        return 1
    fi
    echo -e "  Port $port freed ✓"

    # Start new process
    if [ -n "${CUDA_VISIBLE_DEVICES:-}" ]; then
        echo -e "  ${CYAN}[GPU]${NC} CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES}"
    else
        echo -e "  ${CYAN}[GPU]${NC} CUDA_VISIBLE_DEVICES not set, using all available GPUs"
    fi

    cd "$SERVER_DIR"
    nohup "$PYTHON" -m uvicorn "$app" \
        --host 0.0.0.0 --port "$port" --log-level info --workers "$workers" \
        $extra_args >> "$LOG_DIR/${name}.log" 2>&1 &
    local new_pid=$!
    echo "$new_pid" > "$LOG_DIR/${name}.pid"

    # Health check
    echo -n "  Waiting for health check"
    for i in {1..30}; do
        if curl -sf "http://127.0.0.1:${port}/health" > /dev/null 2>&1; then
            echo ""; echo -e "${GREEN}[$name]${NC} ✓ Restarted (PID: $new_pid)"; return 0
        fi
        echo -n "."; sleep 1
    done
    echo ""; echo -e "${RED}[$name]${NC} ✗ Health check timed out. See the log: $LOG_DIR/${name}.log"; return 1
}

# ============================================================
reload_backend() {
    # Order: AI (least critical) -> Preprocessing -> Gateway
    restart_service "ai"
    restart_service "preprocessing"
    restart_service "gateway"
    restart_worker "task-worker" "task_worker.main"
    restart_worker "research-worker" "backend.autoresearch.engine.worker"
}

restart_worker() {
    local name="$1" module="$2"
    local pid_file="$LOG_DIR/${name}.pid"
    if [ -f "$pid_file" ]; then
        local old_pid
        old_pid=$(cat "$pid_file")
        if [ -r "/proc/$old_pid/cmdline" ] && tr '\0' ' ' < "/proc/$old_pid/cmdline" | grep -q -- "$module"; then
            kill -TERM "$old_pid"
            for i in {1..30}; do
                kill -0 "$old_pid" 2>/dev/null || break
                sleep 1
            done
        fi
    fi
    cd "$SERVER_DIR"
    nohup "$PYTHON" -m "$module" >> "$LOG_DIR/${name}.log" 2>&1 &
    echo "$!" > "$pid_file"
    echo "[$name] started (PID: $(cat "$pid_file"))"
}

# ============================================================
# Main
# ============================================================
ACTION="${1:-help}"

echo -e "${CYAN}╔════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║       PathLab hot reload               ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════╝${NC}"
echo ""

case "$ACTION" in
    frontend)       reload_frontend ;;
    backend)        reload_backend ;;
    gateway|preprocessing|ai) restart_service "$ACTION" ;;
    task-worker) restart_worker "task-worker" "task_worker.main" ;;
    research-worker) restart_worker "research-worker" "backend.autoresearch.engine.worker" ;;
    all)            reload_frontend; echo ""; reload_backend ;;
    *)
        echo "Usage: $0 {frontend|backend|gateway|preprocessing|ai|all}"
        echo ""
        echo "  frontend        rebuild the web client only (atomic swap, no downtime)"
        echo "  backend         rolling restart of all backend services (brief 502s)"
        echo "  gateway         restart Gateway only"
        echo "  preprocessing   restart Preprocessing only"
        echo "  ai              restart AI only"
        echo "  all             web client + rolling backend restart"
        exit 1 ;;
esac

echo ""; echo -e "${GREEN}Done.${NC}"
