#!/bin/bash
# PathLab start script
# Usage: ./start.sh

set -e
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SERVER_DIR="$PROJECT_DIR/server"
RENDERER_DIR="$PROJECT_DIR/src/renderer"
LOG_DIR="$PROJECT_DIR/logs"
FRONTEND_BUILD_LOG="$LOG_DIR/frontend-build.log"

source "$SCRIPT_DIR/python-runtime.sh"
select_pathlab_python

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'


load_autoresearch_env_file() {
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
        if [[ "$key" != AUTORESEARCH_* && "$key" != APPTAINER_BIN && "$key" != PATHLAB_SANDBOX_IMAGE ]]; then
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

resolve_apptainer_bin() {
    local configured="${APPTAINER_BIN:-}"
    if [ -n "$configured" ]; then
        if [ -x "$configured" ]; then
            echo "$configured"
            return 0
        fi
        if command -v "$configured" > /dev/null 2>&1; then
            command -v "$configured"
            return 0
        fi
        return 1
    fi

    if command -v apptainer > /dev/null 2>&1; then
        command -v apptainer
        return 0
    fi
    if [ -x /cm/local/apps/apptainer/current/bin/apptainer ]; then
        echo /cm/local/apps/apptainer/current/bin/apptainer
        return 0
    fi
    return 1
}

resolve_autoresearch_sandbox_image() {
    if [ -n "${AUTORESEARCH_SANDBOX_IMAGE:-}" ]; then
        echo "$AUTORESEARCH_SANDBOX_IMAGE"
        return 0
    fi
    if [ -n "${PATHLAB_SANDBOX_IMAGE:-}" ]; then
        echo "$PATHLAB_SANDBOX_IMAGE"
        return 0
    fi

    echo "${XDG_DATA_HOME:-$HOME/.local/share}/PathLab/sandbox/pathlab-sandbox.sif"
}

check_autoresearch_python_packages() {
    "$PYTHON" "$SCRIPT_DIR/verify-runtime.py"
}

install_autoresearch_python_packages() {
    echo "Runtime validation failed. Install a verified bundle before starting:"
    echo "  bash deploy/install-runtime.sh BUNDLE server/.venv"
    echo "See deploy/guides/MIGRATION.md. Startup will not modify your environment."
    return 1
}

check_autoresearch_sandbox() {
    local opencode_bin="${PATHLAB_OPENCODE_BIN:-$(command -v opencode || echo "$HOME/.opencode/bin/opencode")}"
    local opencode_version
    opencode_version=$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["opencodeVersion"])' "$PROJECT_DIR/package.json")
    if [ "$("$opencode_bin" --version)" != "opencode v$opencode_version" ]; then
        echo "OpenCode $opencode_version is required. Run deploy/install-opencode.py or set PATHLAB_OPENCODE_BIN."
        return 1
    fi
    local sandbox_mode="${AUTORESEARCH_SANDBOX:-auto}"
    case "$sandbox_mode" in
        local)
            echo -e "  ${YELLOW}[!]${NC} AUTORESEARCH_SANDBOX=local, skip Apptainer check"
            return 0
            ;;
        auto|apptainer|"")
            ;;
        *)
            echo -e "${RED}[✗]${NC} Unsupported AUTORESEARCH_SANDBOX=$sandbox_mode (expected auto, apptainer, or local)"
            return 1
            ;;
    esac

    local apptainer_bin
    if ! apptainer_bin=$(resolve_apptainer_bin); then
        echo -e "${RED}[✗]${NC} Apptainer not found. Install Apptainer or set APPTAINER_BIN."
        return 1
    fi
    if ! "$apptainer_bin" --version > /dev/null 2>&1; then
        echo -e "${RED}[✗]${NC} Apptainer is not executable: $apptainer_bin"
        return 1
    fi

    local sandbox_image
    sandbox_image=$(resolve_autoresearch_sandbox_image)
    if [ ! -f "$sandbox_image" ]; then
        echo -e "${RED}[✗]${NC} AutoResearch sandbox image not found: $sandbox_image"
        echo -e "    Build it with: $PYTHON $PROJECT_DIR/deploy/build-skills-runtime.py --rebuild-base"
        return 1
    fi

    export AUTORESEARCH_SANDBOX="$sandbox_mode"
    export AUTORESEARCH_SANDBOX_IMAGE="$sandbox_image"
    echo -e "  ${GREEN}[✓]${NC} Apptainer OK: $apptainer_bin"
    echo -e "  ${GREEN}[✓]${NC} AutoResearch sandbox image: $sandbox_image"
}

