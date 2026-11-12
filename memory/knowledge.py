"""Memoria cross-proyecto (feature #6) - ADES-AI.

Almacén persistente de conocimiento (preferencias, decisiones, lecciones y
hechos) compartido entre proyectos:

  - SQLite en `global_state_dir()/knowledge.db`, con el embedding de cada
    recuerdo guardado (nomic-embed-text vía Ollama) para buscar por similitud.
  - `scope="global"`: lo aprendido en el proyecto A (p.ej. "prefiero FastAPI")
    aparece en `recall` del proyecto B. `scope="project"`: solo en ese proyecto.
  - Sincronización best-effort con Mem0 (`memory/mem0_client.py`) solo si
    `ADES_MEM0_SYNC=1` (desactivada por defecto: Mem0 llama a un LLM de pago
    en cada `add`).

Si Ollama no responde, el recuerdo se guarda sin embedding y la búsqueda cae a
similitud léxica (Jaccard de palabras), así la memoria nunca bloquea la fábrica.

Uso:
    python -m memory.knowledge remember "prefiero FastAPI" [--kind preference] [--scope global]
    python -m memory.knowledge recall "qué framework web uso" [--project P]
"""
import argparse
import json
import math
import os
import re
import sqlite3
import sys
import threading
import time
import urllib.request
import uuid
from contextlib import contextmanager
from pathlib import Path

from core.config import DEFAULT_PROJECT, OLLAMA_URL, global_state_dir

KINDS = ("preference", "decision", "lesson", "fact")
SCOPES = ("global", "project")
EMBED_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
# Peso de la recencia en el ranking (el resto es similitud semántica).
RECENCY_WEIGHT = 0.15
RECENCY_HALF_LIFE_DAYS = 30.0
# Similitud mínima para que un recuerdo entre en el prompt (recall_context).
CONTEXT_MIN_SIM = float(os.getenv("ADES_RECALL_MIN_SIM", "0.62"))

