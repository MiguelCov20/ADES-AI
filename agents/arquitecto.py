"""Nodo Arquitecto (Gemini) - ADES-AI.

PRD -> diseño de sistema. Usa la memoria cross-proyecto (#6) y registra la
decisión en el timeline (#9).
"""
from agents.common import call_agent, memory_context
from agents.prompts import get_prompt


def arquitecto_node(state: dict) -> dict:
    prd = state.get("prd", "")
    requerimiento = state.get("requerimiento", "")
    project = state.get("project")
    ctx = memory_context(requerimiento, project)
    if state.get("repomap"):
        ctx = (ctx + "\n\nMapa del repositorio actual:\n" + state["repomap"]).strip()
    res = call_agent("arquitecto", get_prompt("arquitecto"),
                     f"Requerimiento: {requerimiento}\n\nPRD:\n{prd}", state, context=ctx,
                     fallback=("gemini", "auto"))
    def _record():
        try:
            from memory import timeline
            timeline.record_decision(f"Arquitectura: {requerimiento[:80]}", res.text[:1500],
                                     project=project)
        except Exception:
            pass
    # Graphiti tarda ~60 s por episodio: se registra en segundo plano (no bloquea la fábrica)
    import threading
    threading.Thread(target=_record, daemon=True, name="timeline-record").start()
    return {"arquitectura": res.text}
