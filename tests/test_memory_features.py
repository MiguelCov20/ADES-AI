"""Tests unitarios de la memoria avanzada (features #6 #7 #8 #9).

Embeddings simulados (bolsa de palabras con hash) y LLM simulado (`mock_llm`):
no usan Ollama, Neo4j, Graphiti ni la nube.
"""
import hashlib
import math
import re
import time

import pytest

from memory import knowledge, reflection, timeline, vaccine


def fake_embed(text: str, prefix: str = "") -> list[float]:
    """Embedding determinista: bolsa de palabras hasheadas en 64 dimensiones."""
    v = [0.0] * 64
    for w in re.findall(r"\w+", text.lower()):
        if len(w) > 2:
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Cada test con sus propias bases SQLite, embeddings falsos y sin Graphiti."""
    monkeypatch.setattr(knowledge, "db_path", lambda: tmp_path / "knowledge.db")
    monkeypatch.setattr(vaccine, "db_path", lambda: tmp_path / "vaccines.db")
    monkeypatch.setattr(timeline, "db_path", lambda: tmp_path / "timeline.db")
    monkeypatch.setattr(knowledge, "_embed", fake_embed)
    monkeypatch.setenv("ADES_TIMELINE_GRAPHITI", "0")
    monkeypatch.setenv("ADES_MEM0_SYNC", "0")
    monkeypatch.setattr(reflection, "_runs", lambda p, s, u: [])
    yield tmp_path


# ---------------------------------------------------------------------------
# #6 Memoria cross-proyecto
# ---------------------------------------------------------------------------
def test_global_memory_crosses_projects():
    knowledge.remember("Prefiero FastAPI para las APIs web en Python", project="proyecto-a")
    knowledge.remember("En este proyecto la API usa Django", kind="fact",
                       project="proyecto-a", scope="project")
    hits = knowledge.recall("qué framework uso para APIs web Python", project="proyecto-b")
    texts = [h["text"] for h in hits]
    assert "Prefiero FastAPI para las APIs web en Python" in texts
    assert all("Django" not in t for t in texts)  # scope=project no cruza
    hits_a = knowledge.recall("framework API web", project="proyecto-a")
    assert any("Django" in h["text"] for h in hits_a)


def test_recall_orders_by_similarity_and_filters_kinds():
    knowledge.remember("Usa pytest para los tests", kind="preference")
    knowledge.remember("Usa tabs para indentar", kind="preference")
    knowledge.remember("Los tests con pytest deben ser rápidos", kind="lesson")
    hits = knowledge.recall("pytest tests", k=3)
    assert hits[0]["text"] != "Usa tabs para indentar"
    assert hits[0]["score"] >= hits[-1]["score"]
    only_lessons = knowledge.recall("pytest tests", kinds=["lesson"])
    assert [h["kind"] for h in only_lessons] == ["lesson"]


def test_recall_recency_breaks_ties():
    old = knowledge.remember("Prefiero snake_case en Python", kind="preference")
    with knowledge._conn() as c:
        c.execute("UPDATE items SET ts=?, updated=? WHERE id=?",
                  (time.time() - 200 * 86400, time.time() - 200 * 86400, old["id"]))
    knowledge.remember("Prefiero snake_case en Python siempre", kind="preference",
                       project="otro")
    hits = knowledge.recall("Prefiero snake_case en Python", k=2)
    assert hits[0]["id"] != old["id"] or hits[0]["similarity"] > hits[1]["similarity"]


def test_remember_exact_duplicate_and_validation():
    a = knowledge.remember("Prefiero Postgres", project="x")
    b = knowledge.remember("  prefiero   postgres ", project="y")  # global: mismo item
    assert b["duplicate"] and b["id"] == a["id"] and b["hits"] == 2
    with pytest.raises(ValueError):
        knowledge.remember("algo", kind="otra-cosa")
    with pytest.raises(ValueError):
        knowledge.remember("algo", scope="universo")
    with pytest.raises(ValueError):
        knowledge.remember("   ")


def test_recall_context_text_and_empty():
    assert knowledge.recall_context("cualquier cosa") == ""
    knowledge.remember("Prefiero FastAPI para las APIs web", project="a")
    ctx = knowledge.recall_context("Prefiero FastAPI para APIs web", project="b")
    assert "Prefiero FastAPI" in ctx and "global" in ctx
    assert knowledge.recall_context("receta de tortilla de patatas", project="b") == ""


def test_lexical_fallback_without_ollama(monkeypatch):
    def down(text, prefix=""):
        raise ConnectionError("Ollama caído")
    monkeypatch.setattr(knowledge, "_embed", down)
    knowledge.remember("Prefiero FastAPI para APIs web", project="a")
    hits = knowledge.recall("FastAPI APIs web", project="b")
    assert hits and hits[0]["similarity"] > 0.5


def test_mem0_sync_only_when_enabled(monkeypatch):
    calls = []
    import memory.mem0_client as m0
    monkeypatch.setattr(m0, "add", lambda text, user_id="x": calls.append(user_id) or {"results": [1]})
    knowledge.remember("Prefiero Vue", project="a")
    assert calls == []
    monkeypatch.setenv("ADES_MEM0_SYNC", "1")
    r = knowledge.remember("Prefiero Svelte", project="a")
    assert calls == ["ades-global"] and r["mem0"]["ok"] is True
    monkeypatch.setattr(m0, "add", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sin red")))
    r = knowledge.remember("Prefiero Angular", project="a", scope="project")
    assert r["mem0"]["ok"] is False and r["id"]  # best-effort: no rompe


# ---------------------------------------------------------------------------
# #8 Vacuna contra bugs
# ---------------------------------------------------------------------------
TRACE = '''Traceback (most recent call last):
  File "C:\\Users\\dev\\proyecto\\app\\calc.py", line 42, in total
    return count + label
TypeError: unsupported operand type(s) for +: 'int' and 'str'
'''


def test_normalize_signature_removes_variable_parts():
    s = vaccine.normalize_signature(
        'File "/home/u/app/x.py", line 12: KeyError at 0x7f3a2b at C:\\proj\\m.py:33 value 15')
    assert "/home" not in s and "C:\\" not in s and "0x7f" not in s
    assert "12" not in s and "33" not in s and "15" not in s
    assert "line <n>" in s and "<dir>" in s and "<ruta>" in s


def test_extract_signature_variants():
    assert vaccine.extract_signature(TRACE) == \
        "TypeError: unsupported operand type(s) for +: 'int' and 'str'"
    pyt = "FAILED tests/test_x.py::test_suma - assert 3 == 4\n1 failed in 0.1s"
    assert vaccine.extract_signature(pyt) == "assert <n> == <n>"
    e_line = ">       assert suma(1, 2) == 4\nE       assert 3 == 4\n"
    assert vaccine.extract_signature(e_line).startswith("AssertionError: assert <n> == <n>")
    assert vaccine.extract_signature("todo correcto, 5 passed") is None
    assert "return count + label" in vaccine.extract_code_pattern(TRACE)


def test_learn_from_failure_and_match_similar():
    v = vaccine.learn_from_failure(TRACE, "return count + int(label)", project="a")
    assert v and v["error_type"] == "TypeError" and "count + label" in v["code_pattern"]
    other = TRACE.replace("calc.py", "otro.py").replace("line 42", "line 7")
    hits = vaccine.match(other)
    assert hits and hits[0]["id"] == v["id"] and hits[0]["score"] == 1.0
    assert vaccine.match("ZeroDivisionError: division by zero") == []
    ctx = vaccine.context_for(other)
    assert "int(label)" in ctx and "TypeError" in ctx
    assert vaccine.context_for("ModuleNotFoundError: No module named 'requests'") == ""


def test_vaccine_dedupe_and_learn_none():
    a = vaccine.add("KeyError: 'id' in line 3", "usa d.get('id')")
    b = vaccine.add("KeyError: 'id' in line 99", "usa d.get('id')")
    assert b["duplicate"] and b["id"] == a["id"] and b["hits"] == 2
    assert vaccine.learn_from_failure("5 passed", "x = 1") is None
    assert vaccine.learn_from_failure(TRACE, "   ") is None


# ---------------------------------------------------------------------------
# #9 Timeline de decisiones
# ---------------------------------------------------------------------------
MARCH = time.mktime((2026, 3, 10, 12, 0, 0, 0, 0, -1))
JUNE = time.mktime((2026, 6, 1, 12, 0, 0, 0, 0, -1))


def test_timeline_record_filter_and_query():
    timeline.record_decision("Usar Qdrant como vector store", "ya está en Docker y es rápido",
                             project="p", alternatives=["Chroma"], when=MARCH)
    timeline.record_decision("Cambiar de Chroma a Qdrant", "Chroma no escalaba", project="p",
                             when=JUNE)
    timeline.record_decision("Usar Redis para caché", "latencia baja", project="otro", when=JUNE)
    all_p = timeline.timeline("p")
    assert [d["title"] for d in all_p] == ["Usar Qdrant como vector store",
                                           "Cambiar de Chroma a Qdrant"]
    assert all_p[0]["date"].startswith("2026-03-10") and all_p[0]["alternatives"] == ["Chroma"]
    assert all_p[0]["graphiti"] == {"ok": False, "skipped": True}
    march = timeline.timeline("p", since=MARCH - 86400, until=MARCH + 86400)
    assert len(march) == 1
    q = timeline.timeline("p", query="Qdrant como vector store")
    assert q and q[0]["title"].startswith("Usar Qdrant")
    with pytest.raises(ValueError):
        timeline.record_decision("", "x")


def test_record_decision_passes_reference_time_to_graphiti(monkeypatch):
    monkeypatch.setenv("ADES_TIMELINE_GRAPHITI", "1")
    import memory.graphiti_client as gc
    seen = {}

    def fake_add(text, name="episodio", source="usuario", reference_time=None, group_id=None):
        seen.update(text=text, reference_time=reference_time, group_id=group_id)
        return {"nodes": 2, "edges": 1}
    monkeypatch.setattr(gc, "add_text", fake_add)
    d = timeline.record_decision("Usar FastAPI", "async nativo", project="mi proyecto", when=MARCH)
    assert seen["reference_time"] == MARCH and seen["group_id"] == "ades-decisions-mi-proyecto"
    assert "2026-03-10" in seen["text"] and d["graphiti"]["ok"] is True


def test_graphiti_failure_is_best_effort(monkeypatch):
    monkeypatch.setenv("ADES_TIMELINE_GRAPHITI", "1")
    import memory.graphiti_client as gc
    monkeypatch.setattr(gc, "add_text", lambda *a, **k: (_ for _ in ()).throw(OSError("neo4j caído")))
    d = timeline.record_decision("Usar SQLite", "simple", project="p")
    assert d["graphiti"]["ok"] is False and "neo4j" in d["graphiti"]["error"]


def test_why_uses_llm_with_dates_and_local_fallback(mock_llm, monkeypatch):
    timeline.record_decision("Usar Qdrant como vector store", "ya está en Docker", project="p",
                             when=MARCH)
    seen = {}

    def fake(provider, model, messages):
        seen["prompt"] = "\n".join(str(m.content) for m in messages)
        return "En 2026-03-10 se decidió usar Qdrant porque ya estaba en Docker.", 10, 10
    mock_llm(fake)
    ans = timeline.why("¿por qué usamos Qdrant como vector store?", project="p")
    assert "2026-03-10" in ans and "2026-03-10" in seen["prompt"]
    # Graphiti desactivado -> solo registro local; sin decisiones -> mensaje claro
    assert "No hay decisiones" in timeline.why("¿por qué Kubernetes?", project="vacio")

    def broken(provider, model, messages):
        raise RuntimeError("LLM caído")
    mock_llm(broken)
    ans = timeline.why("¿por qué usamos Qdrant como vector store?", project="p")
    assert "2026-03-10" in ans and "Qdrant" in ans


def test_why_includes_graphiti_facts(mock_llm, monkeypatch):
    monkeypatch.setenv("ADES_TIMELINE_GRAPHITI", "1")
    monkeypatch.setattr(timeline, "_graphiti_facts", lambda q, p, num=8: [
        {"fact": "El equipo eligió Qdrant", "valid_at": "2026-03-10T12:00:00+00:00",
         "invalid_at": None, "created_at": None}])
    seen = {}

    def fake(provider, model, messages):
        seen["p"] = "\n".join(str(m.content) for m in messages)
        return "ok 2026-03-10", 1, 1
    mock_llm(fake)
    assert timeline.why("¿por qué Qdrant?", project="sin-local") == "ok 2026-03-10"
    assert "El equipo eligió Qdrant" in seen["p"] and "[2026-03-10]" in seen["p"]


# ---------------------------------------------------------------------------
# #7 Consolidación nocturna
# ---------------------------------------------------------------------------
def test_consolidate_dedupes_and_saves_lessons(mock_llm):
    knowledge.remember("Prefiero FastAPI para APIs web", project="p")
    knowledge.remember("prefiero FastAPI para APIs web!", project="p")  # casi igual (sim=1)
    knowledge.remember("Prefiero Postgres como base de datos", project="p")
    timeline.record_decision("Usar Redis", "caché rápida", project="p")
    vaccine.add("KeyError: 'id'", "usa get", project="p")
    vaccine.add("KeyError: 'id' ", "usa get ", project="p")  # misma firma+fix -> ya dedupe en add
    mock_llm(lambda prov, mod, msgs: (
        "- Validar claves de diccionarios con get()\n- Preferir FastAPI en APIs nuevas\nbasura", 5, 5))

    dry = reflection.consolidate("p", dry_run=True)
    assert dry["dry_run"] and dry["lessons"] == [] and dry["deduped"]["knowledge"] == 1
    assert len(knowledge.items("p", kinds=["preference"])) == 3  # dry_run no borra

    r = reflection.consolidate("p")
    assert r["activity"]["decisions"] == 1 and r["activity"]["memories"] == 3
    assert r["activity"]["vaccines"] == 1
    assert r["lessons"] == ["Validar claves de diccionarios con get()",
                            "Preferir FastAPI en APIs nuevas"]
    assert r["deduped"]["knowledge"] == 1
    prefs = knowledge.items("p", kinds=["preference"])
    assert len(prefs) == 2 and max(p["hits"] for p in prefs) == 2
    lessons = knowledge.items("p", kinds=["lesson"])
    assert {lsn["source"] for lsn in lessons} == {"reflection"}
    assert all(lsn["scope"] == "project" for lsn in lessons)


def test_consolidate_nothing_to_do_and_ninguna(mock_llm):
    called = []
    mock_llm(lambda prov, mod, msgs: called.append(1) or ("NINGUNA", 1, 1))
    r = reflection.consolidate("vacio")
    assert r["lessons"] == [] and called == [] and r["deduped"] == {"knowledge": 0, "vaccines": 0}
    knowledge.remember("algo nuevo", kind="fact", project="q", scope="project")
    r = reflection.consolidate("q")
    assert called == [1] and r["lessons"] == []


def test_schedule_nightly_is_dry_by_default(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("no debe crear la tarea"))
    cmd = reflection.schedule_nightly(4)
    assert cmd.startswith("schtasks /Create") and "/ST 04:00" in cmd
    assert "memory.reflection --all" in cmd and "/SC DAILY" in cmd
    with pytest.raises(ValueError):
        reflection.schedule_nightly(25)
