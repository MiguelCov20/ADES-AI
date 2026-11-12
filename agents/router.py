"""Router de tareas / Brain Selector automático (Fase 3, features #20 y #21).

Clasifica una tarea con llama3.2:3b (local) y elige:
  - provider + modelo óptimo según complejidad (local $0 vs nube),
  - reasoning effort (low / medium / high),
  - la cascada de fallback (si un modelo falla, se escala al siguiente).

Tiene un fallback heurístico por si el modelo local no está disponible, y
respeta el nivel del Token Budget Governor (#10).

Uso:
    from agents.router import route_task
    decision = route_task("implementar un endpoint de login con JWT")
"""
import json
import os
import urllib.request

from core.config import OLLAMA_URL

OLLAMA = OLLAMA_URL

# complejidad -> (provider, model, effort)
COMPLEXITY_MAP = {
    "simple": {"provider": "ollama", "model": "llama3.2:3b", "effort": "low"},
    "medium": {"provider": "ollama", "model": "gpt-oss:20b", "effort": "medium"},
    "complex": {"provider": "opencode", "model": "deepseek-v4-pro", "effort": "high"},
}

# Cascadas de fallback (#21): el primer elemento es el modelo pedido.
def _gemini_default() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-flash-latest")


def cascade_for(provider: str, model: str) -> list[tuple[str, str]]:
    """Cadena de fallback para un (provider, model). Siempre termina en local ($0)."""
    first = (provider, model)
    if provider == "gemini":
        chain = [first, ("gemini", "gemini-flash-lite-latest"),
                 ("opencode", "deepseek-v4.1-flash"), ("ollama", "gpt-oss:20b")]
    elif provider == "opencode" and model == "deepseek-v4-pro":
        chain = [first, ("opencode", "deepseek-v4.1-flash"),
                 ("gemini", _gemini_default()), ("ollama", "gpt-oss:20b")]
    elif provider == "opencode":
        chain = [first, ("gemini", "gemini-flash-lite-latest"), ("ollama", "gpt-oss:20b")]
    elif model == "llama3.2:3b":
        chain = [first, ("ollama", "gpt-oss:20b")]
    else:  # ollama grande: otro grande local antes del pequeño (3B no sirve para código)
        chain = [first, ("ollama", "gpt-oss:20b"), ("ollama", "llama3.2:3b")]
    out, seen = [], set()
    for p in chain:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _heuristic(task: str) -> str:
    t = task.lower()
    if any(k in t for k in ("refactor", "debug", "arquitect", "complejo", "seguridad",
                            "optimiz", "migra", "escalab", "concurren")):
        return "complex"
    if any(k in t for k in ("formato", "docstring", "simple", "comentario",
                            "renombr", "ping", "hola", "typo")):
        return "simple"
    return "medium"


def _classify_llm(task: str) -> str | None:
    """Clasifica con llama3.2:3b; devuelve 'simple'|'medium'|'complex' o None."""
    payload = {
        "model": "llama3.2:3b",
        "prompt": (
            "Classify the complexity of this programming task with ONE word only: "
            f"simple, medium or complex.\n\nTask: {task}\n\nAnswer:"
        ),
        "stream": False,
        "options": {"temperature": 0, "num_predict": 15, "num_ctx": 2048},
    }
    req = urllib.request.Request(
        OLLAMA + "/api/generate", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        text = json.loads(resp.read().decode("utf-8")).get("response", "").strip().lower()
    return parse_label(text)


def parse_label(text: str) -> str | None:
    text = text.lower()
    if "complex" in text:
        return "complex"
    if "medium" in text:
        return "medium"
    if "simple" in text:
        return "simple"
    if "complej" in text or "dificil" in text or "alta" in text:
        return "complex"
    if "medi" in text:
        return "medium"
    if "sencill" in text or "facil" in text or "baja" in text or "bajo" in text:
        return "simple"
    return None


def route_task(task: str, use_llm: bool = True, tier: str = "any") -> dict:
    """Decide modelo, effort y cascada para una tarea.

    Devuelve: {provider, model, effort, complexity, source, cascade}.
    `tier` viene del Token Budget Governor: "any" | "cheap" | "local".
    """
    complexity = None
    if use_llm:
        try:
            complexity = _classify_llm(task)
        except Exception:
            complexity = None
    if complexity is None:
        complexity = _heuristic(task)
        source = "heuristico"
    else:
        source = "llama3.2:3b"

    decision = dict(COMPLEXITY_MAP[complexity])
    if tier == "cheap" and decision["provider"] != "ollama":
        decision.update(provider="opencode", model="deepseek-v4.1-flash")
    elif tier == "local" and decision["provider"] != "ollama":
        decision.update(provider="ollama", model="gpt-oss:20b")
    decision["complexity"] = complexity
    decision["source"] = source
    decision["cascade"] = cascade_for(decision["provider"], decision["model"])
    return decision
