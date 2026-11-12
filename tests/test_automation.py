"""Tests unitarios (deterministas) del paquete `automation/` (features #3, #12, #28, #30, #31, #32)."""
import json
import threading
import time
import urllib.error
import urllib.request
import uuid

import pytest

from core.sandbox import SandboxResult


# =============================================================== #3 Watchdog
def _mini_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "mod.py").write_text("def suma(a, b):\n    return a + b\n", encoding="utf-8")
    (repo / "test_mod.py").write_text(
        "from mod import suma\n\ndef test_suma():\n    assert suma(2, 3) == 5\n", encoding="utf-8")
    return repo


class _Runner:
    def __init__(self, passed=True):
        self.passed = passed
        self.calls = []

    def __call__(self, files):
        self.calls.append(sorted(files))
        return SandboxResult(passed=self.passed, exit_code=0 if self.passed else 1,
                             output="1 passed" if self.passed else "1 failed",
                             tests_run=1, tests_failed=0 if self.passed else 1)


def _wd(tmp_path, runner, notes):
    from automation.watchdog import Watchdog
    project = f"wd-{uuid.uuid4().hex[:6]}"
    return Watchdog(project, _mini_repo(tmp_path), sandbox_runner=runner, notify=True,
                    notifier=lambda t, m: notes.append((t, m)) or True)


def test_watchdog_baseline_sin_cambios_y_rotura(tmp_path):
    runner, notes = _Runner(), []
    wd = _wd(tmp_path, runner, notes)
    r1 = wd.run_once()
    assert r1["baseline"] and not r1["broken"]
    assert "mod.py" in r1["changes"]["added"]
    assert runner.calls and "test_mod.py" in runner.calls[0]

    r2 = wd.run_once()
    assert r2.get("skipped") and len(runner.calls) == 1  # sin cambios no re-ejecuta

    time.sleep(0.01)
    (wd.repo / "mod.py").write_text("def suma(a, b)\n    return a + b\n", encoding="utf-8")
    r3 = wd.run_once()
    assert r3["changes"]["modified"] == ["mod.py"]
    assert r3["broken"] and r3["compile_errors"][0]["file"] == "mod.py"
    alerts = [json.loads(l) for l in wd.alerts_path.read_text(encoding="utf-8").splitlines()]
    assert alerts and "mod.py" in alerts[-1]["problems"][0]
    assert notes and "SyntaxError" in notes[-1][1]
    assert "ROTO" in wd.log_path.read_text(encoding="utf-8")

    (wd.repo / "mod.py").write_text("def suma(a, b):\n    return a + b\n", encoding="utf-8")
    r4 = wd.run_once()
    assert not r4["broken"]
    assert "RECUPERADO" in wd.log_path.read_text(encoding="utf-8")


def test_watchdog_tests_fallan_alerta(tmp_path):
    runner, notes = _Runner(passed=False), []
    wd = _wd(tmp_path, runner, notes)
    r = wd.run_once()
    assert r["broken"] and r["tests"]["tests_failed"] == 1
    assert r["alert"]["notified"] is True
    assert "tests fallan" in r["alert"]["problems"][0]


def test_watchdog_archivo_borrado_y_sin_toast(tmp_path):
    from automation.watchdog import Watchdog
    runner = _Runner()
    wd = Watchdog(f"wd-{uuid.uuid4().hex[:6]}", _mini_repo(tmp_path), sandbox_runner=runner,
                  notify=False, notifier=lambda *a: pytest.fail("no debe notificar"))
    wd.run_once()
    (wd.repo / "extra.py").write_text("x = 1\n", encoding="utf-8")
    wd.run_once()
    (wd.repo / "extra.py").unlink()
    r = wd.run_once()
    assert r["changes"]["removed"] == ["extra.py"]
    runner.passed = False
    (wd.repo / "mod.py").write_text("def suma(a, b):\n    return a - b\n", encoding="utf-8")
    r = wd.run_once()
    assert r["broken"] and r["alert"]["notified"] is False


