"""vLLM multi-model serving (feature #30).

Dos piezas:

1. `generate_config(...)`: genera en `environment/vllm/` un docker-compose con un
   servicio vLLM por modelo (imagen `rocm/vllm` para AMD/ROCm o `vllm/vllm-openai`
   para NVIDIA/CUDA) + un servicio `router` que expone un único endpoint
   OpenAI-compatible y reparte las peticiones con `ModelPool`.
   vLLM requiere Linux: en la máquina de desarrollo (Windows + AMD) NO se puede
   ejecutar; la configuración generada no está verificada en ejecución.

2. `ModelPool`: enrutador OpenAI-compatible por modelo y por carga:
   - cola por modelo (peticiones esperando un hueco),
   - límite de concurrencia por backend,
   - métrica de peticiones en vuelo (actual y pico), latencias y errores,
   - failover a otro backend del mismo modelo si uno falla.
   Funciona igual contra vLLM que contra Ollama (`http://localhost:11434/v1`).

Este módulo usa SOLO la librería estándar para que el contenedor `router` pueda
ejecutarlo montando únicamente este archivo:
    python model_serving.py serve --config models.json --port 8080
"""
import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VLLM_DIR = Path(__file__).resolve().parent.parent / "environment" / "vllm"
OLLAMA_OPENAI = "http://localhost:11434/v1"


class PoolError(RuntimeError):
    pass


@dataclass
class Backend:
    """Un servidor OpenAI-compatible (vLLM u Ollama) que sirve uno o varios modelos.

    `models`: {nombre_lógico: nombre_remoto}. Una lista se convierte en identidad.
    """
    name: str
    base_url: str
    models: dict = field(default_factory=dict)
    max_concurrency: int = 4
    api_key: str = ""
    in_flight: int = 0
    peak_in_flight: int = 0
    served: int = 0
    errors: int = 0
    total_latency: float = 0.0
    healthy: bool = True

    def __post_init__(self):
        if isinstance(self.models, (list, tuple)):
            self.models = {m: m for m in self.models}
        self.base_url = self.base_url.rstrip("/")

    def serves(self, model: str) -> bool:
        return model in self.models

    def load(self) -> float:
        return self.in_flight / max(1, self.max_concurrency)


