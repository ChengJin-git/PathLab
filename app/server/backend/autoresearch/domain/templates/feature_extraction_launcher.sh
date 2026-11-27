#!/usr/bin/env bash
set -euo pipefail

: "${WSI_DIR:=/data/raw/WSIs}"
: "${OUTPUT_DIR:=/results}"
: "${DATA_OUTPUT_DIR:=$OUTPUT_DIR}"
: "${AUTORESEARCH_FEATURE_EXTRACTOR:=uni2}"
: "${AUTORESEARCH_FEATURE_BATCH_SIZE:=64}"
: "${AUTORESEARCH_FEATURE_MIN_FREE_MB:=0}"
: "${PYTHON_BIN:=python3}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_COMMON_PARENT=""
for candidate in "$SCRIPT_DIR"; do
  if [ -d "$candidate/common" ]; then
    TEMPLATE_COMMON_PARENT="$candidate"
    break
  fi
done
if [ -n "$TEMPLATE_COMMON_PARENT" ]; then
  export PYTHONPATH="$TEMPLATE_COMMON_PARENT:${PYTHONPATH:-}"
fi

if [ ! -d "$WSI_DIR" ] && [ "$WSI_DIR" = "/data/raw/WSIs" ] && [ -d /data/WSIs ]; then
  WSI_DIR=/data/WSIs
fi
if [ ! -d "$WSI_DIR" ] && [ "$WSI_DIR" = "/data/raw/WSIs" ] && [ -d /data/wsi_files ]; then
  WSI_DIR=/data/wsi_files
fi
if [ -d "$DATA_OUTPUT_DIR/wsi_files" ]; then
  export AUTORESEARCH_PATHLAB_UPLOADS_LAYOUT=1
fi

mkdir -p "$OUTPUT_DIR/logs" "$OUTPUT_DIR/worker_meta"
if [ "${AUTORESEARCH_PATHLAB_UPLOADS_LAYOUT:-}" = "1" ]; then
  mkdir -p "$DATA_OUTPUT_DIR/coordinates" "$DATA_OUTPUT_DIR/features/$AUTORESEARCH_FEATURE_EXTRACTOR"
else
  mkdir -p "$DATA_OUTPUT_DIR/patches" "$DATA_OUTPUT_DIR/pt_files/$AUTORESEARCH_FEATURE_EXTRACTOR"
fi

# Default to a single worker. Multi-GPU extraction is opt-in via
# AUTORESEARCH_FEATURE_GPUS=all or a comma/space separated GPU list.
if [ -n "${AUTORESEARCH_FEATURE_GPUS:-}" ]; then
  GPU_SOURCE="$AUTORESEARCH_FEATURE_GPUS"
else
  VISIBLE_GPUS_SOURCE="${CUDA_VISIBLE_DEVICES:-0}"
  if [ "$VISIBLE_GPUS_SOURCE" = "all" ]; then
    GPU_SOURCE="0"
  else
    VISIBLE_GPUS_SOURCE="${VISIBLE_GPUS_SOURCE//,/ }"
    read -r -a VISIBLE_GPUS <<< "$VISIBLE_GPUS_SOURCE"
    GPU_SOURCE="${VISIBLE_GPUS[0]:-0}"
  fi
fi
if [ "$GPU_SOURCE" = "all" ] && command -v nvidia-smi >/dev/null 2>&1; then
  GPU_SOURCE="$(nvidia-smi --query-gpu=index --format=csv,noheader,nounits | tr '\n' ',' | sed 's/,$//')"
fi
GPU_SOURCE="${GPU_SOURCE//,/ }"
read -r -a ALL_GPUS <<< "$GPU_SOURCE"

select_gpus=()
for gpu in "${ALL_GPUS[@]}"; do
  if [ -z "$gpu" ]; then
    continue
  fi
  if command -v nvidia-smi >/dev/null 2>&1 && [ "$AUTORESEARCH_FEATURE_MIN_FREE_MB" -gt 0 ]; then
    free_mb=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits -i "$gpu" | awk '{print $1}')
    if [ "$free_mb" -lt "$AUTORESEARCH_FEATURE_MIN_FREE_MB" ]; then
      echo "skip gpu=$gpu free_mb=$free_mb threshold=$AUTORESEARCH_FEATURE_MIN_FREE_MB"
      continue
    fi
  fi
  select_gpus+=("$gpu")
done

if [ "${#select_gpus[@]}" -eq 0 ]; then
  echo "No usable GPU found from GPU_SOURCE=$GPU_SOURCE" >&2
  exit 2
fi

WORLD_SIZE="${#select_gpus[@]}"
echo "feature_extraction launcher: world_size=$WORLD_SIZE gpus=${select_gpus[*]}"
echo "WSI_DIR=$WSI_DIR"
echo "DATA_OUTPUT_DIR=$DATA_OUTPUT_DIR"
echo "EXTRACTOR=$AUTORESEARCH_FEATURE_EXTRACTOR"
# feature_extraction_aggregate.py writes OUTPUT_DIR/metrics.json.

pids=()
cleanup() {
  for pid in "${pids[@]:-}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT INT TERM

status=0
for rank in "${!select_gpus[@]}"; do
  gpu="${select_gpus[$rank]}"
  log_file="$OUTPUT_DIR/logs/feature_worker_${rank}.log"
  (
    export CUDA_VISIBLE_DEVICES="$gpu"
    export AUTORESEARCH_WORKER_RANK="$rank"
    export AUTORESEARCH_WORLD_SIZE="$WORLD_SIZE"
    export AUTORESEARCH_FEATURE_EXTRACTOR
    export AUTORESEARCH_FEATURE_BATCH_SIZE
    "$PYTHON_BIN" feature_extraction_worker.py \
      --rank "$rank" \
      --world-size "$WORLD_SIZE" \
      --wsi-dir "$WSI_DIR" \
      --output-dir "$OUTPUT_DIR" \
      --data-output-dir "$DATA_OUTPUT_DIR" \
      --extractor "$AUTORESEARCH_FEATURE_EXTRACTOR" \
      --batch-size "$AUTORESEARCH_FEATURE_BATCH_SIZE"
  ) > "$log_file" 2>&1 &
  pid=$!
  pids+=("$pid")
  echo "started rank=$rank gpu=$gpu pid=$pid log=$log_file"
done

for pid in "${pids[@]}"; do
  if ! wait "$pid"; then
    status=1
  fi
done

trap - EXIT INT TERM
set +e
"$PYTHON_BIN" feature_extraction_aggregate.py \
  --output-dir "$OUTPUT_DIR" \
  --data-output-dir "$DATA_OUTPUT_DIR" \
  --extractor "$AUTORESEARCH_FEATURE_EXTRACTOR" \
  --world-size "$WORLD_SIZE"
aggregate_status=$?
set -e

if [ "$status" -ne 0 ]; then
  exit "$status"
fi
exit $aggregate_status
