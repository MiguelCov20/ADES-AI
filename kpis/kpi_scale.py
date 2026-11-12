"""KPI 5 — Escalabilidad: N agentes concurrentes sin saturar la GPU.

Texto del plan: "fábrica sirve N agentes concurrentes vía vLLM + Bifrost sin
saturar GPU".

Método: N agentes lanzan peticiones a la vez a través de la pasarela
(`core.llm_gateway.chat`, que con ADES_GATEWAY=bifrost enruta todo por Bifrost con
virtual keys). Mezcla: agentes locales (gpt-oss:20b vía Ollama, concurrencia
acotada en Bifrost) y agentes de nube (deepseek-v4.1-flash / gemini-flash-lite).
Durante la carga se muestrea la GPU (Ollama /api/ps) cada segundo.

Criterios: 100% de peticiones correctas, sin offload a CPU, VRAM usada ≤ 16 GB y
nunca dos modelos grandes cargados a la vez.

LIMITACIÓN CONOCIDA: vLLM no puede ejecutarse en esta máquina (Windows + AMD
RX 9070 XT; vLLM requiere Linux con CUDA/ROCm). Esta prueba usa Ollama como
backend local. Por eso el KPI, tal como está redactado ("vía vLLM"), no puede
darse por cumplido aquí aunque la prueba pase.
"""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from agents.llm import gateway_enabled
from core import gpu_manager
from core.config import global_state_dir
from core.llm_gateway import chat


def run(n_local: int = 8, n_cloud: int = 4) -> dict:
    ts = time.strftime("%Y%m%d-%H%M%S")
    project = f"kpi5-{ts}"
    samples, stop = [], threading.Event()

    def sampler():
        while not stop.is_set():
            try:
                samples.append(gpu_manager.status())
            except Exception:
                pass
            time.sleep(1)

    def job(i: int, kind: str):
        t0 = time.time()
        p, m = (("ollama", "gpt-oss:20b") if kind == "local" else
                (("opencode", "deepseek-v4.1-flash") if i % 2 else ("gemini", "gemini-flash-lite-latest")))
        try:
            r = chat(f"agente-{kind}-{i}", "Responde en una sola frase.",
                     f"Agente {i}: resume en una frase que es una API REST (variante {i}).",
                     project=project, run_id=f"kpi5-{ts}-{i}", provider=p, model=m,
                     use_cache=False, effort="low")
            return {"i": i, "tipo": kind, "ok": bool(r.text.strip()), "modelo": f"{r.provider}/{r.model}",
                    "fallback": r.fallback_from, "latencia": round(time.time() - t0, 1)}
        except Exception as e:  # noqa: BLE001
            return {"i": i, "tipo": kind, "ok": False, "error": str(e)[:200],
                    "latencia": round(time.time() - t0, 1)}

    th = threading.Thread(target=sampler, daemon=True)
    th.start()
    t0 = time.time()
    jobs = [(i, "local") for i in range(n_local)] + [(n_local + i, "cloud") for i in range(n_cloud)]
    with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        results = list(ex.map(lambda a: job(*a), jobs))
    stop.set()
    th.join(timeout=3)
    wall = round(time.time() - t0, 1)

    max_used = max((s["used_gb"] for s in samples), default=0)
    offload = sorted({m for s in samples for m in s["cpu_offload"]})
    big_together = max((sum(1 for m in s["loaded"] if m["size_gb"] >= gpu_manager.BIG_MODEL_GB)
                        for s in samples), default=0)
    ok = sum(1 for r in results if r["ok"])
    res = {
        "fecha": ts, "gateway_bifrost": gateway_enabled(), "agentes": len(jobs),
        "ok": ok, "duracion_s": wall, "latencia_max_s": max(r["latencia"] for r in results),
        "vram_max_gb": max_used, "vram_total_gb": gpu_manager.VRAM_GB, "cpu_offload": offload,
        "max_modelos_grandes_simultaneos": big_together, "muestras_gpu": len(samples),
        "resultados": results, "vllm": "no ejecutable en Windows+AMD (no probado)",
    }
    res["prueba_ok"] = (ok == len(jobs) and not offload and max_used <= gpu_manager.VRAM_GB
                        and big_together <= 1 and res["gateway_bifrost"])
    res["kpi5_cumplido_segun_plan"] = False  # requiere vLLM, ver docstring
    d = global_state_dir() / "kpis"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"kpi5_{ts}.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    return res


def main(argv=None) -> int:
    r = run()
    print(json.dumps({k: v for k, v in r.items() if k != "resultados"}, indent=2, ensure_ascii=False))
    return 0 if r["prueba_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
