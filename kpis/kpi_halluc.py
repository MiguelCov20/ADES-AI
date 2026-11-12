"""KPI 4 — Anti-alucinación: el agente no referencia clases inexistentes.

Método:
  Tareas que obligan a usar APIs internas reales de ADES-AI. Para cada una el
  Developer (gpt-oss:20b local, mismo prompt de la fábrica) genera código con el
  RepoMap del grafo como contexto; el validador (memory.validator, contra Neo4j)
  rechaza referencias inexistentes y se reintenta (igual que el nodo QA).

  Verificación INDEPENDIENTE del resultado final (no se fía del propio grafo):
  cada `from paquete.mod import Nombre`, `import paquete.mod` y `mod.Atributo` del
  proyecto se comprueba importando el módulo real y usando `hasattr`.

  También se mide la tasa de alucinación del primer intento SIN mapa del repo
  (baseline) para mostrar qué aporta el grafo.

Criterio KPI: 0 referencias inexistentes en las entregas finales (verificación
independiente) en el 100% de las tareas.
"""
import ast
import importlib
import json
import time

from agents.prompts import get_prompt
from core.config import ROOT, global_state_dir
from core.llm_gateway import chat
from core.sandbox import extract_files
from memory.validator import GraphIndex, validate_files

TASKS = [
    "Escribe informe.py con una funcion `informe(project)` que use core.metrics_store.summary y "
    "core.budget.status para devolver un dict con costo, hit-rate y nivel de presupuesto.",
    "Escribe limpiar.py con una funcion que use la clase SemanticCache de cache.semantic_cache "
    "para vaciar la cache de un namespace y devolver cuantas entradas habia.",
    "Escribe ruta.py con una funcion `modelo_para(tarea)` que use agents.router.route_task sin "
    "LLM (use_llm=False) y devuelva el string 'provider/model'.",
    "Escribe tablero.py con una funcion que use agents.backlog para crear un ticket en el "
    "proyecto 'demo' y devolver el tablero.",
    "Escribe costos.py con una funcion que use cache.token_metrics.TokenMetrics para registrar "
    "dos llamadas y devolver el report().",
    "Escribe proyectos.py con una funcion que use core.projects para crear un proyecto y listar "
    "todos los ids.",
    "Escribe gpu.py con una funcion que use core.gpu_manager.plan_for para decidir que descargar "
    "antes de cargar gpt-oss:20b dados unos modelos cargados de ejemplo.",
    "Escribe validar.py con una funcion que use memory.validator.validate_code con un GraphIndex "
    "vacio y devuelva la lista de hallazgos como strings.",
]


def independent_check(code: str, top_packages: set) -> list[str]:
    """Comprueba con imports reales que cada referencia al proyecto existe."""
    bad = []
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"syntax: {e}"]
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0 \
                and node.module.split(".")[0] in top_packages:
            try:
                mod = importlib.import_module(node.module)
            except Exception as e:  # noqa: BLE001
                bad.append(f"{node.module} ({type(e).__name__})")
                continue
            for a in node.names:
                if a.name != "*" and not hasattr(mod, a.name):
                    try:
                        importlib.import_module(f"{node.module}.{a.name}")
                    except Exception:
                        bad.append(f"{node.module}.{a.name}")
                aliases[a.asname or a.name] = f"{node.module}.{a.name}"
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] in top_packages:
                    try:
                        importlib.import_module(a.name)
                        aliases[a.asname or a.name.split(".")[0]] = a.asname and a.name or a.name.split(".")[0]
                    except Exception:
                        bad.append(a.name)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                and node.value.id in aliases:
            target = aliases[node.value.id]
            try:
                obj = importlib.import_module(target)
            except Exception:
                parent, _, name = target.rpartition(".")
                try:
                    obj = getattr(importlib.import_module(parent), name)
                except Exception:
                    continue
            if isinstance(obj, type(importlib)) and not hasattr(obj, node.attr):
                bad.append(f"{target}.{node.attr}")
    return sorted(set(bad))


def run(max_attempts: int = 4) -> dict:
    from memory.indexer import _driver_from_env, index_repo
    from memory.repomap import generate_repomap
    d = _driver_from_env()
    try:
        index_repo(str(ROOT), d)
        idx = GraphIndex.from_neo4j(d, repo=str(ROOT.resolve()))
        repomap = generate_repomap(d, repo=str(ROOT))
    finally:
        d.close()
    tops = {"core", "agents", "cache", "memory", "registry", "evals", "automation"} & idx.top_packages
    ts = time.strftime("%Y%m%d-%H%M%S")
    project, rows = f"kpi4-{ts}", []
    system = get_prompt("developer")
    for i, task in enumerate(TASKS):
        # baseline: primer intento SIN mapa del repo
        b = chat("kpi4-baseline", system, task, project=project, provider="ollama",
                 model="gpt-oss:20b", use_cache=False)
        bfiles = extract_files(b.text)
        b_find = sum(len(v) for v in validate_files(bfiles, idx).values())
        # ADES: mapa del repo + validador en bucle
        feedback, files, attempts, first_find = "", {}, 0, None
        for attempts in range(1, max_attempts + 1):
            user = task + (f"\n\nCORRIGE:\n{feedback}" if feedback else "")
            r = chat("kpi4-developer", system, user, context="Mapa del repositorio:\n" + repomap,
                     project=project, provider="ollama", model="gpt-oss:20b", use_cache=False,
                     effort="medium" if attempts == 1 else "high")
            files = extract_files(r.text) or files
            if not any(p.endswith(".py") for p in files):
                # Igual que el nodo QA de la fábrica: sin archivos -> FAIL y reintento
                feedback = ("No se encontraron archivos. Entrega cada archivo en un bloque "
                            "``` cuya primera linea sea '# FILE: ruta.py'.")
                continue
            found = [f"{p}: {f}" for p, fs in validate_files(files, idx).items() for f in fs]
            if first_find is None:
                first_find = len(found)
            if not found:
                break
            feedback = "Referencias que NO existen en el repositorio:\n" + "\n".join(found)
        final_graph = sum(len(v) for v in validate_files(files, idx).values())
        indep = []
        for p, c in files.items():
            if p.endswith(".py") and not p.split("/")[-1].startswith("test_"):
                indep += independent_check(c, tops)
        rows.append({"tarea": i + 1, "baseline_alucinaciones": b_find,
                     "ades_primer_intento": first_find, "intentos": attempts,
                     "final_grafo": final_graph, "final_verificacion_independiente": indep,
                     "archivos": list(files)})
        print(f"  tarea {i + 1}: baseline={b_find} ades_1er={first_find} intentos={attempts} "
              f"final_grafo={final_graph} independiente={indep}")
    ok_tasks = sum(1 for r in rows if r["final_grafo"] == 0 and not r["final_verificacion_independiente"]
                   and r["archivos"])
    res = {"fecha": ts, "tareas": rows, "tareas_sin_alucinaciones": ok_tasks, "total": len(rows),
           "baseline_tareas_con_alucinacion": sum(1 for r in rows if r["baseline_alucinaciones"]),
           "kpi4": ok_tasks == len(rows)}
    out = global_state_dir() / "kpis"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"kpi4_{ts}.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    return res


def main(argv=None) -> int:
    r = run()
    print(json.dumps({k: v for k, v in r.items() if k != "tareas"}, indent=2))
    return 0 if r["kpi4"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
