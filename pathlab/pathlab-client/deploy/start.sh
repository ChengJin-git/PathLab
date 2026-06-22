#!/bin/bash
# PathLab 一键启动脚本
# Usage: ./start.sh

set -e
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SERVER_DIR="$PROJECT_DIR/server"
RENDERER_DIR="$PROJECT_DIR/src/renderer"
LOG_DIR="$PROJECT_DIR/logs"
FRONTEND_BUILD_LOG="$LOG_DIR/frontend-build.log"

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
    echo "Error: Python3 not found"
    exit 1
fi

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}╔════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║          PathLab 一键启动脚本          ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════╝${NC}"
echo ""

mkdir -p "$LOG_DIR"

if systemctl is-active --quiet pathlab 2>/dev/null; then
    echo -e "${RED}[✗]${NC} 检测到 systemd 服务 pathlab 正在运行。"
    echo -e "    当前端口 6100/6101/6102 已被 systemd 管理的后端占用，deploy/start.sh 无法安全接管。"
    echo -e "    请先执行: sudo systemctl stop pathlab"
    echo -e "    或者更新 systemd 的 PATHLAB_UPLOADS_DIR 后继续使用 systemd。"
    exit 1
fi

# ========== Step 1: 停止旧进程 ==========
echo -e "${YELLOW}[1/5]${NC} 停止旧进程..."

# Function to kill process by port
kill_by_port() {
    local port=$1
    local pids=$(ss -tlnp 2>/dev/null | grep ":$port " | grep -oP 'pid=\K[0-9]+' | sort -u)
    if [ -n "$pids" ]; then
        echo "  清理端口 $port (PID: $pids)"
        for pid in $pids; do
            kill -9 $pid 2>/dev/null || true
        done
    fi
}

kill_server_main_processes() {
    local server_dir="$1"
    local pids
    pids=$(pgrep -f "python[0-9]* .*main\.py" 2>/dev/null || true)
    if [ -z "$pids" ]; then
        return
    fi

    for pid in $pids; do
        [ -d "/proc/$pid" ] || continue
        local cwd=""
        cwd=$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)
        if [ "$cwd" = "$server_dir" ]; then
            echo "  清理 server/main.py 进程树 (PID: $pid)"
            pkill -9 -P "$pid" 2>/dev/null || true
            kill -9 "$pid" 2>/dev/null || true
        fi
    done
}

listener_pids_for_port() {
    local port="$1"
    ss -tlnp 2>/dev/null | sed -n "s/.*:${port} .*pid=\([0-9]\+\).*/\1/p" | sort -u
}

is_descendant_of() {
    local pid="$1"
    local ancestor="$2"
    while [ -n "$pid" ] && [ "$pid" != "0" ]; do
        if [ "$pid" = "$ancestor" ]; then
            return 0
        fi
        [ -r "/proc/$pid/status" ] || break
        pid=$(awk '/^PPid:/ {print $2}' "/proc/$pid/status" 2>/dev/null)
    done
    return 1
}

current_run_owns_ports() {
    local root_pid="$1"
    local port pid found
    for port in 6100 6101 6102; do
        found=false
        while read -r pid; do
            [ -n "$pid" ] || continue
            found=true
            if ! is_descendant_of "$pid" "$root_pid"; then
                return 1
            fi
        done < <(listener_pids_for_port "$port")
        [ "$found" = true ] || return 1
    done
    return 0
}

# Kill existing backend processes by pattern
pkill -9 -f "python.*server/main.py" 2>/dev/null || true
kill_server_main_processes "$SERVER_DIR"
pkill -9 -f "uvicorn.*gateway" 2>/dev/null || true
pkill -9 -f "uvicorn.*preprocessing" 2>/dev/null || true
pkill -9 -f "uvicorn.*ai" 2>/dev/null || true

kill_by_port 6100
kill_by_port 6101
kill_by_port 6102

# Kill vLLM / PDF parsing related processes
pkill -9 -f "vllm.entrypoints" 2>/dev/null || true
pkill -9 -f "vllm.engine" 2>/dev/null || true
pkill -9 -f "ray::vLLM" 2>/dev/null || true
pkill -9 -f "EngineCore" 2>/dev/null || true
pkill -9 -f "vllm.v1" 2>/dev/null || true

