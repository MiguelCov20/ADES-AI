"""Nodo Developer - ADES-AI.

Arquitectura + feedback de QA -> archivos de código + tests.

Self-Healing pipeline (#4): cada iteración del bucle Dev⇄QA usa una ESTRATEGIA
distinta en vez de repetir lo mismo:

  1. base       -> modelo del roster (gpt-oss:20b local, $0), effort medio
  2. contexto   -> mismo modelo, effort alto + salida completa del sandbox,
                   vacunas de bugs parecidos y archivos previos completos
  3. local-alt  -> otro modelo LOCAL (qwen3.8:27b, $0) con todo el contexto
  4. modelo     -> escala a nube barata (deepseek-v4.1-flash)
  5. pesado     -> deepseek-v4-pro (effort alto)

Los pasos 1-3 cuestan $0 (KPI 2). Con ADES_SELF_HEAL_CLOUD=0 nunca se escala a nube.

El Token Budget Governor puede bloquear los pasos 3-4 (la pasarela cae a local).
La salida pasa por el validador anti-alucinación (KPI 4) antes de QA.
"""
import re

from agents.common import call_agent, llm_cfg, memory_context
from agents.prompts import get_prompt
from core.sandbox import extract_files

STRATEGIES = [
    {"name": "base", "effort": "medium", "model": None},
    {"name": "contexto", "effort": "high", "model": None},
    {"name": "local-alt", "effort": "high", "model": ("ollama", "qwen3.8:27b-iq3")},
    {"name": "modelo", "effort": "medium", "model": ("opencode", "deepseek-v4.1-flash")},
    {"name": "pesado", "effort": "high", "model": ("opencode", "deepseek-v4-pro")},
]


def strategy_for(iteracion: int) -> dict:
    """Estrategia para la iteración (0-based) del bucle Dev⇄QA."""
    import os
    strategies = STRATEGIES
    if os.getenv("ADES_SELF_HEAL_CLOUD", "1") == "0":
        strategies = [s for s in STRATEGIES if not s["model"] or s["model"][0] == "ollama"]
    return strategies[min(iteracion, len(strategies) - 1)]


def fix_default_name(files: dict, requerimiento: str) -> dict:
    """Si el modelo no puso `# FILE:` y el extractor usó `main.py`, pero el requerimiento
    nombra el módulo (p. ej. `duracion.py`), se usa ese nombre (el KPI 3 falló por esto)."""
    if set(files) != {"main.py"}:
        return files
    named = [n for n in re.findall(r"([\w/-]+\.py)\b", requerimiento)
             if not n.split("/")[-1].startswith("test_")]
    if named and named[0] != "main.py":
        return {named[0]: files["main.py"]}
    return files


def _files_block(files: dict) -> str:
    return "\n\n".join(f"```python\n# FILE: {p}\n{c}```" for p, c in files.items())


def developer_node(state: dict) -> dict:
    requerimiento = state.get("requerimiento", "")
    arquitectura = state.get("arquitectura", "")
    feedback = state.get("qa_feedback", "")
    it = state.get("iteracion", 0)
    st = strategy_for(it)
    project = state.get("project")

    # Contexto estático primero (cacheable): mapa del repo + memoria
    ctx_parts = []
    if state.get("repomap"):
        ctx_parts.append("Mapa del repositorio (clases/funciones que EXISTEN):\n"
                         + state["repomap"])
    mem = memory_context(requerimiento + "\n" + feedback[:500], project)
    if mem:
        ctx_parts.append(mem)
    context = "\n\n".join(ctx_parts)

    tickets = state.get("tickets") or []
    crit = []
    for t in tickets:
        crit += [c for c in t.get("criterios", []) if isinstance(c, str)]
    human = f"Requerimiento: {requerimiento}\n\nArquitectura:\n{arquitectura[:6000]}"
    if crit:
        human += "\n\nCriterios de aceptacion:\n" + "\n".join(f"- {c}" for c in crit)
    if feedback:
        fb = feedback if st["name"] != "base" else feedback[:2500]
        human += f"\n\nFeedback de QA (CORREGIR, iteracion {it + 1}):\n{fb}"
        if state.get("files") and st["name"] != "base":
            human += "\n\nArchivos de la entrega anterior:\n" + _files_block(state["files"])

    if st["model"]:
        provider, model = st["model"]
    else:
        provider, model = llm_cfg("dev_backend", ("ollama", "gpt-oss:20b"))
    res = call_agent("developer", get_prompt("developer"), human, state, context=context,
                     provider=provider, model=model, effort=st["effort"],
                     use_cache=not feedback)
    files = fix_default_name(extract_files(res.text), requerimiento) or state.get("files", {})
    estrategias = list(state.get("estrategias", [])) + [
        f"{st['name']}:{res.provider}/{res.model}"]
    return {"codigo": res.text, "files": files, "iteracion": it + 1,
            "estrategias": estrategias}
