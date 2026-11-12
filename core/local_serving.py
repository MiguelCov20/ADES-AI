"""Serving local concurrente: llama.cpp `llama-server` (alternativa a vLLM en Windows + AMD).

Por qué llama.cpp y no vLLM en esta máquina
-------------------------------------------
- En **Linux** (ROCm/CUDA) la mejor opción es **vLLM** (PagedAttention, batching continuo,
  máximo throughput). `environment/vllm/` tiene su despliegue.
- En **Windows 11 + AMD RX 9070 XT (RDNA4, gfx1201)** vLLM no corre de forma nativa
  (solo forks experimentales o WSL2 con ROCm). La alternativa nativa más cercana es
  `llama-server` de llama.cpp: **batching continuo + N slots paralelos con caché KV
  unificada**, API OpenAI-compatible, backends **ROCm/HIP** y **Vulkan** con binarios
  oficiales para Windows. Un solo modelo cargado atiende a N agentes a la vez.
- Ollama también usa llama.cpp, pero expone menos control (slots, KV unificada,
  contexto por slot) y en las pruebas de este proyecto serializaba la carga.

Este módulo:
  - reutiliza los GGUF que ya descargó Ollama (sin volver a descargar pesos),
  - arranca/para un `llama-server` por modelo (puertos 8081+), aplicando la regla de
    16 GB (un solo modelo grande a la vez; libera antes la VRAM de Ollama),
  - expone `ensure(model)` para la pasarela y `status()` para el panel / KPI 5.

Binarios: `.ades/runtime/llamacpp/<build>/{rocm,vulkan}/llama-server.exe` (release
oficial ggml-org). Backend con ADES_LLAMACPP_BACKEND=rocm|vulkan.
"""
import json
import os
import re
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from core.config import OLLAMA_URL, ROOT, global_state_dir

BUILD = os.getenv("ADES_LLAMACPP_BUILD", "b12292")
RUNTIME = Path(os.getenv("ADES_LLAMACPP_DIR", ROOT / ".ades" / "runtime" / "llamacpp" / BUILD))
BACKEND = os.getenv("ADES_LLAMACPP_BACKEND", "rocm")
HOST = "127.0.0.1"
TEMPLATES = ROOT / "environment" / "llamacpp" / "templates"
MAX_PREDICT = int(os.getenv("ADES_LLAMACPP_MAX_PREDICT", "8192"))

# modelo (nombre Ollama) -> configuración del servidor
MODELS: dict[str, dict] = {
    # ctx_total: con --kv-unified es UN bloque de caché KV compartido por los slots (cada
    # petición puede usar hasta el total). 8 slots × 8192 reservaba 16.09 GB (al límite).
    # El GGUF de gpt-oss que trae Ollama NO incluye chat template (Ollama maneja el formato
    # "harmony" por su cuenta): sin la plantilla oficial, el razonamiento se mezcla con la
    # respuesta y las generaciones no terminan. Plantilla: llama.cpp models/templates (b12292).
    "gpt-oss:20b": {"alias": "gpt-oss-20b", "port": 8081, "parallel": 8, "ctx_total": 32768,
                    "big": True, "chat_template": "gpt-oss.jinja",
                    "template_kwargs": {"reasoning_effort": "medium"},
                    # Muestreo recomendado por OpenAI para gpt-oss (temp 1.0, top_p 1.0): con
                    # temperatura baja entraba en bucles de >10k tokens en llama.cpp.
                    "sampling": {"temperature": 1.0, "top_p": 1.0}},
    "qwen3.8:27b-iq3": {"alias": "qwen3.8-27b", "port": 8083, "parallel": 2,
                        "ctx_total": 8192, "big": True},
    "llama3.2:3b": {"alias": "llama3.2-3b", "port": 8082, "parallel": 4, "ctx_total": 16384,
                    "big": False},
}

_LOCK = threading.Lock()
_procs: dict[str, subprocess.Popen] = {}


def _cleanup_at_exit() -> None:
    # En Windows los hijos sobreviven al padre: sin esto, un llama-server huérfano
    # seguiría reteniendo ~14 GB de VRAM al terminar la CLI.
    for p in list(_procs.values()):
        try:
            p.terminate()
        except Exception:
            pass


import atexit  # noqa: E402

atexit.register(_cleanup_at_exit)


