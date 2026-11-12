"""Orquestador de la fábrica multiagente (LangGraph) - ADES-AI.

Grafo: contexto -> PM -> Arquitecto -> Developer <-> QA -> Escritura -> Reviewer -> DevOps

  - contexto: RepoMap del proyecto (Neo4j) + índice del grafo para validar
    alucinaciones (KPI 4).
  - PM (Gemini): requerimiento -> PRD + tickets (JSON).
  - Arquitecto (Gemini): diseño; usa memoria cross-proyecto y registra la decisión.
  - Developer: estrategias de self-healing por iteración (#4).
  - QA: anti-alucinación + tests de aceptación + sandbox Docker (bucle cerrado).
  - Escritura: guarda los archivos aprobados en el proyecto vía MCP filesystem.
  - Reviewer (DeepSeek V4 pro) + auditoría anti-IA; DevOps (DeepSeek V4.1 flash).

Todas las llamadas LLM pasan por `core.llm_gateway` (fallback en cascada,
presupuesto, caché, tracing en Langfuse y métricas).

Uso:
    python -m agents.orquestador "requerimiento" [--project P] [--max-iter N] [--no-write]
"""
import json
import operator
import time
import uuid
from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from agents.arquitecto import arquitecto_node
from agents.developer import developer_node
from agents.pm import pm_node
from agents.qa import qa_node
from agents.reviewer import devops_node, reviewer_node
from core import metrics_store
from core.config import state_dir


class FactoryState(TypedDict, total=False):
    requerimiento: str
    project: str
    run_id: str
    skip_pm: bool
    write: bool
    prd: str
    tickets: list
    repomap: str
    arquitectura: str
    codigo: str
    files: dict
    qa_tests: str | None
    qa_tests_regen: int
    qa_acceptance: bool
    qa_veredicto: str
    qa_feedback: str
    sandbox: dict
    alucinaciones: list
    alucinaciones_detectadas: int
    estrategias: list
    escritos: list
    review: str
    auditoria: dict
    despliegue: str
    estado: str
    iteracion: int
    max_iteraciones: int
    messages: Annotated[list, operator.add]


# Índices del grafo por repo (no serializables: se guardan fuera del estado)
_GRAPH_CACHE: dict[str, object] = {}


def context_node(state: dict) -> dict:
    """RepoMap del proyecto + índice del grafo para el validador anti-alucinación."""
    from core import projects
    project = state.get("project") or "ades-ai"
    try:
        repo = str(projects.path_of(project).resolve())
    except KeyError:
        return {}
    try:
        from memory.indexer import _driver_from_env, index_repo
        from memory.repomap import generate_repomap
        from memory.validator import GraphIndex
        d = _driver_from_env()
        try:
            if any(Path(repo).rglob("*.py")):
                index_repo(repo, d)  # incremental (MERGE)
            repomap = generate_repomap(d, repo=repo)
            _GRAPH_CACHE[state["run_id"]] = GraphIndex.from_neo4j(d, repo=repo)
        finally:
            d.close()
        return {"repomap": repomap[:12000]}
    except Exception:
        return {}


def _qa_with_graph(state: dict) -> dict:
    s = dict(state)
    s["_graph_index"] = _GRAPH_CACHE.get(state.get("run_id"))
    return qa_node(s)


def write_node(state: dict) -> dict:
    """Escribe los archivos aprobados en la carpeta del proyecto (MCP filesystem)."""
    if not state.get("write", True):
        return {"escritos": []}
    from core import projects
    root = projects.path_of(state.get("project") or "ades-ai")
    if root.resolve() == Path(__file__).resolve().parent.parent:
        # Nunca sobrescribir el propio ADES-AI: se escribe en una subcarpeta generada
        root = root / "workspace" / "_generado" / state["run_id"]
    escritos = []
    for rel, content in (state.get("files") or {}).items():
        target = (root / rel).resolve()
        if root.resolve() not in target.parents:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            from mcp_servers.client import call_tool
            r = call_tool("filesystem", "write_file", {"path": str(target), "content": content})
            if getattr(r, "isError", False):
                raise RuntimeError(str(r.content)[:200])
            via = "mcp"
        except Exception:
            target.write_text(content, encoding="utf-8")
            via = "local"
        escritos.append({"path": str(target), "via": via})
    return {"escritos": escritos}


