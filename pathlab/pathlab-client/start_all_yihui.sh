#!/bin/bash
# PathLab Client Startup Script (Yihui's Development Version)
# 基于 README.md 的调试模式配置
# Usage: ./start_all_yihui.sh

set -e

# Ensure we are in the pathlab-client directory
cd "$(dirname "${BASH_SOURCE[0]}")"

# Avoid proxying localhost WebSocket/HTTP checks (ASR/vLLM health checks).
# A SOCKS ALL_PROXY can break local ws://127.0.0.1 connections in gateway checks.
unset ALL_PROXY
unset all_proxy
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}127.0.0.1,localhost"
export no_proxy="${no_proxy:+$no_proxy,}127.0.0.1,localhost"

# 本地开发模式：使用 VLLM_URL/LLM_BASE_URL 等本地 LLM
export PATHLAB_ENV="${PATHLAB_ENV:-development}"

# 调试模式：固定端口（5100 开头）
# Gateway: 5100, Preprocessing: 5101, AI: 5102
export PATHLAB_DEBUG=1
export GATEWAY_PORT=5100
export PREPROCESSING_PORT=5101
export AI_PORT=5102

# 测试模式：禁用登录验证
export PATHLAB_TEST_MODE=1
# export DISABLE_AUTH=1  # 也可以使用这个，效果相同

echo "=== Starting PathLab Client (Dev Mode - Yihui) ==="
echo "Working Directory: $(pwd)"
echo "运行模式: 网页端调试模式 (xvfb-run npm run dev)"
echo "端口配置: Gateway=5100, Preprocessing=5101, AI=5102"
echo ""

# ============================================
# 1. 检查并安装 Node 依赖
# ============================================
echo "[1/5] 检查 Node 依赖..."
if [ ! -d "node_modules" ]; then
    echo "  安装 Node 依赖..."
    npm install
else
    echo "  ✓ Node 依赖已安装"
fi
echo ""

# ============================================
# 2. 设置 Python 虚拟环境
# ============================================
echo "[2/5] 设置 Python 虚拟环境..."
VENV_PATH="server/.venv"
VENV_PYTHON="${VENV_PATH}/bin/python"