_LOCK = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    ts REAL, updated REAL,
    kind TEXT, scope TEXT, project TEXT,
    text TEXT, norm TEXT, source TEXT,
    embedding TEXT, hits INTEGER DEFAULT 1,
    mem0 TEXT
);
CREATE INDEX IF NOT EXISTS idx_items_scope ON items(scope, project);
CREATE INDEX IF NOT EXISTS idx_items_ts ON items(ts);
"""


# ---------------------------------------------------------------------------
# Embeddings y similitud (compartidos con vaccine/timeline/reflection)
# ---------------------------------------------------------------------------
def _embed(text: str, prefix: str = "search_query: ") -> list[float]:
    """Embedding con Ollama (nomic-embed-text). Lanza excepción si no responde."""
    payload = json.dumps({"model": EMBED_MODEL,
                          "input": prefix + text[:8000]}).encode("utf-8")
    req = urllib.request.Request(f"{OLLAMA_URL}/api/embed", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))["embeddings"][0]


def embed(text: str) -> list[float] | None:
    """Embedding best-effort: devuelve None si Ollama no está disponible."""
    try:
        return _embed(text)
    except Exception:
        return None


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", text.lower()) if len(w) > 2}


def lexical(a: str, b: str) -> float:
    """Similitud léxica (Jaccard de palabras) para cuando no hay embeddings."""
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


def similarity(q_text: str, q_emb: list[float] | None, text: str,
               emb: list[float] | None) -> float:
    if q_emb and emb and len(q_emb) == len(emb):
        return cosine(q_emb, emb)
    return lexical(q_text, text)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def recency(ts: float, now: float | None = None) -> float:
    age_days = max(0.0, ((now or time.time()) - ts) / 86400)
    return 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)


# ---------------------------------------------------------------------------
# Almacén SQLite
# ---------------------------------------------------------------------------
def db_path() -> Path:
    return global_state_dir() / "knowledge.db"


@contextmanager
def _conn():
    """Conexión con commit al salir y cierre garantizado."""
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
    d.pop("norm", None)
    emb = d.pop("embedding", None)
    if with_embedding:
        d["embedding"] = json.loads(emb) if emb else None
    d["mem0"] = json.loads(d["mem0"]) if d.get("mem0") else None
    return d


def _mem0_sync(text: str, scope: str, project: str) -> dict | None:
    """Envía el recuerdo a Mem0 si ADES_MEM0_SYNC=1 (best-effort, nunca lanza)."""
    if os.getenv("ADES_MEM0_SYNC", "0") != "1":
        return None
    user_id = "ades-global" if scope == "global" else f"ades-{project}"
    try:
        from memory import mem0_client
        res = mem0_client.add(text, user_id=user_id)
        n = len(res.get("results", [])) if isinstance(res, dict) else 0
        return {"ok": True, "user_id": user_id, "memories": n}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "user_id": user_id, "error": f"{type(e).__name__}: {str(e)[:200]}"}


def remember(text: str, kind: str = "preference", project: str | None = None,
             scope: str = "global", source: str = "usuario") -> dict:
    """Guarda un recuerdo. `scope="global"` lo comparte entre todos los proyectos.

    Si ya existe exactamente el mismo texto (mismo kind/scope/proyecto) no se
    duplica: se refresca su fecha y se incrementa `hits`.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("remember: texto vacío")
    if kind not in KINDS:
        raise ValueError(f"remember: kind '{kind}' inválido (usa {', '.join(KINDS)})")
    if scope not in SCOPES:
        raise ValueError(f"remember: scope '{scope}' inválido (usa {', '.join(SCOPES)})")
    project = project or DEFAULT_PROJECT
    now = time.time()
    norm = normalize(text)
    with _LOCK, _conn() as c:
        if scope == "global":  # un recuerdo global es el mismo venga del proyecto que venga
            dup = c.execute("SELECT * FROM items WHERE norm=? AND kind=? AND scope='global'",
                            (norm, kind)).fetchone()
        else:
            dup = c.execute(
                "SELECT * FROM items WHERE norm=? AND kind=? AND scope=? AND project=?",
                (norm, kind, scope, project)).fetchone()
        if dup is not None:
            c.execute("UPDATE items SET updated=?, hits=hits+1 WHERE id=?", (now, dup["id"]))
            out = _row(c.execute("SELECT * FROM items WHERE id=?", (dup["id"],)).fetchone())
            out["duplicate"] = True
            return out
    emb = embed(text)
    mem0 = _mem0_sync(text, scope, project)
    item_id = uuid.uuid4().hex[:16]
    with _LOCK, _conn() as c:
        c.execute(
            "INSERT INTO items (id, ts, updated, kind, scope, project, text, norm, source, "
            "embedding, hits, mem0) VALUES (?,?,?,?,?,?,?,?,?,?,1,?)",
            (item_id, now, now, kind, scope, project, text, norm, source,
             json.dumps(emb) if emb else None, json.dumps(mem0) if mem0 else None))
        out = _row(c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone())
    out["duplicate"] = False
    return out


def items(project: str | None = None, since: float | None = None,
          kinds: list[str] | None = None, include_global: bool = True,
          with_embedding: bool = False, all_projects: bool = False) -> list[dict]:
    """Lista recuerdos visibles desde `project` (globales + del proyecto)."""
    where, params = [], []
    if not all_projects:
        project = project or DEFAULT_PROJECT
        if include_global:
            where.append("(scope='global' OR (scope='project' AND project=?))")
        else:
            where.append("(scope='project' AND project=?)")
        params.append(project)
    if since is not None:
        where.append("updated >= ?")
        params.append(since)
    if kinds:
        where.append(f"kind IN ({','.join('?' * len(kinds))})")
        params.extend(kinds)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    with _LOCK, _conn() as c:
        rows = c.execute(f"SELECT * FROM items {w} ORDER BY ts", tuple(params)).fetchall()
    return [_row(r, with_embedding) for r in rows]


