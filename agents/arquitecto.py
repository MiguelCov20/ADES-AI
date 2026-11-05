"""Nodo Arquitecto (Gemini) - ADES-AI, Fase 3.

PRD -> diseño de sistema y stack.
"""
from langchain_core.messages import HumanMessage, SystemMessage

from agents.llm import get_llm


def arquitecto_node(state: dict) -> dict:
    prd = state.get("prd", "")
    requerimiento = state.get("requerimiento", "")
    llm = get_llm("gemini", "auto")
    system = (
        "Eres el Arquitecto de ADES-AI. Recibes el PRD del Project Manager y "
        "debes disenar la solucion: componentes, stack tecnologico, estructura de "
        "archivos y API. Responde de forma clara y accionable para el Developer."
    )
    resp = llm.invoke([
        SystemMessage(content=system),
        HumanMessage(content=f"Requerimiento: {requerimiento}\n\nPRD:\n{prd}"),
    ])
    return {"arquitectura": resp.content}


if __name__ == "__main__":
    r = arquitecto_node({"requerimiento": "endpoint ping", "prd": "crear endpoint /ping"})
    print(r["arquitectura"])
