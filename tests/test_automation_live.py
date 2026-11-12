"""Tests live del paquete `automation/`: usan Docker, Ollama y Neo4j reales.

Ejecutar solo estos:  python -m pytest tests/test_automation_live.py -m live -s
"""
import json
import statistics
import time
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.config import OLLAMA_URL, global_state_dir

pytestmark = pytest.mark.live


def _ollama_has(model: str) -> bool:
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=5) as r:
            return any(m["name"] == model for m in json.loads(r.read())["models"])
    except Exception:  # noqa: BLE001
        return False


def _docker_ok() -> bool:
    import subprocess
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=30).returncode == 0
    except Exception:  # noqa: BLE001
        return False


needs_llama = pytest.mark.skipif(not _ollama_has("llama3.2:3b"), reason="Ollama/llama3.2:3b no disponible")


# ------------------------------------------------------------ #3 Watchdog real
@pytest.mark.skipif(not _docker_ok(), reason="Docker no disponible")
def test_live_watchdog_sandbox_docker(tmp_path):
    from automation.watchdog import Watchdog
    repo = tmp_path / "mini"
    repo.mkdir()
    (repo / "calc.py").write_text("def mul(a, b):\n    return a * b\n", encoding="utf-8")
    (repo / "test_calc.py").write_text(
        "from calc import mul\n\ndef test_mul():\n    assert mul(3, 4) == 12\n", encoding="utf-8")
    wd = Watchdog(f"wdlive-{uuid.uuid4().hex[:6]}", repo, notify=False)
    r1 = wd.run_once()
    assert r1["tests"] is not None, r1.get("tests_error")
    assert r1["tests"]["passed"] and r1["tests"]["tests_run"] == 1 and not r1["broken"]

    time.sleep(0.01)
    (repo / "calc.py").write_text("def mul(a, b):\n    return a + b\n", encoding="utf-8")
    r2 = wd.run_once()
    assert r2["changes"]["modified"] == ["calc.py"]
    assert r2["broken"] and not r2["tests"]["passed"] and r2["tests"]["tests_failed"] == 1
    alert = json.loads(wd.alerts_path.read_text(encoding="utf-8").splitlines()[-1])
    assert "tests fallan" in alert["problems"][0]
    print(f"\n[watchdog live] baseline ok={r1['tests']['passed']} | rotura detectada="
          f"{r2['broken']} | problemas={alert['problems']}")


# ----------------------------------------------- #30 ModelPool concurrente real
@needs_llama
def test_live_modelpool_concurrencia_ollama():
    from automation.model_serving import ModelPool
    n = 6
    pool = ModelPool.ollama(["llama3.2:3b"], max_concurrency=3, replicas=2, timeout=180)
    prompts = [f"Responde solo con el número {i} escrito en palabras en español." for i in range(n)]
    pool.chat("llama3.2:3b", [{"role": "user", "content": "hola"}], max_tokens=5)  # calienta
    warm = pool.stats()["backends"]
    base_served = sum(b["served"] for b in warm)

    def one(p):
        t0 = time.time()
        r = pool.chat("llama3.2:3b", [{"role": "user", "content": p}], max_tokens=20,
                      temperature=0)
        return time.time() - t0, r

    t0 = time.time()
    with ThreadPoolExecutor(n) as ex:
        results = list(ex.map(one, prompts))
    wall = time.time() - t0
    lats = [lat for lat, _ in results]
    texts = [r["choices"][0]["message"]["content"].strip() for _, r in results]
    assert len(results) == n and all(texts)
    st = pool.stats()
    served = sum(b["served"] for b in st["backends"]) - base_served
    assert served == n and st["in_flight"] == 0
    assert all(b["peak_in_flight"] <= b["max_concurrency"] for b in st["backends"])
    metrics = {"n": n, "wall_s": round(wall, 3), "lat_min_s": round(min(lats), 3),
               "lat_avg_s": round(statistics.mean(lats), 3),
               "lat_p50_s": round(statistics.median(lats), 3), "lat_max_s": round(max(lats), 3),
               "sum_lat_s": round(sum(lats), 3),
               "backends": {b["name"]: {"served": b["served"], "peak_in_flight":
                                        b["peak_in_flight"]} for b in st["backends"]},
               "respuestas": texts}
    (global_state_dir() / "modelpool_live.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n[modelpool live] " + json.dumps(metrics, ensure_ascii=False))


