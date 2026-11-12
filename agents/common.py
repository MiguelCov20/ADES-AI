"""Utilidades compartidas por los nodos de la fábrica."""
import json
import re

from agents import roster
from core.llm_gateway import chat


def llm_cfg(agent_id: str, fallback: tuple[str, str]) -> tuple[str, str]:
    """(provider, model) del agente según el roster (fuente de verdad del Reclutador)."""
    a = roster.get_agent(agent_id)
    if a and a.get("llm"):
        return a["llm"].get("provider", fallback[0]), a["llm"].get("model", fallback[1])
    return fallback


def call_agent(agent_id: str, system: str, user: str, state: dict, *, context: str = "",
               fallback=("ollama", "gpt-oss:20b"), provider=None, model=None, effort=None,
               use_cache: bool = True):
    p, m = (provider, model) if provider else llm_cfg(agent_id, fallback)
    if m == "auto":
        m = None
    return chat(agent_id, system, user, context=context, project=state.get("project"),
                run_id=state.get("run_id"), provider=p, model=m, effort=effort,
                use_cache=use_cache)


def parse_json(text: str):
    """Extrae el primer objeto JSON de un texto (tolera ```json ... ```)."""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    raw = m.group(1) if m else None
    if raw is None:
        start = text.find("{")
        end = text.rfind("}")
        raw = text[start:end + 1] if start >= 0 and end > start else ""
    try:
        return json.loads(raw)
    except Exception:
        return None


def memory_context(query: str, project: str | None) -> str:
    """Preferencias/lecciones cross-proyecto + vacunas relevantes (si la memoria está disponible)."""
    parts = []
    try:
        from memory import knowledge
        c = knowledge.recall_context(query, project=project, k=5)
        if c:
            parts.append("Memoria (preferencias, decisiones y lecciones):\n" + c)
    except Exception:
        pass
    try:
        from memory import vaccine
        c = vaccine.context_for(query)
        if c:
            parts.append("Bugs ya resueltos parecidos (no repetirlos):\n" + c)
    except Exception:
        pass
    return "\n\n".join(parts)