def ruta_despues_qa(state: dict) -> str:
    """PASS -> escribir; FAIL con iteraciones -> developer; agotadas -> fin (escalar)."""
    if state.get("qa_veredicto") == "PASS":
        return "write"
    if state.get("iteracion", 0) < state.get("max_iteraciones", 4):
        return "developer"
    # Tests en verde pero el revisor LLM sigue con objeciones: se acepta con observaciones
    if (state.get("sandbox") or {}).get("passed"):
        return "write"
    return "failed"


def failed_node(state: dict) -> dict:
    return {"estado": "failed"}


def build_graph(checkpointer=None, nodes=None):
    """Construye el grafo de la fábrica. Permite inyectar nodos mock para tests."""
    nodes = nodes or {}
    g = StateGraph(FactoryState)
    g.add_node("contexto", nodes.get("contexto", context_node))
    g.add_node("pm", nodes.get("pm", pm_node))
    g.add_node("arquitecto", nodes.get("arquitecto", arquitecto_node))
    g.add_node("developer", nodes.get("developer", developer_node))
    g.add_node("qa", nodes.get("qa", _qa_with_graph))
    g.add_node("write", nodes.get("write", write_node))
    g.add_node("reviewer", nodes.get("reviewer", reviewer_node))
    g.add_node("devops", nodes.get("devops", devops_node))
    g.add_node("failed", nodes.get("failed", failed_node))

    g.set_entry_point("contexto")
    g.add_edge("contexto", "pm")
    g.add_edge("pm", "arquitecto")
    g.add_edge("arquitecto", "developer")
    g.add_edge("developer", "qa")
    g.add_conditional_edges("qa", ruta_despues_qa,
                            {"developer": "developer", "write": "write", "failed": "failed"})
    g.add_edge("write", "reviewer")
    g.add_edge("reviewer", "devops")
    g.add_edge("devops", END)
    g.add_edge("failed", END)
    return g.compile(checkpointer=checkpointer or MemorySaver())


def run(requerimiento: str, max_iteraciones: int = 5, project: str = "ades-ai",
        skip_pm: bool = False, tickets: list | None = None, write: bool = True,
        qa_acceptance: bool = True, nodes=None, run_id: str | None = None) -> dict:
    run_id = run_id or f"run-{uuid.uuid4().hex[:12]}"
    app = build_graph(nodes=nodes)
    initial = {
        "requerimiento": requerimiento, "project": project, "run_id": run_id,
        "skip_pm": skip_pm, "tickets": tickets or [], "write": write,
        "qa_acceptance": qa_acceptance,
        "iteracion": 0, "max_iteraciones": max_iteraciones, "messages": [],
    }
    t0 = time.time()
    result = app.invoke(initial, config={"configurable": {"thread_id": run_id},
                                         "recursion_limit": 60})
    _GRAPH_CACHE.pop(run_id, None)
    result = dict(result)
    result["estado"] = result.get("estado") or "ok"
    result["duracion_s"] = round(time.time() - t0, 1)
    result["metricas"] = metrics_store.summary(run_id=run_id)
    _save_run(result)
    try:
        from evals import tracing
        tracing.flush()
    except Exception:
        pass
    return result


def _save_run(result: dict) -> None:
    d = state_dir(result.get("project")) / "runs"
    d.mkdir(parents=True, exist_ok=True)
    keep = {k: v for k, v in result.items() if k not in ("messages",)}
    (d / f"{result['run_id']}.json").write_text(
        json.dumps(keep, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Fabrica multiagente")
    ap.add_argument("requerimiento")
    ap.add_argument("--project", default="ades-ai")
    ap.add_argument("--max-iter", type=int, default=5)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    print(f"\n=== FABRICA [{args.project}]: {args.requerimiento} ===\n")
    r = run(args.requerimiento, args.max_iter, project=args.project, write=not args.no_write)
    print(f"estado={r['estado']} run={r['run_id']} iteraciones={r.get('iteracion')} "
          f"estrategias={r.get('estrategias')}")
    print(f"sandbox={r.get('sandbox')} alucinaciones={r.get('alucinaciones')}")
    print(f"archivos={list((r.get('files') or {}).keys())}")
    print(f"escritos={[e['path'] for e in r.get('escritos', [])]}")
    m = r["metricas"]
    print(f"llamadas={m['calls']} tokens={m['tokens_in']}+{m['tokens_out']} "
          f"costo=${m['cost']:.5f} cache_hits={m['cache_hits']} duracion={r['duracion_s']}s")
    print("\n--- REVIEW ---\n" + (r.get("review") or "")[:600])
    return 0 if r["estado"] == "ok" else 1


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