def test_watchdog_docker_caido_no_rompe(tmp_path):
    from automation.watchdog import Watchdog

    def boom(files):
        raise RuntimeError("docker no responde")
    wd = Watchdog(f"wd-{uuid.uuid4().hex[:6]}", _mini_repo(tmp_path), sandbox_runner=boom,
                  notify=False)
    r = wd.run_once()
    assert "docker no responde" in r["tests_error"] and not r["broken"]


def test_watchdog_run_forever_e_install_task_dry_run(tmp_path, monkeypatch):
    import subprocess
    from automation import watchdog
    runner, notes = _Runner(), []
    wd = _wd(tmp_path, runner, notes)
    sleeps = []
    assert wd.run_forever(interval=5, max_iterations=3, sleep=sleeps.append) == 3
    assert sleeps == [5, 5]

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("no debe ejecutar"))
    r = watchdog.install_task("demo", interval_minutes=10, dry_run=True)
    assert r["dry_run"] and not r["created"]
    assert r["command"][:2] == ["schtasks", "/Create"]
    assert "10" in r["command"] and "ADES-AI Watchdog demo" in r["command"]
    assert "automation.watchdog --project demo --once" in r["command"][r["command"].index("/TR") + 1]
    assert watchdog.uninstall_task("demo")["command"][1] == "/Delete"


def test_toast_script_escapa_comillas():
    from automation.watchdog import toast_script
    s = toast_script("Título 'x'", "línea1\nlínea2 'y'")
    assert "''x''" in s and "''y''" in s and "\n" not in s
    assert "ToastNotificationManager" in s


# ================================================================ #12 Prefetch
def _code_repo(tmp_path):
    repo = tmp_path / "code"
    (repo / "app").mkdir(parents=True)
    (repo / "app" / "auth.py").write_text(
        "class AuthManager:\n    def login(self, user, pwd):\n        return True\n\n"
        "def logout(user):\n    pass\n", encoding="utf-8")
    (repo / "app" / "db.py").write_text(
        "class Database:\n    def connect(self, url):\n        pass\n", encoding="utf-8")
    (repo / "app" / "utils.py").write_text("def slugify(s):\n    return s\n", encoding="utf-8")
    return repo


def test_keywords_y_clave():
    from automation.prefetch import keywords, task_key
    kws = keywords("Arreglar el login del AuthManager en auth_service")
    assert "login" in kws and "authmanager" in kws and "auth" in kws and "manager" in kws
    assert "del" not in kws
    assert task_key("login AuthManager") == task_key("AuthManager login")


def test_prefetch_lexico_hit_rate_y_ttl(tmp_path):
    from automation.prefetch import Prefetcher
    pf = Prefetcher(f"pf-{uuid.uuid4().hex[:6]}", _code_repo(tmp_path), use_graph=False,
                    use_embeddings=False)
    entry = pf.prefetch("Arreglar el login del AuthManager")
    assert entry["source"] == "lexical"
    assert entry["files"][0]["path"] == "app/auth.py"
    assert "class AuthManager" in entry["repomap"] and "login(self, user, pwd)" in entry["repomap"]
    assert (pf.dir / f"{entry['key']}.json").exists()

    assert "AuthManager" in pf.get("Arreglar el login del AuthManager")        # exacto
    assert pf.get("el login de AuthManager falla") is not None                  # similar
    assert pf.get("conectar la base de datos Database") is None                 # miss
    st = pf.stats()
    assert st["hits"] == 2 and st["misses"] == 1 and st["hit_rate"] == pytest.approx(0.667, 0.01)

    # caché en disco: otra instancia (otro proceso) lo encuentra
    from automation import prefetch as mod
    mod._MEM.clear()
    pf2 = Prefetcher(pf.project, pf.repo, use_graph=False, use_embeddings=False)
    assert pf2.get("Arreglar el login del AuthManager") is not None

    expired = Prefetcher(f"pf-{uuid.uuid4().hex[:6]}", pf.repo, use_graph=False,
                         use_embeddings=False, ttl=-1)
    expired.prefetch("login AuthManager")
    assert expired.get("login AuthManager") is None and expired.stats()["cached"] == 0


