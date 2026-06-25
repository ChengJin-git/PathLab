#!/bin/bash
# Build and verify the AutoResearch Apptainer sandbox image.
# Equivalent core command: apptainer build --fakeroot --force <image> <pathlab-sandbox.def>
# Verification uses: apptainer exec --nv <image> python -c ...
# Usage:
#   ./deploy/build-autoresearch-sandbox.sh
#   APPTAINER_TMPDIR=$HOME/.apptainer-tmp ./deploy/build-autoresearch-sandbox.sh
#   AUTORESEARCH_SANDBOX_IMAGE=/path/to/pathlab-sandbox.sif ./deploy/build-autoresearch-sandbox.sh
#   AUTORESEARCH_SANDBOX_VERIFY=0 ./deploy/build-autoresearch-sandbox.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SERVER_DIR="$PROJECT_DIR/server"
SANDBOX_DEF="${AUTORESEARCH_SANDBOX_DEF:-$SERVER_DIR/backend/autoresearch/runtime/containers/pathlab-sandbox.def}"
SANDBOX_IMAGE="${AUTORESEARCH_SANDBOX_IMAGE:-$PROJECT_DIR/.local/autoresearch/sandbox/pathlab-sandbox.sif}"
APPTAINER_BIN="${APPTAINER_BIN:-apptainer}"
VERIFY_SANDBOX="${AUTORESEARCH_SANDBOX_VERIFY:-1}"
USE_NV="${AUTORESEARCH_SANDBOX_USE_NV:-1}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

if ! command -v "$APPTAINER_BIN" > /dev/null 2>&1 && [ ! -x "$APPTAINER_BIN" ]; then
    echo -e "${RED}[✗]${NC} Apptainer not found: $APPTAINER_BIN"
    echo "    Install Apptainer or set APPTAINER_BIN=/absolute/path/to/apptainer"
    exit 1
fi

if [ ! -f "$SANDBOX_DEF" ]; then
    echo -e "${RED}[✗]${NC} Sandbox definition file not found: $SANDBOX_DEF"
    exit 1
fi

mkdir -p "$(dirname "$SANDBOX_IMAGE")"
if [ -n "${APPTAINER_TMPDIR:-}" ]; then
    mkdir -p "$APPTAINER_TMPDIR"
    export APPTAINER_TMPDIR
fi

echo -e "${CYAN}[AutoResearch sandbox]${NC} Building image"
echo "  definition: $SANDBOX_DEF"
echo "  output:     $SANDBOX_IMAGE"
echo "  apptainer:  $APPTAINER_BIN"
echo "  tmpdir:     ${APPTAINER_TMPDIR:-<apptainer default>}"

"$APPTAINER_BIN" build --fakeroot --force "$SANDBOX_IMAGE" "$SANDBOX_DEF"

if [ "$VERIFY_SANDBOX" = "0" ]; then
    echo -e "${YELLOW}[!]${NC} Verification skipped because AUTORESEARCH_SANDBOX_VERIFY=0"
    exit 0
fi

exec_args=(exec)
if [ "$USE_NV" != "0" ]; then
    exec_args+=(--nv)
fi

echo -e "${CYAN}[AutoResearch sandbox]${NC} Verifying image imports"
"$APPTAINER_BIN" "${exec_args[@]}" "$SANDBOX_IMAGE" python - <<'PY'
import importlib
import torch

mods = [
    "numpy", "PIL", "cv2", "openslide", "tifffile", "h5py", "pandas",
    "sklearn", "scipy", "tqdm", "timm", "transformers", "huggingface_hub",
    "safetensors", "einops", "torchmetrics", "omegaconf", "open_clip", "kaggle",
]
for mod in mods:
    importlib.import_module(mod)
print("torch", torch.__version__)
print("cuda_available", torch.cuda.is_available())
print("cuda_device_count", torch.cuda.device_count())
print("imports_ok")
PY

echo -e "${GREEN}[✓]${NC} AutoResearch sandbox image ready: $SANDBOX_IMAGE"
