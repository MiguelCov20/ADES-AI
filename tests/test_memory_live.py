"""Tests live de la memoria avanzada (features #6 #7 #8 #9).

Usan servicios reales: Ollama (nomic-embed-text), Neo4j + Graphiti (LLM de
OpenCode Go: 1 episodio) y la pasarela LLM real para `why()`/`consolidate()`.
Los datos van a bases SQLite temporales y a un group_id de test en Neo4j, que
se borra al final.
"""
import time
import uuid

import pytest

from memory import knowledge, reflection, timeline, vaccine

pytestmark = pytest.mark.live


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge, "db_path", lambda: tmp_path / "knowledge.db")
    monkeypatch.setattr(vaccine, "db_path", lambda: tmp_path / "vaccines.db")
    monkeypatch.setattr(timeline, "db_path", lambda: tmp_path / "timeline.db")
    monkeypatch.setenv("ADES_MEM0_SYNC", "0")
    try:
        knowledge._embed("ping")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"Ollama no disponible: {e}")
    yield tmp_path


def test_live_cross_project_recall(isolated):
    knowledge.remember("Prefiero FastAPI para construir APIs web en Python",
                       project="ades-test-a")
    knowledge.remember("Me gusta la pasta carbonara con mucho queso", kind="fact",
                       project="ades-test-a")
    knowledge.remember("Este proyecto usa Django REST", kind="fact",
                       project="ades-test-a", scope="project")
    ctx = knowledge.recall_context("¿qué framework uso para la API web?", project="ades-test-b")
    assert "FastAPI" in ctx
    assert "carbonara" not in ctx and "Django" not in ctx
    hits = knowledge.recall("framework para la API web", project="ades-test-b", k=1)
    assert "FastAPI" in hits[0]["text"]


def test_live_vaccine_matches_similar_bug(isolated):
    trace = ('Traceback (most recent call last):\n'
             '  File "C:\\work\\shop\\cart.py", line 31, in total\n'
             '    return qty + price_label\n'
             "TypeError: unsupported operand type(s) for +: 'int' and 'str'\n")
    v = vaccine.learn_from_failure(trace, "return qty + float(price_label)", project="ades-test")
    assert v is not None
    similar = ('  File "/srv/app/billing.py", line 8, in add\n    return n + other\n'
               "TypeError: unsupported operand type(s) for +: 'int' and 'NoneType'\n")
    hits = vaccine.match(similar)
    assert hits and hits[0]["id"] == v["id"] and 0.8 <= hits[0]["score"] < 1.0
    assert vaccine.match("ZeroDivisionError: division by zero") == []
    assert "float(price_label)" in vaccine.context_for(similar)


def test_live_timeline_graphiti_and_why(isolated, monkeypatch):
    from neo4j import GraphDatabase

    from core.config import ROOT  # noqa: F401  (carga .env)
    import os
    import memory.graphiti_client as gc

    monkeypatch.setenv("ADES_TIMELINE_GRAPHITI", "1")
    project = f"ades-test-{uuid.uuid4().hex[:8]}"
    gid = timeline.group_id(project)
    march = time.mktime((2026, 3, 10, 12, 0, 0, 0, 0, -1))
    driver = GraphDatabase.driver(os.getenv("NEO4J_URI", "bolt://localhost:7687"),
                                  auth=(os.getenv("NEO4J_USERNAME", "neo4j"),
                                        os.getenv("NEO4J_PASSWORD", "")))
    try:
        d = timeline.record_decision(
            "Usar Qdrant como base de datos vectorial",
            "ya corre en Docker y es más rápido que Chroma en nuestras pruebas",
            project=project, alternatives=["Chroma", "Pinecone"], when=march)
        assert d["graphiti"]["ok"] is True, d["graphiti"]
        # El episodio quedó con su fecha real (reference_time), no la de hoy
        with driver.session() as s:
            rows = s.run("MATCH (e:Episodic {group_id: $g}) RETURN e.valid_at AS v",
                         g=gid).data()
        assert len(rows) == 1 and str(rows[0]["v"]).startswith("2026-03-10")
        facts = gc.search("Qdrant base de datos vectorial", num=5, group_ids=[gid])
        assert facts and all(f["group_id"] == gid for f in facts)

        ans = timeline.why("¿Por qué decidimos usar Qdrant?", project=project)
        print("\nwhy() ->", ans)
        assert "Qdrant" in ans and "2026-03" in ans
    finally:
        gc.clear_group(gid)
        with driver.session() as s:
            left = s.run("MATCH (n {group_id: $g}) RETURN count(n) AS c", g=gid).single()["c"]
        driver.close()
        assert left == 0


def test_live_consolidate_real_embeddings_and_llm(isolated, monkeypatch):
    monkeypatch.setenv("ADES_TIMELINE_GRAPHITI", "0")
    monkeypatch.setattr(reflection, "_runs", lambda p, s, u: [])
    p = "ades-test-reflection"
    knowledge.remember("Prefiero FastAPI para las APIs web en Python", project=p, scope="project")
    knowledge.remember("Prefiero FastAPI para APIs web en Python.", project=p, scope="project")
    knowledge.remember("Prefiero PostgreSQL como base de datos", project=p, scope="project")
    vaccine.learn_from_failure("KeyError: 'user_id'", "uid = data.get('user_id')", project=p)
    timeline.record_decision("Validar siempre las claves de entrada", "hubo KeyError en prod",
                             project=p)
    r = reflection.consolidate(p)
    print("\nconsolidate() ->", r["lessons"], r["llm_error"])
    assert r["deduped"]["knowledge"] == 1
    assert len(knowledge.items(p, kinds=["preference"])) == 2
    assert r["llm_error"] == ""
    assert len(r["lessons"]) >= 1
    assert len(knowledge.items(p, kinds=["lesson"])) == len(set(r["lessons"]))
