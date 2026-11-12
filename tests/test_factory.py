"""Tests de la fábrica: bucle Dev⇄QA, self-healing, anti-alucinación, sandbox,
backlog, bootstrapper, dashboard y CLI."""
import json

import pytest

from core import projects
from memory.validator import GraphIndex, validate_code, validate_files

GOOD = '''```python
# FILE: calc.py
def suma(a, b):
    return a + b
```
```python
# FILE: test_calc.py
from calc import suma


def test_suma():
    assert suma(2, 3) == 5
```'''
BAD = GOOD.replace("return a + b", "return a - b")


def _idx():
    idx = GraphIndex()
    idx.modules = {"cache": {"token_metrics"}, "cache.token_metrics": {"TokenMetrics", "COST_PER_1M"},
                   "agents": {"llm"}, "agents.llm": {"get_llm", "default_model"}}
    idx.class_methods = {"cache.token_metrics.TokenMetrics": {"record", "report", "hit_rate"}}
    return idx


# --- KPI 4: validador anti-alucinación ---------------------------------------
def test_validator_detecta_alucinaciones():
    code = ("from cache.token_metrics import TokenMetrics, TokenBudget\n"
            "from agents.inexistente import algo\n"
            "import agents.llm as L\n"
            "m = TokenMetrics()\nm.record('a','b',1,1)\nm2 = TokenMetrics().guardar()\n"
            "L.get_llm('ollama')\nL.crear_llm()\n")
    refs = {f.ref for f in validate_code(code, _idx())}
    assert "cache.token_metrics.TokenBudget" in refs
    assert "agents.inexistente" in refs
    assert "cache.token_metrics.TokenMetrics.guardar" in refs
    assert "agents.llm.crear_llm" in refs
    assert "cache.token_metrics.TokenMetrics.record" not in refs
    assert "agents.llm.get_llm" not in refs


def test_validator_ignora_terceros_y_locales():
    code = "import os\nfrom fastapi import FastAPI\nfrom calc import suma\n"
    assert validate_files({"main.py": code, "calc.py": "def suma(): pass"}, _idx()) == {
        "main.py": [], "calc.py": []}


def test_validator_codigo_valido():
    code = "from cache.token_metrics import TokenMetrics\nTokenMetrics().hit_rate()\n"
    assert validate_code(code, _idx()) == []


# --- extracción de archivos ----------------------------------------------------
def test_extract_files_formatos():
    from core.sandbox import extract_files
    assert set(extract_files(GOOD)) == {"calc.py", "test_calc.py"}
    t = "FILE: app.py\n```python\nx = 1\n```"
    assert extract_files(t) == {"app.py": "x = 1\n"}
    evil = "```python\n# FILE: ../../etc/x.py\nprint(1)\n```"
    assert "../../etc/x.py" not in extract_files(evil)


# --- Feature #4: estrategias de self-healing --------------------------------
def test_estrategias_self_healing():
    from agents.developer import strategy_for
    names = [strategy_for(i)["name"] for i in range(6)]
    assert names == ["base", "contexto", "local-alt", "modelo", "pesado", "pesado"]
    assert strategy_for(2)["model"] == ("ollama", "qwen3.8:27b-iq3")
    assert strategy_for(3)["model"][0] == "opencode"


def test_self_healing_solo_local(monkeypatch):
    from agents.developer import strategy_for
    monkeypatch.setenv("ADES_SELF_HEAL_CLOUD", "0")
    assert all(not strategy_for(i)["model"] or strategy_for(i)["model"][0] == "ollama"
               for i in range(6))


