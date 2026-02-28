#!/bin/bash
# PathLab 热更新脚本 (零停机滚动重启)
# Usage:
#   ./hot-reload.sh frontend          # 仅更新前端 (零停机)
#   ./hot-reload.sh backend           # 滚动重启所有后端服务
#   ./hot-reload.sh gateway           # 仅重启 Gateway 服务
#   ./hot-reload.sh preprocessing     # 仅重启 Preprocessing 服务
#   ./hot-reload.sh ai                # 仅重启 AI 服务
#   ./hot-reload.sh all               # 更新前端 + 滚动重启后端

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SERVER_DIR="$PROJECT_DIR/server"
RENDERER_DIR="$PROJECT_DIR/src/renderer"
LOG_DIR="$PROJECT_DIR/logs"

# Auto-detect Python path (conda > venv > system)
if [ -n "$CONDA_PREFIX" ]; then
    PYTHON="$CONDA_PREFIX/bin/python3"
elif [ -f "$PROJECT_DIR/venv/bin/python3" ]; then
    PYTHON="$PROJECT_DIR/venv/bin/python3"
elif command -v python3 &> /dev/null; then
    PYTHON="$(which python3)"
else
    echo "Error: Python3 not found"; exit 1
fi

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

# Service definitions
declare -A SERVICE_PORT=( [gateway]=6100 [preprocessing]=6101 [ai]=6102 )
declare -A SERVICE_APP=( [gateway]="gateway.main:app" [preprocessing]="backend.preprocessing.main:app" [ai]="backend.ai.main:app" )
declare -A SERVICE_PATTERN=( [gateway]="uvicorn.*gateway" [preprocessing]="uvicorn.*preprocessing" [ai]="uvicorn.*ai" )

# Load .env if exists
if [ -f "$SERVER_DIR/.env" ]; then set -a; source "$SERVER_DIR/.env"; set +a; fi

# Ensure env vars
export PATHLAB_DEBUG=1 GATEWAY_PORT=6100 PREPROCESSING_PORT=6101 AI_PORT=6102
export PREPROCESSING_SERVICE_URL="http://127.0.0.1:6101" AI_SERVICE_URL="http://127.0.0.1:6102"

mkdir -p "$LOG_DIR"

# ============================================================
reload_frontend() {
    echo -e "${CYAN}[Frontend]${NC} 开始构建..."
    cd "$PROJECT_DIR"
    [ ! -d "node_modules" ] && { echo "  安装 Node 依赖..."; npm install --silent; }

    local dist_dir="$RENDERER_DIR/dist"
    local tmp_dir="$RENDERER_DIR/dist_new_$$"

    cd "$RENDERER_DIR"
    node "$PROJECT_DIR/node_modules/vite/bin/vite.js" \
        build --config vite.config.ts --outDir "$tmp_dir" 2>&1 | tail -5

    cp -r public/assets "$tmp_dir/" 2>/dev/null || true
    cp -r public/images "$tmp_dir/" 2>/dev/null || true

    # Atomic swap
    local old_dir="$RENDERER_DIR/dist_old_$$"
    [ -d "$dist_dir" ] && mv "$dist_dir" "$old_dir"
    mv "$tmp_dir" "$dist_dir"
    rm -rf "$old_dir"

    echo -e "${GREEN}[Frontend]${NC} ✓ 更新完成 (零停机，用户刷新即生效)"
}

# ============================================================
restart_service() {
    local name=$1
    local port=${SERVICE_PORT[$name]}
    local app=${SERVICE_APP[$name]}
    local pattern=${SERVICE_PATTERN[$name]}

    echo -e "${CYAN}[$name]${NC} 滚动重启中 (端口 $port)..."

    local workers=1 extra_args=""
    if [ "$name" = "preprocessing" ]; then
        workers=${PREPROCESSING_WORKERS:-4}
        extra_args="--limit-max-requests ${PREPROCESSING_MAX_REQUESTS:-500}"
    fi

    # Gracefully stop old process
    local old_pids=$(pgrep -f "$pattern" 2>/dev/null || true)
    if [ -n "$old_pids" ]; then
        echo "  停止旧进程 (PID: $old_pids)..."
        for pid in $old_pids; do kill -TERM "$pid" 2>/dev/null || true; done
        for i in {1..10}; do
            pgrep -f "$pattern" > /dev/null 2>&1 || break
            sleep 0.5
        done
        for pid in $old_pids; do kill -9 "$pid" 2>/dev/null || true; done
        sleep 0.5
    fi

    # 强制杀掉仍然占用端口的进程
    local port_pids=$(lsof -ti :"$port" 2>/dev/null || true)
    if [ -n "$port_pids" ]; then
        echo -e "  ${YELLOW}端口 $port 仍被占用 (PID: $port_pids)，强制释放...${NC}"
        for pid in $port_pids; do kill -9 "$pid" 2>/dev/null || true; done
    fi

    # 等待端口完全释放
    echo -n "  等待端口 $port 释放"
    for i in {1..20}; do
        if ! lsof -ti :"$port" > /dev/null 2>&1; then
            echo " ✓"; break
        fi
        if [ "$i" -eq 20 ]; then
            echo ""; echo -e "${RED}[$name]${NC} ✗ 端口 $port 释放超时！"; return 1
        fi
        echo -n "."; sleep 0.5
    done

    # Start new process
    cd "$SERVER_DIR"
    nohup "$PYTHON" -m uvicorn "$app" \
        --host 0.0.0.0 --port "$port" --log-level info --workers "$workers" \
        $extra_args >> "$LOG_DIR/${name}.log" 2>&1 &
    local new_pid=$!
    echo "$new_pid" > "$LOG_DIR/${name}.pid"

    # Health check
    echo -n "  等待健康检查"
    for i in {1..30}; do
        if curl -sf "http://127.0.0.1:${port}/health" > /dev/null 2>&1; then
            echo ""; echo -e "${GREEN}[$name]${NC} ✓ 重启完成 (PID: $new_pid)"; return 0
        fi
        echo -n "."; sleep 1
    done
    echo ""; echo -e "${RED}[$name]${NC} ✗ 健康检查超时！查看日志: $LOG_DIR/${name}.log"; return 1
}

# ============================================================
reload_backend() {
    # Order: AI (least critical) -> Preprocessing -> Gateway
    restart_service "ai"
    restart_service "preprocessing"
    restart_service "gateway"
}

# ============================================================
# Main
# ============================================================
ACTION="${1:-help}"

echo -e "${CYAN}╔════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║       PathLab 热更新 (零停机)          ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════╝${NC}"
echo ""

case "$ACTION" in
    frontend)       reload_frontend ;;
    backend)        reload_backend ;;
    gateway|preprocessing|ai) restart_service "$ACTION" ;;
    all)            reload_frontend; echo ""; reload_backend ;;
    *)
        echo "Usage: $0 {frontend|backend|gateway|preprocessing|ai|all}"
        echo ""
        echo "  frontend        仅更新前端 (零停机，构建后原子替换)"
        echo "  backend         滚动重启所有后端服务 (逐个重启，短暂 502)"
        echo "  gateway         仅重启 Gateway 服务"
        echo "  preprocessing   仅重启 Preprocessing 服务"
        echo "  ai              仅重启 AI 服务"
        echo "  all             更新前端 + 滚动重启后端"
        exit 1 ;;
esac

echo ""; echo -e "${GREEN}完成！${NC}"
