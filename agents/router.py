"""Router de tareas (Brain Selector) - ADES-AI, Fase 3.

Clasifica una tarea con llama3.2:3b (local) y elige el modelo óptimo
(local $0 vs nube) según complejidad. Tiene un fallback determinista por si
el modelo local no está disponible.

Uso:
    from agents.router import route_task
    decision = route_task("implementar un endpoint de login con JWT")
"""
import json
import urllib.request

OLLAMA = "http://localhost:11434"

# complejidad -> (provider, model)
COMPLEXITY_MAP = {
    "simple": {"provider": "ollama", "model": "llama3.2:3b"},
    "medium": {"provider": "ollama", "model": "gpt-oss:20b"},
    "complex": {"provider": "opencode", "model": "deepseek-v4-pro"},
}


def _heuristic(task: str) -> str:
    t = task.lower()
    if any(k in t for k in ("refactor", "debug", "arquitect", "complejo", "seguridad",
                            "optimiz", "migra", "escalab", "concurren")):
        return "complex"
    if any(k in t for k in ("test", "formato", "doc", "simple", "comentario",
                            "renombr", "ping", "hola")):
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
        "options": {"temperature": 0, "num_predict": 15},
    }
    req = urllib.request.Request(
        OLLAMA + "/api/generate", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        text = json.loads(resp.read().decode("utf-8")).get("response", "").strip().lower()

    # Inglés
    if "complex" in text:
        return "complex"
    if "medium" in text:
        return "medium"
    if "simple" in text:
        return "simple"
    # Español (el modelo a veces responde en español)
    if "complej" in text or "dificil" in text or "alta" in text:
        return "complex"
    if "medi" in text:
        return "medium"
    if "sencill" in text or "facil" in text or "baja" in text or "bajo" in text:
        return "simple"
    return None


def route_task(task: str, use_llm: bool = True) -> dict:
    """Decide el modelo para una tarea.

    Devuelve: {provider, model, complexity, source} donde source indica
    si la decisión vino del LLM (llama3.2:3b) o del heurístico.
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
    decision["complexity"] = complexity
    decision["source"] = source
    return decision