def _mock_factory(mock_llm, dev_outputs):
    calls = {"dev": 0, "models": []}

    def fn(provider, model, messages):
        system = messages[0].content
        calls["models"].append((provider, model))
        if "Project Manager" in system:
            return (json.dumps({"prd": "suma", "tickets": [
                {"titulo": "suma", "descripcion": "suma(a,b)", "criterios": ["suma(2,3)==5"]}]}), 5, 5)
        if system.startswith("Eres el Developer"):
            out = dev_outputs[min(calls["dev"], len(dev_outputs) - 1)]
            calls["dev"] += 1
            return (out, 50, 50)
        if "pytest de ACEPTACION" in system:
            return ("```python\nfrom calc import suma\n\ndef test_acc():\n    assert suma(1, 1) == 2\n```", 5, 5)
        if "QA Tester" in system:
            return ("VEREDICTO: PASS\nCumple.", 5, 5)
        return ("ok", 5, 5)

    mock_llm(fn)
    return calls


# --- KPI 3: bucle cerrado Dev⇄QA (sandbox real) -------------------------------
@pytest.mark.live
def test_bucle_dev_qa_corrige_sin_intervencion(mock_llm):
    from agents.orquestador import run
    calls = _mock_factory(mock_llm, [BAD, GOOD])
    r = run("Funcion suma(a,b)", project="ades-ai", write=False,
            nodes={"contexto": lambda s: {}})
    assert r["estado"] == "ok"
    assert r["iteracion"] == 2 and calls["dev"] == 2
    assert r["sandbox"]["passed"] and r["sandbox"]["tests_run"] >= 2
    assert r["estrategias"][0].startswith("base") and r["estrategias"][1].startswith("contexto")


@pytest.mark.live
def test_bucle_escala_modelo_y_falla_honesto(mock_llm):
    from agents.orquestador import run
    calls = _mock_factory(mock_llm, [BAD])
    r = run("Funcion suma(a,b)", project="ades-ai", write=False, max_iteraciones=4,
            nodes={"contexto": lambda s: {}})
    assert r["estado"] == "failed"  # nunca marca OK si los tests no pasan
    assert [e.split(":")[0] for e in r["estrategias"]] == ["base", "contexto", "local-alt", "modelo"]
    assert ("opencode", "deepseek-v4.1-flash") in calls["models"]


@pytest.mark.live
def test_qa_rechaza_alucinaciones(mock_llm):
    from agents import orquestador
    halluc = GOOD.replace("def suma(a, b):",
                          "from cache.token_metrics import TokenBudget\n\ndef suma(a, b):")
    _mock_factory(mock_llm, [halluc, GOOD])
    orquestador_ctx = lambda s: orquestador._GRAPH_CACHE.__setitem__(s["run_id"], _idx()) or {}
    r = orquestador.run("suma", project="ades-ai", write=False, nodes={"contexto": orquestador_ctx})
    assert r["estado"] == "ok" and r["iteracion"] == 2
    assert r["alucinaciones"] == []


def test_ruta_despues_qa():
    from agents.orquestador import ruta_despues_qa
    assert ruta_despues_qa({"qa_veredicto": "PASS"}) == "write"
    assert ruta_despues_qa({"qa_veredicto": "FAIL", "iteracion": 1, "max_iteraciones": 3}) == "developer"
    assert ruta_despues_qa({"qa_veredicto": "FAIL", "iteracion": 3, "max_iteraciones": 3}) == "failed"
    assert ruta_despues_qa({"qa_veredicto": "FAIL", "iteracion": 3, "max_iteraciones": 3,
                            "sandbox": {"passed": True}}) == "write"


# --- Sandbox (regla 5) ---------------------------------------------------------
@pytest.mark.live
def test_sandbox_aislado_y_veredicto():
    from core.sandbox import extract_files, run_tests
    files = extract_files(GOOD)
    assert run_tests(files).passed
    assert not run_tests(extract_files(BAD)).passed
    net = run_tests({"n.py": "import socket\nsocket.create_connection(('1.1.1.1', 80), timeout=3)\n"})
    assert not net.passed and "unreachable" in net.output.lower()


