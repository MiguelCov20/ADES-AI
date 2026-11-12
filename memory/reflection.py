"""Consolidación nocturna / Reflection (feature #7) - ADES-AI.

Proceso batch (pensado para correr de madrugada) que:
  1. Lee la actividad del periodo: runs (métricas de llamadas LLM), decisiones
     (timeline), recuerdos nuevos (knowledge) y vacunas nuevas.
  2. Resume con el LLM las lecciones del día y las guarda como
     `knowledge.remember(kind="lesson", scope="project")`.
  3. Deduplica memorias casi iguales (similitud de embeddings ≥ 0.95) en
     knowledge y en vacunas: conserva la más reciente y acumula `hits`.
  4. Compacta los almacenes SQLite (VACUUM).

`dry_run=True` no escribe, no borra y no llama al LLM: solo informa de lo que
haría.

Uso:
    python -m memory.reflection [--project P | --all] [--hours 24] [--dry-run]
    python -m memory.reflection --schedule [--hour 3] [--create]
"""
import argparse
import json
import re
import subprocess
import sys
import time

from core.config import DEFAULT_PROJECT, ROOT, state_dir
from memory import knowledge, timeline, vaccine

DEDUPE_THRESHOLD = 0.95
MAX_LESSONS = 5
TASK_NAME = r"ADES-AI\Reflection"


# ---------------------------------------------------------------------------
# Lectura de actividad
# ---------------------------------------------------------------------------
def _runs(project: str, since: float, until: float) -> list[dict]:
    """Runs del periodo agregados desde el almacén de métricas (best-effort)."""
    try:
        from core import metrics_store
        return metrics_store.query(
            "SELECT run_id, MIN(task) AS task, COUNT(*) AS calls, "
            "SUM(1-ok) AS errors, MAX(error) AS last_error, SUM(cost) AS cost "
            "FROM calls WHERE project = ? AND ts >= ? AND ts <= ? GROUP BY run_id "
            "ORDER BY MIN(ts)", (project, since, until))
    except Exception:
        return []


def _activity(project: str, since: float, until: float) -> dict:
    return {
        "runs": _runs(project, since, until),
        "decisions": timeline.timeline(project, since=since, until=until),
        "memories": [m for m in knowledge.items(project, since=since)
                     if m["updated"] <= until and m["source"] != "reflection"],
        "vaccines": [v for v in vaccine.all_vaccines(since=since)
                     if v["project"] == project and v["updated"] <= until],
    }


def _activity_text(act: dict) -> str:
    parts = []
    if act["runs"]:
        parts.append("Runs de la fábrica:")
        for r in act["runs"][:30]:
            err = f", errores={r['errors']} ({(r['last_error'] or '')[:150]})" if r["errors"] else ""
            parts.append(f"- {r['task'] or r['run_id']}: llamadas={r['calls']}{err}")
    if act["decisions"]:
        parts.append("Decisiones:")
        parts += [f"- [{d['date']}] {d['title']}: {d['rationale']}" for d in act["decisions"][:30]]
    if act["memories"]:
        parts.append("Memorias nuevas:")
        parts += [f"- ({m['kind']}) {m['text']}" for m in act["memories"][:30]]
    if act["vaccines"]:
        parts.append("Bugs resueltos (vacunas):")
        parts += [f"- {v['signature']}" for v in act["vaccines"][:30]]
    return "\n".join(parts)


REFLECT_SYSTEM = (
    "Eres el proceso de reflexión nocturna de una fábrica de software multi-agente. "
    "A partir de la actividad del día, extrae como máximo {n} lecciones accionables y "
    "generalizables (qué repetir, qué evitar) para futuros trabajos. Responde en español, "
    "una lección por línea, cada línea empezando por '- '. Sin introducción ni cierre. "
    "Si no hay nada que aprender, responde exactamente: NINGUNA"
)


def _parse_lessons(text: str) -> list[str]:
    out = []
    for ln in (text or "").splitlines():
        m = re.match(r"^\s*(?:[-*•]|\d+[.)])\s+(.+)$", ln)
        if m:
            lesson = m.group(1).strip()
            if len(lesson) > 8:
                out.append(lesson[:500])
    return out[:MAX_LESSONS]


# ---------------------------------------------------------------------------
# Deduplicación
# ---------------------------------------------------------------------------
def _dedupe_groups(rows: list[dict], key, emb_field: str, text_field: str,
                   threshold: float) -> list[tuple[dict, list[dict]]]:
    """Agrupa filas casi idénticas. Devuelve [(superviviente, [duplicados])].

    Solo compara filas con la misma `key(row)` (p.ej. kind/scope/proyecto).
    Superviviente = la más reciente del grupo.
    """
    buckets: dict = {}
    for r in rows:
        buckets.setdefault(key(r), []).append(r)
    result = []
    for group in buckets.values():
        group.sort(key=lambda r: r["updated"], reverse=True)
        used = set()
        for i, keep in enumerate(group):
            if keep["id"] in used:
                continue
            dups = []
            for other in group[i + 1:]:
                if other["id"] in used:
                    continue
                a, b = keep.get(emb_field), other.get(emb_field)
                if a and b:
                    sim = knowledge.cosine(a, b)
                else:
                    sim = 1.0 if knowledge.normalize(keep[text_field]) == \
                        knowledge.normalize(other[text_field]) else 0.0
                if sim >= threshold:
                    dups.append(other)
                    used.add(other["id"])
            if dups:
                result.append((keep, dups))
    return result


