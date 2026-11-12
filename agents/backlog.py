"""Backlog auto-gestionado ticket-driven (feature #2).

El PM mantiene un kanban persistente por proyecto en `.ades/<proyecto>/backlog.json`
(columnas: todo -> doing -> done | failed). Los Developers trabajan solos, en
background, hasta agotar los tickets: `work()` toma el siguiente ticket, ejecuta
la fábrica (Dev⇄QA con sandbox) y lo mueve a done/failed.

Uso:
    python -m agents.backlog add "Requerimiento grande" --project tienda   # el PM lo trocea
    python -m agents.backlog board --project tienda
    python -m agents.backlog work --project tienda [--max 5] [--background]
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
import uuid

from core.config import ROOT, state_dir

STATES = ("todo", "doing", "done", "failed")
_LOCK = threading.Lock()


def _path(project: str):
    return state_dir(project) / "backlog.json"


def load(project: str) -> dict:
    p = _path(project)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"tickets": []}


def save(project: str, data: dict) -> None:
    tmp = _path(project).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, _path(project))


def add_ticket(project: str, titulo: str, descripcion: str = "", criterios=None,
               origen: str = "", prioridad: int = 3) -> dict:
    with _LOCK:
        data = load(project)
        t = {"id": f"T-{len(data['tickets']) + 1:03d}-{uuid.uuid4().hex[:4]}",
             "titulo": titulo, "descripcion": descripcion, "criterios": criterios or [],
             "estado": "todo", "prioridad": prioridad, "origen": origen,
             "intentos": 0, "runs": [], "creado": time.time(), "actualizado": time.time()}
        data["tickets"].append(t)
        save(project, data)
        return t


def add_tickets(project: str, tickets: list[dict], origen: str = "") -> list[dict]:
    return [add_ticket(project, t.get("titulo", "ticket"), t.get("descripcion", ""),
                       t.get("criterios", []), origen) for t in tickets]


def plan_requirement(project: str, requerimiento: str, run_id: str | None = None) -> list[dict]:
    """El PM trocea un requerimiento grande en tickets y los añade al backlog."""
    from agents.pm import pm_node
    out = pm_node({"requerimiento": requerimiento, "project": project, "run_id": run_id})
    return add_tickets(project, out["tickets"], origen=requerimiento[:120])


def update(project: str, ticket_id: str, **changes) -> dict:
    with _LOCK:
        data = load(project)
        for t in data["tickets"]:
            if t["id"] == ticket_id:
                if "estado" in changes and changes["estado"] not in STATES:
                    raise ValueError(f"estado inválido: {changes['estado']}")
                t.update(changes)
                t["actualizado"] = time.time()
                save(project, data)
                return t
    raise KeyError(ticket_id)


def claim_next(project: str) -> dict | None:
    """Toma (atómicamente) el siguiente ticket `todo` por prioridad y lo pasa a `doing`."""
    with _LOCK:
        data = load(project)
        todo = sorted([t for t in data["tickets"] if t["estado"] == "todo"],
                      key=lambda t: (t["prioridad"], t["creado"]))
        if not todo:
            return None
        t = todo[0]
        t["estado"] = "doing"
        t["intentos"] += 1
        t["actualizado"] = time.time()
        save(project, data)
        return t


def board(project: str) -> dict:
    data = load(project)
    return {s: [t for t in data["tickets"] if t["estado"] == s] for s in STATES}


def ticket_requirement(t: dict) -> str:
    crit = "\n".join(f"- {c}" for c in t.get("criterios", []))
    return f"{t['titulo']}\n\n{t.get('descripcion', '')}" + (
        f"\n\nCriterios de aceptacion:\n{crit}" if crit else "")


def work(project: str, max_tickets: int | None = None, max_iter: int = 4,
         runner=None, max_attempts: int = 2) -> list[dict]:
    """Procesa tickets hasta agotarlos (o `max_tickets`). Devuelve los resultados.

    `runner(requerimiento, project, ticket) -> dict` (por defecto la fábrica). Un
    ticket que falla vuelve a `todo` hasta `max_attempts` intentos; luego `failed`.
    """
    if runner is None:
        from agents.orquestador import run as factory_run

        def runner(req, proj, ticket):
            return factory_run(req, max_iteraciones=max_iter, project=proj,
                               skip_pm=True, tickets=[ticket])
    done = []
    while max_tickets is None or len(done) < max_tickets:
        t = claim_next(project)
        if t is None:
            break
        try:
            res = runner(ticket_requirement(t), project, t)
            ok = res.get("estado") == "ok"
            err = "" if ok else (res.get("qa_feedback") or "")[:500]
            run_id = res.get("run_id", "")
        except Exception as e:  # noqa: BLE001
            ok, err, run_id = False, f"{type(e).__name__}: {e}"[:500], ""
        if ok:
            estado = "done"
        else:
            estado = "failed" if t["intentos"] >= max_attempts else "todo"
        update(project, t["id"], estado=estado, ultimo_error=err,
               runs=t["runs"] + ([run_id] if run_id else []))
        done.append({"ticket": t["id"], "estado": estado, "run_id": run_id})
    return done


def work_background(project: str, max_tickets: int | None = None) -> int:
    """Lanza el worker en un proceso desacoplado. Devuelve el PID."""
    args = [sys.executable, "-m", "agents.backlog", "work", "--project", project]
    if max_tickets:
        args += ["--max", str(max_tickets)]
    log = open(state_dir(project) / "backlog_worker.log", "a", encoding="utf-8")
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    p = subprocess.Popen(args, cwd=str(ROOT), stdout=log, stderr=log, creationflags=flags)
    (state_dir(project) / "backlog_worker.pid").write_text(str(p.pid))
    return p.pid


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Backlog auto-gestionado (#2)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("requerimiento")
    a.add_argument("--project", default="ades-ai")
    a.add_argument("--raw", action="store_true", help="añadir como ticket sin pasar por el PM")
    b = sub.add_parser("board")
    b.add_argument("--project", default="ades-ai")
    w = sub.add_parser("work")
    w.add_argument("--project", default="ades-ai")
    w.add_argument("--max", type=int, default=None)
    w.add_argument("--background", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "add":
        ts = ([add_ticket(args.project, args.requerimiento)] if args.raw
              else plan_requirement(args.project, args.requerimiento))
        for t in ts:
            print(f"  + {t['id']} {t['titulo']}")
    elif args.cmd == "board":
        for s, ts in board(args.project).items():
            print(f"[{s}] ({len(ts)})")
            for t in ts:
                print(f"   {t['id']} {t['titulo']} (intentos {t['intentos']})")
    elif args.cmd == "work":
        if args.background:
            print(f"worker en background, PID {work_background(args.project, args.max)}")
        else:
            for r in work(args.project, args.max):
                print(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
