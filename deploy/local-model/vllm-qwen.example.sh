#!/usr/bin/env bash
set -euo pipefail

# Example only. Run this on the DGX/local GPU host after installing vLLM.
# Pin the exact model revision used in production before go-live.

MODEL_NAME="${LOCAL_MODEL_NAME:-Qwen/Qwen3.6-35B-A3B}"
HOST="${VLLM_HOST:-0.0.0.0}"
PORT="${VLLM_PORT:-8000}"

python -m vllm.entrypoints.openai.api_server \
  --model "$MODEL_NAME" \
  --host "$HOST" \
  --port "$PORT" \
  --served-model-name "$MODEL_NAME" \
  --trust-remote-code
