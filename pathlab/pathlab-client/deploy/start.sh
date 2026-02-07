#!/bin/bash
# PathLab 一键启动脚本
# Usage: ./start.sh

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

# ========== Step 1: 停止旧进程 ==========
echo -e "${YELLOW}[1/4]${NC} 停止旧进程..."

# Kill existing backend processes
pkill -f "python.*server/main.py" 2>/dev/null || true
pkill -f "uvicorn.*gateway" 2>/dev/null || true
pkill -f "uvicorn.*preprocessing" 2>/dev/null || true
pkill -f "uvicorn.*ai" 2>/dev/null || true

# Wait for ports to be released
sleep 2

if ss -tlnp 2>/dev/null | grep -qE ':6100|:6101|:6102'; then
    echo -e "${RED}[!] 端口仍被占用，强制清理...${NC}"
    fuser -k 6100/tcp 2>/dev/null || true
    fuser -k 6101/tcp 2>/dev/null || true
    fuser -k 6102/tcp 2>/dev/null || true
    sleep 1
fi

echo -e "${GREEN}[✓]${NC} 旧进程已清理"

# ========== Step 2: 构建前端 ==========
echo -e "${YELLOW}[2/4]${NC} 构建前端..."

cd "$PROJECT_DIR"

# Check node_modules
if [ ! -d "node_modules" ]; then
    echo "  安装 Node 依赖..."
    npm install --silent
fi

# Build frontend
cd "$RENDERER_DIR"
node "$PROJECT_DIR/node_modules/vite/bin/vite.js" build --config vite.config.ts 2>&1 | tail -5

# Copy assets
cp -r public/assets dist/ 2>/dev/null || true
cp -r public/images dist/ 2>/dev/null || true

echo -e "${GREEN}[✓]${NC} 前端构建完成: $RENDERER_DIR/dist"

# ========== Step 3: 启动后端 ==========
echo -e "${YELLOW}[3/4]${NC} 启动后端服务..."

cd "$SERVER_DIR"

# Set environment and start
export PATHLAB_DEBUG=1
export GATEWAY_PORT=6100
export PREPROCESSING_PORT=6101
export AI_PORT=6102

nohup "$PYTHON" main.py > "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
echo $BACKEND_PID > "$LOG_DIR/backend.pid"

# Wait for services to start
echo -n "  等待服务启动"
for i in {1..50}; do
    if curl -s http://127.0.0.1:6100/health > /dev/null 2>&1; then
        echo ""
        echo -e "${GREEN}[✓]${NC} 后端服务已启动 (PID: $BACKEND_PID)"
        break
    fi
    echo -n "."
    sleep 1
done

if ! curl -s http://127.0.0.1:6100/health > /dev/null 2>&1; then
    echo ""
    echo -e "${RED}[✗] 后端启动失败！查看日志: $LOG_DIR/backend.log${NC}"
    exit 1
fi

# ========== Step 4: 检查 Nginx ==========
echo -e "${YELLOW}[4/4]${NC} 检查 Nginx..."

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