def enabled() -> bool:
    """¿Los modelos locales se sirven con llama.cpp? (ADES_LOCAL_BACKEND=llamacpp)."""
    return os.getenv("ADES_LOCAL_BACKEND", "ollama").lower() == "llamacpp"


def base_model(model: str) -> str:
    return re.sub(r"-ctx\d+k$", "", model)


def config_for(model: str) -> dict | None:
    return MODELS.get(base_model(model))


def server_exe(backend: str | None = None) -> Path:
    return RUNTIME / (backend or BACKEND) / "llama-server.exe"


def gguf_path(model: str) -> str:
    """Ruta del GGUF que Ollama ya tiene descargado (`ollama show --modelfile`)."""
    cache = global_state_dir() / "gguf_paths.json"
    data = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    m = base_model(model)
    if m in data and Path(data[m]).exists():
        return data[m]
    out = subprocess.run(["ollama", "show", "--modelfile", m], capture_output=True,
                         text=True, encoding="utf-8", errors="replace").stdout
    hit = re.search(r"^FROM (.+)$", out, re.M)
    if not hit or not Path(hit.group(1).strip()).exists():
        raise FileNotFoundError(f"No encuentro el GGUF de {m} en Ollama")
    data[m] = hit.group(1).strip()
    cache.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data[m]


def build_args(model: str, backend: str | None = None, parallel: int | None = None,
               ctx_total: int | None = None) -> list[str]:
    """Línea de comandos de llama-server (lógica pura, testeable)."""
    cfg = config_for(model)
    if cfg is None:
        raise KeyError(f"Modelo sin configuración de serving: {model}")
    n = parallel or cfg["parallel"]
    ctx = ctx_total or cfg["ctx_total"]  # bloque KV compartido por los n slots
    return [str(server_exe(backend)), "-m", gguf_path(model), "--alias", cfg["alias"],
            "--host", HOST, "--port", str(cfg["port"]),
            "-ngl", "999",              # todas las capas en la GPU (sin offload a CPU)
            "-c", str(ctx), "-np", str(n),
            "--cont-batching",          # batching continuo (como vLLM)
            "--kv-unified",             # caché KV compartida entre slots
            "-fa", "on", "--jinja", "--metrics", "--no-webui",
            "-n", str(MAX_PREDICT),     # tope duro de tokens por petición (anti-desbordes)
            *_template_args(cfg)]


def _template_args(cfg: dict) -> list[str]:
    out = []
    if cfg.get("chat_template"):
        out += ["--chat-template-file", str(TEMPLATES / cfg["chat_template"])]
    if cfg.get("template_kwargs"):
        out += ["--chat-template-kwargs", json.dumps(cfg["template_kwargs"])]
    return out


def server_env(backend: str | None = None) -> dict:
    """Entorno del proceso. El build ROCm de Windows ya no incluye hipBLAS/rocBLAS: se
    añaden desde `rocm-libs/` (copiadas del runtime ROCm 7.1 que trae Ollama, o del HIP SDK
    de AMD si está instalado)."""
    env = dict(os.environ)
    if (backend or BACKEND) == "rocm":
        libs = RUNTIME / "rocm-libs"
        sdk = os.getenv("HIP_PATH")
        extra = [str(libs)] + ([str(Path(sdk) / "bin")] if sdk else [])
        env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "")])
    return env


def running(model: str) -> bool:
    """¿Hay un servidor nuestro vivo para el modelo? (no depende de /health, que bajo
    carga puede tardar: antes un health check lento provocaba un reinicio en falso)."""
    p = _procs.get(base_model(model))
    return p is not None and p.poll() is None


def resolve(model: str) -> str:
    """Modelo que realmente atenderá la petición.

    En 16 GB no caben dos servidores a la vez (gpt-oss ocupa ~15 GB). Si piden un modelo
    pequeño y ya hay uno grande sano, se atiende con el grande en vez de arrancar otro
    servidor (antes llama3.2 y gpt-oss quedaban cargados juntos y la GPU desbordaba ~4 GB a
    la RAM, multiplicando la latencia)."""
    m = base_model(model)
    cfg = config_for(m)
    if cfg and not cfg["big"]:
        for other, ocfg in MODELS.items():
            if ocfg["big"] and other != m and (running(other) or healthy(other, 3.0)):
                return other
    return m


def url(model: str) -> str:
    return f"http://{HOST}:{config_for(model)['port']}"


