"""KPI 5 — Escalabilidad: N agentes concurrentes sin saturar la GPU.

Texto original del plan: "fábrica sirve N agentes concurrentes vía vLLM + Bifrost sin
saturar GPU". En Linux la herramienta indicada es vLLM (`environment/vllm/`). En esta
máquina (Windows 11 + AMD RX 9070 XT, gfx1201) vLLM no corre de forma nativa, así que
el KPI se mide con la mejor alternativa nativa: **llama.cpp `llama-server`** (batching
continuo + slots paralelos + KV unificada, ROCm/HIP o Vulkan), detrás de **Bifrost**
(registrado como proveedor `vllm`, OpenAI-compatible).

Método: N agentes lanzan a la vez una tarea de generación al modelo de código
(gpt-oss:20b) a través de la pasarela -> Bifrost -> backend local. Se ejecuta la MISMA
carga contra Ollama (referencia) y contra llama-server, y se mide:

  - éxito de todas las peticiones,
  - throughput agregado (tokens generados / tiempo de pared) y latencias p50/p95,
  - VRAM dedicada real (contadores de Windows, cualquier proceso) muestreada cada 1 s,
  - capas en GPU (sin offload a CPU) según el log de llama-server.

Criterio de cumplimiento (backend llama.cpp): 100% OK con N ≥ 8 agentes concurrentes,
VRAM pico < 16 GB, todas las capas en GPU, peticiones realmente en paralelo (slots
ocupados > 1) y throughput agregado mayor que la referencia Ollama.

Uso:
    python -m kpis.kpi_scale [--agents 12] [--backend rocm|vulkan] [--solo llamacpp|ollama]
"""
import argparse
import json
import os
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from core import gpu_manager, local_serving
from core.config import global_state_dir

PROMPT = ("Agente {i}: escribe en Python una funcion `es_primo(n)` eficiente con docstring y "
          "explica en dos frases su complejidad. Variante {i}.")


def _sampler(samples: list, stop: threading.Event):
    while not stop.is_set():
        try:
            samples.append(gpu_manager.vram_windows()["used_gb"])
        except Exception:
            pass
        time.sleep(1)


def run_load(local_backend: str, n: int, max_tokens: int = 384) -> dict:
    """Carga concurrente contra un backend local ('ollama' o 'llamacpp') vía Bifrost."""
    os.environ["ADES_LOCAL_BACKEND"] = local_backend
    from core.llm_gateway import chat
    ts = time.strftime("%Y%m%d-%H%M%S")
    project = f"kpi5-{local_backend}-{ts}"
    # Calentamiento: carga del modelo fuera de la medición
    t0 = time.time()
    chat("kpi5-warmup", "Responde breve.", "hola", project=project, provider="ollama",
         model="gpt-oss:20b", use_cache=False, effort="low")
    warm = round(time.time() - t0, 1)

    samples, stop = [], threading.Event()
    th = threading.Thread(target=_sampler, args=(samples, stop), daemon=True)
    th.start()
    peak_slots = {"v": 0}

    def slot_watch():
        while not stop.is_set():
            if local_backend == "llamacpp":
                m = local_serving.server_metrics("gpt-oss:20b")
                peak_slots["v"] = max(peak_slots["v"], int(m.get("requests_processing", 0)))
            time.sleep(0.5)
    sw = threading.Thread(target=slot_watch, daemon=True)
    sw.start()

    def job(i: int):
        t = time.time()
        try:
            r = chat(f"agente-{i}", "Eres un desarrollador Python conciso.", PROMPT.format(i=i),
                     project=project, run_id=f"{project}-{i}", provider="ollama",
                     model="gpt-oss:20b", use_cache=False, effort="low", max_tokens=max_tokens)
            return {"i": i, "ok": bool(r.text.strip()) and r.provider == "ollama",
                    "tokens_out": r.tokens_out, "latencia": round(time.time() - t, 2),
                    "modelo": f"{r.provider}/{r.model}", "fallback": r.fallback_from}
        except Exception as e:  # noqa: BLE001
            return {"i": i, "ok": False, "error": str(e)[:200], "latencia": round(time.time() - t, 2)}

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=n) as ex:
        results = list(ex.map(job, range(n)))
    wall = time.time() - t0
    offload = local_serving.offload_report("gpt-oss:20b") if local_backend == "llamacpp" else None
    stop.set()
    th.join(timeout=3)
    lat = sorted(r["latencia"] for r in results)
    tokens = sum(r.get("tokens_out", 0) for r in results)
    out = {
        "backend": local_backend, "agentes": n, "ok": sum(r["ok"] for r in results),
        "calentamiento_s": warm, "pared_s": round(wall, 1), "tokens_generados": tokens,
        "throughput_tok_s": round(tokens / wall, 1),
        "latencia_p50_s": round(statistics.median(lat), 1),
        "latencia_p95_s": round(lat[max(0, int(0.95 * len(lat)) - 1)], 1),
        "vram_pico_gb": max(samples) if samples else None,
        "resultados": results,
    }
    if local_backend == "llamacpp":
        out["slots_ocupados_pico"] = peak_slots["v"]
        out["offload"] = offload
        out["backend_gpu"] = local_serving.BACKEND
    return out