if [ ! -d "$VENV_PATH" ]; then
    echo "  创建虚拟环境..."
    cd server
    uv venv .venv || {
        echo "  ❌ 虚拟环境创建失败"
        echo "  请确保已安装 uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    }
    cd ..
    echo "  ✓ 虚拟环境创建成功"
else
    echo "  ✓ 虚拟环境已存在"
fi

# 激活虚拟环境（用于当前脚本）
source "${VENV_PYTHON%/*}/activate"

# 检查并安装依赖
echo "  检查 Python 依赖..."
MISSING_DEPS=()
if ! "$VENV_PYTHON" -c "import fastapi" 2>/dev/null; then MISSING_DEPS+=("fastapi"); fi
if ! "$VENV_PYTHON" -c "import uvicorn" 2>/dev/null; then MISSING_DEPS+=("uvicorn"); fi
if ! "$VENV_PYTHON" -c "import PIL" 2>/dev/null; then MISSING_DEPS+=("pillow"); fi
if ! "$VENV_PYTHON" -c "import aiosqlite" 2>/dev/null; then MISSING_DEPS+=("aiosqlite"); fi
if ! "$VENV_PYTHON" -c "import asyncpg" 2>/dev/null; then MISSING_DEPS+=("asyncpg"); fi
if ! "$VENV_PYTHON" -c "import sqlalchemy" 2>/dev/null; then MISSING_DEPS+=("sqlalchemy"); fi
if ! "$VENV_PYTHON" -c "import torch" 2>/dev/null; then MISSING_DEPS+=("torch"); fi
if ! "$VENV_PYTHON" -c "import cv2" 2>/dev/null; then MISSING_DEPS+=("opencv-python"); fi

if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
    echo "  ⚠️  缺少 Python 依赖: ${MISSING_DEPS[*]}"
    echo "  正在安装 Python 依赖..."
    cd server
    uv pip install fastapi "uvicorn[standard]" sqlalchemy aiosqlite asyncpg pillow numpy opencv-python torch torchvision einops einops-exts httpx python-multipart openai || {
        echo "  ❌ Python 依赖安装失败"
        exit 1
    }
    cd ..
    echo "  ✓ Python 依赖安装完成"
else
    echo "  ✓ Python 依赖已安装"
fi
echo ""

# ============================================
# 3. 配置 LLM 环境变量
# ============================================
echo "[3/5] 配置 LLM 环境变量..."
# 优先使用本地 vLLM：VLLM_URL + VLLM_KEY（用于本地测试）
if [ -n "$VLLM_URL" ]; then
    echo "  ✓ 使用本地 vLLM: VLLM_URL=$VLLM_URL"
    [ -n "$VLLM_KEY" ] && echo "  ✓ VLLM_KEY 已设置" || echo "  ⚠️  VLLM_KEY 未设置 (部分 vLLM 可省略)"
    [ -n "$VLLM_MODEL" ] && echo "  ✓ VLLM_MODEL=$VLLM_MODEL"
    _LLM_CHECK_URL="$VLLM_URL"
else
    export LLM_BASE_URL="${LLM_BASE_URL:-http://127.0.0.1:8000/v1}"
    export LLM_MODEL="${LLM_MODEL:-Qwen/Qwen3-235B-A22B-Instruct-2507}"
    _LLM_CHECK_URL="$LLM_BASE_URL"
    echo "  ✓ LLM_BASE_URL=$LLM_BASE_URL"
    echo "  ✓ LLM_MODEL=$LLM_MODEL"
fi

# 检查本地 LLM 服务是否运行
if curl -s --max-time 2 "${_LLM_CHECK_URL}/models" >/dev/null 2>&1; then
    echo "  ✓ 本地 LLM 服务运行中"
else
    echo "  ⚠️  本地 LLM 服务未运行 (${_LLM_CHECK_URL})"
    echo "  将使用 OpenRouter API (需要 API key)"
fi
echo ""

# ============================================
# 4. 配置 X Server (DISPLAY)
# ============================================
echo "[4/5] 配置 X Server..."

# 检测操作系统
OS_TYPE="$(uname -s)"

if [ "$OS_TYPE" = "Darwin" ]; then
    # macOS 不需要 X Server，Electron 直接使用 Quartz
    echo "  ✓ macOS 检测到，不需要 X Server"
    USE_XVFB=false
elif [ -z "$DISPLAY" ]; then
    echo "  ⚠️  DISPLAY 环境变量未设置"
    
    if command -v xvfb-run >/dev/null 2>&1; then
        echo "  ✓ 使用 xvfb-run 启动虚拟显示"
        USE_XVFB=true
    else
        echo "  ❌ xvfb-run 未找到"
        echo "  请安装: sudo apt-get install xvfb"
        echo "  或设置 DISPLAY: export DISPLAY=:0"
        echo "  或使用 SSH X11 forwarding: ssh -X user@host"
        exit 1
    fi
else
    echo "  ✓ 使用现有 DISPLAY: $DISPLAY"
    USE_XVFB=false
fi
echo ""

# ============================================
# 5. 显示环境配置摘要
# ============================================
echo "[5/5] 环境配置摘要:"
echo "  - PATHLAB_ENV: development"
echo "  - 端口配置: Gateway=5100, Preprocessing=5101, AI=5102 (固定端口)"
if [ -n "$VLLM_URL" ]; then
    echo "  - VLLM_URL: $VLLM_URL"
    echo "  - VLLM_KEY: ${VLLM_KEY:+已设置}"
    [ -n "$VLLM_MODEL" ] && echo "  - VLLM_MODEL: $VLLM_MODEL"
else
    echo "  - LLM_BASE_URL: $LLM_BASE_URL"
    echo "  - LLM_MODEL: $LLM_MODEL"
fi
if [ "$USE_XVFB" = true ]; then
    echo "  - DISPLAY: 使用 xvfb-run (虚拟显示，符合 README 网页端调试模式)"
else
    echo "  - DISPLAY: $DISPLAY"
fi
echo ""

# ============================================
# 6. 启动 Python 后端服务
# ============================================
echo "[6/7] 启动 Python 后端服务..."

# 检查后端是否已经在运行
if curl -s --max-time 1 "http://127.0.0.1:${GATEWAY_PORT}/health" >/dev/null 2>&1; then
    echo "  ⚠️  后端服务已在运行 (端口 ${GATEWAY_PORT})"
    echo "  跳过启动，使用现有服务"
    BACKEND_PID=""
else
    echo "  启动后端服务..."
    
    # 获取绝对路径（脚本开头已经切换到项目根目录）
    SCRIPT_DIR="$(pwd)"
    VENV_PYTHON_ABS="${SCRIPT_DIR}/${VENV_PYTHON}"
    MAIN_PY_ABS="${SCRIPT_DIR}/server/main.py"
    
    echo "  命令: PATHLAB_DEBUG=1 GATEWAY_PORT=${GATEWAY_PORT} PREPROCESSING_PORT=${PREPROCESSING_PORT} AI_PORT=${AI_PORT} ${VENV_PYTHON_ABS} ${MAIN_PY_ABS}"
    
    # 在后台启动 Python 后端（在项目根目录运行，日志输出到根目录）
    PATHLAB_DEBUG=1 \
    DEBUG=true \
    GATEWAY_PORT=${GATEWAY_PORT} \
    PREPROCESSING_PORT=${PREPROCESSING_PORT} \
    AI_PORT=${AI_PORT} \
    "${VENV_PYTHON_ABS}" "${MAIN_PY_ABS}" > "${SCRIPT_DIR}/backend.log" 2>&1 &
    BACKEND_PID=$!
    
    echo "  后端进程 PID: $BACKEND_PID"
    echo "  日志文件: backend.log"
    
    # 等待后端启动（最多等待30秒）
    echo "  等待后端服务启动..."
    for i in {1..30}; do
        if curl -s --max-time 1 "http://127.0.0.1:${GATEWAY_PORT}/health" >/dev/null 2>&1; then
            echo "  ✓ 后端服务已启动 (端口 ${GATEWAY_PORT})"
            break
        fi
        if [ $i -eq 30 ]; then
            echo "  ❌ 后端服务启动超时"
            echo "  请检查 backend.log 查看错误信息"
            kill $BACKEND_PID 2>/dev/null || true
            exit 1
        fi
        sleep 1
    done
fi

echo ""

# ============================================
# 7. 启动 Electron 应用
# ============================================
echo "[7/7] 启动 Electron 应用 ==="
echo "运行模式: 网页端调试模式 (符合 README.md)"
echo "启动方式: xvfb-run npm run dev"
echo "数据库: SQLite (零配置，自动创建)"
echo "端口: Gateway=${GATEWAY_PORT}, Preprocessing=${PREPROCESSING_PORT}, AI=${AI_PORT}"
echo "后端进程 PID: ${BACKEND_PID:-已运行}"
echo "按 Ctrl+C 停止"
echo ""

# 设置环境变量，告诉 Electron 后端已经启动
export PATHLAB_BACKEND_STARTED=1

# 清理函数：停止后端进程
cleanup_backend() {
    if [ -n "$BACKEND_PID" ]; then
        echo ""
        echo "停止后端服务 (PID: $BACKEND_PID)..."
        kill $BACKEND_PID 2>/dev/null || true
        wait $BACKEND_PID 2>/dev/null || true
        echo "后端服务已停止"
    fi
}

# 注册清理函数
trap cleanup_backend EXIT INT TERM

if [ "$USE_XVFB" = true ]; then
    # 使用 xvfb-run 启动（虚拟显示，符合 README 中的网页端调试模式）
    # Vite 热更新，浏览器访问，固定端口
    echo "使用 xvfb-run 启动虚拟显示..."
    xvfb-run -a -s "-screen 0 1280x1024x24 -ac +extension GLX +render -noreset" npm run dev
else
    # 直接启动（有真实显示）
    echo "使用真实显示启动..."
    npm run dev
fi

# Electron 退出后，清理后端进程
cleanup_backend