def healthy(model: str, timeout: float = 8.0) -> bool:
    try:
        with urllib.request.urlopen(url(model) + "/health", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _free_ollama_vram() -> list[str]:
    """Descarga de Ollama todos los modelos (la VRAM pasa a llama.cpp)."""
    freed = []
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/ps", timeout=5) as r:
            loaded = [m["name"] for m in json.loads(r.read()).get("models", [])]
        for name in loaded:
            if name.startswith("nomic-embed"):
                continue  # embeddings pequeños: se quedan
            req = urllib.request.Request(OLLAMA_URL + "/api/generate",
                                         data=json.dumps({"model": name, "keep_alive": 0}).encode(),
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=30).read()
            freed.append(name)
    except Exception:
        pass
    return freed


def stop(model: str) -> bool:
    m = base_model(model)
    p = _procs.pop(m, None)
    if p is None:
        return False
    p.terminate()
    try:
        p.wait(timeout=20)
    except subprocess.TimeoutExpired:
        p.kill()
    return True


def stop_all() -> None:
    for m in list(_procs):
        stop(m)


def start(model: str, backend: str | None = None, parallel: int | None = None,
          ctx_total: int | None = None, timeout: float = 300) -> dict:
    """Arranca llama-server para `model` (si no está ya) respetando la regla de 16 GB."""
    m = base_model(model)
    with _LOCK:
        if running(m):
            return {"model": m, "url": url(m), "reused": True}
        if m not in _procs and healthy(m):
            # Servidor ya levantado por otro proceso (otra CLI, el worker del backlog...)
            return {"model": m, "url": url(m), "reused": True, "externo": True}
        cfg = config_for(m)
        # Un solo servidor en la GPU: al arrancar uno, se paran los demás (grandes y pequeños)
        for other in list(_procs):
            if other != m:
                stop(other)
        freed = _free_ollama_vram()
        exe = server_exe(backend)
        if not exe.exists():
            raise FileNotFoundError(f"No está {exe}. Ejecuta environment/setup_llamacpp.ps1")
        log = open(global_state_dir() / f"llama-server-{cfg['alias']}.log", "w", encoding="utf-8")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        p = subprocess.Popen(build_args(m, backend, parallel, ctx_total), stdout=log,
                             stderr=subprocess.STDOUT, creationflags=flags,
                             env=server_env(backend))
        _procs[m] = p
        t0 = time.time()
        while time.time() - t0 < timeout:
            if p.poll() is not None:
                raise RuntimeError(f"llama-server terminó (código {p.returncode}); ver {log.name}")
            if healthy(m):
                return {"model": m, "url": url(m), "reused": False, "ollama_liberado": freed,
                        "arranque_s": round(time.time() - t0, 1)}
            time.sleep(1)
        stop(m)
        raise TimeoutError(f"llama-server no respondió en {timeout}s")


def ensure(model: str) -> str:
    """Garantiza que el modelo (o el grande ya cargado, ver `resolve`) está servido."""
    m = resolve(model)
    start(m)
    return url(m) + "/v1"


def server_metrics(model: str) -> dict:
    """Métricas Prometheus de llama-server (slots ocupados, tokens/s...)."""
    try:
        with urllib.request.urlopen(url(model) + "/metrics", timeout=3) as r:
            text = r.read().decode()
    except Exception:
        return {}
    out = {}
    for line in text.splitlines():
        if line and not line.startswith("#"):
            k, _, v = line.partition(" ")
            try:
                out[k.replace("llamacpp:", "")] = float(v)
            except ValueError:
                pass
    return out


def offload_report(model: str) -> dict:
    """¿Está el modelo entero en la GPU? Compara la VRAM dedicada del proceso llama-server
    (contadores de Windows) con el tamaño del GGUF. Si hubiera offload a CPU, la VRAM del
    proceso quedaría claramente por debajo del tamaño de los pesos."""
    from core import gpu_manager
    p = _procs.get(base_model(model))
    if p is None or p.poll() is not None:
        return {}
    pesos_gb = round(Path(gguf_path(model)).stat().st_size / 1e9, 2)
    vram_gb = gpu_manager.vram_windows()["por_pid"].get(str(p.pid), 0.0)
    return {"pesos_gb": pesos_gb, "vram_proceso_gb": vram_gb,
            "todo_en_gpu": vram_gb >= pesos_gb * 0.95}


def status() -> dict:
    return {m: {"pid": p.pid, "vivo": p.poll() is None, "url": url(m), "healthy": healthy(m)}
            for m, p in _procs.items()}