MAX_VRAM_LIBRE_GB = 3.0  # uso base del escritorio de Windows ≈ 1.3-1.9 GB


def gpu_libre() -> tuple[bool, float]:
    """Precondición: la GPU no debe estar ocupada por otro proceso (otra corrida, un pytest,
    un llama-server huérfano...). Si lo está, las cifras saldrían contaminadas."""
    used = gpu_manager.vram_windows()["used_gb"]
    return used <= MAX_VRAM_LIBRE_GB, used


def run(n: int = 12, solo: str | None = None) -> dict:
    from agents.llm import gateway_enabled
    local_serving.stop_all()
    libre, used = gpu_libre()
    if not libre:
        raise RuntimeError(f"GPU ocupada ({used} GB en uso antes de empezar): cierra otros "
                           "procesos (Get-Process llama-server, ollama ps) y repite.")
    ts = time.strftime("%Y%m%d-%H%M%S")
    res = {"fecha": ts, "gateway_bifrost": gateway_enabled(), "vram_total_gb": gpu_manager.VRAM_GB}
    if solo in (None, "ollama"):
        local_serving.stop_all()
        res["ollama"] = run_load("ollama", n)
    if solo in (None, "llamacpp"):
        # Ollama retiene el modelo unos minutos: se descarga para que llama.cpp parta de cero
        local_serving._free_ollama_vram()
        res["llamacpp"] = run_load("llamacpp", n)
        local_serving.stop_all()
    lc, ol = res.get("llamacpp"), res.get("ollama")
    if lc:
        capas = lc.get("offload") or {}
        res["criterios"] = {
            "todas_ok": lc["ok"] == n,
            "n_concurrentes>=8": n >= 8,
            "vram_pico<16GB": lc["vram_pico_gb"] is not None and lc["vram_pico_gb"] < gpu_manager.VRAM_GB,
            "modelo_entero_en_gpu": bool(capas.get("todo_en_gpu")),
            "paralelismo_real": lc.get("slots_ocupados_pico", 0) > 1,
            "via_bifrost": res["gateway_bifrost"],
        }
        if ol:
            res["criterios"]["throughput>ollama"] = lc["throughput_tok_s"] > ol["throughput_tok_s"]
            res["mejora_throughput_x"] = round(lc["throughput_tok_s"] / max(ol["throughput_tok_s"], 0.1), 2)
        res["kpi5"] = all(res["criterios"].values())
    d = global_state_dir() / "kpis"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"kpi5_{ts}.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agents", type=int, default=12)
    ap.add_argument("--backend", default=None, help="rocm | vulkan (llama.cpp)")
    ap.add_argument("--solo", default=None, choices=["llamacpp", "ollama"])
    a = ap.parse_args(argv)
    if a.backend:
        local_serving.BACKEND = a.backend
    r = run(a.agents, a.solo)

    def brief(x):
        return {k: v for k, v in x.items() if k != "resultados"} if isinstance(x, dict) else x
    print(json.dumps({k: brief(v) for k, v in r.items()}, indent=2, ensure_ascii=False))
    return 0 if r.get("kpi5") else 1


if __name__ == "__main__":
    raise SystemExit(main())
