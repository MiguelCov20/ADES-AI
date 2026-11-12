# AGENTS.md — agents/ (Fábrica multiagente LangGraph)

Convenciones locales de la fábrica. Completa al `AGENTS.md` raíz.

- **`orquestador.py`** es el grafo completo (PM → Arquitecto → Developer ⇄ QA → Reviewer → DevOps). No añadas nodos sin pasar por `build_graph`.
- Cada agente es un nodo **puro**: recibe `state` (dict) y devuelve un dict de actualizaciones. No hacen I/O más allá del LLM.
- **`roster.json`** es la fuente de verdad de los agentes (modelo, skills, permisos). El Reclutador (`reclutador.py`) es el único que lo escribe.
- **`llm.py`** es la fábrica de LLMs (gemini / opencode / ollama). No instancies `ChatGoogleGenerativeAI`/`ChatOpenAI` fuera de `llm.py`.
- El **router** (`router.py`) decide el modelo por tarea (llama3.2:3b, o el modelo ya cargado en llama-server si `ADES_LOCAL_BACKEND=llamacpp`, + fallback heurístico).
- Modelos locales: Ollama o llama.cpp `llama-server` (`core/local_serving.py`, batching continuo; KPI 5). En Linux, vLLM.
- El bucle Dev⇄QA usa `add_conditional_edges` + `MemorySaver` (checkpoint).
- Modelos: Gemini (nube, `GEMINI_MODEL` configurable), DeepSeek V4 (OpenCode Go), gpt-oss:20b / qwen3.8 / llama3.2:3b (Ollama local).