check_autoresearch_environment() {
    echo -e "${YELLOW}[0/5]${NC} Checking the research environment..."

    if [ -f "$SERVER_DIR/.env" ]; then
        set -a
        source "$SERVER_DIR/.env"
        set +a
    fi

    load_autoresearch_env_file "${AUTORESEARCH_ENV_FILE:-$SERVER_DIR/backend/autoresearch/.env.local}"

    if ! check_autoresearch_python_packages; then
        install_autoresearch_python_packages
        check_autoresearch_python_packages
    fi
    check_autoresearch_sandbox
    (cd "$SERVER_DIR" && "$PYTHON" "$SCRIPT_DIR/install-pathtrove-data.py")
    # Pinned retrieval models for Chat/training recommendations; offline check first, download only if missing.
    "$PYTHON" "$SCRIPT_DIR/prepare-knowledge.py" --check > /dev/null 2>&1 \
        || "$PYTHON" "$SCRIPT_DIR/prepare-knowledge.py" > /dev/null
    echo -e "${GREEN}[✓]${NC} Research environment OK"
}

echo -e "${CYAN}╔════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║          PathLab start script          ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════╝${NC}"
echo ""

mkdir -p "$LOG_DIR"

if systemctl is-active --quiet pathlab 2>/dev/null; then
    echo -e "${RED}[✗]${NC} The systemd service pathlab is running."
    echo -e "    Ports 6100/6101/6102 are held by the systemd-managed backend; deploy/start.sh will not take over."
    echo -e "    Run first: sudo systemctl stop pathlab"
    echo -e "    or keep using systemd (update its environment instead)."
    exit 1
fi

check_autoresearch_environment

# ========== Step 1: stop previous processes ==========
echo -e "${YELLOW}[1/5]${NC} Stopping previous processes..."

