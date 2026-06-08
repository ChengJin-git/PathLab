#!/bin/bash
# PathLab 热更新脚本 (零停机滚动重启)
# Usage:
#   ./hot-reload.sh frontend          # 仅更新前端 (零停机)
#   ./hot-reload.sh backend           # 滚动重启所有后端服务
#   ./hot-reload.sh gateway           # 仅重启 Gateway 服务
#   ./hot-reload.sh preprocessing     # 仅重启 Preprocessing 服务
#   ./hot-reload.sh ai                # 仅重启 AI 服务
#   ./hot-reload.sh all               # 更新前端 + 滚动重启后端

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SERVER_DIR="$PROJECT_DIR/server"
RENDERER_DIR="$PROJECT_DIR/src/renderer"
LOG_DIR="$PROJECT_DIR/logs"

# Auto-detect Python path.
# Priority: explicit override > PathScientist venv > project venv > conda > system.
# The PathScientist venv is preferred because it carries OpenHands/agent deps.
PATHSCIENTIST_PYTHON="$SERVER_DIR/backend/pathscientist/.venv/bin/python"
PROJECT_VENV_PYTHON="$PROJECT_DIR/venv/bin/python3"

if [ -n "${PATHLAB_PYTHON:-}" ]; then
    if [ -x "$PATHLAB_PYTHON" ]; then
        PYTHON="$PATHLAB_PYTHON"
    elif command -v "$PATHLAB_PYTHON" &> /dev/null; then
        PYTHON="$(command -v "$PATHLAB_PYTHON")"
    else
        echo "Error: PATHLAB_PYTHON is set but not executable/found: $PATHLAB_PYTHON"
        exit 1
    fi
elif [ -x "$PATHSCIENTIST_PYTHON" ]; then
    PYTHON="$PATHSCIENTIST_PYTHON"
elif [ -x "$PROJECT_VENV_PYTHON" ]; then
    PYTHON="$PROJECT_VENV_PYTHON"
elif [ -n "${CONDA_PREFIX:-}" ] && [ -x "$CONDA_PREFIX/bin/python3" ]; then
    PYTHON="$CONDA_PREFIX/bin/python3"
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
export DEFAULT_ADMIN_PASSWORD="${DEFAULT_ADMIN_PASSWORD:-admin}"
export PREPROCESSING_SERVICE_URL="http://127.0.0.1:6101" AI_SERVICE_URL="http://127.0.0.1:6102"

mkdir -p "$LOG_DIR"

# ============================================================
reload_frontend() {
    echo -e "${CYAN}[Frontend]${NC} 开始构建..."
    cd "$PROJECT_DIR"

    local vite_bin="$PROJECT_DIR/node_modules/vite/bin/vite.js"
    if [ ! -d "node_modules" ] || [ ! -f "$vite_bin" ]; then
        echo "  Node 依赖缺失或不完整，执行 npm install..."
        npm install --silent
    fi

    local dist_dir="$RENDERER_DIR/dist"
    local tmp_dir="$RENDERER_DIR/dist_new_$$"

    cd "$RENDERER_DIR"
    if ! node "$vite_bin" build --config vite.config.ts --outDir "$tmp_dir" 2>&1 | tail -5; then
        echo -e "${RED}[Frontend]${NC} 构建失败，未替换线上 dist 目录"
        rm -rf "$tmp_dir"
        exit 1
    fi

    if [ ! -d "$tmp_dir" ]; then
        echo -e "${RED}[Frontend]${NC} 构建未生成输出目录: $tmp_dir"
        exit 1
    fi

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
        # 1) 先杀子进程树 (uvicorn workers)
        for pid in $old_pids; do
            pkill -9 -P "$pid" 2>/dev/null || true
        done
        # 2) SIGTERM 优雅关闭主进程
        for pid in $old_pids; do kill -TERM "$pid" 2>/dev/null || true; done
        for i in {1..10}; do
            pgrep -f "$pattern" > /dev/null 2>&1 || break
            sleep 0.5
        done
        # 3) 仍未退出则 SIGKILL
        for pid in $old_pids; do kill -9 "$pid" 2>/dev/null || true; done
        sleep 0.5
    fi

    # 从 PID 文件清理旧进程树 (兜底: 捕获孤儿子进程)
    if [ -f "$LOG_DIR/${name}.pid" ]; then
        local old_main_pid=$(cat "$LOG_DIR/${name}.pid" 2>/dev/null)
        if [ -n "$old_main_pid" ] && kill -0 "$old_main_pid" 2>/dev/null; then
            echo "  清理旧进程树 (PID: $old_main_pid)"
            pkill -9 -P "$old_main_pid" 2>/dev/null || true
            kill -9 "$old_main_pid" 2>/dev/null || true
        fi
    fi

    # 按端口强制清理 + 重试循环 (对齐 start.sh 逻辑)
    local max_retries=5
    for retry in $(seq 1 $max_retries); do
        sleep 1
        local port_pids=$(ss -tlnp 2>/dev/null | grep ":$port " | grep -oP 'pid=\K[0-9]+' | sort -u)
        if [ -z "$port_pids" ]; then
            break
        fi
        if [ "$retry" -lt "$max_retries" ]; then
            echo -e "  ${YELLOW}端口 $port 仍被占用 (PID: $port_pids)，强制清理... (尝试 $retry/$max_retries)${NC}"
            for pid in $port_pids; do kill -9 "$pid" 2>/dev/null || true; done
        fi
    done

    # 最终检查
    if ss -tlnp 2>/dev/null | grep -q ":$port "; then
        echo -e "${RED}[$name]${NC} ✗ 端口 $port 释放失败！请手动执行: sudo fuser -k ${port}/tcp"
        return 1
    fi
    echo -e "  端口 $port 已释放 ✓"

    # Start new process
    if [ -n "${CUDA_VISIBLE_DEVICES:-}" ]; then
        echo -e "  ${CYAN}[GPU]${NC} CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES}"
    else
        echo -e "  ${CYAN}[GPU]${NC} CUDA_VISIBLE_DEVICES 未设置，使用全部可用 GPU"
    fi

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
