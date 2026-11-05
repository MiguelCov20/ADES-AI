---
name: Benchmark local
description: Mide la velocidad (tokens/s) de los modelos locales de Ollama para elegir el mejor por tarea
---

## Objetivo

Comparar la velocidad de codificación de los modelos locales (gpt-oss:20b,
qwen3.8:27b-iq3) para asignar cada tarea al modelo óptimo.

## Workflow

1. Ejecuta `python environment/benchmark_local.py [modelo1 modelo2 ...]`.
2. Por defecto compara `gpt-oss:20b` vs `qwen3.8:27b-iq3`.
3. El script usa `num_ctx=8192` para que los modelos quepan en 16 GB de VRAM.

## Notas

- La GPU es una AMD Radeon RX 9070 XT (16 GB) vía ROCm.
- gpt-oss:20b ~93 tok/s; qwen3.8:27b-iq3 ~27 tok/s (con *thinking*).
