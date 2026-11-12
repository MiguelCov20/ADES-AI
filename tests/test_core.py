"""Tests del núcleo: pasarela LLM (fallback/presupuesto/circuito), router, QA parser,
reclutador, integración de métricas y multi-proyecto."""
import pytest

from core import budget, llm_gateway, metrics_store, projects


# --- Bug 2: parser de QA -----------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("VEREDICTO: PASS\nEl codigo maneja errores correctamente.", "PASS"),
    ("PASS\nNo hay ERROR de sintaxis.", "PASS"),
    ("**VEREDICTO: PASS**\nIncluye manejo de error 404", "PASS"),
    ("VEREDICTO: FAIL\nfalta la ruta", "FAIL"),
    ("FAIL", "FAIL"),
    ("El codigo parece bien.", "FAIL"),  # ambiguo -> conservador
    ("", "FAIL"),
])
def test_qa_parser_primera_linea(text, expected):
    from agents.qa import _parse_veredicto
    assert _parse_veredicto(text) == expected


# --- Bug 7: reclutador alineado con el plan ----------------------------------
@pytest.mark.parametrize("rol,provider,model", [
    ("Ingeniero DevOps de docker y CI", "opencode", "deepseek-v4.1-flash"),
    ("Project Manager", "gemini", "auto"),
    ("Arquitecto de software", "gemini", "auto"),
    ("Developer backend FastAPI", "ollama", "gpt-oss:20b"),
    ("Agente UX/UI", "ollama", "qwen3.8:27b-iq3"),
    ("Revisor de seguridad", "opencode", "deepseek-v4-pro"),
    ("Explorador de codigo", "ollama", "llama3.2:3b"),
])
def test_reclutador_suggest_llm(rol, provider, model):
    from agents.reclutador import suggest_llm
    assert suggest_llm(rol) == {"provider": provider, "model": model}


def test_reclutador_create_update_delete(tmp_path, monkeypatch):
    import json
    from agents import reclutador, roster
    p = tmp_path / "roster.json"
    p.write_text(json.dumps({"agents": []}), encoding="utf-8")
    monkeypatch.setattr(roster, "ROSTER_PATH", p)
    a = reclutador.create_agent("Agente Datos", "analista de datos")
    assert a["llm"]["provider"] == "gemini"
    reclutador.update_agent("agente_datos", skills=["sql"])
    assert roster.get_agent("agente_datos")["skills"] == ["sql"]
    assert reclutador.delete_agent("agente_datos")


# --- Bug 5: sesión estable para prompt caching --------------------------------
def test_opencode_session_estable(monkeypatch):
    monkeypatch.setenv("ADES_GATEWAY", "direct")
    from agents.llm import get_llm
    a = get_llm("opencode", session_id="run-123")
    b = get_llm("opencode", session_id="run-123")
    assert a.default_headers["x-opencode-session"] == b.default_headers["x-opencode-session"]


def test_bifrost_routing_headers(monkeypatch):
    monkeypatch.setenv("ADES_GATEWAY", "bifrost")
    monkeypatch.setenv("BIFROST_VK_LOCAL", "vk-local")
    monkeypatch.setenv("BIFROST_VK_FACTORY", "vk-factory")
    from agents.llm import get_llm
    loc = get_llm("ollama", "gpt-oss:20b")
    assert loc.model_name == "ollama/gpt-oss:20b-ctx16k"
    assert loc.default_headers["x-bf-vk"] == "vk-local"
    cloud = get_llm("opencode", "deepseek-v4-pro", session_id="s1")
    assert cloud.model_name == "opencode-go/deepseek-v4-pro"
    assert cloud.default_headers["x-bf-vk"] == "vk-factory"
    assert cloud.default_headers["x-opencode-session"] == "s1"