# Kill entire process tree from previous PID file (catches orphaned children)
if [ -f "$LOG_DIR/backend.pid" ]; then
    OLD_PID=$(cat "$LOG_DIR/backend.pid" 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "  清理旧进程树 (PID: $OLD_PID)"
        pkill -9 -P "$OLD_PID" 2>/dev/null || true
        kill -9 "$OLD_PID" 2>/dev/null || true
    fi
fi

# Wait for ports to be released with retry logic
MAX_RETRIES=5
RETRY_COUNT=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    sleep 2

    if ! ss -tlnp 2>/dev/null | grep -qE ':6100|:6101|:6102'; then
        # Ports are free
        break
    fi

    RETRY_COUNT=$((RETRY_COUNT + 1))

    if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
        echo -e "${YELLOW}[!] 端口仍被占用，强制清理... (尝试 $RETRY_COUNT/$MAX_RETRIES)${NC}"
        kill_by_port 6100
        kill_by_port 6101
        kill_by_port 6102
    fi
done

# Final check
if ss -tlnp 2>/dev/null | grep -qE ':6100|:6101|:6102'; then
    echo -e "${RED}[✗] 端口清理失败，请手动执行:${NC}"
    echo -e "    sudo fuser -k 6100/tcp 6101/tcp 6102/tcp"
    exit 1
fi

echo -e "${GREEN}[✓]${NC} 旧进程已清理"

# ========== Step 2: 确保 Redis 运行 ==========
echo -e "${YELLOW}[2/5]${NC} 检查 Redis..."

if command -v redis-cli &> /dev/null && redis-cli ping &> /dev/null; then
    echo -e "${GREEN}[✓]${NC} Redis 已运行"
else
    # Try to start via systemd
    if systemctl is-active --quiet redis-server 2>/dev/null || systemctl is-active --quiet redis 2>/dev/null; then
        echo -e "${GREEN}[✓]${NC} Redis 已运行 (systemd)"
    else
        echo -n "  启动 Redis..."
        if sudo systemctl start redis-server 2>/dev/null || sudo systemctl start redis 2>/dev/null; then
            sleep 1
            if redis-cli ping &> /dev/null; then
                echo ""
                echo -e "${GREEN}[✓]${NC} Redis 启动成功"
            else
                echo ""
                echo -e "${RED}[✗] Redis 启动后无法连接，请检查 Redis 配置${NC}"
                exit 1
            fi
        else
            # Fallback: try redis-server directly
            echo ""
            echo -e "${YELLOW}[!]${NC} systemd 启动失败，尝试直接启动 redis-server..."
            redis-server --daemonize yes --loglevel warning 2>/dev/null
            sleep 1
            if redis-cli ping &> /dev/null; then
                echo -e "${GREEN}[✓]${NC} Redis 启动成功 (standalone)"
            else
                echo -e "${RED}[✗] Redis 启动失败，请手动安装/启动 Redis:${NC}"
                echo -e "    sudo apt install redis-server && sudo systemctl enable redis-server"
                exit 1
            fi
        fi
    fi
fi

# ========== Step 3: 构建前端 ==========
echo -e "${YELLOW}[3/5]${NC} 构建前端..."

cd "$PROJECT_DIR"

# Check node_modules
if [ ! -d "node_modules" ]; then
    echo "  安装 Node 依赖..."
    npm install --silent
fi

# Build frontend
cd "$RENDERER_DIR"

echo "  构建日志: $FRONTEND_BUILD_LOG"
if ! node "$PROJECT_DIR/node_modules/vite/bin/vite.js" build --config vite.config.ts > "$FRONTEND_BUILD_LOG" 2>&1; then
    echo -e "${RED}[✗] 前端构建失败！最近日志如下:${NC}"
    tail -50 "$FRONTEND_BUILD_LOG" || true
    echo -e "${YELLOW}完整日志:${NC} $FRONTEND_BUILD_LOG"
    exit 1
fi

# Copy assets
cp -r public/assets dist/ 2>/dev/null || true
cp -r public/images dist/ 2>/dev/null || true

echo -e "${GREEN}[✓]${NC} 前端构建完成: $RENDERER_DIR/dist"

# ========== Step 4: 启动后端 ==========
echo -e "${YELLOW}[4/5]${NC} 启动后端服务..."

cd "$SERVER_DIR"

# Load .env if exists (DATABASE_URL, JWT_SECRET, etc.)
if [ -f "$SERVER_DIR/.env" ]; then
    set -a
    source "$SERVER_DIR/.env"
    set +a
fi

unset PATHLAB_UPLOADS_DIR
RESOLVED_UPLOADS_DIR=$(
    "$PYTHON" - <<'PY'
from backend.common.config import Config
print(Config.get_uploads_dir())
PY
)
export PATHLAB_UPLOADS_DIR="$RESOLVED_UPLOADS_DIR"

# Set environment and start
export PATHLAB_DEBUG=1
export GATEWAY_PORT=6100
export PREPROCESSING_PORT=6101
export AI_PORT=6102
export DEFAULT_ADMIN_PASSWORD="${DEFAULT_ADMIN_PASSWORD:-admin}"

if [ -n "${CUDA_VISIBLE_DEVICES:-}" ]; then
    echo -e "  ${CYAN}[GPU]${NC} CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES}"
    if command -v nvidia-smi &> /dev/null; then
        available_raw=$(nvidia-smi --query-gpu=index --format=csv,noheader 2>/dev/null | tr '\n' ' ' | sed 's/ $//')
        echo -e "  ${CYAN}[GPU]${NC} 系统物理 GPU 索引: ${available_raw:-未知}"
        invalid=""
        IFS=',' read -ra _configured_gpus <<< "$CUDA_VISIBLE_DEVICES"
        for _idx in "${_configured_gpus[@]}"; do
            _idx=$(echo "$_idx" | tr -d ' ')
            if ! echo " $available_raw " | grep -qE " $_idx "; then
                invalid="${invalid:+$invalid,}$_idx"
            fi
        done
        if [ -n "$invalid" ]; then
            echo -e "  ${YELLOW}[GPU][!]${NC} 以下卡号在系统中不存在，请检查: ${invalid}"
        else
            echo -e "  ${GREEN}[GPU][✓]${NC} 配置有效"
        fi
    fi
else
    echo -e "  ${CYAN}[GPU]${NC} CUDA_VISIBLE_DEVICES 未设置，使用全部可用 GPU"
fi

nohup "$PYTHON" main.py > "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
echo $BACKEND_PID > "$LOG_DIR/backend.pid"

# Wait for services to start
health_ready() {
    curl -s http://127.0.0.1:6100/health > /dev/null 2>&1 \
        && curl -s http://127.0.0.1:6101/health > /dev/null 2>&1 \
        && curl -s http://127.0.0.1:6102/health > /dev/null 2>&1
}

echo -n "  等待服务启动"
for i in {1..50}; do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        break
    fi
    if health_ready && current_run_owns_ports "$BACKEND_PID"; then
        echo ""
        echo -e "${GREEN}[✓]${NC} 后端服务已启动 (PID: $BACKEND_PID)"
        break
    fi
    echo -n "."
    sleep 1
done

if ! kill -0 "$BACKEND_PID" 2>/dev/null || ! health_ready || ! current_run_owns_ports "$BACKEND_PID"; then
    echo ""
    echo -e "${RED}[✗] 后端启动失败！查看日志: $LOG_DIR/backend.log${NC}"
    exit 1
fi

# ========== Step 5: 检查 Nginx ==========
echo -e "${YELLOW}[5/5]${NC} 检查 Nginx..."

if systemctl is-active --quiet nginx 2>/dev/null; then
    echo -e "${GREEN}[✓]${NC} Nginx 运行中"
else
    echo -e "${YELLOW}[!]${NC} Nginx 未运行，请执行: sudo systemctl start nginx"
fi

# ========== 完成 ==========
echo ""
echo -e "${CYAN}╔════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║               启动完成！               ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${GREEN}本地访问:${NC}  http://127.0.0.1:6100"
echo -e "  ${GREEN}Python:${NC}    $PYTHON"
echo ""
echo -e "  ${YELLOW}查看日志:${NC}  tail -f $LOG_DIR/backend.log"
echo -e "  ${YELLOW}停止服务:${NC}  kill \$(cat $LOG_DIR/backend.pid)"
echo ""
