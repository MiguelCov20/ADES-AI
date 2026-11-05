"""Nodo Developer (local gpt-oss:20b) - ADES-AI, Fase 3.

Arquitectura + (feedback de QA) -> código. Recibe el feedback de QA en
iteraciones posteriores para corregir (bucle cerrado Dev<->QA).
"""
from langchain_core.messages import HumanMessage, SystemMessage

from agents.llm import get_llm


def developer_node(state: dict) -> dict:
    requerimiento = state.get("requerimiento", "")
    arquitectura = state.get("arquitectura", "")
    feedback = state.get("qa_feedback", "")
    llm = get_llm("ollama", "gpt-oss:20b")
    system = (
        "Eres el Developer de ADES-AI. Escribes codigo Python limpio y funcional "
        "segun la arquitectura recibida. Si hay feedback de QA, corregirlo. "
        "Devuelve SOLO el codigo (con un comentario breve al inicio si es necesario)."
    )
    human = f"Requerimiento: {requerimiento}\n\nArquitectura:\n{arquitectura}"
    if feedback:
        human += f"\n\nFeedback de QA (CORREGIR):\n{feedback}"
    resp = llm.invoke([SystemMessage(content=system), HumanMessage(content=human)])
    return {"codigo": resp.content, "iteracion": state.get("iteracion", 0) + 1}


if __name__ == "__main__":
    r = developer_node({"requerimiento": "endpoint ping", "arquitectura": "FastAPI"})
    print(r["codigo"][:300])
