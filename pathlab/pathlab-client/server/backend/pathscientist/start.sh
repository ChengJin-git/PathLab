#!/bin/bash
# PathScientist — Autonomous Research Agent
#
# Usage:
#   ./start.sh                                    # 交互模式
#   ./start.sh -q "Improve AUC on BRACS"          # research 模式（默认，带 orchestrator）
#   ./start.sh -q "Improve AUC" --mode code       # code 模式（跳过 orchestrator，直接 code agent）
#   ./start.sh -q "Extract UNI features" \
#     --data-mount "/path/WSIs:/data/wsi" \
#     --data-mount "/path/output:/output"          # 带数据挂载
#   ./start.sh --skill mil_classification         # 指定 skill
#   ./start.sh --sandbox local                     # 不用容器，直接本机跑
#
# 环境变量 (可选，命令行参数优先):
#   PATHSCIENTIST_ENV_FILE        项目本地 env 文件 (默认 ./pathscientist/.env.local)
#   PATHSCIENTIST_LLM_PROFILE     LLM profile (默认 codex-relay，走远端 GPT relay)
#   PATHSCIENTIST_LLM_MODEL       模型名
#   PATHSCIENTIST_LLM_API_KEY     API key
#   PATHSCIENTIST_LLM_BASE_URL    模型地址
#   PATHSCIENTIST_LLM_WIRE_API    wire API (codex-relay 默认 responses)
#   PATHSCIENTIST_SANDBOX         sandbox 模式: auto|apptainer|local
#   PATHSCIENTIST_BASE_DIR        AutoResearch 根目录 (默认 Settings uploads/autoresearch)
#   PATHSCIENTIST_DATASET_CACHE_DIR 统一数据根目录；本地先查这里，下载也落这里
#                                  (默认 $PATHSCIENTIST_BASE_DIR/dataset_cache)
#   PATHSCIENTIST_GENERATE_PAPER_DRAFT 是否在 synthesis 阶段生成 paper_draft.md
#                                  (默认 0，关闭；置 1 显式开启)
#   PATHSCIENTIST_FEATURE_EXTRACTOR 显式固定 WSI feature extractor
#   PATHSCIENTIST_FEATURE_EXTRACTOR_MODE=auto|fixed (默认 auto)
#   PATHSCIENTIST_TIMEOUT              默认执行 timeout 秒数 (默认 3600)
#   PATHSCIENTIST_QUICK_CHECK_TIMEOUT  quick_check 最小 timeout 秒数 (默认 3600)
#   PATHSCIENTIST_STOP_BEFORE_EXECUTION  只跑训练前流程并在 code agent 执行前停止
#   PATHSCIENTIST_LITERATURE_ONLINE         启用 OpenAlex 在线论文检索 (默认 1，开)
#                                            置 0 关闭，仅用本地 seed + cache
#   PATHSCIENTIST_AUTO_ACQUIRE_DATA         启用数据集自动发现+下载 (默认 1，开)
#                                            默认允许 gated/manual 大数据集下载:
#                                            DOWNLOAD_POLICY=all,
#                                            MAX_DOWNLOAD_SIZE_GB=500,
#                                            ALLOW_LARGE_DOWNLOADS=1
#                                            置 0 关闭自动获取；可用 env 覆盖策略
#   PATHSCIENTIST_RAG                       启用文献 RAG: 1|true|yes
#   PATHSCIENTIST_RAG_CORPUS_DIR            本地论文语料目录 (txt/md/pdf)
#   PATHSCIENTIST_RAG_TOP_K                 每次检索的 passage 数量 (默认 3)
#   PATHSCIENTIST_RAG_EMBEDDING_MODEL       嵌入模型名 (默认 Qwen/Qwen3-Embedding-8B)
#   PATHSCIENTIST_RAG_EMBEDDING_BASE_URL    嵌入 API 地址 (默认 http://dgx-24.cm.cluster:9001/v1)
#   PATHSCIENTIST_RAG_EMBEDDING_API_KEY     嵌入 API key (默认 sk-pathlab)
#
# RAG 用法示例:
#   # 0. 只用 14 篇种子论文 bootstrap (最快，开箱即用)
#   .venv/bin/python -m pathscientist.rag_ingest --from-seed-data
#
#   # 1. 预建索引 (用户自己的语料)
#   .venv/bin/python -m pathscientist.rag_ingest --corpus-dir /path/to/papers
#
#   # 2. 种子论文 + 用户语料
#   .venv/bin/python -m pathscientist.rag_ingest --from-seed-data --corpus-dir /path/to/papers
#
#   # 3. 查看索引状态
#   .venv/bin/python -m pathscientist.rag_ingest --status
#
#   # 4. 强制重建 (换 embedding 模型、语料大改动时)
#   .venv/bin/python -m pathscientist.rag_ingest --from-seed-data --force
#
#   # 5. 启动 session 时启用 RAG (预建的索引会被复用)
#   ./start.sh --rag                              # 只用种子 + 默认语料路径
#   ./start.sh --rag --rag-corpus-dir /path       # 带用户语料
#   PATHSCIENTIST_RAG=1 ./start.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
SERVER_DIR="$(dirname "$BACKEND_DIR")"
PATHLAB_CLIENT_DIR="$(dirname "$(dirname "$BACKEND_DIR")")"