def recall(query: str, project: str | None = None, k: int = 5,
           kinds: list[str] | None = None) -> list[dict]:
    """Recupera los `k` recuerdos más relevantes (globales + del proyecto).

    Ranking = (1-RECENCY_WEIGHT)·similitud + RECENCY_WEIGHT·recencia. Cada
    resultado incluye `similarity` y `score`.
    """
    cands = items(project, kinds=kinds, with_embedding=True)
    if not cands or k <= 0:
        return []
    q_emb = embed(query)
    now = time.time()
    for it in cands:
        sim = similarity(query, q_emb, it["text"], it.pop("embedding"))
        it["similarity"] = round(sim, 4)
        it["score"] = round((1 - RECENCY_WEIGHT) * sim
                            + RECENCY_WEIGHT * recency(it["updated"], now), 4)
    cands.sort(key=lambda d: d["score"], reverse=True)
    return cands[:k]


_LABELS = {"preference": "Preferencia", "decision": "Decisión",
           "lesson": "Lección", "fact": "Hecho"}


def recall_context(query: str, project: str | None = None, k: int = 5) -> str:
    """Texto compacto con los recuerdos relevantes para el prompt ("" si no hay)."""
    hits = [h for h in recall(query, project, k) if h["similarity"] >= CONTEXT_MIN_SIM]
    if not hits:
        return ""
    lines = ["Memoria del usuario (preferencias/decisiones/lecciones previas):"]
    for h in hits:
        origin = "global" if h["scope"] == "global" else f"proyecto {h['project']}"
        lines.append(f"- [{_LABELS.get(h['kind'], h['kind'])}, {origin}] {h['text']}")
    return "\n".join(lines)


def forget(item_ids: list[str]) -> int:
    """Borra recuerdos por id. Devuelve cuántos se borraron."""
    if not item_ids:
        return 0
    with _LOCK, _conn() as c:
        cur = c.execute(f"DELETE FROM items WHERE id IN ({','.join('?' * len(item_ids))})",
                        tuple(item_ids))
        return cur.rowcount


def bump(item_id: str, hits: int = 1, updated: float | None = None) -> None:
    """Suma `hits` a un recuerdo (usado al fusionar duplicados)."""
    with _LOCK, _conn() as c:
        c.execute("UPDATE items SET hits=hits+?, updated=MAX(updated, ?) WHERE id=?",
                  (hits, updated or 0, item_id))


def forget_project(project: str) -> int:
    """Borra todos los recuerdos con ese proyecto (ambos scopes)."""
    with _LOCK, _conn() as c:
        return c.execute("DELETE FROM items WHERE project=?", (project,)).rowcount


def vacuum() -> None:
    with _LOCK:
        c = sqlite3.connect(str(db_path()), timeout=30)
        try:
            c.execute("VACUUM")
        finally:
            c.close()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Memoria cross-proyecto (#6)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_r = sub.add_parser("remember", help="guarda un recuerdo")
    p_r.add_argument("text")
    p_r.add_argument("--kind", default="preference", choices=KINDS)
    p_r.add_argument("--scope", default="global", choices=SCOPES)
    p_r.add_argument("--project", default=None)
    p_q = sub.add_parser("recall", help="busca recuerdos")
    p_q.add_argument("query")
    p_q.add_argument("--project", default=None)
    p_q.add_argument("-k", type=int, default=5)
    args = ap.parse_args(argv)
    if args.cmd == "remember":
        r = remember(args.text, args.kind, args.project, args.scope)
        print(f"[OK] {'(ya existía) ' if r['duplicate'] else ''}{r['id']}: {r['text']}")
    else:
        for h in recall(args.query, args.project, args.k):
            print(f"  {h['score']:.3f} [{h['kind']}/{h['scope']}:{h['project']}] {h['text']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
