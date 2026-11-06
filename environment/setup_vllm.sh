#!/usr/bin/env bash
# ============================================================
#  ADES-AI - setup_vllm.sh (Fase 9 - Escalado de inferencia)
#
#  Sirve un modelo local (gpt-oss:20b / Qwen3.8 27B) con vLLM para
#  atender a MUCHOS agentes concurrentes (10-24x mas throughput que
#  Ollama gracias a PagedAttention).
#
#  REQUISITOS:
#    - Linux. vLLM NO soporta Windows de forma estable.
#    - GPU NVIDIA (CUDA) o AMD (ROCm) en el host Linux.
#
#  NOTA (ADES-AI): en la maquina de desarrollo (Windows + AMD RX 9070 XT)
#  se sigue usando Ollama via ROCm (Fase 1). Este script se usa cuando la
#  fabrica se despliegue en un host Linux y exija concurrencia.
#
#  Uso:
#    bash environment/setup_vllm.sh [modelo] [puerto]
# ============================================================

set -euo pipefail

MODEL="${1:-gpt-oss:20b}"
PORT="${2:-8000}"

echo "==> Instalando vLLM..."
pip install vllm

echo "==> Sirviendo el modelo '$MODEL' en el puerto $PORT (endpoint OpenAI-compatible)..."
vllm serve "$MODEL" --host 0.0.0.0 --port "$PORT"

# Los agentes apuntan su base_url a http://<host>:$PORT/v1
# (mismo patron que Ollama, ver agents/llm.py).
