"""Prompt caching — contexto estático primero (ADES-AI, Fase 7).

El prompt caching (Gemini nativo + header `x-opencode-session` de OpenCode Go)
funciona cuando el prefijo ESTÁTICO (system + contexto fijo) va PRIMERO y se
mantiene estable entre llamadas. Este módulo ordena los mensajes de esa forma
y expone el prefijo estático para verificación.
"""
from langchain_core.messages import HumanMessage, SystemMessage


def build_messages(system: str, context: str, user_input: str) -> list:
    """Construye mensajes con el contenido estático primero (cacheable).

    Orden: [SystemMessage(system), SystemMessage(context)?, HumanMessage(user_input)].
    El prefijo (system + context) es estático y el proveedor lo cachea.
    """
    messages = [SystemMessage(content=system)]
    if context:
        messages.append(SystemMessage(content=context))
    messages.append(HumanMessage(content=user_input))
    return messages


def static_prefix(system: str, context: str) -> str:
    """Devuelve el prefijo estático que el proveedor cachea entre llamadas."""
    return f"{system}\n\n{context}" if context else system


def static_first(parts: list[str]) -> list[str]:
    """Reordena una lista de fragmentos poniendo lo estático primero.

    Convención: los fragmentos marcados con el prefijo "[STATIC] " se consideran
    estáticos (cacheables) y se colocan antes de los variables.
    """
    static = [p for p in parts if p.startswith("[STATIC] ")]
    variable = [p for p in parts if not p.startswith("[STATIC] ")]
    return static + variable
