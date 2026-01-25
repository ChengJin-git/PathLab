#!/bin/bash
# PathLab Client Startup Script
# Usage: ./start_all.sh

set -e

# Ensure we are in the pathlab-client directory
cd "$(dirname "${BASH_SOURCE[0]}")"

# 本地开发模式：使用 VLLM_URL/LLM_BASE_URL 等本地 LLM
export PATHLAB_ENV="${PATHLAB_ENV:-development}"

echo "=== Starting PathLab Client (Dev Mode) ==="
echo "Working Directory: $(pwd)"
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
if ! "$VENV_PYTHON" -c "import sqlalchemy" 2>/dev/null; then MISSING_DEPS+=("sqlalchemy"); fi
if ! "$VENV_PYTHON" -c "import torch" 2>/dev/null; then MISSING_DEPS+=("torch"); fi
if ! "$VENV_PYTHON" -c "import cv2" 2>/dev/null; then MISSING_DEPS+=("opencv-python"); fi

if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
    echo "  ⚠️  缺少 Python 依赖: ${MISSING_DEPS[*]}"
    echo "  正在安装 Python 依赖..."
    cd server
    uv pip install fastapi "uvicorn[standard]" sqlalchemy aiosqlite pillow numpy opencv-python torch torchvision einops einops-exts httpx python-multipart openai || {
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
if [ -z "$DISPLAY" ]; then
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
echo "  - PATHLAB_ENV: development (由 Electron 自动设置)"
if [ -n "$VLLM_URL" ]; then
    echo "  - VLLM_URL: $VLLM_URL"
    echo "  - VLLM_KEY: ${VLLM_KEY:+已设置}"
    [ -n "$VLLM_MODEL" ] && echo "  - VLLM_MODEL: $VLLM_MODEL"
else
    echo "  - LLM_BASE_URL: $LLM_BASE_URL"
    echo "  - LLM_MODEL: $LLM_MODEL"
fi
if [ "$USE_XVFB" = true ]; then
    echo "  - DISPLAY: 使用 xvfb-run (虚拟显示)"
else
    echo "  - DISPLAY: $DISPLAY"
fi
echo ""

# ============================================
# 启动 Electron 应用
# ============================================
echo "=== 启动 Electron 应用 ==="
echo "数据库: SQLite (自动配置)"
echo "按 Ctrl+C 停止"
echo ""

if [ "$USE_XVFB" = true ]; then
    # 使用 xvfb-run 启动（虚拟显示，窗口不可见但后端服务正常）
    xvfb-run -a -s "-screen 0 1280x1024x24 -ac +extension GLX +render -noreset" npm run dev
else
    # 直接启动（有真实显示）
    npm run dev
fi
