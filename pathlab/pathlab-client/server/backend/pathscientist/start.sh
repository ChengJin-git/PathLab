#!/bin/bash
# PathScientist Code Agent — Interactive CLI
#
# Usage:
#   ./start.sh                                    # 交互模式 (apptainer sandbox)
#   ./start.sh --skill mil_classification         # 带 skill
#   ./start.sh -q "Improve AUC on BRACS"          # 非交互
#   ./start.sh --sandbox local                     # 不用容器，直接本机跑
#
# 环境变量 (可选，命令行参数优先):
#   PATHSCIENTIST_LLM_MODEL    模型名
#   PATHSCIENTIST_LLM_API_KEY  API key
#   PATHSCIENTIST_LLM_BASE_URL 模型地址
#   PATHSCIENTIST_SANDBOX      sandbox 模式: auto|apptainer|local
#   PATHSCIENTIST_BASE_DIR     workspace 根目录 (默认 /project/vcompath/storage/ywangrm/tmp/pathscientist)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"

# --- 检查 venv ---
if [ ! -f "$VENV_DIR/bin/python" ]; then
    echo "❌ Python venv not found at $VENV_DIR"
    echo "   Run: cd $SCRIPT_DIR && uv venv .venv --python 3.12 && uv pip install openhands-sdk openhands-tools torch --index-url https://download.pytorch.org/whl/cpu"
    exit 1
fi

# --- 加载 apptainer module (HPC 集群需要) ---
if [ -f /etc/profile.d/modules.sh ]; then
    source /etc/profile.d/modules.sh 2>/dev/null
    module load apptainer 2>/dev/null || true
fi

# --- 默认配置 ---
export PATHSCIENTIST_LLM_MODEL="${PATHSCIENTIST_LLM_MODEL:-openai/Qwen/Qwen3.5-397B-A17B-FP8}"
export PATHSCIENTIST_LLM_API_KEY="${PATHSCIENTIST_LLM_API_KEY:-sk-pathlab}"
export PATHSCIENTIST_LLM_BASE_URL="${PATHSCIENTIST_LLM_BASE_URL:-http://dgx-52.cm.cluster:8000/v1}"
export PATHSCIENTIST_SANDBOX="${PATHSCIENTIST_SANDBOX:-auto}"
export PATHSCIENTIST_BASE_DIR="${PATHSCIENTIST_BASE_DIR:-/project/vcompath/storage/ywangrm/tmp/pathscientist}"
export OPENHANDS_SUPPRESS_BANNER=1

# --- 判断交互 vs 非交互模式 ---
MODE="interactive"
for arg in "$@"; do
    if [ "$arg" = "-q" ] || [ "$arg" = "--question" ]; then
        MODE="batch"
        break
    fi
done

cd "$BACKEND_DIR"

COMMON_ARGS=(
    --model "$PATHSCIENTIST_LLM_MODEL"
    --api-key "$PATHSCIENTIST_LLM_API_KEY"
    --base-url "$PATHSCIENTIST_LLM_BASE_URL"
)

if [ "$MODE" = "batch" ]; then
    exec "$VENV_DIR/bin/python" -m pathscientist.run "${COMMON_ARGS[@]}" "$@"
else
    exec "$VENV_DIR/bin/python" -m pathscientist "${COMMON_ARGS[@]}" "$@"
fi