def _http_post(url: str, payload: dict, api_key: str, timeout: float) -> dict:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class ModelPool:
    """Pool de backends OpenAI-compatibles con enrutado por modelo y por carga."""

    def __init__(self, backends: list[Backend], *, timeout: float = 180.0,
                 queue_timeout: float = 300.0, transport=None):
        if not backends:
            raise ValueError("ModelPool necesita al menos un backend")
        self.backends = backends
        self.timeout = timeout
        self.queue_timeout = queue_timeout
        self.transport = transport or _http_post
        self._cond = threading.Condition()
        self.queued: dict[str, int] = {}
        self.peak_queued: dict[str, int] = {}
        self.latencies: dict[str, list[float]] = {}

    # ------------------------------------------------------------ construcción
    @classmethod
    def from_config(cls, cfg: dict | str | Path, **kw) -> "ModelPool":
        if not isinstance(cfg, dict):
            cfg = json.loads(Path(cfg).read_text(encoding="utf-8"))
        bks = [Backend(name=b["name"], base_url=b["base_url"], models=b["models"],
                       max_concurrency=int(b.get("max_concurrency", 4)),
                       api_key=b.get("api_key", "")) for b in cfg["backends"]]
        return cls(bks, timeout=float(cfg.get("timeout", kw.pop("timeout", 180))), **kw)

    @classmethod
    def ollama(cls, models: list[str], base_url: str = OLLAMA_OPENAI,
               max_concurrency: int = 2, replicas: int = 1, **kw) -> "ModelPool":
        """Pool contra Ollama (OpenAI-compatible). `replicas` crea N backends lógicos."""
        bks = [Backend(name=f"ollama-{i}", base_url=base_url, models=list(models),
                       max_concurrency=max_concurrency, api_key="ollama")
               for i in range(replicas)]
        return cls(bks, **kw)

    def models(self) -> list[str]:
        return sorted({m for b in self.backends for m in b.models})

    # --------------------------------------------------------------- enrutado
    def _acquire(self, model: str, exclude: set) -> Backend:
        deadline = time.time() + self.queue_timeout
        with self._cond:
            self.queued[model] = self.queued.get(model, 0) + 1
            self.peak_queued[model] = max(self.peak_queued.get(model, 0), self.queued[model])
            try:
                while True:
                    cands = [b for b in self.backends if b.serves(model) and b.healthy
                             and b.name not in exclude]
                    if not cands:
                        raise PoolError(f"Ningún backend disponible sirve el modelo '{model}'")
                    free = [b for b in cands if b.in_flight < b.max_concurrency]
                    if free:
                        b = min(free, key=lambda x: (x.load(), x.served))
                        b.in_flight += 1
                        b.peak_in_flight = max(b.peak_in_flight, b.in_flight)
                        return b
                    left = deadline - time.time()
                    if left <= 0 or not self._cond.wait(timeout=left):
                        if time.time() >= deadline:
                            raise PoolError(f"Timeout en cola para '{model}'")
            finally:
                self.queued[model] -= 1

    def _release(self, b: Backend, latency: float, ok: bool, model: str) -> None:
        with self._cond:
            b.in_flight -= 1
            if ok:
                b.served += 1
                b.total_latency += latency
                self.latencies.setdefault(model, []).append(latency)
            else:
                b.errors += 1
            self._cond.notify_all()

    def chat(self, model: str, messages: list[dict], **params) -> dict:
        """POST /chat/completions al backend menos cargado que sirva `model`.

        Devuelve la respuesta OpenAI con un campo extra `_ades` (backend, latencia).
        """
        tried: set = set()
        last_err = None
        while True:
            try:
                b = self._acquire(model, tried)
            except PoolError:
                if last_err is not None:
                    raise PoolError(f"Todos los backends fallaron para '{model}': "
                                    f"{last_err}") from last_err
                raise
            t0 = time.time()
            payload = {"model": b.models[model], "messages": messages, **params}
            try:
                resp = self.transport(f"{b.base_url}/chat/completions", payload, b.api_key,
                                      self.timeout)
            except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
                self._release(b, time.time() - t0, False, model)
                tried.add(b.name)
                last_err = e
                continue
            lat = time.time() - t0
            self._release(b, lat, True, model)
            resp["_ades"] = {"backend": b.name, "latency": round(lat, 3)}
            return resp

    def stats(self) -> dict:
        with self._cond:
            bks = [{"name": b.name, "base_url": b.base_url, "models": list(b.models),
                    "in_flight": b.in_flight, "peak_in_flight": b.peak_in_flight,
                    "max_concurrency": b.max_concurrency, "served": b.served,
                    "errors": b.errors,
                    "avg_latency": round(b.total_latency / b.served, 3) if b.served else 0.0}
                   for b in self.backends]
            per_model = {}
            for m, lats in self.latencies.items():
                s = sorted(lats)
                per_model[m] = {"n": len(s), "avg": round(sum(s) / len(s), 3),
                                "p50": round(s[len(s) // 2], 3), "max": round(s[-1], 3),
                                "queued": self.queued.get(m, 0),
                                "peak_queued": self.peak_queued.get(m, 0)}
            return {"backends": bks, "models": per_model,
                    "in_flight": sum(b.in_flight for b in self.backends)}


# ------------------------------------------------------------------ router HTTP
def make_handler(pool: ModelPool):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: dict):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            if self.path.rstrip("/") == "/v1/models":
                self._send(200, {"object": "list", "data": [
                    {"id": m, "object": "model", "owned_by": "ades"} for m in pool.models()]})
            elif self.path.rstrip("/") in ("/stats", "/health"):
                self._send(200, pool.stats())
            else:
                self._send(404, {"error": "no encontrado"})

        def do_POST(self):  # noqa: N802
            if self.path.rstrip("/") != "/v1/chat/completions":
                return self._send(404, {"error": "no encontrado"})
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                if body.get("stream"):
                    return self._send(400, {"error": "stream no soportado por el router"})
                model = body.pop("model")
                messages = body.pop("messages")
                self._send(200, pool.chat(model, messages, **body))
            except PoolError as e:
                self._send(503, {"error": str(e)})
            except (KeyError, ValueError) as e:
                self._send(400, {"error": f"petición inválida: {e}"})

        def log_message(self, *a):  # silencio
            pass
    return Handler


def serve(pool: ModelPool, host: str = "0.0.0.0", port: int = 8080) -> ThreadingHTTPServer:
    """Crea el servidor HTTP del router (llama a `.serve_forever()` para atender)."""
    return ThreadingHTTPServer((host, port), make_handler(pool))


# ----------------------------------------------------------- generador de config
@dataclass
class ModelSpec:
    """Modelo a servir con vLLM. `name` = nombre lógico; `hf_id` = repo de Hugging Face."""
    name: str
    hf_id: str
    gpu_memory_utilization: float = 0.45
    max_model_len: int = 8192
    max_concurrency: int = 8
    extra_args: list = field(default_factory=list)


# Pesos HF equivalentes a los modelos Ollama del plan. Qwen3.8 27B se deja fuera
# por defecto: no cabe junto a gpt-oss-20b en 16 GB (regla de oro del plan §3.1).
DEFAULT_MODELS = [
    ModelSpec("gpt-oss:20b", "openai/gpt-oss-20b", gpu_memory_utilization=0.70),
    ModelSpec("llama3.2:3b", "meta-llama/Llama-3.2-3B-Instruct", gpu_memory_utilization=0.20,
              max_concurrency=16),
]


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")


def compose_yaml(models: list[ModelSpec], platform: str = "rocm",
                 router_port: int = 8080, base_port: int = 8001) -> str:
    """docker-compose (YAML escrito a mano, sin dependencias) para `platform` rocm|cuda."""
    if platform not in ("rocm", "cuda"):
        raise ValueError("platform debe ser 'rocm' o 'cuda'")
    image = "rocm/vllm:latest" if platform == "rocm" else "vllm/vllm-openai:latest"
    L = [f"# Generado por automation/model_serving.py ({platform}). NO verificado en ejecucion:",
         "# vLLM requiere Linux; la maquina de desarrollo (Windows + AMD) usa Ollama.",
         "# Uso (host Linux):  HF_TOKEN=... docker compose -f <este archivo> up -d",
         "# Router OpenAI-compatible en http://<host>:%d/v1" % router_port,
         "services:"]
    for i, m in enumerate(models):
        svc = f"vllm-{_slug(m.name)}"
        args = [m.hf_id, "--served-model-name", m.name, "--host", "0.0.0.0", "--port", "8000",
                "--gpu-memory-utilization", str(m.gpu_memory_utilization),
                "--max-model-len", str(m.max_model_len), *m.extra_args]
        L += [f"  {svc}:",
              f"    image: {image}",
              "    entrypoint: [\"vllm\", \"serve\"]",
              "    command: [" + ", ".join(json.dumps(a) for a in args) + "]",
              "    environment:",
              "      - HF_TOKEN=${HF_TOKEN:-}",
              "    volumes:",
              "      - hf-cache:/root/.cache/huggingface",
              f"    ports: [\"{base_port + i}:8000\"]",
              "    ipc: host",
              "    restart: unless-stopped"]
        if platform == "rocm":
            L += ["    devices: [\"/dev/kfd\", \"/dev/dri\"]",
                  "    group_add: [\"video\"]",
                  "    security_opt: [\"seccomp=unconfined\"]"]
        else:
            L += ["    deploy:",
                  "      resources:",
                  "        reservations:",
                  "          devices:",
                  "            - driver: nvidia",
                  "              count: all",
                  "              capabilities: [gpu]"]
    L += ["  router:",
          "    image: python:3.11-slim",
          "    command: [\"python\", \"/app/model_serving.py\", \"serve\", \"--config\", "
          "\"/config/models.json\", \"--port\", \"8080\"]",
          "    volumes:",
          "      - ../../automation/model_serving.py:/app/model_serving.py:ro",
          "      - ./models.json:/config/models.json:ro",
          f"    ports: [\"{router_port}:8080\"]",
          "    depends_on: [" + ", ".join(f"vllm-{_slug(m.name)}" for m in models) + "]",
          "    restart: unless-stopped",
          "volumes:",
          "  hf-cache: {}"]
    return "\n".join(L) + "\n"


def router_config(models: list[ModelSpec]) -> dict:
    """Config del ModelPool del router: un backend por servicio vLLM (red interna compose)."""
    return {"timeout": 180, "backends": [
        {"name": f"vllm-{_slug(m.name)}", "base_url": f"http://vllm-{_slug(m.name)}:8000/v1",
         "models": [m.name], "max_concurrency": m.max_concurrency} for m in models]}


def generate_config(models: list[ModelSpec] | None = None, out_dir: str | Path | None = None,
                    platforms: tuple = ("rocm", "cuda")) -> dict:
    """Escribe docker-compose.<platform>.yml y models.json en `out_dir`. Devuelve las rutas."""
    models = models or DEFAULT_MODELS
    total = sum(m.gpu_memory_utilization for m in models)
    if total > 0.95:
        raise ValueError(f"gpu_memory_utilization suma {total:.2f} > 0.95 en una sola GPU")
    out = Path(out_dir) if out_dir else VLLM_DIR
    out.mkdir(parents=True, exist_ok=True)
    paths = {}
    for p in platforms:
        f = out / f"docker-compose.{p}.yml"
        f.write_text(compose_yaml(models, p), encoding="utf-8")
        paths[p] = str(f)
    cfg = out / "models.json"
    cfg.write_text(json.dumps(router_config(models), indent=2), encoding="utf-8")
    paths["models.json"] = str(cfg)
    return paths


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Serving multi-modelo (vLLM/Ollama) - ADES-AI #30")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="router OpenAI-compatible sobre un ModelPool")
    s.add_argument("--config", default=None, help="models.json (si falta: Ollama local)")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8080)
    s.add_argument("--models", nargs="*", default=["llama3.2:3b"])
    g = sub.add_parser("generate", help="genera environment/vllm/*")
    g.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    if a.cmd == "generate":
        print(json.dumps(generate_config(out_dir=a.out), indent=2))
        return 0
    pool = ModelPool.from_config(a.config) if a.config else ModelPool.ollama(a.models)
    srv = serve(pool, a.host, a.port)
    print(f"Router ADES-AI en http://{a.host}:{a.port}/v1 (modelos: {pool.models()})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
