"""Serving local con llama.cpp (alternativa a vLLM en Windows + AMD, KPI 5)."""
import pytest

from core import local_serving as ls


def test_build_args_batching_continuo(monkeypatch):
    monkeypatch.setattr(ls, "gguf_path", lambda m: "C:/blobs/gpt-oss.gguf")
    a = ls.build_args("gpt-oss:20b-ctx16k", backend="vulkan")
    assert a[0].endswith("vulkan\llama-server.exe") or a[0].endswith("vulkan/llama-server.exe")
    s = " ".join(a)
    for flag in ("--cont-batching", "--kv-unified", "-np 8", "-ngl 999", "--alias gpt-oss-20b",
                 "--port 8081", "--host 127.0.0.1"):
        assert flag in s
    assert a[a.index("-c") + 1] == "32768"  # bloque KV unificado compartido por los 8 slots
    assert a[a.index("--chat-template-file") + 1].endswith("gpt-oss.jinja")  # harmony
    assert "-n" in a  # tope anti-desbordes


def test_config_y_alias():
    assert ls.config_for("llama3.2:3b-ctx16k")["alias"] == "llama3.2-3b"
    assert ls.config_for("modelo-desconocido") is None
    assert ls.base_model("qwen3.8:27b-iq3-ctx16k") == "qwen3.8:27b-iq3"


def test_routing_llamacpp(monkeypatch):
    monkeypatch.setenv("ADES_LOCAL_BACKEND", "llamacpp")
    monkeypatch.setenv("ADES_GATEWAY", "bifrost")
    monkeypatch.setenv("BIFROST_VK_LOCAL", "vk")
    from agents.llm import get_llm
    assert get_llm("ollama", "gpt-oss:20b").model_name == "vllm/gpt-oss-20b"
    monkeypatch.setenv("ADES_GATEWAY", "direct")
    d = get_llm("ollama", "gpt-oss:20b")
    assert d.model_name == "gpt-oss-20b" and d.openai_api_base == "http://127.0.0.1:8081/v1"
    monkeypatch.setenv("ADES_LOCAL_BACKEND", "ollama")
    assert get_llm("ollama", "gpt-oss:20b").model_name == "gpt-oss:20b"


@pytest.mark.live
def test_gguf_de_ollama():
    from pathlib import Path
    p = Path(ls.gguf_path("llama3.2:3b"))
    assert p.exists() and p.read_bytes()[:4] == b"GGUF"


@pytest.mark.live
@pytest.mark.parametrize("backend", ["rocm", "vulkan"])
def test_llama_server_concurrente(backend):
    """llama-server atiende varias peticiones A LA VEZ (batching continuo) con todo en GPU."""
    import json
    import threading
    import time
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor

    if not ls.server_exe(backend).exists():
        pytest.skip("llama.cpp no instalado (environment/setup_llamacpp.ps1)")
    try:
        ls.start("llama3.2:3b", backend=backend)
        assert ls.offload_report("llama3.2:3b")["todo_en_gpu"]
        peak, stop = {"v": 0}, threading.Event()

        def watch():
            while not stop.is_set():
                peak["v"] = max(peak["v"], int(ls.server_metrics("llama3.2:3b").get(
                    "requests_processing", 0)))
                time.sleep(0.1)
        threading.Thread(target=watch, daemon=True).start()

        def req(i):
            body = json.dumps({"model": "llama3.2-3b", "max_tokens": 120, "messages": [
                {"role": "user", "content": f"Cuenta del 1 al 40 en palabras (variante {i})"}]})
            r = urllib.request.Request(ls.url("llama3.2:3b") + "/v1/chat/completions",
                                       data=body.encode(), headers={"Content-Type": "application/json"})
            return json.loads(urllib.request.urlopen(r, timeout=120).read())
        with ThreadPoolExecutor(4) as ex:
            out = list(ex.map(req, range(4)))
        stop.set()
        assert all(o["choices"][0]["message"]["content"] for o in out)
        assert peak["v"] >= 2  # más de un slot procesando a la vez
    finally:
        ls.stop_all()


def test_resolve_no_arranca_pequeno_con_grande_cargado(monkeypatch):
    monkeypatch.setattr(ls, "healthy", lambda m, timeout=2.0: ls.base_model(m) == "gpt-oss:20b")
    assert ls.resolve("llama3.2:3b") == "gpt-oss:20b"
    assert ls.resolve("qwen3.8:27b-iq3") == "qwen3.8:27b-iq3"  # grande pedido: se respeta
    monkeypatch.setattr(ls, "healthy", lambda m, timeout=2.0: False)
    assert ls.resolve("llama3.2:3b") == "llama3.2:3b"


def test_no_reinicia_si_el_proceso_vive(monkeypatch):
    class Vivo:
        pid = 1
        def poll(self):
            return None
    monkeypatch.setitem(ls._procs, "gpt-oss:20b", Vivo())
    monkeypatch.setattr(ls, "healthy", lambda m, timeout=8.0: False)  # /health lento bajo carga
    assert ls.start("gpt-oss:20b")["reused"] is True
    assert ls.resolve("llama3.2:3b") == "gpt-oss:20b"
    ls._procs.pop("gpt-oss:20b", None)


def test_muestreo_recomendado_gpt_oss(monkeypatch):
    monkeypatch.setenv("ADES_LOCAL_BACKEND", "llamacpp")
    monkeypatch.setenv("ADES_GATEWAY", "direct")
    from agents.llm import get_llm
    assert get_llm("ollama", "gpt-oss:20b", temperature=0.2).temperature == 1.0


def test_gguf_desde_directorio_configurado(tmp_path, monkeypatch):
    (tmp_path / "gpt-oss-20b.gguf").write_bytes(b"GGUF")
    monkeypatch.setattr(ls, "GGUF_DIR", tmp_path)
    assert ls.gguf_path("gpt-oss:20b") == str(tmp_path / "gpt-oss-20b.gguf")


def test_qwen36_moe_con_expertos_en_cpu(monkeypatch):
    monkeypatch.setattr(ls, "gguf_path", lambda m: "F:/IA/gguf/qwen36.gguf")
    a = ls.build_args("qwen3.6:35b-a3b")
    assert "--n-cpu-moe" in a and "--load-mode" in a
    assert a[a.index("--alias") + 1] == "qwen3.6-35b-a3b" and "8084" in a
