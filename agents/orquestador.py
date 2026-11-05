"""Orquestador de la fábrica multiagente (LangGraph) - ADES-AI, Fase 3.

Grafo completo: PM -> Arquitecto -> Developer <-> QA -> Reviewer -> DevOps.

  - PM (Gemini): requerimiento -> PRD + tickets.
  - Arquitecto (Gemini): PRD -> diseño de sistema.
  - Developer (gpt-oss:20b local): arquitectura -> código.
  - QA (local): revisa el código y emite PASS/FAIL -> bucle cerrado con Developer.
  - Reviewer (DeepSeek V4): revisa el código final (seguridad/calidad).
  - DevOps (DeepSeek V4 flash): plan de despliegue.

El bucle Dev<->QA itera hasta que QA da PASS o se alcanza `max_iteraciones`.
Incluye checkpointing (MemorySaver) para poder reanudar/inspeccionar el estado.

Uso:
    python -m agents.orquestador "requerimiento" [--max-iter N] [--mock]
"""
import operator
import sys
import uuid
from typing import Annotated, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from agents.arquitecto import arquitecto_node
from agents.developer import developer_node
from agents.llm import get_llm
from agents.pm import pm_node
from agents.qa import qa_node
from agents.reviewer import reviewer_node

load_dotenv()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


class FactoryState(TypedDict, total=False):
    requerimiento: str
    prd: str
    tickets: list
    arquitectura: str
    codigo: str
    qa_veredicto: str
    qa_feedback: str
    review: str
    despliegue: str
    iteracion: int
    max_iteraciones: int
    messages: Annotated[list, operator.add]


def devops_node(state: dict) -> dict:
    """Nodo final: plan de despliegue (Docker/CI)."""
    codigo = state.get("codigo", "")
    llm = get_llm("opencode", "deepseek-v4.1-flash")
    resp = llm.invoke([
        SystemMessage(content=(
            "Eres el DevOps de ADES-AI. Genera un plan breve de despliegue "
            "(Dockerfile, CI/CD) para el codigo recibido. Conciso."
        )),
        HumanMessage(content=f"Codigo:\n{codigo}"),
    ])
    return {"despliegue": resp.content}


def ruta_despues_qa(state: dict) -> str:
    """Tras QA: si pasa (o se agotan iteraciones) -> reviewer; si no -> developer."""
    veredicto = state.get("qa_veredicto", "PASS")
    iteracion = state.get("iteracion", 0)
    max_iter = state.get("max_iteraciones", 3)
    if veredicto == "PASS" or iteracion >= max_iter:
        return "reviewer"
    return "developer"


def build_graph(checkpointer=None, nodes=None):
    """Construye el grafo de la fábrica. Permite inyectar nodos mock para tests."""
    nodes = nodes or {}
    workflow = StateGraph(FactoryState)
    workflow.add_node("pm", nodes.get("pm", pm_node))
    workflow.add_node("arquitecto", nodes.get("arquitecto", arquitecto_node))
    workflow.add_node("developer", nodes.get("developer", developer_node))
    workflow.add_node("qa", nodes.get("qa", qa_node))
    workflow.add_node("reviewer", nodes.get("reviewer", reviewer_node))
    workflow.add_node("devops", nodes.get("devops", devops_node))

    workflow.set_entry_point("pm")
    workflow.add_edge("pm", "arquitecto")
    workflow.add_edge("arquitecto", "developer")
    workflow.add_edge("developer", "qa")
    workflow.add_conditional_edges(
        "qa", ruta_despues_qa,
        {"developer": "developer", "reviewer": "reviewer"},
    )
    workflow.add_edge("reviewer", "devops")
    workflow.add_edge("devops", END)

    return workflow.compile(checkpointer=checkpointer or MemorySaver())


def run(requerimiento: str, max_iteraciones: int = 3) -> dict:
    app = build_graph()
    initial = {
        "requerimiento": requerimiento,
        "iteracion": 0,
        "max_iteraciones": max_iteraciones,
        "messages": [],
    }
    config = {"configurable": {"thread_id": f"fabrica-{uuid.uuid4().hex}"}}
    return app.invoke(initial, config=config)


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Fabrica multiagente (Fase 3)")
    ap.add_argument("requerimiento")
    ap.add_argument("--max-iter", type=int, default=3)
    args = ap.parse_args(argv)

    print(f"\n=== FABRICA: {args.requerimiento} ===\n")
    result = run(args.requerimiento, args.max_iter)

    print("\n--- PRD (PM) ---")
    print((result.get("prd") or "")[:600])
    print("\n--- ARQUITECTURA ---")
    print((result.get("arquitectura") or "")[:600])
    print("\n--- CODIGO (Developer) ---")
    print((result.get("codigo") or "")[:800])
    print(f"\n--- QA ---")
    print(f"veredicto={result.get('qa_veredicto')} iteracion={result.get('iteracion')}")
    print("\n--- REVIEW (Reviewer) ---")
    print((result.get("review") or "")[:400])
    print("\n--- DESPLIEGUE (DevOps) ---")
    print((result.get("despliegue") or "")[:400])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