# ---------------------------------------------------------- #28 voz con LLM real
@needs_llama
def test_live_voice_fallback_llama():
    from automation.voice import ACCIONES, dispatch, parse
    r = parse("oye, dime cuánta plata he gastado en modelos este mes")
    print(f"\n[voice live] {r}")
    assert r["fuente"] == "llm" and r["accion"] in ACCIONES
    assert r["accion"] in ("tokens", "estado"), r
    assert dispatch(r)[0] == "ades"


# ------------------------------------------------ #31 skill generator con LLM real
@needs_llama
def test_live_skill_generator_llm_local(tmp_path):
    from automation import skill_generator as sg
    tasks = [{"task": t, "agent": "developer", "run": f"r{i}", "source": "metrics"}
             for i, t in enumerate([
                 "Crear endpoint FastAPI para usuarios con validación pydantic",
                 "crear endpoint fastapi para productos con validación pydantic",
                 "Crear endpoint FastAPI de pedidos con validación pydantic"])]
    project = f"sklive-{uuid.uuid4().hex[:6]}"
    out = sg.run(min_count=3, project=project, tasks=tasks, provider="ollama",
                 model="llama3.2:3b", skills_dir=tmp_path)
    assert len(out) == 1 and out[0]["errores_formato"] == []
    text = (sg.staging_dir(project) / f"auto-{out[0]['slug']}" / "SKILL.md").read_text("utf-8")
    print(f"\n[skill live] slug={out[0]['slug']}\n{text[:600]}")
    dst = sg.publish(out[0]["slug"], project=project, skills_dir=tmp_path)
    assert sg.validate_skill(dst.read_text(encoding="utf-8")) == []


# ------------------------------------------ #12 prefetch con Neo4j/embeddings reales
def test_live_prefetch_repo_real():
    from automation.prefetch import Prefetcher
    from core.config import ROOT
    pf = Prefetcher(f"pflive-{uuid.uuid4().hex[:6]}", ROOT)
    e = pf.prefetch("Mejorar el GPU Memory Manager: ensure_fits y loaded_models")
    print(f"\n[prefetch live] fuente={e['source']} archivos={[f['path'] for f in e['files']]} "
          f"embeddings={len(e['file_embeddings'])} t={e['elapsed']}s")
    assert e["files"] and any("gpu_manager" in f["path"] for f in e["files"])
    assert pf.get("ensure_fits y loaded_models del GPU Memory Manager") is not None
    assert pf.stats()["hit_rate"] == 1.0


# -------------------------------------- #32 automejora con propuesta de LLM real
@pytest.mark.skipif(not _ollama_has("gpt-oss:20b"), reason="gpt-oss:20b no disponible")
def test_live_self_improve_propuesta_real():
    from agents import prompts
    from automation import self_improve as si
    from core import metrics_store
    project = f"silive-{uuid.uuid4().hex[:6]}"
    metrics_store.record(project, "r1", "Implementar parser CSV", "reviewer", "ollama",
                         "gpt-oss:20b", 0, 0, 0.0, ok=False,
                         error="El review no menciona riesgos de inyección SQL")
    try:
        r = si.improve("reviewer", project, provider="ollama", model="gpt-oss:20b",
                       evaluator=lambda a, p: {"regression": False, "improved": False})
        print(f"\n[self_improve live] status={r['status']} reason={r.get('reason')} "
              f"candidato={str(r.get('candidate', ''))[:300]!r}")
        assert r["status"] in ("descartado", "error")
        assert prompts.get_prompt("reviewer") == prompts.DEFAULTS["reviewer"]
        assert r.get("candidate"), r  # el LLM devolvió un prompt extraíble
    finally:
        prompts.rollback("reviewer", None)