# --- Feature #2: backlog -------------------------------------------------------
def test_backlog_worker_hasta_agotar():
    from agents import backlog
    p = projects.create("bk-test")["id"]
    backlog.add_tickets(p, [{"titulo": "a"}, {"titulo": "b"}, {"titulo": "c"}])
    seen = []

    def runner(req, proj, ticket):
        seen.append(ticket["titulo"])
        return {"estado": "ok" if ticket["titulo"] != "b" else "failed", "run_id": "r"}

    res = backlog.work(p, runner=runner, max_attempts=2)
    b = backlog.board(p)
    assert [t["titulo"] for t in b["done"]] == ["a", "c"]
    assert [t["titulo"] for t in b["failed"]] == ["b"]
    assert seen.count("b") == 2 and not b["todo"] and not b["doing"]
    assert len(res) == 4


# --- Feature #1: bootstrapper --------------------------------------------------
def test_bootstrap_sin_llm(tmp_path, monkeypatch, mock_llm):
    from agents import bootstrap, backlog
    mock_llm(lambda p, m, msgs: (json.dumps({"prd": "PRD tienda", "tickets": [
        {"titulo": "catalogo", "criterios": []}, {"titulo": "carrito", "criterios": []}]}), 5, 5))
    import memory.indexer as ix
    monkeypatch.setattr(ix, "_driver_from_env", lambda: (_ for _ in ()).throw(RuntimeError("sin neo4j")))
    r = bootstrap.bootstrap("Tienda Demo", "API de productos")
    root = projects.path_of("tienda-demo")
    for f in ("README.md", "Dockerfile", ".github/workflows/ci.yml", "tienda_demo/__init__.py",
              "tests/test_smoke.py", "requirements.txt"):
        assert (root / f).exists(), f
    assert r["tickets"] == 2 and len(backlog.board("tienda-demo")["todo"]) == 2
    assert (root / ".git").exists() and r["commit"]


# --- Feature #27/#11: dashboard ----------------------------------------------
def test_dashboard_api(mock_llm):
    from fastapi.testclient import TestClient
    from core import llm_gateway
    from dashboard.app import app
    mock_llm(lambda p, m, msgs: ("x", 3, 4))
    llm_gateway.chat("dev", "s", "u", provider="ollama", model="gpt-oss:20b", project="t-dash")
    c = TestClient(app)
    m = c.get("/api/metrics").json()
    assert m["summary"]["calls"] >= 1 and isinstance(m["series"], list)
    assert any(p["id"] == "ades-ai" for p in c.get("/api/projects").json())
    assert c.get("/api/agents").status_code == 200
    assert "ADES-AI" in c.get("/").text


# --- Feature #26: CLI ------------------------------------------------------------
def test_cli_unificado(capsys):
    import ades_cli
    assert ades_cli.main(["help"]) == 0
    assert ades_cli.main(["project", "list"]) == 0
    assert "ades-ai" in capsys.readouterr().out
    assert ades_cli.main(["tokens"]) == 0
    assert ades_cli.main(["budget", "show", "--project", "ades-ai"]) == 0
    assert ades_cli.main(["comando-que-no-existe"]) == 1
    for cmd in ("tools", "agent", "backlog"):
        assert cmd in ades_cli.PASSTHROUGH


# --- Indexador + grafo real (KPI 4, live) --------------------------------------
@pytest.mark.live
def test_indexer_y_validator_contra_neo4j(tmp_path):
    from memory.indexer import _driver_from_env, index_repo
    pkg = tmp_path / "libx"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "core.py").write_text("class Motor:\n    def arrancar(self):\n        return 1\n\n"
                                 "def helper():\n    return 2\nVERSION = '1'\n")
    d = _driver_from_env()
    try:
        index_repo(str(tmp_path), d)
        idx = GraphIndex.from_neo4j(d, repo=str(tmp_path.resolve()))
        assert {"Motor", "helper", "VERSION"} <= idx.modules["libx.core"]
        ok = "from libx.core import Motor, helper\nMotor().arrancar()\n"
        bad = "from libx.core import Turbo\nfrom libx.core import Motor\nMotor().volar()\n"
        assert validate_code(ok, idx) == []
        assert {f.ref for f in validate_code(bad, idx)} == {"libx.core.Turbo", "libx.core.Motor.volar"}
    finally:
        with d.session() as s:
            s.run("MATCH (f:CodeFile {repo: $r}) OPTIONAL MATCH (f)-[:CONTAINS*1..2]->(x) "
                  "DETACH DELETE f, x", r=str(tmp_path.resolve()))
        d.close()


