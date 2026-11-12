"""Almacén persistente de métricas de llamadas LLM (SQLite).

Fuente de datos del Token Budget Governor (#10), del Cache Hit-Rate Dashboard
en vivo (#11), del dashboard web (#27) y del CLI `ades tokens` (#26).
Cada llamada se registra también en Langfuse vía `evals.tracing`.
"""
import sqlite3
import threading
import time
from pathlib import Path

from core.config import global_state_dir

_LOCK = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL, project TEXT, run_id TEXT, task TEXT, agent TEXT,
    provider TEXT, model TEXT, effort TEXT,
    tokens_in INTEGER, tokens_out INTEGER, cost REAL,
    cache_hit INTEGER, latency REAL, ok INTEGER, error TEXT,
    fallback_from TEXT
);
CREATE INDEX IF NOT EXISTS idx_calls_project ON calls(project);
CREATE INDEX IF NOT EXISTS idx_calls_run ON calls(run_id);
"""


def db_path() -> Path:
    return global_state_dir() / "metrics.db"


def _conn(path: Path | None = None) -> sqlite3.Connection:
    c = sqlite3.connect(str(path or db_path()), timeout=30)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def record(project: str, run_id: str, task: str, agent: str, provider: str, model: str,
           tokens_in: int, tokens_out: int, cost: float, cache_hit: bool = False,
           latency: float = 0.0, ok: bool = True, error: str = "", effort: str = "",
           fallback_from: str = "", path: Path | None = None) -> None:
    with _LOCK, _conn(path) as c:
        c.execute(
            "INSERT INTO calls (ts, project, run_id, task, agent, provider, model, effort, "
            "tokens_in, tokens_out, cost, cache_hit, latency, ok, error, fallback_from) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (time.time(), project, run_id, task, agent, provider, model, effort,
             int(tokens_in), int(tokens_out), float(cost), int(cache_hit), float(latency),
             int(ok), error[:500], fallback_from),
        )


def query(sql: str, params: tuple = (), path: Path | None = None) -> list[dict]:
    with _LOCK, _conn(path) as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def summary(project: str | None = None, run_id: str | None = None,
            path: Path | None = None) -> dict:
    where, params = [], []
    if project:
        where.append("project = ?")
        params.append(project)
    if run_id:
        where.append("run_id = ?")
        params.append(run_id)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    rows = query(
        f"SELECT COUNT(*) AS calls, COALESCE(SUM(cache_hit),0) AS hits, "
        f"COALESCE(SUM(tokens_in),0) AS tin, COALESCE(SUM(tokens_out),0) AS tout, "
        f"COALESCE(SUM(cost),0) AS cost, "
        f"COALESCE(SUM(CASE WHEN cost = 0 AND cache_hit = 0 THEN tokens_in + tokens_out ELSE 0 END),0) AS local_tokens, "
        f"COALESCE(SUM(1-ok),0) AS errors FROM calls {w}", tuple(params), path)
    r = rows[0]
    by_agent = query(
        f"SELECT agent, model, COUNT(*) AS calls, SUM(cache_hit) AS hits, "
        f"SUM(tokens_in + tokens_out) AS tokens, SUM(cost) AS cost FROM calls {w} "
        f"GROUP BY agent, model ORDER BY cost DESC", tuple(params), path)
    return {
        "calls": r["calls"], "cache_hits": r["hits"],
        "hit_rate": round(r["hits"] / r["calls"], 3) if r["calls"] else 0.0,
        "tokens_in": r["tin"], "tokens_out": r["tout"],
        "cost": round(r["cost"], 6), "local_tokens": r["local_tokens"],
        "errors": r["errors"], "by_agent": by_agent,
    }


def spent(project: str, path: Path | None = None) -> dict:
    r = query("SELECT COALESCE(SUM(cost),0) AS cost, "
              "COALESCE(SUM(CASE WHEN cost > 0 THEN tokens_in + tokens_out ELSE 0 END),0) AS paid_tokens "
              "FROM calls WHERE project = ?", (project,), path)[0]
    return {"cost": r["cost"], "paid_tokens": r["paid_tokens"]}
