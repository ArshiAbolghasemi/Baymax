#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="medgemma-4b"
IMAGE="vllm/vllm-openai:latest"
PORT="${PORT:-8000}"
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
  -e VLLM_ENFORCE_STRICT_TOOL_CALLING=true \
  -v hf-cache:/root/.cache/huggingface \
  -v "$(pwd)/tool_chat_template_medgemma.jinja:/templates/tool_chat_template_medgemma.jinja:ro" \
  "$IMAGE" \
  --model=google/medgemma-4b-it \
  --served-model-name=medgemma-4b \
  --dtype=bfloat16 \
  --max-model-len=32768 \
  --gpu-memory-utilization=0.60 \
  --max-num-seqs=64 \
  --enable-auto-tool-choice \
  --tool-call-parser=hermes \
  --chat-template=/templates/tool_chat_template_medgemma.jinja \
  --host=0.0.0.0 \
  --port=8000

echo "MedGemma 4B started on GPU ${GPU}, port ${PORT}"
echo "Logs: docker logs -f ${CONTAINER_NAME}"
