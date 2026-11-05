---
name: Fabrica multiagente
description: Ejecuta la fábrica multiagente de LangGraph (PM → Arquitecto → Developer ⇄ QA → Reviewer → DevOps)
---

## Objetivo

Procesar un requerimiento de software con la fábrica multiagente de ADES-AI,
que orquesta agentes especializados con LangGraph y bucle cerrado Dev⇄QA.

## Workflow

1. Ejecuta `python -m agents.orquestador "<requerimiento>" --max-iter 3`.
2. El flujo es: PM (Gemini) → Arquitecto (Gemini) → Developer (gpt-oss:20b local)
   ⇄ QA (local) → Reviewer (deepseek-v4-pro) → DevOps (deepseek-v4.1-flash).
3. `--max-iter` limita las iteraciones del bucle Dev⇄QA.

## Notas

- El router (`agents/router.py`) elige el modelo por tarea (llama3.2:3b).
- El roster (`agents/roster.json`) define los agentes; el Reclutador
  (`agents/reclutador.py`) los crea/elimina.
- Gemini es intermitente; usa `GEMINI_MODEL=gemini-flash-lite-latest` si hay 503.
