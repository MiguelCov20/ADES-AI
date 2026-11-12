"""KPI 2 (costo local $0 en codificación iterativa) y KPI 3 (Dev⇄QA en bucle cerrado).

Método: se ejecuta la fábrica REAL (PM/Arquitecto en nube, Developer/QA locales,
QA con sandbox Docker y tests de aceptación propios) sobre varios requerimientos,
con ADES_SELF_HEAL_CLOUD=0 para que todo el bucle Dev⇄QA sea local. Nadie
interviene durante la ejecución.

  KPI 2: costo de TODAS las llamadas de los agentes developer y qa = $0
         (leído del almacén de métricas, que es lo mismo que se envía a Langfuse).
  KPI 3: todos los requerimientos terminan en estado ok con los tests en verde en
         el sandbox, sin intervención humana. Se informa cuántos necesitaron
         corrección (iteración > 1), que es la evidencia de que el bucle corrige.
"""
import json
import os
import time

from core import metrics_store, projects
from core.config import global_state_dir

REQS = [
    "Modulo Python `inventario.py` con una clase Inventario: agregar(producto, cantidad), "
    "retirar(producto, cantidad) que lanza ValueError si no hay stock suficiente, y "
    "stock(producto) que devuelve 0 si no existe.",
    "API FastAPI `app.py` con GET /convertir?celsius=<float> que devuelve {'fahrenheit': x} "
    "redondeado a 2 decimales, y 422 si falta el parametro.",
    "Funcion `parse_duracion(texto)` en `duracion.py` que convierte '1h30m', '45s', '2h' en "
    "segundos (int) y lanza ValueError con formatos invalidos.",
]


def run(reqs=None, max_iter: int = 4) -> dict:
    os.environ["ADES_SELF_HEAL_CLOUD"] = "0"
    from agents.orquestador import run as factory
    ts = time.strftime("%Y%m%d-%H%M%S")
    pid = projects.create(f"kpi-loop-{ts}")["id"]
    rows = []
    for req in reqs or REQS:
        r = factory(req, max_iteraciones=max_iter, project=pid)
        calls = metrics_store.query(
            "SELECT agent, provider, model, cost, cache_hit FROM calls WHERE run_id=?", (r["run_id"],))
        loop = [c for c in calls if c["agent"] in ("developer", "qa")]
        rows.append({
            "run_id": r["run_id"], "estado": r["estado"], "iteraciones": r.get("iteracion"),
            "estrategias": r.get("estrategias"), "sandbox": r.get("sandbox"),
            "llamadas_dev_qa": len(loop),
            "modelos_dev_qa": sorted({f"{c['provider']}/{c['model']}" for c in loop}),
            "costo_dev_qa": round(sum(c["cost"] for c in loop), 6),
            "costo_total_run": round(sum(c["cost"] for c in calls), 6),
            "duracion_s": r.get("duracion_s"),
        })
        print(f"  {r['estado']} it={r.get('iteracion')} sandbox={r.get('sandbox')} "
              f"dev/qa=${rows[-1]['costo_dev_qa']} total=${rows[-1]['costo_total_run']}")
    res = {
        "fecha": ts, "proyecto": pid, "runs": rows,
        "kpi2": all(x["costo_dev_qa"] == 0 for x in rows),
        "kpi3": all(x["estado"] == "ok" and (x["sandbox"] or {}).get("passed") for x in rows),
        "runs_con_correccion": sum(1 for x in rows if (x["iteraciones"] or 0) > 1),
    }
    d = global_state_dir() / "kpis"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"kpi23_{ts}.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    return res


def main(argv=None) -> int:
    r = run()
    print(json.dumps({k: v for k, v in r.items() if k != "runs"}, indent=2))
    return 0 if (r["kpi2"] and r["kpi3"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
