"""Nodo Project Manager (Gemini) - ADES-AI, Fase 3.

Requerimiento -> PRD + tickets (plan de acción).
"""
from langchain_core.messages import HumanMessage, SystemMessage

from agents.llm import get_llm


def pm_node(state: dict) -> dict:
    requerimiento = state.get("requerimiento", "")
    llm = get_llm("gemini", "auto")
    system = (
        "Eres el Project Manager de ADES-AI, una Software Factory autonoma. "
        "Tu trabajo NO es escribir codigo, sino planificar. Recibes un requerimiento "
        "y debes producir un PRD conciso con los pasos tecnicos (tickets) para que "
        "el Arquitecto y el Developer puedan trabajar. Responde de forma estructurada."
    )
    resp = llm.invoke([
        SystemMessage(content=system),
        HumanMessage(content=f"Requerimiento del usuario: {requerimiento}"),
    ])
    return {"prd": resp.content, "tickets": [resp.content]}


if __name__ == "__main__":
    r = pm_node({"requerimiento": "Un endpoint /ping en FastAPI"})
    print(r["prd"])
