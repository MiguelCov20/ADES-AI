"""Nodo Project Manager (Gemini) - ADES-AI.

Requerimiento -> PRD + tickets estructurados (JSON) que alimentan el backlog (#2).
"""
from agents.common import call_agent, memory_context, parse_json
from agents.prompts import get_prompt


def pm_node(state: dict) -> dict:
    requerimiento = state.get("requerimiento", "")
    if state.get("skip_pm") and state.get("tickets"):
        t = state["tickets"]
        return {"prd": requerimiento, "tickets": t}
    ctx = memory_context(requerimiento, state.get("project"))
    res = call_agent("pm", get_prompt("pm"), f"Requerimiento del usuario: {requerimiento}",
                     state, context=ctx, fallback=("gemini", "auto"))
    data = parse_json(res.text) or {}
    prd = data.get("prd") or res.text
    tickets = data.get("tickets") or [{"titulo": requerimiento[:80],
                                       "descripcion": requerimiento, "criterios": []}]
    tickets = [t if isinstance(t, dict) else {"titulo": str(t), "descripcion": str(t),
                                               "criterios": []} for t in tickets]
    return {"prd": prd, "tickets": tickets}
