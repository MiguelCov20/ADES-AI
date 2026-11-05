# AGENTS.md — environment/ (Scripts de entorno)

Convenciones locales de los scripts. Completa al `AGENTS.md` raíz.

- **`setup_ollama.ps1`**: instala Ollama y los modelos locales. Importa qwen3.8 desde GGUF local (no `pull`). Los scripts `.ps1` se escriben en **ASCII puro** (Windows PowerShell 5.1 lee UTF-8 sin BOM como ANSI).
- **`benchmark_local.py`**: mide tokens/s de los modelos locales. Usa `num_ctx=8192` para que quepan en 16 GB de VRAM. Reconfigura stdout a UTF-8 (consola cp1252).
- **`scan_secrets.py`** + `pre-commit`: escáner de secretos (Fase 0). Antes de commitear, `python environment/scan_secrets.py`.
- GPU: **AMD Radeon RX 9070 XT (16 GB)** vía ROCm. No asumas NVIDIA/CUDA.
- Discos/VRAM ajustados: no cargues dos modelos grandes a la vez.