def test_cli_todos_los_subcomandos_tienen_destino():
    import importlib
    import ades_cli
    for cmd, (mod, fn) in ades_cli.PASSTHROUGH.items():
        assert callable(getattr(importlib.import_module(mod), fn, None)), cmd


def test_qa_regenera_tests_por_desajuste():
    from agents.qa import qa_mismatch
    out_desajuste = ("FAILED test_qa_acceptance.py::test_x - TypeError: f() takes 1 positional\n"
                     "1 failed, 9 passed")
    assert qa_mismatch(out_desajuste)
    assert qa_mismatch("ERROR test_qa_acceptance.py\nImportError while importing\nInterrupted: 1 error")
    # Si también fallan los tests del Developer, la culpa es del código: no se regenera
    assert not qa_mismatch("FAILED test_app.py::t - TypeError\nFAILED test_qa_acceptance.py::t - TypeError")
    # Fallo de comportamiento (assert) en QA: no es desajuste
    assert not qa_mismatch("FAILED test_qa_acceptance.py::t - AssertionError: 3 != 4")


def test_nombre_de_modulo_desde_el_requerimiento():
    from agents.developer import fix_default_name
    req = "Funcion `parse_duracion(texto)` en `duracion.py` que convierte"
    assert fix_default_name({"main.py": "def f(): pass"}, req) == {"duracion.py": "def f(): pass"}
    assert fix_default_name({"a.py": "x", "test_a.py": "y"}, req) == {"a.py": "x", "test_a.py": "y"}
    assert fix_default_name({"main.py": "x"}, "sin nombres") == {"main.py": "x"}


def test_arbitro_descarta_tests_de_qa_invalidos():
    from agents.qa import drop_tests, only_qa_tests_failed
    out = ("FAILED test_qa_acceptance.py::test_espacios - ValueError\n"
           "FAILED test_qa_acceptance.py::test_retorno - AssertionError\n2 failed, 9 passed")
    assert only_qa_tests_failed(out) == ["test_espacios", "test_retorno"]
    assert only_qa_tests_failed("FAILED test_app.py::t - x\nFAILED test_qa_acceptance.py::u") == []
    code = "def test_ok():\n    assert 1\n\ndef test_espacios():\n    assert 0\n"
    pruned = drop_tests(code, ["test_espacios"])
    assert "test_ok" in pruned and "test_espacios" not in pruned


@pytest.mark.live
def test_arbitro_en_el_bucle(mock_llm):
    """Tests del Developer en verde + un test de QA que inventa un requisito -> el árbitro lo
    descarta y la entrega pasa sin culpar al código."""
    import json as _json
    from agents.orquestador import run

    def fn(provider, model, messages):
        system = messages[0].content
        if "Project Manager" in system:
            return (_json.dumps({"prd": "suma", "tickets": [{"titulo": "suma", "criterios": []}]}), 5, 5)
        if system.startswith("Eres el Developer"):
            return (GOOD, 50, 50)
        if "pytest de ACEPTACION" in system:
            return ("```python\nfrom calc import suma\n\ndef test_basico():\n    assert suma(2, 3) == 5\n\n"
                    "def test_inventado():\n    assert suma('1', 2) == 3\n```", 5, 5)
        if "revisor de tests" in system:
            return ('{"invalidos": ["test_inventado"], "motivo": "pide sumar strings"}', 5, 5)
        if "QA Tester" in system:
            return ("VEREDICTO: PASS\nCumple.", 5, 5)
        return ("ok", 5, 5)
    mock_llm(fn)
    r = run("Funcion suma(a,b)", project="ades-ai", write=False, nodes={"contexto": lambda s: {}})
    assert r["estado"] == "ok" and r["iteracion"] == 1
    assert r["sandbox"]["tests_qa_descartados"] == ["test_inventado"]