class _FakeSession:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, q, **kw):
        assert "CodeFile" in q and kw["kws"]
        rows = self.rows
        return type("R", (), {"data": lambda self: rows})()


class _FakeDriver:
    def __init__(self, rows):
        self.rows = rows

    def session(self):
        return _FakeSession(self.rows)


def test_prefetch_via_grafo_y_embeddings(tmp_path):
    from automation.prefetch import Prefetcher
    repo = _code_repo(tmp_path)
    auth = str(repo / "app" / "auth.py")
    rows = [{"kw": "login", "fs": [],
             "syms": [{"path": auth, "name": "login", "kind": "method", "params": "self, user"}]},
            {"kw": "auth", "fs": [{"path": auth, "name": "auth.py", "kind": "file"}],
             "syms": [{"path": auth, "name": "AuthManager", "kind": "class", "params": None},
                      {"path": "/otro/repo/x.py", "name": "auth_x", "kind": "function",
                       "params": ""}]}]
    vocab = ["login", "auth", "database", "falla", "sesion"]

    def embed(text):
        low = text.lower()
        return [float(low.count(w)) + 0.01 for w in vocab]

    pf = Prefetcher(f"pf-{uuid.uuid4().hex[:6]}", repo, driver=_FakeDriver(rows), embed_fn=embed,
                    similarity=0.99)
    e = pf.prefetch("login auth")
    assert e["source"] == "graph"
    assert [f["path"] for f in e["files"]] == [auth]  # filtra rutas de otros repos
    assert "class AuthManager" in e["files"][0]["symbols"]
    assert e["task_embedding"] and auth in e["file_embeddings"]
    # sin coincidencia léxica suficiente (similarity=0.99) pero embedding casi igual -> hit
    assert pf.get("autenticacion auth login") is not None
    assert pf.get("database falla sesion") is None


def test_prefetch_grafo_caido_usa_fallback(tmp_path):
    from automation.prefetch import Prefetcher

    class Broken:
        def session(self):
            raise ConnectionError("neo4j caído")
    pf = Prefetcher(f"pf-{uuid.uuid4().hex[:6]}", _code_repo(tmp_path), driver=Broken(),
                    use_embeddings=False)
    assert pf.prefetch("conectar Database")["files"][0]["path"] == "app/db.py"


# ====================================================================== #28 Voz
@pytest.mark.parametrize("texto,accion,args", [
    ("integra llmfit en ades-ai", "integrar", {"herramienta": "llmfit", "proyecto": "ades-ai"}),
    ("Integra la herramienta graphiti", "integrar", {"herramienta": "graphiti"}),
    ("activa context7", "activar", {"herramienta": "context7"}),
    ("desactiva context7", "desactivar", {"herramienta": "context7"}),
    ("crea un proyecto de tienda online", "crear_proyecto",
     {"descripcion": "tienda online", "nombre": "tienda-online"}),
    ("¿cuántos tokens llevo?", "tokens", {}),
    ("estado del ecosistema", "estado", {}),
    ("crea un agente de UX", "crear_agente", {"rol": "ux"}),
    ("agrega https://github.com/foo/bar a ADES-AI", "agregar_herramienta",
     {"url": "https://github.com/foo/bar"}),
    ("¿qué herramientas hay para testing de APIs?", "buscar_herramienta",
     {"consulta": "testing de apis"}),
    ("lista las herramientas", "listar_herramientas", {}),
    ("arranca el ecosistema", "iniciar", {}),
])
def test_voice_reglas(texto, accion, args):
    from automation.voice import parse
    r = parse(texto, use_llm=False)
    assert r["accion"] == accion and r["fuente"] == "reglas"
    assert r["args"] == args