# Function to kill process by port
kill_by_port() {
    local port=$1
    local pids=$(ss -tlnp 2>/dev/null | grep ":$port " | grep -oP 'pid=\K[0-9]+' | sort -u)
    if [ -n "$pids" ]; then
        echo "  Freeing port $port (PID: $pids)"
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
            echo "  Stopping server/main.py process tree (PID: $pid)"
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

# Stop worker processes started independently by hot-reload, scoped to this checkout.
for worker_pid_file in "$LOG_DIR/task-worker.pid" "$LOG_DIR/research-worker.pid"; do
    if [ -f "$worker_pid_file" ]; then
        worker_pid=$(cat "$worker_pid_file")
        if [ "$(readlink -f "/proc/$worker_pid/cwd" 2>/dev/null || true)" = "$SERVER_DIR" ]; then
            kill -TERM "$worker_pid" 2>/dev/null || true
        fi
    fi
done

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
        echo "  Stopping previous process tree (PID: $OLD_PID)"
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
        echo -e "${YELLOW}[!] Ports still in use, forcing clean-up... (attempt $RETRY_COUNT/$MAX_RETRIES)${NC}"
        kill_by_port 6100
        kill_by_port 6101
        kill_by_port 6102
    fi
done

# Final check
if ss -tlnp 2>/dev/null | grep -qE ':6100|:6101|:6102'; then
    echo -e "${RED}[✗] Could not free the ports; run manually:${NC}"
    echo -e "    sudo fuser -k 6100/tcp 6101/tcp 6102/tcp"
    exit 1
fi

echo -e "${GREEN}[✓]${NC} Previous processes stopped"

# ========== Step 2: make sure Redis is running ==========
echo -e "${YELLOW}[2/5]${NC} Checking Redis..."

if command -v redis-cli &> /dev/null && redis-cli ping &> /dev/null; then
    echo -e "${GREEN}[✓]${NC} Redis is running"
else
    # Try to start via systemd
    if systemctl is-active --quiet redis-server 2>/dev/null || systemctl is-active --quiet redis 2>/dev/null; then
        echo -e "${GREEN}[✓]${NC} Redis is running (systemd)"
    else
        echo -n "  Starting Redis..."
        if sudo systemctl start redis-server 2>/dev/null || sudo systemctl start redis 2>/dev/null; then
            sleep 1
            if redis-cli ping &> /dev/null; then
                echo ""
                echo -e "${GREEN}[✓]${NC} Redis started"
            else
                echo ""
                echo -e "${RED}[✗] Redis started but is not reachable; check the Redis configuration${NC}"
                exit 1
            fi
        else
            # Fallback: try redis-server directly
            echo ""
            echo -e "${YELLOW}[!]${NC} systemd start failed, starting redis-server directly..."
            redis-server --daemonize yes --loglevel warning 2>/dev/null
            sleep 1
            if redis-cli ping &> /dev/null; then
                echo -e "${GREEN}[✓]${NC} Redis started (standalone)"
            else
                echo -e "${RED}[✗] Redis failed to start; install or start it manually:${NC}"
                echo -e "    sudo apt install redis-server && sudo systemctl enable redis-server"
                exit 1
            fi
        fi
    fi
fi

# ========== Step 3: build the web client ==========
echo -e "${YELLOW}[3/5]${NC} Building the web client..."

cd "$PROJECT_DIR"

# Check node_modules
if [ ! -d "node_modules" ]; then
    echo "  Installing Node dependencies..."
    npm ci --silent
fi

# Build frontend
cd "$RENDERER_DIR"

echo "  Build log: $FRONTEND_BUILD_LOG"
if ! node "$PROJECT_DIR/node_modules/vite/bin/vite.js" build --config vite.config.ts > "$FRONTEND_BUILD_LOG" 2>&1; then
    echo -e "${RED}[✗] Web client build failed. Last log lines:${NC}"
    tail -50 "$FRONTEND_BUILD_LOG" || true
    echo -e "${YELLOW}Full log:${NC} $FRONTEND_BUILD_LOG"
    exit 1
fi

# Copy assets
cp -r public/assets dist/ 2>/dev/null || true
cp -r public/images dist/ 2>/dev/null || true

echo -e "${GREEN}[✓]${NC} Web client built: $RENDERER_DIR/dist"

# ========== Step 4: start the backend ==========
echo -e "${YELLOW}[4/5]${NC} Starting backend services..."

cd "$SERVER_DIR"

# Load .env if exists (DATABASE_URL, JWT_SECRET, etc.)
if [ -f "$SERVER_DIR/.env" ]; then
    set -a
    source "$SERVER_DIR/.env"
    set +a
fi

RESOLVED_UPLOADS_DIR=$(
    "$PYTHON" - <<'PY'
from backend.common.config import Config
print(Config.get_uploads_dir())
PY
)
export PATHLAB_UPLOADS_DIR="$RESOLVED_UPLOADS_DIR"

# Set environment and start
export GATEWAY_PORT=6100
export PREPROCESSING_PORT=6101
export AI_PORT=6102
export DEFAULT_ADMIN_PASSWORD="${DEFAULT_ADMIN_PASSWORD:-admin}"

if [ -n "${CUDA_VISIBLE_DEVICES:-}" ]; then
    echo -e "  ${CYAN}[GPU]${NC} CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES}"
    if command -v nvidia-smi &> /dev/null; then
        available_raw=$(nvidia-smi --query-gpu=index --format=csv,noheader 2>/dev/null | tr '\n' ' ' | sed 's/ $//')
        echo -e "  ${CYAN}[GPU]${NC} Physical GPU indices: ${available_raw:-unknown}"
        invalid=""
        IFS=',' read -ra _configured_gpus <<< "$CUDA_VISIBLE_DEVICES"
        for _idx in "${_configured_gpus[@]}"; do
            _idx=$(echo "$_idx" | tr -d ' ')
            if ! echo " $available_raw " | grep -qE " $_idx "; then
                invalid="${invalid:+$invalid,}$_idx"
            fi
        done
        if [ -n "$invalid" ]; then
            echo -e "  ${YELLOW}[GPU][!]${NC} These GPU indices do not exist: ${invalid}"
        else
            echo -e "  ${GREEN}[GPU][✓]${NC} configuration valid"
        fi
    fi
else
    echo -e "  ${CYAN}[GPU]${NC} CUDA_VISIBLE_DEVICES not set, using all available GPUs"
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

echo -n "  Waiting for services"
for i in {1..50}; do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        break
    fi
    if health_ready && current_run_owns_ports "$BACKEND_PID"; then
        echo ""
        echo -e "${GREEN}[✓]${NC} Backend started (PID: $BACKEND_PID)"
        break
    fi
    echo -n "."
    sleep 1
done

if ! kill -0 "$BACKEND_PID" 2>/dev/null || ! health_ready || ! current_run_owns_ports "$BACKEND_PID"; then
    echo ""
    echo -e "${RED}[✗] Backend failed to start. See the log: $LOG_DIR/backend.log${NC}"
    exit 1
fi

# ========== Step 5: check nginx ==========
echo -e "${YELLOW}[5/5]${NC} Checking nginx..."

if systemctl is-active --quiet nginx 2>/dev/null; then
    echo -e "${GREEN}[✓]${NC} nginx is running"
else
    echo -e "${YELLOW}[!]${NC} nginx is not running; run: sudo systemctl start nginx"
fi

# ========== done ==========
echo ""
echo -e "${CYAN}╔════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║               Started                  ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${GREEN}Local URL:${NC}  http://127.0.0.1:6100"
echo -e "  ${GREEN}Python:${NC}    $PYTHON"
echo ""
echo -e "  ${YELLOW}Logs:${NC}  tail -f $LOG_DIR/backend.log"
echo -e "  ${YELLOW}Stop:${NC}  kill \$(cat $LOG_DIR/backend.pid)"
echo ""