# --- Feature #21: fallback en cascada (y bug 1: no colgarse) ----------------
def test_fallback_en_cascada(mock_llm):
    seen = []

    def fn(provider, model, messages):
        seen.append(f"{provider}:{model}")
        if provider == "gemini":
            raise RuntimeError("503 UNAVAILABLE")
        return ("respuesta", 10, 5)

    mock_llm(fn)
    r = llm_gateway.chat("pm", "sys", "hola", provider="gemini", model="gemini-flash-latest",
                         project="t-fallback")
    assert r.text == "respuesta"
    assert r.provider == "opencode" and r.model == "deepseek-v4.1-flash"
    assert r.fallback_from == "gemini:gemini-flash-latest"
    assert seen[:2] == ["gemini:gemini-flash-latest", "gemini:gemini-flash-lite-latest"]
    errs = metrics_store.query("SELECT COUNT(*) n FROM calls WHERE project='t-fallback' AND ok=0")
    assert errs[0]["n"] == 2


def test_todos_fallan(mock_llm):
    mock_llm(lambda p, m, msgs: (_ for _ in ()).throw(RuntimeError("caido")))
    with pytest.raises(llm_gateway.AllModelsFailed):
        llm_gateway.chat("x", "s", "u", provider="ollama", model="gpt-oss:20b", project="t-all")


def test_timeout_duro_pasa_al_siguiente(monkeypatch):
    """Una llamada de nube que no responde no cuelga la pasarela (bug observado: >6 min)."""
    import time as _t

    class Lento:
        def invoke(self, messages):
            _t.sleep(5)

    class Rapido:
        def invoke(self, messages):
            class R:
                content = "ok"
                usage_metadata = {"input_tokens": 1, "output_tokens": 1}
            return R()

    import agents.llm as llm_mod
    monkeypatch.setattr(llm_gateway, "LLM_TIMEOUT", 0.5)
    monkeypatch.setattr(llm_mod, "get_llm",
                        lambda p, m, **kw: Lento() if p == "gemini" else Rapido())
    t0 = _t.time()
    r = llm_gateway.chat("pm", "s", "u", provider="gemini", model="gemini-flash-latest",
                         project="t-timeout", use_cache=False)
    assert r.text == "ok" and r.provider == "opencode"
    assert _t.time() - t0 < 4


# --- Feature #10: Token Budget Governor --------------------------------------
def test_budget_governor_niveles(mock_llm):
    proj = "t-budget"
    budget.set_budget(proj, usd=0.001, paid_tokens=10_000_000)
    assert budget.status(proj)["tier"] == "any"
    metrics_store.record(proj, "r", "t", "a", "opencode", "deepseek-v4-pro", 100, 100, 0.0009)
    assert budget.status(proj)["tier"] == "cheap"
    metrics_store.record(proj, "r", "t", "a", "opencode", "deepseek-v4-pro", 100, 100, 0.0002)
    assert budget.status(proj)["tier"] == "local"
    seen = []
    mock_llm(lambda p, m, msgs: (seen.append((p, m)) or ("ok", 1, 1)))
    r = llm_gateway.chat("reviewer", "s", "u", provider="opencode", model="deepseek-v4-pro",
                         project=proj)
    assert r.provider == "ollama"  # presupuesto agotado -> solo local ($0)
    assert all(p == "ollama" for p, _ in seen)


def test_budget_allowed():
    assert budget.allowed("ollama", "gpt-oss:20b", "local")
    assert not budget.allowed("opencode", "deepseek-v4-pro", "cheap")
    assert budget.allowed("opencode", "deepseek-v4.1-flash", "cheap")


def test_circuit_breaker():
    for _ in range(2):
        metrics_store.record("t-cb", "r", "t", "a", "gemini", "gemini-cb-test", 0, 0, 0, ok=False)
    assert llm_gateway.circuit_open("gemini", "gemini-cb-test")
    assert not llm_gateway.circuit_open("gemini", "otro-modelo")


# --- Feature #20: Brain Selector ---------------------------------------------
def test_brain_selector_effort_y_cascada():
    from agents.router import route_task
    d = route_task("refactor de autenticacion con concurrencia", use_llm=False)
    assert d["complexity"] == "complex" and d["effort"] == "high"
    assert d["cascade"][0] == ("opencode", "deepseek-v4-pro")
    assert d["cascade"][-1][0] == "ollama"
    d = route_task("agregar docstring", use_llm=False)
    assert d["model"] == "llama3.2:3b" and d["effort"] == "low"
    d = route_task("refactor grande", use_llm=False, tier="local")
    assert d["provider"] == "ollama"