def test_voice_dispatch():
    from automation.voice import dispatch, parse
    assert dispatch(parse("integra llmfit en ades-ai", use_llm=False)) == \
        ["ades", "integrate", "llmfit"]
    assert dispatch(parse("activa context7", use_llm=False)) == \
        ["ades", "tools", "activate", "context7"]
    assert dispatch(parse("agrega https://github.com/foo/bar a ADES-AI", use_llm=False)) == \
        ["ades", "tools", "add", "https://github.com/foo/bar"]
    assert dispatch(parse("¿cuántos tokens llevo?", use_llm=False)) == ["ades", "tokens"]
    assert dispatch(parse("estado del ecosistema", use_llm=False)) == ["ades", "status"]
    assert dispatch(parse("crea un proyecto de tienda online", use_llm=False)) == \
        ["ades", "project", "create", "tienda-online"]
    assert dispatch({"accion": "crear_agente", "args": {"rol": "ux"}}) == \
        ["ades", "agent", "create", "agente-ux", "ux"]
    with pytest.raises(ValueError):
        dispatch({"accion": "integrar", "args": {}})
    with pytest.raises(ValueError):
        dispatch({"accion": "borrar_todo", "args": {}})


def test_voice_fallback_llm(mock_llm):
    from automation.voice import parse
    seen = {}

    def fake(provider, model, messages):
        seen["model"] = model
        return '{"accion": "tokens", "args": {"proyecto": "tienda"}}', 10, 5
    mock_llm(fake)
    r = parse("dime cuánta pasta he quemado en la tienda")
    assert r == {"accion": "tokens", "args": {"proyecto": "tienda"}, "fuente": "llm",
                 "texto": "dime cuánta pasta he quemado en la tienda"}
    assert seen["model"] == "llama3.2:3b"

    mock_llm(lambda p, m, msgs: ("ni idea: {\"accion\": \"formatear_disco\"}", 1, 1))
    assert parse("haz algo raro")["accion"] == "desconocida"


def test_voice_listen_sin_backend_y_loop(monkeypatch):
    from automation import voice
    monkeypatch.setattr(voice, "backend", lambda: None)
    with pytest.raises(voice.VoiceUnavailable, match="pip install"):
        voice.listen()
    entradas = iter(["estado del ecosistema", "", "integra llmfit", "salir", "no llega"])
    out = []
    cmds = voice.voice_loop(input_fn=lambda: next(entradas), output=out.append, use_llm=False)
    assert [c["accion"] for c in cmds] == ["estado", "integrar"]
    assert out[0] == "[estado] -> ades status"


def test_entrypoints_main_para_ades_cli(capsys, tmp_path):
    from automation import model_serving, prefetch, self_improve, skill_generator, voice
    assert voice.main(["--no-llm", "estado", "del", "ecosistema"]) == 0
    assert json.loads(capsys.readouterr().out)["invocacion"] == ["ades", "status"]
    assert skill_generator.main(["staged", "--project", f"ep-{uuid.uuid4().hex[:6]}"]) == 0
    assert self_improve.main(["--history"]) == 0
    assert prefetch.main(["--stats", "--project", f"ep-{uuid.uuid4().hex[:6]}"]) == 0
    assert model_serving.main(["generate", "--out", str(tmp_path)]) == 0
    assert (tmp_path / "models.json").exists()


# ============================================================= #30 ModelPool
class _FakeTransport:
    def __init__(self, delay=0.05, fail=()):
        self.delay, self.fail = delay, set(fail)
        self.lock = threading.Lock()
        self.cur, self.peak, self.calls = {}, {}, []

    def __call__(self, url, payload, api_key, timeout):
        host = url.split("/")[2]
        with self.lock:
            self.calls.append((host, payload["model"]))
            self.cur[host] = self.cur.get(host, 0) + 1
            self.peak[host] = max(self.peak.get(host, 0), self.cur[host])
        try:
            if host in self.fail:
                raise urllib.error.URLError("conexión rechazada")
            time.sleep(self.delay)
            return {"choices": [{"message": {"role": "assistant",
                                             "content": f"ok {payload['model']}"}}]}
        finally:
            with self.lock:
                self.cur[host] -= 1