resolve_default_base_dir() {
    PATHLAB_CLIENT_DIR="$PATHLAB_CLIENT_DIR" \
    PYTHONPATH="$SERVER_DIR${PYTHONPATH:+:$PYTHONPATH}" \
    "$VENV_DIR/bin/python" - <<'PY'
import os
from pathlib import Path

try:
    from backend.common.config import Config

    print(Config.get_autoresearch_dir())
except Exception:
    uploads_dir = os.environ.get("PATHLAB_UPLOADS_DIR", "")
    if uploads_dir:
        print(Path(uploads_dir).expanduser() / "autoresearch")
    else:
        print(Path(os.environ["PATHLAB_CLIENT_DIR"]) / "uploads" / "autoresearch")
PY
}

load_project_env() {
    local env_file="$1"
    if [ ! -f "$env_file" ]; then
        return 0
    fi

    local line key value
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line#"${line%%[![:space:]]*}"}"
        line="${line%"${line##*[![:space:]]}"}"
        if [ -z "$line" ] || [[ "$line" == \#* ]]; then
            continue
        fi
        if [[ "$line" == export\ * ]]; then
            line="${line#export }"
        fi
        if [[ "$line" != *=* ]]; then
            continue
        fi

        key="${line%%=*}"
        value="${line#*=}"
        key="${key%"${key##*[![:space:]]}"}"
        value="${value#"${value%%[![:space:]]*}"}"
        value="${value%"${value##*[![:space:]]}"}"
        if [[ "$key" != PATHSCIENTIST_* ]]; then
            continue
        fi
        if [[ "$value" == \"*\" && "$value" == *\" ]]; then
            value="${value:1:${#value}-2}"
        elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
            value="${value:1:${#value}-2}"
        fi
        if [ -z "${!key+x}" ]; then
            export "$key=$value"
        fi
    done < "$env_file"
}

# --- 检查 venv ---
if [ ! -f "$VENV_DIR/bin/python" ]; then
    echo "❌ Python venv not found at $VENV_DIR"
    echo "   Run: cd $SCRIPT_DIR && uv venv .venv --python 3.12 && uv pip install openhands-sdk openhands-tools torch --index-url https://download.pytorch.org/whl/cpu"
    exit 1
fi
export PATH="$VENV_DIR/bin:$PATH"

# --- 加载 apptainer module (HPC 集群需要) ---
if [ -f /etc/profile.d/modules.sh ]; then
    source /etc/profile.d/modules.sh 2>/dev/null
    module load apptainer 2>/dev/null || true
fi

# --- 加载项目本地 relay 配置（.env.local 已被 gitignore） ---
PROJECT_ENV_FILE="${PATHSCIENTIST_ENV_FILE:-$SCRIPT_DIR/.env.local}"
load_project_env "$PROJECT_ENV_FILE"

# --- 默认配置 ---
PATHSCIENTIST_LLM_PROFILE_DEFAULT="${PATHSCIENTIST_LLM_PROFILE:-codex-relay}"
export PATHSCIENTIST_LLM_MODEL="${PATHSCIENTIST_LLM_MODEL:-gpt-5.5}"
export PATHSCIENTIST_LLM_WIRE_API="${PATHSCIENTIST_LLM_WIRE_API:-responses}"
export PATHSCIENTIST_SANDBOX="${PATHSCIENTIST_SANDBOX:-auto}"
PATHSCIENTIST_BASE_DIR_DEFAULT="$(resolve_default_base_dir)"
export PATHSCIENTIST_BASE_DIR="${PATHSCIENTIST_BASE_DIR:-$PATHSCIENTIST_BASE_DIR_DEFAULT}"
export PATHSCIENTIST_DATASET_CACHE_DIR="${PATHSCIENTIST_DATASET_CACHE_DIR:-$PATHSCIENTIST_BASE_DIR/dataset_cache}"
export PATHSCIENTIST_GENERATE_PAPER_DRAFT="${PATHSCIENTIST_GENERATE_PAPER_DRAFT:-0}"
export PATHSCIENTIST_FEATURE_EXTRACTOR_MODE="${PATHSCIENTIST_FEATURE_EXTRACTOR_MODE:-auto}"
if [[ "$PATHSCIENTIST_FEATURE_EXTRACTOR_MODE" == "fixed" ]]; then
  export PATHSCIENTIST_FEATURE_EXTRACTOR="${PATHSCIENTIST_FEATURE_EXTRACTOR:-virchow2}"
elif [[ -n "${PATHSCIENTIST_FEATURE_EXTRACTOR:-}" ]]; then
  export PATHSCIENTIST_FEATURE_EXTRACTOR
else
  unset PATHSCIENTIST_FEATURE_EXTRACTOR
fi
export PATHSCIENTIST_MIL_MODEL="${PATHSCIENTIST_MIL_MODEL:-}"
export PATHSCIENTIST_TIMEOUT="${PATHSCIENTIST_TIMEOUT:-3600}"
export PATHSCIENTIST_QUICK_CHECK_TIMEOUT="${PATHSCIENTIST_QUICK_CHECK_TIMEOUT:-3600}"
export PATHSCIENTIST_FEATURE_EXTRACTION_QUICK_TIMEOUT="${PATHSCIENTIST_FEATURE_EXTRACTION_QUICK_TIMEOUT:-3600}"
# Default-on OpenAlex paper search (and SOTA cache via PwC). Backend config
# defaults to off; we flip it here so the typical interactive launch gets
# literature grounding without needing to set env vars manually. Override
# with ``PATHSCIENTIST_LITERATURE_ONLINE=0 ./start.sh ...`` if you want
# pure-local mode.
export PATHSCIENTIST_LITERATURE_ONLINE="${PATHSCIENTIST_LITERATURE_ONLINE:-1}"
# How many papers to retrieve per grounding (default 10). Was 5 hardcoded
# in grounding.py before; now wired through config.literature_online_max_results.
export PATHSCIENTIST_LITERATURE_ONLINE_MAX_RESULTS="${PATHSCIENTIST_LITERATURE_ONLINE_MAX_RESULTS:-10}"
# Default-on dataset acquisition. For the current PathLab test-data workflow,
# default to TCGA/PANDA-capable acquisition: gated/manual datasets are allowed
# and large-download opt-in is enabled. Override with env vars if you want
# public-only/smaller downloads. Disable entirely with
# ``PATHSCIENTIST_AUTO_ACQUIRE_DATA=0 ./start.sh ...``.
export PATHSCIENTIST_AUTO_ACQUIRE_DATA="${PATHSCIENTIST_AUTO_ACQUIRE_DATA:-1}"
export PATHSCIENTIST_DOWNLOAD_POLICY="${PATHSCIENTIST_DOWNLOAD_POLICY:-all}"
export PATHSCIENTIST_MAX_DOWNLOAD_SIZE_GB="${PATHSCIENTIST_MAX_DOWNLOAD_SIZE_GB:-500}"
export PATHSCIENTIST_ALLOW_LARGE_DOWNLOADS="${PATHSCIENTIST_ALLOW_LARGE_DOWNLOADS:-1}"
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
    --llm-profile "$PATHSCIENTIST_LLM_PROFILE_DEFAULT"
)

if [ "$MODE" = "batch" ]; then
    exec "$VENV_DIR/bin/python" -m pathscientist.run "${COMMON_ARGS[@]}" "$@"
else
    exec "$VENV_DIR/bin/python" -m pathscientist "${COMMON_ARGS[@]}" "$@"
fi
