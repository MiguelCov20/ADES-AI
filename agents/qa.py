"""Nodo QA Tester (local) - ADES-AI, Fase 3.

Revisa el código del Developer y emite un veredicto PASS/FAIL con feedback.
Alimenta el bucle cerrado Dev<->QA.
"""
from langchain_core.messages import HumanMessage, SystemMessage

from agents.llm import get_llm


def _parse_veredicto(text: str) -> str:
    t = text.upper()
    if "FAIL" in t or "FALLO" in t or "ERROR" in t or "NO PAS" in t:
        return "FAIL"
    return "PASS"


def qa_node(state: dict) -> dict:
    requerimiento = state.get("requerimiento", "")
    codigo = state.get("codigo", "")
    llm = get_llm("ollama", "gpt-oss:20b")
    system = (
        "Eres el QA Tester de ADES-AI. Revisas el codigo del Developer contra el "
        "requerimiento. Responde con una PRIMERA linea que sea exactamente 'PASS' o "
        "'FAIL', y luego el detalle del feedback (que falta, que esta mal, o por que "
        "pasa). Se estricto: si el codigo no cumple el requerimiento, es FAIL."
    )
    resp = llm.invoke([
        SystemMessage(content=system),
        HumanMessage(content=f"Requerimiento: {requerimiento}\n\nCodigo:\n{codigo}"),
    ])
    veredicto = _parse_veredicto(resp.content)
    return {"qa_veredicto": veredicto, "qa_feedback": resp.content}


if __name__ == "__main__":
    r = qa_node({"requerimiento": "endpoint ping", "codigo": "def hola(): return 'pong'"})
    print(r["qa_veredicto"], "-", r["qa_feedback"][:200])