def test_modelpool_concurrencia_y_balanceo():
    from concurrent.futures import ThreadPoolExecutor
    from automation.model_serving import Backend, ModelPool
    tr = _FakeTransport()
    pool = ModelPool([Backend("a", "http://a:1/v1", ["m"], max_concurrency=2),
                      Backend("b", "http://b:1/v1", ["m"], max_concurrency=2),
                      Backend("c", "http://c:1/v1", {"otro": "otro-remoto"}, max_concurrency=1)],
                     transport=tr)
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda i: pool.chat("m", [{"role": "user", "content": str(i)}]),
                          range(8)))
    assert all(r["choices"][0]["message"]["content"] == "ok m" for r in res)
    st = pool.stats()
    bk = {b["name"]: b for b in st["backends"]}
    assert bk["a"]["peak_in_flight"] <= 2 and bk["b"]["peak_in_flight"] <= 2
    assert bk["a"]["served"] + bk["b"]["served"] == 8 and bk["a"]["served"] >= 2
    assert bk["c"]["served"] == 0 and st["in_flight"] == 0
    assert st["models"]["m"]["n"] == 8 and st["models"]["m"]["peak_queued"] >= 1
    assert tr.peak["a:1"] <= 2
    pool.chat("otro", [{"role": "user", "content": "x"}])
    assert ("c:1", "otro-remoto") in tr.calls  # alias lógico -> nombre remoto


def test_modelpool_failover_y_errores():
    from automation.model_serving import Backend, ModelPool, PoolError
    tr = _FakeTransport(fail={"bad:1"})
    pool = ModelPool([Backend("bad", "http://bad:1/v1", ["m"], max_concurrency=4),
                      Backend("good", "http://good:1/v1", ["m"], max_concurrency=1)],
                     transport=tr)
    r = pool.chat("m", [{"role": "user", "content": "hola"}])
    assert r["_ades"]["backend"] == "good"
    bk = {b["name"]: b for b in pool.stats()["backends"]}
    assert bk["bad"]["errors"] == 1 and bk["good"]["served"] == 1
    with pytest.raises(PoolError, match="sirve el modelo"):
        pool.chat("inexistente", [])
    only_bad = ModelPool([Backend("bad", "http://bad:1/v1", ["m"])], transport=tr)
    with pytest.raises(PoolError, match="fallaron"):
        only_bad.chat("m", [])


def test_modelpool_from_config_y_router_http():
    from automation.model_serving import ModelPool, serve
    tr = _FakeTransport(delay=0)
    pool = ModelPool.from_config({"backends": [
        {"name": "x", "base_url": "http://x:1/v1/", "models": ["m1", "m2"], "max_concurrency": 3}]},
        transport=tr)
    assert pool.models() == ["m1", "m2"] and pool.backends[0].base_url == "http://x:1/v1"
    srv = serve(pool, "127.0.0.1", 0)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        models = json.loads(urllib.request.urlopen(base + "/v1/models", timeout=5).read())
        assert [m["id"] for m in models["data"]] == ["m1", "m2"]
        req = urllib.request.Request(base + "/v1/chat/completions", data=json.dumps(
            {"model": "m2", "messages": [{"role": "user", "content": "hi"}],
             "max_tokens": 5}).encode(), headers={"Content-Type": "application/json"})
        body = json.loads(urllib.request.urlopen(req, timeout=5).read())
        assert body["choices"][0]["message"]["content"] == "ok m2"
        req = urllib.request.Request(base + "/v1/chat/completions", data=json.dumps(
            {"model": "nope", "messages": []}).encode())
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req, timeout=5)
        assert ei.value.code == 503
    finally:
        srv.shutdown()


