"""Timeline de decisiones (feature #9) - ADES-AI.

Cada decisión de arquitectura/diseño se registra:
  1. En Graphiti (grafo temporal sobre Neo4j) como episodio con su fecha real
     (`reference_time`) y `group_id` del proyecto, para responder preguntas
     temporales tipo "¿por qué decidimos X en marzo?".
  2. En un registro local SQLite (`global_state_dir()/timeline.db`) para
     consulta rápida, filtrado por fechas y como respaldo si Graphiti no está
     disponible.

Graphiti usa un LLM de pago (OpenCode Go) por episodio. Se puede desactivar con
`ADES_TIMELINE_GRAPHITI=0` (solo registro local).

`project=None` equivale al proyecto por defecto (`ADES_PROJECT`).

Uso:
    python -m memory.timeline add "Usar Qdrant" "Ya está en Docker y es rápido"
    python -m memory.timeline list [--project P] [--query Q]
    python -m memory.timeline why "¿por qué usamos Qdrant?"
"""
import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from core.config import DEFAULT_PROJECT, global_state_dir
from memory import knowledge

QUERY_MIN_SIM = 0.5
_LOCK = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    ts REAL, recorded REAL, project TEXT,
    title TEXT, rationale TEXT, alternatives TEXT,
    embedding TEXT, graphiti TEXT
);
CREATE INDEX IF NOT EXISTS idx_dec_proj_ts ON decisions(project, ts);
"""


def db_path() -> Path:
    return global_state_dir() / "timeline.db"


@contextmanager
def _conn():
    c = sqlite3.connect(str(db_path()), timeout=30)
    c.row_factory = sqlite3.Row
    try:
        c.executescript(SCHEMA)
        with c:
            yield c
    finally:
        c.close()


def _row(r: sqlite3.Row, with_embedding: bool = False) -> dict:
    d = dict(r)
    emb = d.pop("embedding", None)
    if with_embedding:
        d["embedding"] = json.loads(emb) if emb else None
    d["alternatives"] = json.loads(d["alternatives"]) if d.get("alternatives") else []
    d["graphiti"] = json.loads(d["graphiti"]) if d.get("graphiti") else None
    d["date"] = fmt_date(d["ts"])
    return d


def fmt_date(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def group_id(project: str | None) -> str:
    """group_id de Graphiti para las decisiones de un proyecto."""
    from memory.graphiti_client import safe_group_id
    return safe_group_id(f"ades-decisions-{project or DEFAULT_PROJECT}")


def _graphiti_enabled() -> bool:
    return os.getenv("ADES_TIMELINE_GRAPHITI", "1") != "0"


def _episode_text(title: str, rationale: str, alternatives: list[str], project: str,
                  when: float) -> str:
    alt = f" Alternativas descartadas: {', '.join(alternatives)}." if alternatives else ""
    return (f"El {fmt_date(when)}, en el proyecto {project}, el equipo decidió: {title}. "
            f"Motivo: {rationale}.{alt}")


def _graphiti_add(text: str, title: str, when: float, project: str) -> dict:
    """Ingiere la decisión en Graphiti (best-effort: nunca lanza)."""
    if not _graphiti_enabled():
        return {"ok": False, "skipped": True}
    try:
        from memory import graphiti_client
        r = graphiti_client.add_text(text, name=f"decision: {title[:80]}",
                                     source="ades-timeline", reference_time=when,
                                     group_id=group_id(project))
        return {"ok": True, **r}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}


def record_decision(title: str, rationale: str, project: str | None = None,
                    alternatives: list[str] | None = None,
                    when: float | None = None) -> dict:
    """Registra una decisión (registro local + episodio temporal en Graphiti).

    `when` es el epoch real de la decisión (por defecto, ahora).
    """
    title, rationale = (title or "").strip(), (rationale or "").strip()
    if not title:
        raise ValueError("record_decision: título vacío")
    project = project or DEFAULT_PROJECT
    alternatives = [a for a in (alternatives or []) if a]
    when = float(when) if when is not None else time.time()
    did = uuid.uuid4().hex[:16]
    emb = knowledge.embed(f"{title}. {rationale}")
    with _LOCK, _conn() as c:
        c.execute(
            "INSERT INTO decisions (id, ts, recorded, project, title, rationale, alternatives, "
            "embedding, graphiti) VALUES (?,?,?,?,?,?,?,?,NULL)",
            (did, when, time.time(), project, title, rationale,
             json.dumps(alternatives, ensure_ascii=False), json.dumps(emb) if emb else None))
    g = _graphiti_add(_episode_text(title, rationale, alternatives, project, when),
                      title, when, project)
    with _LOCK, _conn() as c:
        c.execute("UPDATE decisions SET graphiti=? WHERE id=?", (json.dumps(g), did))
        return _row(c.execute("SELECT * FROM decisions WHERE id=?", (did,)).fetchone())


def timeline(project: str | None = None, query: str | None = None,
             since: float | None = None, until: float | None = None) -> list[dict]:
    """Decisiones del proyecto en orden cronológico, filtradas por fechas.

    Con `query`, solo las relevantes (similitud ≥ QUERY_MIN_SIM o coincidencia
    literal), cada una con su `score`, también en orden cronológico.
    """
    project = project or DEFAULT_PROJECT
    where, params = ["project = ?"], [project]
    if since is not None:
        where.append("ts >= ?")
        params.append(since)
    if until is not None:
        where.append("ts <= ?")
        params.append(until)
    with _LOCK, _conn() as c:
        rows = c.execute(f"SELECT * FROM decisions WHERE {' AND '.join(where)} ORDER BY ts",
                         tuple(params)).fetchall()
    out = [_row(r, with_embedding=bool(query)) for r in rows]
    if not query:
        return out
    q_emb = knowledge.embed(query)
    ql = query.lower()
    sel = []
    for d in out:
        text = f"{d['title']}. {d['rationale']}"
        score = knowledge.similarity(query, q_emb, text, d.pop("embedding", None))
        if d["title"].lower() in ql or ql in text.lower():
            score = max(score, 1.0)
        if score >= QUERY_MIN_SIM:
            d["score"] = round(score, 4)
            sel.append(d)
    return sel


def _graphiti_facts(question: str, project: str, num: int = 8) -> list[dict] | None:
    """Hechos de Graphiti para la pregunta, o None si Graphiti no está disponible."""
    if not _graphiti_enabled():
        return None
    try:
        from memory import graphiti_client
        return graphiti_client.search(question, num=num, group_ids=[group_id(project)])
    except Exception:
        return None


def _short(iso: str | None) -> str:
    return (iso or "")[:10] or "fecha desconocida"


def _local_answer(question: str, decisions: list[dict]) -> str:
    lines = [f"Decisiones registradas relacionadas con: {question}"]
    for d in decisions:
        alt = f" (alternativas: {', '.join(d['alternatives'])})" if d["alternatives"] else ""
        lines.append(f"- {d['date']}: {d['title']} — {d['rationale']}{alt}")
    return "\n".join(lines)


WHY_SYSTEM = (
    "Eres el historiador de decisiones del proyecto. Responde en español, breve y "
    "concreto, a la pregunta del usuario usando SOLO el historial dado. Cita la fecha "
    "(AAAA-MM-DD) de cada decisión que menciones y explica el motivo. Si hubo cambios "
    "de decisión, explica la evolución en orden cronológico. Si el historial no "
    "responde la pregunta, dilo claramente; no inventes."
)


def why(question: str, project: str | None = None) -> str:
    """Responde "¿por qué decidimos X?" con el historial temporal y fechas.

    Busca en Graphiti (grafo temporal); si no está disponible, solo en el
    registro local. El LLM redacta la respuesta citando fechas; si el LLM falla,
    devuelve el listado de decisiones relevantes.
    """
    project = project or DEFAULT_PROJECT
    local = timeline(project, query=question)
    facts = _graphiti_facts(question, project)
    if not local and not facts:
        return f"No hay decisiones registradas en el proyecto {project} que respondan a: {question}"
    ctx = ["Historial de decisiones (registro local):"]
    for d in local[:8]:
        alt = f" Alternativas: {', '.join(d['alternatives'])}." if d["alternatives"] else ""
        ctx.append(f"- [{d['date']}] {d['title']}. Motivo: {d['rationale']}.{alt}")
    if facts:
        ctx.append("Hechos del grafo temporal (Graphiti):")
        for f in facts:
            inv = f" (dejó de ser válido {_short(f.get('invalid_at'))})" if f.get("invalid_at") else ""
            ctx.append(f"- [{_short(f.get('valid_at') or f.get('created_at'))}] {f.get('fact')}{inv}")
    try:
        from core.llm_gateway import chat
        res = chat("timeline", WHY_SYSTEM, question, context="\n".join(ctx), project=project)
        if res.text.strip():
            # Los LLM a veces escriben fechas con guiones Unicode (U+2010/2011/2013/2014):
            # se normalizan a "-" para que las fechas sean buscables (causa del fallo
            # intermitente del test live de timeline).
            return re.sub("[‐‑‒–—]", "-", res.text.strip())
    except Exception:
        pass
    return _local_answer(question, local) if local else "\n".join(ctx)


def forget_project(project: str) -> int:
    with _LOCK, _conn() as c:
        return c.execute("DELETE FROM decisions WHERE project=?", (project,)).rowcount


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Timeline de decisiones (#9)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_a = sub.add_parser("add", help="registra una decisión")
    p_a.add_argument("title")
    p_a.add_argument("rationale")
    p_a.add_argument("--project", default=None)
    p_a.add_argument("--alt", action="append", default=[])
    p_l = sub.add_parser("list", help="lista la timeline")
    p_l.add_argument("--project", default=None)
    p_l.add_argument("--query", default=None)
    p_w = sub.add_parser("why", help="¿por qué decidimos X?")
    p_w.add_argument("question")
    p_w.add_argument("--project", default=None)
    args = ap.parse_args(argv)
    if args.cmd == "add":
        d = record_decision(args.title, args.rationale, args.project, args.alt)
        print(f"[OK] {d['date']} {d['title']} (graphiti={d['graphiti']})")
    elif args.cmd == "list":
        for d in timeline(args.project, args.query):
            print(f"  {d['date']}  {d['title']} — {d['rationale']}")
    else:
        print(why(args.question, args.project))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
