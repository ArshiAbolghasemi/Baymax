#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="bge-m3"
IMAGE="vllm/vllm-openai:latest"
PORT="${PORT:-8001}"
GPU="${GPU:-0}"

# Remove an existing container with the same name
docker rm -f "$CONTAINER_NAME" 2>/dev/null || true

docker run -d \
  --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  --gpus "device=${GPU}" \
  --ipc=host \
  -p "${PORT}:8000" \
  --env-file ../../../.env \
  -e HF_HOME=/root/.cache/huggingface \
  -v hf-cache:/root/.cache/huggingface \
  "$IMAGE" \
  --model=BAAI/bge-m3 \
  --served-model-name=bge-m3 \
  --runner=pooling \
  --dtype=float16 \
  --max-model-len=8192 \
  --gpu-memory-utilization=0.15 \
  --max-num-seqs=256 \
  --host=0.0.0.0 \
  --port=8000

echo "BGE-M3 started on GPU ${GPU}, port ${PORT}"
echo "Logs: docker logs -f ${CONTAINER_NAME}"
