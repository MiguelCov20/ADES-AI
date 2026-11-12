"""GPU Memory Manager (feature #29).

Aplica la "regla de oro 16GB" del plan: nunca dos modelos grandes a la vez.
Antes de usar un modelo local consulta qué hay cargado en Ollama (/api/ps) y
descarga (keep_alive=0) los modelos grandes que no se van a usar, para que el
nuevo quepa 100% en VRAM sin offload a CPU.
"""
import json
import os
import threading
import urllib.request

from core.config import OLLAMA_URL

VRAM_GB = float(os.getenv("ADES_VRAM_GB", "16"))
BIG_MODEL_GB = 6.0  # a partir de aquí se considera "modelo grande"
_LOCK = threading.Lock()


def _post(path: str, payload: dict, timeout: float = 60) -> dict:
    req = urllib.request.Request(OLLAMA_URL + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode() or "{}"
        return json.loads(body.splitlines()[-1]) if body.strip() else {}


def loaded_models() -> list[dict]:
    """Modelos cargados: [{name, size_gb, vram_gb}]."""
    with urllib.request.urlopen(OLLAMA_URL + "/api/ps", timeout=10) as r:
        data = json.loads(r.read().decode())
    return [{"name": m["name"], "size_gb": round(m.get("size", 0) / 1e9, 2),
             "vram_gb": round(m.get("size_vram", 0) / 1e9, 2)} for m in data.get("models", [])]


def installed_sizes() -> dict[str, float]:
    with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=10) as r:
        data = json.loads(r.read().decode())
    return {m["name"]: m.get("size", 0) / 1e9 for m in data.get("models", [])}


def unload(model: str) -> None:
    _post("/api/generate", {"model": model, "keep_alive": 0}, timeout=30)


def plan_for(model: str, loaded: list[dict], sizes: dict[str, float]) -> list[str]:
    """Devuelve qué modelos descargar antes de usar `model` (lógica pura, testeable)."""
    need = sizes.get(model, sizes.get(f"{model}:latest", 0.0))
    others = [m for m in loaded if m["name"] not in (model, f"{model}:latest")]
    to_unload = []
    if need >= BIG_MODEL_GB:
        to_unload += [m["name"] for m in others if m["size_gb"] >= BIG_MODEL_GB]
    used = sum(m["size_gb"] for m in others if m["name"] not in to_unload)
    # si aún no cabe, descargar lo que quede (de mayor a menor)
    for m in sorted(others, key=lambda m: -m["size_gb"]):
        if used + need <= VRAM_GB * 0.95:
            break
        if m["name"] not in to_unload:
            to_unload.append(m["name"])
            used -= m["size_gb"]
    return to_unload


def ensure_fits(model: str) -> list[str]:
    """Descarga lo necesario para que `model` quepa en VRAM. Devuelve lo descargado."""
    with _LOCK:
        try:
            loaded, sizes = loaded_models(), installed_sizes()
        except Exception:
            return []
        victims = plan_for(model, loaded, sizes)
        for v in victims:
            try:
                unload(v)
            except Exception:
                pass
        return victims


def vram_windows() -> dict:
    """VRAM dedicada real de la GPU según los contadores de Windows (cualquier proceso:
    Ollama, llama-server, juegos...). {"used_gb", "por_pid": {pid: gb}}. Solo Windows."""
    import subprocess
    ps = ("$a=(Get-Counter '\\GPU Adapter Memory(*)\\Dedicated Usage').CounterSamples|"
          "sort CookedValue -desc|select -First 1;"
          "$p=(Get-Counter '\\GPU Process Memory(*)\\Dedicated Usage').CounterSamples|"
          "?{$_.CookedValue -gt 50MB}|%{@{i=$_.InstanceName;v=$_.CookedValue}};"
          "@{used=$a.CookedValue;procs=@($p)}|ConvertTo-Json -Compress -Depth 3")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                         text=True, timeout=30).stdout
    data = json.loads(out)
    por_pid = {}
    for p in data.get("procs") or []:
        pid = p["i"].split("_")[1]
        por_pid[pid] = round(por_pid.get(pid, 0) + p["v"] / 1e9, 2)
    return {"used_gb": round(data["used"] / 1e9, 2), "por_pid": por_pid}


def status() -> dict:
    loaded = loaded_models()
    return {"vram_gb": VRAM_GB, "loaded": loaded,
            "used_gb": round(sum(m["vram_gb"] for m in loaded), 2),
            "cpu_offload": [m["name"] for m in loaded if m["vram_gb"] + 0.05 < m["size_gb"]]}