def _dedupe_knowledge(project: str, dry_run: bool) -> list[dict]:
    rows = knowledge.items(project, with_embedding=True)
    groups = _dedupe_groups(rows, lambda r: (r["kind"], r["scope"], r["project"]),
                            "embedding", "text", DEDUPE_THRESHOLD)
    report = []
    for keep, dups in groups:
        report.append({"keep": keep["text"], "removed": [d["text"] for d in dups]})
        if not dry_run:
            knowledge.bump(keep["id"], hits=sum(d["hits"] for d in dups))
            knowledge.forget([d["id"] for d in dups])
    return report


def _dedupe_vaccines(dry_run: bool) -> list[dict]:
    rows = vaccine.all_vaccines(with_embedding=True)
    # Solo se fusionan vacunas de la misma firma casi idéntica Y la misma corrección.
    groups = _dedupe_groups(rows, lambda r: (r["error_type"], knowledge.normalize(r["fix"])),
                            "sig_embedding", "signature", DEDUPE_THRESHOLD)
    report = []
    for keep, dups in groups:
        report.append({"keep": keep["signature"], "removed": [d["signature"] for d in dups]})
        if not dry_run:
            vaccine.bump(keep["id"], hits=sum(d["hits"] for d in dups))
            vaccine.forget([d["id"] for d in dups])
    return report


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------
def consolidate(project: str | None = None, since: float | None = None,
                dry_run: bool = False) -> dict:
    """Consolida la memoria del proyecto (por defecto, las últimas 24 h)."""
    project = project or DEFAULT_PROJECT
    until = time.time()
    since = since if since is not None else until - 86400
    act = _activity(project, since, until)
    counts = {
        "runs": len(act["runs"]),
        "failed_runs": sum(1 for r in act["runs"] if r["errors"]),
        "decisions": len(act["decisions"]),
        "memories": len(act["memories"]),
        "vaccines": len(act["vaccines"]),
    }
    lessons, saved, llm_error = [], [], ""
    activity_text = _activity_text(act)
    if activity_text and not dry_run:
        try:
            from core.llm_gateway import chat
            res = chat("reflection", REFLECT_SYSTEM.format(n=MAX_LESSONS),
                       "Extrae las lecciones del día.", context=activity_text,
                       project=project, use_cache=False)
            lessons = [] if res.text.strip().upper().startswith("NINGUNA") \
                else _parse_lessons(res.text)
        except Exception as e:  # noqa: BLE001
            llm_error = f"{type(e).__name__}: {str(e)[:200]}"
        for lesson in lessons:
            saved.append(knowledge.remember(lesson, kind="lesson", project=project,
                                            scope="project", source="reflection")["id"])
    dedup_k = _dedupe_knowledge(project, dry_run)
    dedup_v = _dedupe_vaccines(dry_run)
    if not dry_run:
        for fn in (knowledge.vacuum, vaccine.vacuum):
            try:
                fn()
            except Exception:
                pass
    report = {
        "project": project, "since": since, "until": until, "dry_run": dry_run,
        "activity": counts, "lessons": lessons, "saved_lesson_ids": saved,
        "deduped": {"knowledge": sum(len(g["removed"]) for g in dedup_k),
                    "vaccines": sum(len(g["removed"]) for g in dedup_v)},
        "dedupe_detail": {"knowledge": dedup_k, "vaccines": dedup_v},
        "llm_error": llm_error,
    }
    if not dry_run:
        try:
            (state_dir(project) / "reflection_last.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    return report


def schedule_nightly(hour: int = 3, dry_run: bool = True) -> str:
    """Comando `schtasks` que programa la consolidación diaria a las `hour`:00.

    Con `dry_run=True` (por defecto) solo devuelve el comando, NO crea la tarea.
    """
    if not 0 <= int(hour) <= 23:
        raise ValueError("schedule_nightly: hora fuera de rango (0-23)")
    action = f'cmd /c cd /d "{ROOT}" && "{sys.executable}" -m memory.reflection --all'
    args = ["schtasks", "/Create", "/F", "/SC", "DAILY", "/ST", f"{int(hour):02d}:00",
            "/TN", TASK_NAME, "/TR", action]
    cmd = subprocess.list2cmdline(args)
    if not dry_run:
        subprocess.run(args, check=True, capture_output=True, text=True)
    return cmd


def _all_projects() -> list[str]:
    try:
        from core import projects
        return [p["id"] for p in projects.list_projects()]
    except Exception:
        return [DEFAULT_PROJECT]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Consolidación nocturna (#7)")
    ap.add_argument("--project", default=None)
    ap.add_argument("--all", action="store_true", help="todos los proyectos registrados")
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--schedule", action="store_true", help="muestra/crea la tarea programada")
    ap.add_argument("--hour", type=int, default=3)
    ap.add_argument("--create", action="store_true", help="con --schedule: crea la tarea")
    args = ap.parse_args(argv)
    if args.schedule:
        print(schedule_nightly(args.hour, dry_run=not args.create))
        return 0
    since = time.time() - args.hours * 3600
    for p in (_all_projects() if args.all else [args.project or DEFAULT_PROJECT]):
        r = consolidate(p, since=since, dry_run=args.dry_run)
        print(f"[OK] {p}: actividad={r['activity']} lecciones={len(r['lessons'])} "
              f"deduplicados={r['deduped']}" + (f" llm_error={r['llm_error']}" if r["llm_error"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