def test_generate_config_vllm(tmp_path):
    from automation.model_serving import ModelSpec, generate_config
    paths = generate_config(out_dir=tmp_path)
    rocm = (tmp_path / "docker-compose.rocm.yml").read_text(encoding="utf-8")
    cuda = (tmp_path / "docker-compose.cuda.yml").read_text(encoding="utf-8")
    assert "rocm/vllm" in rocm and "/dev/kfd" in rocm and "nvidia" not in rocm
    assert "vllm/vllm-openai" in cuda and "driver: nvidia" in cuda
    for txt in (rocm, cuda):
        assert "vllm-gpt-oss-20b:" in txt and "vllm-llama3-2-3b:" in txt and "router:" in txt
        assert '"--served-model-name", "gpt-oss:20b"' in txt
    cfg = json.loads((tmp_path / "models.json").read_text(encoding="utf-8"))
    assert {b["name"] for b in cfg["backends"]} == {"vllm-gpt-oss-20b", "vllm-llama3-2-3b"}
    assert set(paths) == {"rocm", "cuda", "models.json"}
    try:
        import yaml
        assert set(yaml.safe_load(rocm)["services"]) == {"vllm-gpt-oss-20b", "vllm-llama3-2-3b",
                                                         "router"}
    except ImportError:
        pass
    with pytest.raises(ValueError, match="0.95"):
        generate_config([ModelSpec("a", "x/a", 0.6), ModelSpec("b", "x/b", 0.6)], tmp_path)


# ====================================================== #31 Auto-skill Generator
TAREAS = (
    [("Crear endpoint FastAPI para usuarios con validación", f"r{i}") for i in range(2)] +
    [("crear endpoint fastapi para productos con validación", "r2"),
     ("Crear un endpoint FastAPI de pedidos con validación", "r3"),
     ("crear endpoint fastapi para usuarios con validación", "r3")] +   # mismo run: cuenta 1
    [("Refactorizar el módulo de pagos", "r5"), ("Escribir README del proyecto", "r6")]
)


def _tasks():
    return [{"task": t, "agent": "developer", "run": r, "source": "metrics"} for t, r in TAREAS]


def test_skill_cluster_y_detect():
    from automation.skill_generator import detect
    res = detect(min_count=3, tasks=_tasks())
    assert len(res) == 1
    c = res[0]
    assert c["count"] == 4 and "endpoint" in c["slug"] and "fastapi" in c["slug"]
    assert c["agents"] == ["developer"] and len(c["examples"]) >= 3
    assert detect(min_count=5, tasks=_tasks()) == []


def test_skill_collect_desde_metricas():
    from automation.skill_generator import collect_tasks
    from core import metrics_store
    project = f"sk-{uuid.uuid4().hex[:6]}"
    for i in range(3):
        metrics_store.record(project, f"run{i}", "Generar tests pytest para el modulo X",
                             "developer", "ollama", "gpt-oss:20b", 10, 10, 0.0)
    metrics_store.record(project, "runC", "tarea cacheada", "developer", "cache", "m", 0, 0, 0.0,
                         cache_hit=True)
    tasks = collect_tasks(project, include_traces=False)
    assert len(tasks) == 3 and {t["run"] for t in tasks} == {"run0", "run1", "run2"}


def test_skill_generate_stage_publish(mock_llm, tmp_path):
    from automation import skill_generator as sg
    mock_llm(lambda p, m, msgs: (
        "Claro, aquí tienes:\n```markdown\n## Workflow\n\n1. Define el modelo pydantic.\n"
        "2. Crea el router.\n```", 50, 40))
    project = f"sk-{uuid.uuid4().hex[:6]}"
    skills = tmp_path / "skills"
    (skills / "fabrica").mkdir(parents=True)
    out = sg.run(min_count=3, project=project, tasks=_tasks(), skills_dir=skills)
    assert len(out) == 1 and out[0]["errores_formato"] == []
    slug = out[0]["slug"]
    staged = sg.staging_dir(project) / f"auto-{slug}" / "SKILL.md"
    text = staged.read_text(encoding="utf-8")
    assert text.startswith("---\nname: ") and "description:" in text
    assert "## Objetivo" in text and "## Workflow" in text and "pydantic" in text
    assert not (skills / f"auto-{slug}").exists()          # no se publica solo
    assert sg.run(min_count=3, project=project, tasks=_tasks(), skills_dir=skills) == []  # ya en staging
    dst = sg.publish(slug, project=project, skills_dir=skills)
    assert dst == skills / f"auto-{slug}" / "SKILL.md" and dst.read_text(encoding="utf-8") == text
    with pytest.raises(FileExistsError):
        sg.publish(slug, project=project, skills_dir=skills)
    with pytest.raises(FileNotFoundError):
        sg.publish("no-existe", project=project, skills_dir=skills)


