#!/usr/bin/env python3
"""Benchmark de velocidad (tok/s) de los modelos locales de ADES-AI (Fase 1).

Compara gpt-oss:20b vs qwen3.8:27b en una tarea de codificación.
Usa el endpoint nativo /api/generate de Ollama, que devuelve eval_count y
eval_duration para calcular tokens/segundo de generación.

Uso:
    python environment/benchmark_local.py [modelo1] [modelo2] ...
    (por defecto: gpt-oss:20b qwen3.8:27b)
"""
import json
import sys
import time
import urllib.request

# Forzar UTF-8 en la consola de Windows (evita UnicodeEncodeError al imprimir codigo)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OLLAMA = "http://localhost:11434"

CODING_PROMPT = (
    "Escribe una función en Python llamada `fibonacci(n)` que calcule el "
    "n-ésimo número de Fibonacci usando memoización, con docstring y un "
    "bloque `if __name__ == '__main__':` de ejemplo. Devuelve solo el código."
)


def generate(model: str, prompt: str, timeout: int = 900) -> dict:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        # num_ctx acotado para que el modelo + KV cache quepan en 16 GB de VRAM
        "options": {"temperature": 0.2, "num_ctx": 8192},
    }
    req = urllib.request.Request(
        OLLAMA + "/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def bench(model: str) -> dict:
    print(f"\n>>> Benchmarking {model} (codificacion)...", flush=True)
    t0 = time.time()
    r = generate(model, CODING_PROMPT)
    wall = time.time() - t0

    eval_count = r.get("eval_count", 0)
    eval_dur = r.get("eval_duration", 0)            # nanosegundos
    prompt_count = r.get("prompt_eval_count", 0)
    prompt_dur = r.get("prompt_eval_duration", 0)   # nanosegundos

    tok_s = eval_count / (eval_dur / 1e9) if eval_dur else 0.0
    prompt_tok_s = prompt_count / (prompt_dur / 1e9) if prompt_dur else 0.0

    sample = r.get("response", "").strip()
    return {
        "model": model,
        "tokens": eval_count,
        "eval_dur_s": round(eval_dur / 1e9, 2),
        "tok_s": round(tok_s, 1),
        "prompt_tok_s": round(prompt_tok_s, 1),
        "wall_s": round(wall, 1),
        "sample": sample[:120].replace("\n", " | "),
    }


def main() -> int:
    models = sys.argv[1:] or ["gpt-oss:20b", "qwen3.8:27b-iq3"]
    results = []
    for m in models:
        try:
            results.append(bench(m))
        except Exception as e:
            print(f"  [ERROR] {m}: {type(e).__name__}: {str(e)[:200]}", flush=True)

    print("\n" + "=" * 72)
    print(f"{'MODELO':18s} {'TOKENS':>7s} {'TOK/S':>8s} {'WALL(s)':>8s} {'PROMPT TOK/S':>12s}")
    print("-" * 72)
    for r in results:
        print(f"{r['model']:18s} {r['tokens']:>7d} {r['tok_s']:>8.1f} "
              f"{r['wall_s']:>8.1f} {r['prompt_tok_s']:>12.1f}")
    print("=" * 72)

    if len(results) == 2:
        a, b = results
        faster = a if a["tok_s"] >= b["tok_s"] else b
        slower = b if faster is a else a
        print(f"\nMas rapido: {faster['model']} ({faster['tok_s']} tok/s) "
              f"vs {slower['model']} ({slower['tok_s']} tok/s)")

    print("\nMuestras de salida:")
    for r in results:
        print(f"  [{r['model']}] {r['sample']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
