"""Nodos Code Reviewer (DeepSeek V4 pro) y DevOps (DeepSeek V4.1 flash) - ADES-AI.

El Reviewer combina la revisión LLM con la auditoría anti-IA (#24) si está disponible.
"""
from agents.common import call_agent
from agents.prompts import get_prompt


def _code(state: dict) -> str:
    files = state.get("files") or {}
    if files:
        return "\n\n".join(f"# FILE: {p}\n{c}" for p, c in files.items())
    return state.get("codigo", "")


def reviewer_node(state: dict) -> dict:
    audit_txt, audit = "", None
    try:
        from evals.ai_audit import audit_files
        audit = audit_files(state.get("files") or {})
        audit_txt = f"\n\nAuditoria automatica anti-IA:\n{audit}"[:3000]
    except Exception:
        pass
    res = call_agent("reviewer", get_prompt("reviewer"),
                     f"Codigo a revisar:\n{_code(state)[:15000]}{audit_txt}", state,
                     fallback=("opencode", "deepseek-v4-pro"))
    out = {"review": res.text}
    if audit is not None:
        out["auditoria"] = audit if isinstance(audit, dict) else {"resultado": str(audit)}
    return out


def devops_node(state: dict) -> dict:
    res = call_agent("devops", get_prompt("devops"), f"Codigo:\n{_code(state)[:12000]}",
                     state, fallback=("opencode", "deepseek-v4.1-flash"))
    return {"despliegue": res.text}
