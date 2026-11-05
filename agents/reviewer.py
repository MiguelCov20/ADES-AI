"""Nodo Code Reviewer (DeepSeek V4) - ADES-AI, Fase 3.

Revisa el código final (seguridad/calidad).
"""
from langchain_core.messages import HumanMessage, SystemMessage

from agents.llm import get_llm


def reviewer_node(state: dict) -> dict:
    codigo = state.get("codigo", "")
    llm = get_llm("opencode", "deepseek-v4-pro")
    system = (
        "Eres el Code Reviewer de ADES-AI. Revisas el codigo final enfocandote en "
        "seguridad, calidad y mantenibilidad. Da un veredicto claro y conciso: "
        "que esta bien, que riesgos hay y que mejorarias."
    )
    resp = llm.invoke([
        SystemMessage(content=system),
        HumanMessage(content=f"Codigo a revisar:\n{codigo}"),
    ])
    return {"review": resp.content}


if __name__ == "__main__":
    r = reviewer_node({"codigo": "def ping(): return 'pong'"})
    print(r["review"][:300])