# --- Métricas / tracing ------------------------------------------------------
def test_metricas_y_trazas(mock_llm):
    from evals import tracing
    mock_llm(lambda p, m, msgs: ("hola", 12, 3))
    r = llm_gateway.chat("dev", "s", "u", provider="ollama", model="gpt-oss:20b",
                         project="t-metrics", run_id="run-metrics")
    s = metrics_store.summary(run_id="run-metrics")
    assert s["calls"] == 1 and s["tokens_in"] == 12 and s["cost"] == 0
    assert r.cost == 0
    assert tracing.load_traces()[-1]["agent"] == "dev"


# --- Feature #5: multi-proyecto ----------------------------------------------
def test_multiproyecto_aislado():
    a = projects.create("Tienda Online")
    b = projects.create("blog")
    assert a["id"] == "tienda-online" and b["id"] == "blog"
    from core.config import state_dir
    assert state_dir("tienda-online") != state_dir("blog")
    ids = {p["id"] for p in projects.list_projects()}
    assert {"ades-ai", "tienda-online", "blog"} <= ids
    assert projects.remove("blog") and not projects.remove("ades-ai")


# --- Feature #29: GPU Memory Manager -----------------------------------------
def test_gpu_manager_plan():
    from core.gpu_manager import plan_for
    sizes = {"gpt-oss:20b": 13.0, "qwen3.8:27b-iq3": 12.0, "llama3.2:3b": 2.0}
    loaded = [{"name": "qwen3.8:27b-iq3", "size_gb": 12.0, "vram_gb": 12.0},
              {"name": "llama3.2:3b", "size_gb": 2.0, "vram_gb": 2.0}]
    assert plan_for("gpt-oss:20b", loaded, sizes) == ["qwen3.8:27b-iq3"]
    assert plan_for("llama3.2:3b", loaded, sizes) == []
    assert plan_for("qwen3.8:27b-iq3", loaded, sizes) == []


# --- Caché semántico (bug 3 y bug del KPI 1) -- live: Redis + nomic-embed-text ----
@pytest.mark.live
def test_cache_semantico_no_confunde_tareas():
    from cache.semantic_cache import SemanticCache
    c = SemanticCache(namespace="test-discrimina")
    c.clear()
    c.add("como crear un endpoint ping en fastapi", "RESP_PING")
    assert c.lookup("como crear un endpoint ping en fastapi") == "RESP_PING"
    assert c.lookup("como crear un endpoint de login en django") is None
    assert c.lookup("cual es la capital de Francia?") is None
    c.clear()


@pytest.mark.live
def test_gateway_cache_contexto_largo_no_colisiona():
    """Con el MISMO contexto largo, dos preguntas distintas no deben compartir respuesta."""
    import uuid
    ctx = "Mapa del repositorio:\n" + "\n".join(f"modulo_{i}.py\n  def funcion_{i}(x)" for i in range(400))
    proj = f"t-cache-{uuid.uuid4().hex[:6]}"
    calls = []

    def fake(provider, model, messages):
        calls.append(messages[-1].content)
        return (f"respuesta a: {messages[-1].content}", 5, 5)

    llm_gateway._mock = None
    import core.llm_gateway as g
    orig = g._invoke
    g._invoke = lambda p, m, msgs, s, e, t: fake(p, m, msgs)
    try:
        a = g.chat("dev", "sys", "Escribe un test para budget.status", context=ctx, project=proj,
                   provider="ollama", model="gpt-oss:20b")
        b = g.chat("dev", "sys", "Explica como funciona backlog.work", context=ctx, project=proj,
                   provider="ollama", model="gpt-oss:20b")
        c = g.chat("dev", "sys", "Escribe un test para budget.status", context=ctx, project=proj,
                   provider="ollama", model="gpt-oss:20b")
        d = g.chat("dev", "sys", "Escribe un test para budget.status", context=ctx + "\nextra.py",
                   project=proj, provider="ollama", model="gpt-oss:20b")
    finally:
        g._invoke = orig
    assert not a.cache_hit and not b.cache_hit and b.text != a.text
    assert c.cache_hit and c.text == a.text      # repetición exacta -> caché
    assert not d.cache_hit                        # otro contexto -> no reutiliza