def test_skill_fix_format_respeta_frontmatter():
    from automation.skill_generator import _fix_format, validate_skill
    c = {"slug": "x", "representative": "hacer x"}
    t = _fix_format("---\nname: Hacer X\ndescription: Hace X\n---\n\n## Objetivo\n\nX\n\n"
                    "## Workflow\n\n1. a\n", c)
    assert t.startswith("---\nname: Hacer X\ndescription: Hace X\n---") and validate_skill(t) == []
    assert validate_skill("sin frontmatter") == ["falta el frontmatter ---"]


# ================================================== #32 Ecosistema automejorable
def _fail(agent, project, n=2):
    from core import metrics_store
    for i in range(n):
        metrics_store.record(project, f"run{i}", "Implementar parser CSV", agent, "ollama",
                             "gpt-oss:20b", 0, 0, 0.0, ok=False,
                             error="QA: faltan tests de casos vacíos")


@pytest.fixture
def clean_prompt():
    from agents import prompts
    yield
    for a in ("developer", "qa"):
        prompts.rollback(a, None)


def _proposer(text):
    return lambda agent, failures: {"prompt": text, "motivo": "añade casos límite"}


def test_self_improve_aplica_si_mejora(clean_prompt):
    from agents.prompts import DEFAULTS, get_prompt
    from automation import self_improve as si
    project = f"si-{uuid.uuid4().hex[:6]}"
    _fail("developer", project)
    nuevo = DEFAULTS["developer"] + " Cubre SIEMPRE entradas vacías y casos límite en los tests."
    seen = {}

    def evaluator(agent, prompt):
        seen["args"] = (agent, prompt)
        return {"regression": False, "improved": True, "delta": 0.12}
    r = si.improve("developer", project, evaluator=evaluator, proposer=_proposer(nuevo))
    assert r["status"] == "aplicado" and r["version"] >= 1 and r["failures"] >= 2
    assert get_prompt("developer") == nuevo and seen["args"] == ("developer", nuevo)
    assert si.history()[-1]["status"] == "aplicado"


def test_self_improve_formato_regression_compare():
    from automation.self_improve import _improves
    assert _improves({"regression": False, "pass_rate_baseline": 0.5, "pass_rate_candidate": 0.75,
                      "score_baseline": 6.0, "score_candidate": 6.0})[0] is True
    assert _improves({"pass_rate_baseline": 0.5, "pass_rate_candidate": 0.5,
                      "score_baseline": 6.0, "score_candidate": 7.5}) == (True, 1.5)
    assert _improves({"pass_rate_baseline": 0.75, "pass_rate_candidate": 0.5,
                      "score_baseline": 6.0, "score_candidate": 9.0})[0] is False
    assert _improves({"pass_rate_baseline": 0.5, "pass_rate_candidate": 0.5,
                      "score_baseline": 6.0, "score_candidate": 6.0})[0] is False


@pytest.mark.parametrize("ev,motivo", [
    ({"regression": True, "improved": True}, "regresión detectada"),
    ({"regression": False, "improved": False}, "no mejora"),
    ({"regression": False, "old_score": 0.8, "new_score": 0.7}, "no mejora"),
    ({"regression": False}, "no mejora"),
])
def test_self_improve_descarta(clean_prompt, ev, motivo):
    from agents.prompts import DEFAULTS, get_prompt
    from automation import self_improve as si
    project = f"si-{uuid.uuid4().hex[:6]}"
    _fail("developer", project)
    r = si.improve("developer", project, evaluator=lambda a, p: ev,
                   proposer=_proposer(DEFAULTS["developer"] + " Extra."))
    assert r["status"] == "descartado" and r["reason"] == motivo
    assert get_prompt("developer") == DEFAULTS["developer"]
    assert si.history()[-1]["candidate"].endswith("Extra.")


def test_self_improve_omitido_y_errores(clean_prompt):
    from agents.prompts import DEFAULTS
    from automation import self_improve as si
    project = f"si-{uuid.uuid4().hex[:6]}"
    r = si.improve("qa", project, evaluator=lambda a, p: pytest.fail("no debe evaluar"))
    assert r["status"] == "omitido"
    _fail("qa", project)

    def missing(agent, prompt):
        raise ImportError("No module named 'evals.regression'")
    r = si.improve("qa", project, evaluator=missing, proposer=_proposer(DEFAULTS["qa"] + " Más."))
    assert r["status"] == "error" and "regression detector" in r["reason"]
    r = si.improve("qa", project, evaluator=lambda a, p: {}, proposer=_proposer("corto"))
    assert r["status"] == "descartado" and "corta" in r["reason"]


def test_self_improve_propuesta_con_llm_y_runs(mock_llm, clean_prompt):
    from agents.prompts import DEFAULTS, get_prompt
    from automation import self_improve as si
    from core.config import state_dir
    project = f"si-{uuid.uuid4().hex[:6]}"
    runs = state_dir(project) / "runs"
    runs.mkdir(parents=True)
    (runs / "run1.json").write_text(json.dumps(
        {"task": "parser CSV", "qa_feedback": "VEREDICTO: FAIL\nNo maneja comillas"}),
        encoding="utf-8")
    fails = si.collect_failures("developer", project)
    assert fails and fails[0]["source"] == "runs" and "comillas" in fails[0]["error"]
    nuevo = DEFAULTS["developer"] + " Maneja comillas en CSV."
    captured = {}

    def fake(provider, model, messages):
        captured["user"] = messages[-1].content if hasattr(messages[-1], "content") \
            else str(messages[-1])
        return f"<prompt>\n{nuevo}\n</prompt>\nMOTIVO: comillas", 100, 80
    mock_llm(fake)
    r = si.improve("developer", project,
                   evaluator=lambda a, p: {"regression": False, "delta": 0.05})
    assert r["status"] == "aplicado" and r["motivo"] == "comillas"
    assert get_prompt("developer") == nuevo
    assert "No maneja comillas" in captured["user"]


def test_skill_fix_format_frontmatter_sin_cerrar():
    from automation.skill_generator import _fix_format, validate_skill
    c = {"slug": "x", "representative": "hacer x"}
    raw = ("---\nname: crear-endpoint\ndescription: Crea endpoints FastAPI.\n\n"
           "## Objetivo\nCrear endpoints.\n\n## Workflow\n\n1. Paso.\n")
    t = _fix_format(raw, c)
    assert validate_skill(t) == [] and t.count("name:") == 1
    assert t.startswith("---\nname: crear-endpoint\ndescription: Crea endpoints FastAPI.\n---")
    assert "frontmatter duplicado" in validate_skill(
        "---\nname: a\ndescription: b\n---\n\n---\nname: c\n## Objetivo\n## Workflow\n")


def test_voice_llm_args_saneados(mock_llm):
    from automation.voice import parse
    mock_llm(lambda p, m, msgs: ('{"accion": "tokens", "args": {"proyecto": '
                                 '"gasto de tokens este mes", "extra": "x"}}', 1, 1))
    assert parse("dime cuánta plata he gastado")["args"] == {}
    mock_llm(lambda p, m, msgs: ('{"accion": "integrar", "args": {"herramienta": "LLMFit"}}', 1, 1))
    assert parse("mete eso de llmfit porfa")["args"] == {"herramienta": "llmfit"}
